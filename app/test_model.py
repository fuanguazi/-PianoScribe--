"""Test the trained CRNN model on an audio file and output MIDI."""
import os
import sys
import numpy as np
import torch
import pretty_midi
import librosa

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    SAMPLE_RATE, N_FFT, HOP_SIZE, N_MELS, MEL_FMIN, MEL_FMAX,
    MIDI_MIN, MIDI_MAX, N_PITCHES, FRAME_RATE, SEGMENT_FRAMES,
    CHECKPOINT_DIR,
)
from model import TranscriptionCRNN


def transcribe(audio_path, output_midi_path, checkpoint_path=None, device='cuda'):
    if checkpoint_path is None:
        checkpoint_path = os.path.join(CHECKPOINT_DIR, "best_model.pt")

    device = torch.device(device if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Load model
    model = TranscriptionCRNN(n_mels=N_MELS, n_pitches=N_PITCHES)
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    if "generator" in ckpt:
        model.load_state_dict(ckpt["generator"])
    else:
        model.load_state_dict(ckpt)
    model.to(device)
    model.eval()
    print(f"Loaded checkpoint: {checkpoint_path}")

    # Load audio
    print(f"Loading audio: {audio_path}")
    audio, sr = librosa.load(audio_path, sr=SAMPLE_RATE, mono=True)
    duration = len(audio) / SAMPLE_RATE
    print(f"Duration: {duration:.1f}s")

    # Compute mel spectrogram (match training: torchaudio log-mel + instance norm)
    import torchaudio.transforms as T
    mel_transform = T.MelSpectrogram(
        sample_rate=SAMPLE_RATE, n_fft=N_FFT, hop_length=HOP_SIZE,
        n_mels=N_MELS, f_min=MEL_FMIN, f_max=MEL_FMAX,
    )
    audio_t = torch.from_numpy(audio).float().unsqueeze(0)
    mel_t = mel_transform(audio_t)
    mel_t = torch.log(mel_t + 1e-7)
    mean = mel_t.mean(dim=-1, keepdim=True)
    std = mel_t.std(dim=-1, keepdim=True)
    std = torch.clamp(std, min=1e-5)
    mel_t = (mel_t - mean) / std
    mel = mel_t.squeeze(0).numpy().astype(np.float32)

    n_frames = mel.shape[1]
    print(f"Mel shape: {mel.shape}, Frames: {n_frames}")

    # Process in segments
    all_onset = np.zeros((n_frames, N_PITCHES), dtype=np.float32)
    all_offset = np.zeros((n_frames, N_PITCHES), dtype=np.float32)
    all_frame = np.zeros((n_frames, N_PITCHES), dtype=np.float32)
    all_velocity = np.zeros((n_frames, N_PITCHES), dtype=np.float32)

    hop = SEGMENT_FRAMES // 2  # 50% overlap for smoother predictions
    n_segments = max(1, (n_frames - SEGMENT_FRAMES) // hop + 1)
    print(f"Processing {n_segments} segments...")

    with torch.no_grad():
        for i in range(n_segments):
            start = i * hop
            end = start + SEGMENT_FRAMES

            if end > n_frames:
                # Pad the last segment
                seg = np.zeros((N_MELS, SEGMENT_FRAMES), dtype=np.float32)
                seg[:, :n_frames - start] = mel[:, start:n_frames]
            else:
                seg = mel[:, start:end]

            mel_t = torch.from_numpy(seg).unsqueeze(0).to(device)

            pred_onset, pred_offset, pred_frame, pred_vel = model(mel_t)

            # Apply sigmoid (model outputs logits)
            pred_onset = torch.sigmoid(pred_onset).cpu().numpy()[0]
            pred_offset = torch.sigmoid(pred_offset).cpu().numpy()[0]
            pred_frame = torch.sigmoid(pred_frame).cpu().numpy()[0]
            pred_vel = torch.sigmoid(pred_vel).cpu().numpy()[0]

            # Overlap-add
            actual_end = min(end, n_frames)
            actual_len = actual_end - start
            all_onset[start:actual_end] += pred_onset[:actual_len]
            all_offset[start:actual_end] += pred_offset[:actual_len]
            all_frame[start:actual_end] += pred_frame[:actual_len]
            all_velocity[start:actual_end] += pred_vel[:actual_len]

            if (i + 1) % 10 == 0:
                print(f"  Segment {i+1}/{n_segments}")

    # Average overlap regions
    overlap_count = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_segments):
        start = i * hop
        end = min(start + SEGMENT_FRAMES, n_frames)
        overlap_count[start:end] += 1
    overlap_count = np.maximum(overlap_count, 1)

    all_onset /= overlap_count[:, None]
    all_offset /= overlap_count[:, None]
    all_frame /= overlap_count[:, None]
    all_velocity /= overlap_count[:, None]

    # Extract notes from predictions
    # Use onset threshold and frame threshold
    onset_threshold = 0.3
    frame_threshold = 0.3

    midi = pretty_midi.PrettyMIDI()
    piano = pretty_midi.Instrument(program=0)  # Acoustic Grand Piano

    for pitch_idx in range(N_PITCHES):
        midi_pitch = pitch_idx + MIDI_MIN

        # Find onsets
        onset_frames = np.where(all_onset[:, pitch_idx] > onset_threshold)[0]
        if len(onset_frames) == 0:
            continue

        # Group consecutive onset frames into notes
        active = all_frame[:, pitch_idx] > frame_threshold
        notes = []
        note_start = None

        for f in range(len(active)):
            if active[f] and note_start is None:
                note_start = f
            elif not active[f] and note_start is not None:
                notes.append((note_start, f))
                note_start = None
        if note_start is not None:
            notes.append((note_start, len(active)))

        for start_f, end_f in notes:
            # Check if there's an onset near this note
            onset_near = np.any(all_onset[max(0, start_f-3):min(start_f+4, n_frames), pitch_idx] > onset_threshold)
            if not onset_near:
                continue

            start_time = start_f / FRAME_RATE
            end_time = end_f / FRAME_RATE
            if end_time - start_time < 0.03:  # Skip very short notes
                continue

            # Velocity from prediction
            vel_frames = all_velocity[start_f:end_f, pitch_idx]
            vel = np.mean(vel_frames) if len(vel_frames) > 0 else 0.5
            midi_vel = int(np.clip(vel * 127, 30, 127))

            note = pretty_midi.Note(
                velocity=midi_vel,
                pitch=midi_pitch,
                start=start_time,
                end=end_time,
            )
            piano.notes.append(note)

    midi.instruments.append(piano)
    midi.write(output_midi_path)
    print(f"\nMIDI saved to: {output_midi_path}")
    print(f"Total notes: {len(piano.notes)}")
    if piano.notes:
        pitches = [n.pitch for n in piano.notes]
        print(f"Pitch range: {min(pitches)} - {max(pitches)}")
        durations = [n.end - n.start for n in piano.notes]
        print(f"Duration range: {min(durations):.3f}s - {max(durations):.3f}s")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=str, required=True)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--checkpoint", type=str, default=None)
    parser.add_argument("--device", type=str, default="cuda")
    args = parser.parse_args()

    if args.output is None:
        args.output = args.audio.rsplit('.', 1)[0] + '_crnn.mid'

    transcribe(args.audio, args.output, args.checkpoint, args.device)
