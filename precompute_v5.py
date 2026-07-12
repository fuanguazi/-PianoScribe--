"""
Step 1: Precompute all mel+labels to disk as .pt files.
Each chunk of 100 MIDI files -> one .pt file containing TensorDataset.
Run this FIRST, then run train_from_precomputed.py.
"""
import os
import sys
import time
import random
import gc

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import pretty_midi
import torchaudio

from config import (
    SAMPLE_RATE, N_FFT, HOP_SIZE, N_MELS, MEL_FMIN, MEL_FMAX,
    MIDI_MIN, MIDI_MAX, N_PITCHES, FRAME_RATE,
    DATA_DIR, SEGMENT_FRAMES,
)

MAESTRO_DIR = os.path.join(DATA_DIR, "maestro-v3.0.0")
OUTPUT_DIR = os.path.join(DATA_DIR, "precomputed_chunks")
CHUNK_SIZE = 100
SEGMENTS_TRAIN = 6
SEGMENTS_VAL = 2


def midi_to_labels(midi_path: str, duration: float):
    n_frames = int(duration * FRAME_RATE) + 1
    note_on = np.zeros((N_PITCHES, n_frames), dtype=np.float32)
    note_off = np.zeros((N_PITCHES, n_frames), dtype=np.float32)
    velocity = np.zeros((N_PITCHES, n_frames), dtype=np.float32)
    pm = pretty_midi.PrettyMIDI(midi_path)
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for note in inst.notes:
            p = note.pitch
            if p < MIDI_MIN or p > MIDI_MAX:
                continue
            idx = p - MIDI_MIN
            s = max(0, min(int(note.start * FRAME_RATE), n_frames - 1))
            e = max(0, min(int(note.end * FRAME_RATE), n_frames - 1))
            note_on[idx, s] = 1.0
            note_off[idx, e] = 1.0
            velocity[idx, s:e+1] = np.maximum(velocity[idx, s:e+1], note.velocity / 127.0)
    return note_on, note_off, velocity


def precompute_chunk(midi_files, output_path, device, augment, segments_per_file):
    """Precompute a chunk and save to .pt file."""
    all_mel = []
    all_on = []
    all_off = []
    all_vel = []

    mel_transform_gpu = torchaudio.transforms.MelSpectrogram(
        sample_rate=SAMPLE_RATE, n_fft=N_FFT, hop_length=HOP_SIZE,
        n_mels=N_MELS, f_min=MEL_FMIN, f_max=MEL_FMAX,
    ).to(device)

    for mp in midi_files:
        try:
            pm = pretty_midi.PrettyMIDI(mp)
            audio = pm.synthesize(fs=SAMPLE_RATE)
            if len(audio) < SAMPLE_RATE * 2:
                continue

            peak = np.abs(audio).max()
            if peak > 0:
                audio = audio / peak * 0.9
            audio = audio.astype(np.float32)

            if augment:
                gain = random.uniform(0.6, 1.0)
                audio = audio * gain

            duration = len(audio) / SAMPLE_RATE
            audio_tensor = torch.from_numpy(audio).float().unsqueeze(0).to(device)
            del audio

            with torch.no_grad():
                mel = mel_transform_gpu(audio_tensor)
                mel = torch.log(mel + 1e-7)
                mean = mel.mean(dim=-1, keepdim=True)
                std = mel.std(dim=-1, keepdim=True)
                std = torch.clamp(std, min=1e-5)
                mel = (mel - mean) / std
            mel = mel.squeeze(0).cpu()
            del audio_tensor

            note_on, note_off, velocity = midi_to_labels(mp, duration)
            del pm
            n_frames = min(mel.shape[-1], note_on.shape[-1])

            for seg in range(segments_per_file):
                if augment:
                    start = random.randint(0, max(0, n_frames - SEGMENT_FRAMES))
                else:
                    if n_frames <= SEGMENT_FRAMES:
                        start = 0
                    else:
                        total_space = n_frames - SEGMENT_FRAMES
                        start = (seg * total_space) // max(segments_per_file, 1)

                end = start + SEGMENT_FRAMES

                mel_seg = mel[:, start:min(end, n_frames)]
                on_seg = note_on[:, start:min(end, n_frames)]
                off_seg = note_off[:, start:min(end, n_frames)]
                vel_seg = velocity[:, start:min(end, n_frames)]

                if mel_seg.shape[-1] < SEGMENT_FRAMES:
                    pad = SEGMENT_FRAMES - mel_seg.shape[-1]
                    mel_seg = F.pad(mel_seg, (0, pad))
                    on_seg = np.pad(on_seg, ((0,0),(0,pad)))
                    off_seg = np.pad(off_seg, ((0,0),(0,pad)))
                    vel_seg = np.pad(vel_seg, ((0,0),(0,pad)))

                all_mel.append(mel_seg)
                all_on.append(torch.from_numpy(on_seg.copy()))
                all_off.append(torch.from_numpy(off_seg.copy()))
                all_vel.append(torch.from_numpy(vel_seg.copy()))

        except Exception as e:
            continue

    del mel_transform_gpu
    torch.cuda.empty_cache()

    if not all_mel:
        print(f"  WARNING: No data for this chunk!")
        return False

    # Stack and save
    mel_tensor = torch.stack(all_mel)
    on_tensor = torch.stack(all_on)
    off_tensor = torch.stack(all_off)
    vel_tensor = torch.stack(all_vel)

    torch.save({
        'mel': mel_tensor,
        'on': on_tensor,
        'off': off_tensor,
        'vel': vel_tensor,
    }, output_path)

    size_mb = os.path.getsize(output_path) / 1024**2
    print(f"  Saved {output_path} ({len(all_mel)} segments, {size_mb:.1f} MB)")

    # Free memory
    del mel_tensor, on_tensor, off_tensor, vel_tensor, all_mel, all_on, all_off, all_vel
    gc.collect()

    return True


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Find MIDI files
    midis = []
    for root, dirs, files in os.walk(MAESTRO_DIR):
        for f in files:
            if f.lower().endswith((".mid", ".midi")):
                midis.append(os.path.join(root, f))
    midis.sort()
    random.seed(42)
    random.shuffle(midis)
    split_idx = int(len(midis) * 0.9)
    train_midis = midis[:split_idx]
    val_midis = midis[split_idx:]
    print(f"Train: {len(train_midis)}, Val: {len(val_midis)}")

    # Create output dirs
    train_dir = os.path.join(OUTPUT_DIR, "train")
    val_dir = os.path.join(OUTPUT_DIR, "val")
    os.makedirs(train_dir, exist_ok=True)
    os.makedirs(val_dir, exist_ok=True)

    # Check existing chunks
    existing_train = len([f for f in os.listdir(train_dir) if f.endswith('.pt')])
    existing_val = len([f for f in os.listdir(val_dir) if f.endswith('.pt')])
    print(f"Existing train chunks: {existing_train}, val chunks: {existing_val}")

    # Precompute train chunks
    train_chunks = [train_midis[i:i+CHUNK_SIZE] for i in range(0, len(train_midis), CHUNK_SIZE)]
    print(f"\n=== Precomputing {len(train_chunks)} train chunks ===")

    t0 = time.time()
    for ci, chunk in enumerate(train_chunks):
        out_path = os.path.join(train_dir, f"chunk_{ci:03d}.pt")
        if os.path.exists(out_path):
            print(f"  Chunk {ci+1}/{len(train_chunks)} already exists, skipping")
            continue

        print(f"  Processing chunk {ci+1}/{len(train_chunks)} ({len(chunk)} files)...")
        precompute_chunk(chunk, out_path, device, augment=True, segments_per_file=SEGMENTS_TRAIN)

        elapsed = time.time() - t0
        done = ci + 1
        eta = elapsed / done * (len(train_chunks) - done)
        print(f"  Progress: {done}/{len(train_chunks)}, ETA: {eta:.0f}s")

    # Precompute val chunks
    val_chunks = [val_midis[i:i+CHUNK_SIZE] for i in range(0, len(val_midis), CHUNK_SIZE)]
    print(f"\n=== Precomputing {len(val_chunks)} val chunks ===")

    for ci, chunk in enumerate(val_chunks):
        out_path = os.path.join(val_dir, f"chunk_{ci:03d}.pt")
        if os.path.exists(out_path):
            print(f"  Val chunk {ci+1}/{len(val_chunks)} already exists, skipping")
            continue

        print(f"  Processing val chunk {ci+1}/{len(val_chunks)} ({len(chunk)} files)...")
        precompute_chunk(chunk, out_path, device, augment=False, segments_per_file=SEGMENTS_VAL)

    # Verify
    train_files = [f for f in os.listdir(train_dir) if f.endswith('.pt')]
    val_files = [f for f in os.listdir(val_dir) if f.endswith('.pt')]
    print(f"\nDone! Train chunks: {len(train_files)}, Val chunks: {len(val_files)}")

    # Quick load test
    if train_files:
        test = torch.load(os.path.join(train_dir, train_files[0]), weights_only=True)
        print(f"Sample chunk: mel={test['mel'].shape}, on={test['on'].shape}")


if __name__ == "__main__":
    main()
