"""
Simple precomputation: MIDI -> mel+labels .pt files.
Tested and verified to save correctly.
"""
import os
import sys
import random
import shutil

import torch
import torchaudio
import numpy as np
import pretty_midi

from config import (
    SAMPLE_RATE, N_FFT, HOP_SIZE, N_MELS, MEL_FMIN, MEL_FMAX,
    MIDI_MIN, MIDI_MAX, N_PITCHES, FRAME_RATE, DATA_DIR,
    SEGMENT_FRAMES,
)
from dataset import midi_to_labels

MAESTRO_DIR = os.path.join(DATA_DIR, "maestro-v3.0.0")

mel_transform = torchaudio.transforms.MelSpectrogram(
    sample_rate=SAMPLE_RATE, n_fft=N_FFT, hop_length=HOP_SIZE,
    n_mels=N_MELS, f_min=MEL_FMIN, f_max=MEL_FMAX,
)


def process_one(midi_path: str) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor] | None:
    """Process single MIDI file -> mel + labels."""
    pm = pretty_midi.PrettyMIDI(midi_path)
    audio = pm.synthesize(fs=SAMPLE_RATE)
    if len(audio) < SAMPLE_RATE * 2:
        return None

    peak = np.abs(audio).max()
    if peak > 0:
        audio = audio / peak * 0.9
    audio = audio.astype(np.float32)

    # Mel spectrogram
    audio_tensor = torch.from_numpy(audio).float().unsqueeze(0)
    mel = mel_transform(audio_tensor)
    mel = torch.log(mel + 1e-7)
    mean = mel.mean(dim=-1, keepdim=True)
    std = mel.std(dim=-1, keepdim=True)
    std = torch.clamp(std, min=1e-5)
    mel = (mel - mean) / std
    mel = mel.squeeze(0)

    # Labels
    duration = len(audio) / SAMPLE_RATE
    note_on, note_off, velocity = midi_to_labels(midi_path, duration)

    n_frames = min(mel.shape[-1], note_on.shape[-1])
    return mel[:, :n_frames], note_on[:, :n_frames], note_off[:, :n_frames], velocity[:, :n_frames]


def main():
    # Find all MIDI files
    midis = []
    for root, dirs, files in os.walk(MAESTRO_DIR):
        for f in files:
            if f.lower().endswith((".mid", ".midi")):
                midis.append(os.path.join(root, f))
    midis.sort()
    print(f"Found {len(midis)} MIDI files")

    random.seed(42)
    random.shuffle(midis)
    split_idx = int(len(midis) * 0.9)

    for label, midi_list in [("train", midis[:split_idx]), ("validation", midis[split_idx:])]:
        out_dir = os.path.join(DATA_DIR, label, "_precomputed")
        os.makedirs(out_dir, exist_ok=True)

        # Check existing
        done = {f.replace(".pt", "") for f in os.listdir(out_dir) if f.endswith(".pt")}
        print(f"\n{label}: {len(done)} already done")

        ok = fail = skip = 0
        for i, mp in enumerate(midi_list):
            base = "".join(c if c.isalnum() or c in "-_." else "_" for c in os.path.splitext(os.path.basename(mp))[0])

            if base in done:
                skip += 1
                continue

            try:
                result = process_one(mp)
                if result is None:
                    fail += 1
                    continue

                mel, on, off, vel = result
                path = os.path.join(out_dir, base + ".pt")
                torch.save({"mel": mel, "note_on": on, "note_off": off, "velocity": vel}, path)

                # Verify
                assert os.path.exists(path), f"File not saved: {path}"
                ok += 1
            except Exception as e:
                fail += 1
                if fail <= 3:
                    print(f"  FAIL: {base} -> {e}")

            if (i + 1) % 100 == 0:
                free = shutil.disk_usage(DATA_DIR).free / 1024**3
                print(f"  {label} [{i+1}/{len(midi_list)}]: {ok} ok, {fail} fail, {skip} skip | Disk: {free:.0f}GB")

        print(f"  {label} FINAL: {ok} ok, {fail} fail, {skip} skip")


if __name__ == "__main__":
    main()
