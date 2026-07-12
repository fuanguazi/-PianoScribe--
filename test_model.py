"""Test the trained model on a WAV file and output detected notes."""
import os
import sys
import numpy as np
import torch
import torchaudio
import pretty_midi

from config import (
    SAMPLE_RATE, N_FFT, HOP_SIZE, N_MELS, MEL_FMIN, MEL_FMAX,
    MIDI_MIN, MIDI_MAX, N_PITCHES, FRAME_RATE,
    CHECKPOINT_DIR,
)
from model import TranscriptionNet

def test_audio(wav_path: str):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Load model
    ckpt_path = os.path.join(CHECKPOINT_DIR, "best_model.pt")
    if not os.path.exists(ckpt_path):
        print("ERROR: No checkpoint found!")
        return

    model = TranscriptionNet().to(device)
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    print(f"Model loaded from epoch {ckpt.get('epoch', '?')}, val_loss={ckpt.get('val_loss', '?')}")

    # Load audio
    print(f"\nLoading: {wav_path}")
    waveform, sr = torchaudio.load(wav_path)
    print(f"  Sample rate: {sr}, Duration: {waveform.shape[-1]/sr:.1f}s, Channels: {waveform.shape[0]}")

    # Resample if needed
    if sr != SAMPLE_RATE:
        resampler = torchaudio.transforms.Resample(sr, SAMPLE_RATE)
        waveform = resampler(waveform)
        sr = SAMPLE_RATE
        print(f"  Resampled to {SAMPLE_RATE}Hz")

    # Convert to mono
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    # Process in segments
    mel_transform = torchaudio.transforms.MelSpectrogram(
        sample_rate=SAMPLE_RATE, n_fft=N_FFT, hop_length=HOP_SIZE,
        n_mels=N_MELS, f_min=MEL_FMIN, f_max=MEL_FMAX,
    ).to(device)

    segment_seconds = 8
    segment_samples = segment_seconds * SAMPLE_RATE
    total_samples = waveform.shape[-1]
    n_segments = (total_samples + segment_samples - 1) // segment_samples
    print(f"  Processing in {n_segments} segments of {segment_seconds}s")

    all_note_on = []
    all_note_off = []
    all_velocity = []

    with torch.no_grad():
        for i in range(n_segments):
            start = i * segment_samples
            end = min(start + segment_samples, total_samples)
            segment = waveform[:, start:end]

            # Pad if needed
            if segment.shape[-1] < segment_samples:
                pad = segment_samples - segment.shape[-1]
                segment = torch.nn.functional.pad(segment, (0, pad))

            # Compute mel
            audio_tensor = segment.to(device)
            mel = mel_transform(audio_tensor)
            mel = torch.log(mel + 1e-7)
            mean = mel.mean(dim=-1, keepdim=True)
            std = mel.std(dim=-1, keepdim=True)
            std = torch.clamp(std, min=1e-5)
            mel = (mel - mean) / std

            # Run model
            note_on, note_off, velocity = model(mel)

            all_note_on.append(note_on.squeeze(0).cpu().numpy())
            all_note_off.append(note_off.squeeze(0).cpu().numpy())
            all_velocity.append(velocity.squeeze(0).cpu().numpy())

    # Concatenate segments
    note_on = np.concatenate(all_note_on, axis=1)
    note_off = np.concatenate(all_note_off, axis=1)
    velocity = np.concatenate(all_velocity, axis=1)

    # Trim to actual audio length
    actual_frames = total_samples // HOP_SIZE
    note_on = note_on[:, :actual_frames]
    note_off = note_off[:, :actual_frames]
    velocity = velocity[:, :actual_frames]

    print(f"\n  Output shape: note_on={note_on.shape}, velocity={velocity.shape}")

    # Extract notes with lower threshold
    onset_threshold = 0.3
    notes = []
    for pitch_idx in range(N_PITCHES):
        on_probs = note_on[pitch_idx]
        # Find onset peaks
        on_frames = np.where(on_probs > onset_threshold)[0]
        if len(on_frames) == 0:
            continue

        # Group consecutive frames into note events
        groups = []
        current_group = [on_frames[0]]
        for j in range(1, len(on_frames)):
            if on_frames[j] - on_frames[j-1] <= 3:  # Allow 3-frame gap
                current_group.append(on_frames[j])
            else:
                groups.append(current_group)
                current_group = [on_frames[j]]
        groups.append(current_group)

        for group in groups:
            midi_pitch = pitch_idx + MIDI_MIN
            start_frame = group[0]
            start_time = start_frame / FRAME_RATE

            # Find offset: look for where velocity drops below threshold
            vel_track = velocity[pitch_idx, start_frame:]
            active_frames = np.where(vel_track > 0.2)[0]
            if len(active_frames) > 0:
                end_frame = start_frame + active_frames[-1]
            else:
                end_frame = start_frame + 5
            end_time = end_frame / FRAME_RATE

            # Minimum duration
            if end_time - start_time < 0.05:
                end_time = start_time + 0.05

            vel = velocity[pitch_idx, start_frame]
            notes.append({
                'pitch': midi_pitch,
                'start': start_time,
                'end': end_time,
                'velocity': vel,
            })

    # Sort by start time
    notes.sort(key=lambda n: n['start'])

    print(f"\n  Detected {len(notes)} notes (threshold={onset_threshold})")
    if notes:
        print(f"\n  First 20 notes:")
        for n in notes[:20]:
            pitch_name = pretty_midi.note_number_to_name(n['pitch'])
            print(f"    {pitch_name} (MIDI {n['pitch']}) "
                  f"start={n['start']:.2f}s end={n['end']:.2f}s vel={n['velocity']:.2f}")

    # Save as MIDI
    midi_output = pretty_midi.PrettyMIDI()
    piano = pretty_midi.Instrument(program=0)
    for n in notes:
        note = pretty_midi.Note(
            velocity=int(min(n['velocity'] * 127, 127)),
            pitch=n['pitch'],
            start=n['start'],
            end=n['end'],
        )
        piano.notes.append(note)
    midi_output.instruments.append(piano)

    out_midi = wav_path.replace('.wav', '_transcribed.mid').replace('.WAV', '_transcribed.mid')
    midi_output.write(out_midi)
    print(f"\n  Saved MIDI: {out_midi}")

    # Stats
    if notes:
        pitches = [n['pitch'] for n in notes]
        print(f"\n  Pitch range: {pretty_midi.note_number_to_name(min(pitches))} - "
              f"{pretty_midi.note_number_to_name(max(pitches))}")
        print(f"  Duration range: {min(n['end']-n['start'] for n in notes):.2f}s - "
              f"{max(n['end']-n['start'] for n in notes):.2f}s")
        print(f"  Avg velocity: {np.mean([n['velocity'] for n in notes]):.2f}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_audio(sys.argv[1])
    else:
        # Default test file
        test_path = r"C:\Users\Administrator\Desktop\多多\测试\尸蜡.wav"
        if os.path.exists(test_path):
            test_audio(test_path)
        else:
            print(f"Test file not found: {test_path}")
