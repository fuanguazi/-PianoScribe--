"""
Precompute mel spectrograms + labels from audio+MIDI pairs.
Processes in batches, deletes WAV after precompute to save disk.
"""
import os
import shutil
import torch
import torchaudio
import numpy as np
import pretty_midi
from tqdm import tqdm

from config import (
    SAMPLE_RATE, N_FFT, HOP_SIZE, N_MELS, MEL_FMIN, MEL_FMAX,
    MIDI_MIN, MIDI_MAX, N_PITCHES, FRAME_RATE, DATA_DIR,
    MIN_FREE_GB, PRECOMPUTE_BATCH,
)
from dataset import midi_to_labels

mel_transform = torchaudio.transforms.MelSpectrogram(
    sample_rate=SAMPLE_RATE,
    n_fft=N_FFT,
    hop_length=HOP_SIZE,
    n_mels=N_MELS,
    f_min=MEL_FMIN,
    f_max=MEL_FMAX,
)

resamplers: dict[int, torchaudio.transforms.Resample] = {}

def get_resampler(orig_sr: int) -> torchaudio.transforms.Resample:
    if orig_sr not in resamplers:
        resamplers[orig_sr] = torchaudio.transforms.Resample(orig_sr, SAMPLE_RATE)
    return resamplers[orig_sr]


def compute_mel(audio: torch.Tensor, sr: int) -> torch.Tensor:
    if sr != SAMPLE_RATE:
        audio = get_resampler(sr)(audio)
    mel = mel_transform(audio)
    mel = torch.log(mel + 1e-7)
    mean = mel.mean(dim=-1, keepdim=True)
    std = mel.std(dim=-1, keepdim=True)
    std = torch.clamp(std, min=1e-5)
    mel = (mel - mean) / std
    return mel.squeeze(0)


def get_free_disk_gb(path: str) -> float:
    """Get free disk space in GB."""
    usage = shutil.disk_usage(path)
    return usage.free / (1024 ** 3)


def precompute_split(split: str, delete_wav: bool = False):
    split_dir = os.path.join(DATA_DIR, split)
    cache_dir = os.path.join(split_dir, "_precomputed")
    os.makedirs(cache_dir, exist_ok=True)

    # Find all audio+MIDI pairs
    audio_files = []
    for root, dirs, files in os.walk(split_dir):
        if "_precomputed" in root:
            continue
        for f in files:
            if f.lower().endswith((".wav", ".mp3", ".flac")):
                audio_files.append(os.path.join(root, f))

    # Skip already done
    already_done = set()
    for f in os.listdir(cache_dir):
        if f.endswith(".pt"):
            already_done.add(f.replace(".pt", ""))

    todo = []
    for audio_path in audio_files:
        base = os.path.splitext(os.path.basename(audio_path))[0]
        if base in already_done:
            continue
        midi_candidates = [
            os.path.join(os.path.dirname(audio_path), base + ext)
            for ext in [".mid", ".midi", ".MID", ".MIDI"]
        ]
        midi_path = None
        for mc in midi_candidates:
            if os.path.exists(mc):
                midi_path = mc
                break
        if midi_path:
            todo.append((audio_path, midi_path))

    print(f"Precomputing {split}: {len(todo)} files to process, {len(already_done)} already done")

    success = 0
    failed = 0
    wav_deleted = 0

    for i, (audio_path, midi_path) in enumerate(tqdm(todo, desc=f"Precomputing {split}")):
        base = os.path.splitext(os.path.basename(audio_path))[0]

        # Check disk space periodically
        if i % PRECOMPUTE_BATCH == 0 and i > 0:
            free_gb = get_free_disk_gb(DATA_DIR)
            if free_gb < MIN_FREE_GB:
                print(f"\n  WARNING: Only {free_gb:.1f} GB free on disk. Stopping precompute.")
                break

        try:
            audio, sr = torchaudio.load(audio_path)
            audio = audio.float()
            if audio.dim() > 1:
                audio = audio.mean(dim=0, keepdim=True)

            duration = audio.shape[-1] / sr
            mel = compute_mel(audio, sr)
            note_on, note_off, velocity = midi_to_labels(midi_path, duration)

            n_frames = min(mel.shape[-1], note_on.shape[-1])
            mel = mel[:, :n_frames]
            note_on = note_on[:, :n_frames]
            note_off = note_off[:, :n_frames]
            velocity = velocity[:, :n_frames]

            torch.save(
                {
                    "mel": mel,
                    "note_on": note_on,
                    "note_off": note_off,
                    "velocity": velocity,
                },
                os.path.join(cache_dir, base + ".pt"),
            )
            success += 1

            # Delete WAV after successful precompute to save disk
            if delete_wav and audio_path.lower().endswith(".wav"):
                try:
                    os.remove(audio_path)
                    wav_deleted += 1
                except:
                    pass

        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"\n  Error processing {base}: {e}")

    print(f"  {split}: {success} computed, {failed} failed, {wav_deleted} WAVs deleted")
    print(f"  Disk free: {get_free_disk_gb(DATA_DIR):.1f} GB")


if __name__ == "__main__":
    for split in ["train", "validation"]:
        split_dir = os.path.join(DATA_DIR, split)
        if os.path.exists(split_dir):
            precompute_split(split, delete_wav=True)
    print("\nPrecomputation complete! Now run: python train.py")
