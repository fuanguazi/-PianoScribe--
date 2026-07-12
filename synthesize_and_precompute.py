"""
One-step: synthesize audio from MIDI + precompute mel+labels.
Fixed version with proper error handling and file naming.
"""
import os
import sys
import random
import shutil
import traceback

import torch
import torchaudio
import numpy as np
import pretty_midi

from config import (
    SAMPLE_RATE, N_FFT, HOP_SIZE, N_MELS, MEL_FMIN, MEL_FMAX,
    MIDI_MIN, MIDI_MAX, N_PITCHES, FRAME_RATE, DATA_DIR,
    SEGMENT_FRAMES, MIN_FREE_GB,
)
from dataset import midi_to_labels

MAESTRO_MIDI_DIR = os.path.join(DATA_DIR, "maestro-v3.0.0")

mel_transform = torchaudio.transforms.MelSpectrogram(
    sample_rate=SAMPLE_RATE,
    n_fft=N_FFT,
    hop_length=HOP_SIZE,
    n_mels=N_MELS,
    f_min=MEL_FMIN,
    f_max=MEL_FMAX,
)


def compute_mel_from_array(audio: np.ndarray, sr: int) -> torch.Tensor:
    audio_tensor = torch.from_numpy(audio).float().unsqueeze(0)
    if sr != SAMPLE_RATE:
        audio_tensor = torchaudio.transforms.Resample(sr, SAMPLE_RATE)(audio_tensor)
    mel = mel_transform(audio_tensor)
    mel = torch.log(mel + 1e-7)
    mean = mel.mean(dim=-1, keepdim=True)
    std = mel.std(dim=-1, keepdim=True)
    std = torch.clamp(std, min=1e-5)
    mel = (mel - mean) / std
    return mel.squeeze(0)


def find_midi_files() -> list[str]:
    midis = []
    if not os.path.exists(MAESTRO_MIDI_DIR):
        return midis
    for root, dirs, files in os.walk(MAESTRO_MIDI_DIR):
        for f in files:
            if f.lower().endswith((".mid", ".midi")):
                midis.append(os.path.join(root, f))
    return sorted(midis)


def safe_filename(name: str) -> str:
    """Make a filename safe for Windows filesystem."""
    keepchars = (" ", "_", "-", ".")
    return "".join(c for c in name if c.isalnum() or c in keepchars).rstrip()


def main():
    midi_files = find_midi_files()
    print(f"Found {len(midi_files)} MIDI files in MAESTRO")

    if not midi_files:
        print("ERROR: No MIDI files found.")
        return

    random.seed(42)
    random.shuffle(midi_files)
    split_idx = int(len(midi_files) * 0.9)
    train_midis = midi_files[:split_idx]
    val_midis = midi_files[split_idx:]

    for split, midis in [("train", train_midis), ("validation", val_midis)]:
        cache_dir = os.path.join(DATA_DIR, split, "_precomputed")
        os.makedirs(cache_dir, exist_ok=True)

        # Check already done
        already_done = set()
        for f in os.listdir(cache_dir):
            if f.endswith(".pt"):
                already_done.add(f.replace(".pt", ""))

        success = 0
        failed = 0
        skipped = 0

        for i, midi_path in enumerate(midis):
            base = safe_filename(os.path.splitext(os.path.basename(midi_path))[0])

            if not base:
                base = f"piece_{i:04d}"

            if base in already_done:
                skipped += 1
                continue

            try:
                # Synthesize
                pm = pretty_midi.PrettyMIDI(midi_path)
                audio = pm.synthesize(fs=SAMPLE_RATE)
                if len(audio) < SAMPLE_RATE * 2:
                    failed += 1
                    continue

                peak = np.abs(audio).max()
                if peak > 0:
                    audio = audio / peak * 0.9
                audio = audio.astype(np.float32)

                # Augment for training
                if split == "train":
                    gain = random.uniform(0.6, 1.0)
                    audio = audio * gain

                # Compute mel
                mel = compute_mel_from_array(audio, SAMPLE_RATE)

                # Compute labels
                duration = len(audio) / SAMPLE_RATE
                note_on, note_off, velocity = midi_to_labels(midi_path, duration)

                n_frames = min(mel.shape[-1], note_on.shape[-1])
                mel = mel[:, :n_frames]
                note_on = note_on[:, :n_frames]
                note_off = note_off[:, :n_frames]
                velocity = velocity[:, :n_frames]

                # Save
                save_path = os.path.join(cache_dir, base + ".pt")
                torch.save({
                    "mel": mel,
                    "note_on": note_on,
                    "note_off": note_off,
                    "velocity": velocity,
                }, save_path)

                # Verify
                if os.path.exists(save_path):
                    success += 1
                else:
                    failed += 1
                    print(f"  ERROR: File not saved: {save_path}")

            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"  Error processing {base}: {e}")
                    traceback.print_exc()

            if (i + 1) % 50 == 0:
                free_gb = shutil.disk_usage(DATA_DIR).free / 1024**3
                print(f"  {split}: {i+1}/{len(midis)} ({success} ok, {failed} fail, {skipped} skip) Disk: {free_gb:.0f}GB")

        print(f"  {split} done: {success} computed, {failed} failed, {skipped} skipped")

    print("\nPrecomputation complete! Run: python train.py")


if __name__ == "__main__":
    main()
