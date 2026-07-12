"""
Training script v5: Streaming precompute to avoid OOM.
Instead of loading ALL data into memory at once, we:
1. Precompute mel+labels in chunks and save to .pt files on disk
2. Use a ChunkedDataset that loads one chunk at a time
3. Train on each chunk, then rotate to next chunk

This avoids the OOM crash from torch.stack() on all 6900+ segments.
"""
import os
import sys
import time
import random
import subprocess
import gc
import glob

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import pretty_midi
import torchaudio
from torch.amp import autocast, GradScaler
from torch.utils.data import Dataset, DataLoader, TensorDataset, ConcatDataset
from torch.optim import AdamW
from torch.optim.lr_scheduler import OneCycleLR

from config import (
    SAMPLE_RATE, N_FFT, HOP_SIZE, N_MELS, MEL_FMIN, MEL_FMAX,
    MIDI_MIN, MIDI_MAX, N_PITCHES, FRAME_RATE,
    BATCH_SIZE, LEARNING_RATE, NUM_EPOCHS,
    CHECKPOINT_DIR, EXPORT_DIR, DATA_DIR,
    FOCAL_ALPHA, FOCAL_GAMMA, SEGMENT_FRAMES,
    LOSS_WEIGHT_ONSET, LOSS_WEIGHT_OFFSET, LOSS_WEIGHT_VELOCITY,
)
from model import TranscriptionNet

MAESTRO_DIR = os.path.join(DATA_DIR, "maestro-v3.0.0")
PRECOMPUTE_DIR = os.path.join(DATA_DIR, "precomputed_v5")

# Training params
BATCH_SIZE = 128
GRAD_ACCUM = 2
SEGMENTS_PER_FILE_TRAIN = 6
SEGMENTS_PER_FILE_VAL = 2
CHUNK_SIZE = 100  # Precompute 100 files at a time, then save to disk


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


def precompute_chunk(midi_files, chunk_idx, device, augment, segments_per_file):
    """Precompute a chunk of files and save to .pt file."""
    all_mel = []
    all_on = []
    all_off = []
    all_vel = []

    mel_transform_gpu = torchaudio.transforms.MelSpectrogram(
        sample_rate=SAMPLE_RATE, n_fft=N_FFT, hop_length=HOP_SIZE,
        n_mels=N_MELS, f_min=MEL_FMIN, f_max=MEL_FMAX,
    ).to(device)

    for i, mp in enumerate(midi_files):
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
            del audio_tensor, pm

            note_on, note_off, velocity = midi_to_labels(mp, duration)
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
    gc.collect()

    if not all_mel:
        return None

    # Stack and save
    mel_tensor = torch.stack(all_mel)
    on_tensor = torch.stack(all_on)
    off_tensor = torch.stack(all_off)
    vel_tensor = torch.stack(all_vel)

    return TensorDataset(mel_tensor, on_tensor, off_tensor, vel_tensor)


class FocalLoss(nn.Module):
    def __init__(self, alpha=FOCAL_ALPHA, gamma=FOCAL_GAMMA):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma

    def forward(self, logits, target):
        bce = F.binary_cross_entropy_with_logits(logits, target, reduction="none")
        prob = torch.sigmoid(logits)
        pt = target * prob + (1 - target) * (1 - prob)
        fw = (1 - pt) ** self.gamma
        aw = target * self.alpha + (1 - target) * (1 - self.alpha)
        return (aw * fw * bce).mean()


class VelocityLoss(nn.Module):
    def forward(self, pred, target, mask):
        diff = (pred - target) ** 2
        if mask.sum() > 0:
            return (diff * mask).sum() / (mask.sum() + 1e-8)
        return diff.mean()


def get_gpu_util():
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total',
                          '--format=csv,noheader,nounits'],
                          capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            parts = r.stdout.strip().split(',')
            return float(parts[0]), float(parts[1]), float(parts[2])
    except:
        pass
    return -1, 0, 0


def train():
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"VRAM: {vram:.1f} GB")

    torch.backends.cudnn.benchmark = True
    torch.backends.cudnn.deterministic = False

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
    print(f"Train MIDI: {len(train_midis)}, Val MIDI: {len(val_midis)}")

    # Model
    model = TranscriptionNet().to(device)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {total_params:,}")

    # Training wrapper
    class TrainWrapper(nn.Module):
        def __init__(self, net):
            super().__init__()
            self.net = net
        def forward(self, x):
            h = self.net.frontend(x)
            h = self.net.res1(h)
            h = self.net.trans1(h)
            h = self.net.res2(h)
            h = self.net.trans2(h)
            h = self.net.res3(h)
            on_logits = self.net.note_on_head[:-1](h)
            off_logits = self.net.note_off_head[:-1](h)
            vel_logits = self.net.velocity_head[:-1](h)
            vel = torch.sigmoid(vel_logits)
            return on_logits, off_logits, vel

    train_model = TrainWrapper(model).to(device)

    # Resume
    start_epoch = 0
    best_val_loss = float("inf")
    ckpt_path = os.path.join(CHECKPOINT_DIR, "best_model.pt")
    if os.path.exists(ckpt_path):
        ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
        try:
            model.load_state_dict(ckpt["model_state_dict"], strict=False)
            start_epoch = ckpt.get("epoch", 0) + 1
            best_val_loss = ckpt.get("val_loss", float("inf"))
            print(f"Resumed from epoch {start_epoch}, val_loss={best_val_loss:.4f}")
        except Exception as e:
            print(f"Could not resume: {e}")

    focal = FocalLoss()
    vel_loss_fn = VelocityLoss()
    optimizer = AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)
    scaler = GradScaler("cuda")

    # Split train_midis into chunks
    train_chunks = [train_midis[i:i+CHUNK_SIZE] for i in range(0, len(train_midis), CHUNK_SIZE)]
    print(f"Train chunks: {len(train_chunks)} ({CHUNK_SIZE} files each)")

    print(f"\n{'='*80}")
    print(f"Training from epoch {start_epoch} to {start_epoch + NUM_EPOCHS}")
    print(f"Batch: {BATCH_SIZE}, Accum: {GRAD_ACCUM}, Effective: {BATCH_SIZE*GRAD_ACCUM}")
    print(f"Strategy: Stream chunks of {CHUNK_SIZE} files, train on each chunk")
    print(f"{'='*80}")

    for epoch in range(start_epoch, start_epoch + NUM_EPOCHS):
        model.train()
        epoch_loss = 0.0
        epoch_batches = 0
        epoch_start = time.time()

        # Create scheduler per epoch
        # Estimate total steps: chunks * batches_per_chunk
        total_steps_est = len(train_chunks) * (CHUNK_SIZE * SEGMENTS_PER_FILE_TRAIN // BATCH_SIZE)
        scheduler = OneCycleLR(optimizer, max_lr=LEARNING_RATE, epochs=1,
                              steps_per_epoch=max(total_steps_est, 1), pct_start=0.1)

        for chunk_idx, chunk_midis in enumerate(train_chunks):
            # Precompute chunk to memory
            chunk_ds = precompute_chunk(chunk_midis, chunk_idx, device,
                                        augment=True, segments_per_file=SEGMENTS_PER_FILE_TRAIN)
            if chunk_ds is None:
                continue

            chunk_loader = DataLoader(chunk_ds, batch_size=BATCH_SIZE, shuffle=True,
                                      num_workers=0, pin_memory=True, drop_last=True)

            optimizer.zero_grad(set_to_none=True)

            for batch_idx, (mel, on_t, off_t, vel_t) in enumerate(chunk_loader):
                mel = mel.to(device, non_blocking=True)
                on_t = on_t.to(device, non_blocking=True)
                off_t = off_t.to(device, non_blocking=True)
                vel_t = vel_t.to(device, non_blocking=True)

                with autocast(device_type="cuda"):
                    pred_on, pred_off, pred_vel = train_model(mel)
                    l_on = focal(pred_on, on_t)
                    l_off = focal(pred_off, off_t)
                    mask = (on_t > 0.5).float()
                    l_vel = vel_loss_fn(pred_vel, vel_t, mask)
                    loss = LOSS_WEIGHT_ONSET * l_on + LOSS_WEIGHT_OFFSET * l_off + LOSS_WEIGHT_VELOCITY * l_vel
                    loss = loss / GRAD_ACCUM

                scaler.scale(loss).backward()

                if (batch_idx + 1) % GRAD_ACCUM == 0:
                    scaler.unscale_(optimizer)
                    nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                    scaler.step(optimizer)
                    scaler.update()
                    optimizer.zero_grad(set_to_none=True)
                    scheduler.step()

                epoch_loss += loss.item() * GRAD_ACCUM
                epoch_batches += 1

            # Free chunk memory
            del chunk_ds, chunk_loader
            gc.collect()
            torch.cuda.empty_cache()

            if (chunk_idx + 1) % 3 == 0:
                gpu, mem_used, mem_total = get_gpu_util()
                elapsed = time.time() - epoch_start
                print(f"  E{epoch+1} chunk {chunk_idx+1}/{len(train_chunks)} "
                      f"Loss:{epoch_loss/max(epoch_batches,1):.4f} "
                      f"GPU:{gpu:.0f}% VRAM:{mem_used:.0f}/{mem_total:.0f}MB "
                      f"Time:{elapsed:.0f}s")

        avg_train = epoch_loss / max(epoch_batches, 1)

        # Validation - precompute all val data at once (smaller set)
        print(f"  Computing validation...")
        val_ds = precompute_chunk(val_midis, 0, device,
                                  augment=False, segments_per_file=SEGMENTS_PER_FILE_VAL)
        if val_ds is not None:
            val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                                    num_workers=0, pin_memory=True)
            model.eval()
            val_loss = 0.0
            vb = 0
            with torch.no_grad():
                for mel, on_t, off_t, vel_t in val_loader:
                    mel = mel.to(device, non_blocking=True)
                    on_t = on_t.to(device, non_blocking=True)
                    off_t = off_t.to(device, non_blocking=True)
                    vel_t = vel_t.to(device, non_blocking=True)
                    with autocast(device_type="cuda"):
                        pred_on, pred_off, pred_vel = train_model(mel)
                        l_on = focal(pred_on, on_t)
                        l_off = focal(pred_off, off_t)
                        mask = (on_t > 0.5).float()
                        l_vel = vel_loss_fn(pred_vel, vel_t, mask)
                        loss = LOSS_WEIGHT_ONSET * l_on + LOSS_WEIGHT_OFFSET * l_off + LOSS_WEIGHT_VELOCITY * l_vel
                    val_loss += loss.item()
                    vb += 1
            avg_val = val_loss / max(vb, 1)
            del val_ds, val_loader
            gc.collect()
            torch.cuda.empty_cache()
        else:
            avg_val = float("inf")

        epoch_time = time.time() - epoch_start
        gpu, mem_used, mem_total = get_gpu_util()

        print(f"\nEpoch {epoch+1}: Train:{avg_train:.4f} Val:{avg_val:.4f} "
              f"Time:{epoch_time:.0f}s GPU:{gpu:.0f}%")
        print("-" * 80)

        if avg_val < best_val_loss:
            best_val_loss = avg_val
            torch.save({"epoch": epoch, "model_state_dict": model.state_dict(),
                        "optimizer_state_dict": optimizer.state_dict(),
                        "val_loss": avg_val, "train_loss": avg_train}, ckpt_path)
            print(f"  -> Best model saved (val_loss={avg_val:.4f})")

        if (epoch + 1) % 5 == 0:
            torch.save({"epoch": epoch, "model_state_dict": model.state_dict(),
                        "optimizer_state_dict": optimizer.state_dict(),
                        "val_loss": avg_val, "train_loss": avg_train},
                      os.path.join(CHECKPOINT_DIR, f"checkpoint_epoch{epoch+1}.pt"))

    print(f"\nTraining complete! Best val loss: {best_val_loss:.4f}")


if __name__ == "__main__":
    train()
