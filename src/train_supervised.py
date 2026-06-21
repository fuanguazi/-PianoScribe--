"""Pure supervised CRNN training - no GAN instability.

Trains TranscriptionCRNN with BCEWithLogitsLoss + MSE loss.
All data loaded into memory for max GPU throughput.
"""
import os
import sys
import time
import random
import subprocess
import gc
import argparse

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from torch.amp import autocast, GradScaler
from torch.utils.data import DataLoader, TensorDataset
from torch.optim import AdamW

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    SAMPLE_RATE, N_FFT, HOP_SIZE, N_MELS, MEL_FMIN, MEL_FMAX,
    MIDI_MIN, MIDI_MAX, N_PITCHES, FRAME_RATE,
    BATCH_SIZE, NUM_EPOCHS,
    SEGMENT_FRAMES,
    CHECKPOINT_DIR, PRECOMPUTE_DIR,
)
from model import TranscriptionCRNN


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
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

    torch.backends.cudnn.benchmark = True

    # Load ALL data into memory
    train_dir = os.path.join(PRECOMPUTE_DIR, "train")
    val_dir = os.path.join(PRECOMPUTE_DIR, "val")
    train_chunk_files = sorted([
        os.path.join(train_dir, f) for f in os.listdir(train_dir) if f.endswith('.pt')
    ])
    val_chunk_files = sorted([
        os.path.join(val_dir, f) for f in os.listdir(val_dir) if f.endswith('.pt')
    ])

    if not train_chunk_files:
        print("ERROR: No precomputed data! Run train_adversarial.py --precompute first.")
        return

    print(f"Loading {len(train_chunk_files)} train chunks + {len(val_chunk_files)} val chunks...")
    t0 = time.time()

    all_mel, all_on, all_off, all_fr, all_vel = [], [], [], [], []
    for cf in train_chunk_files:
        d = torch.load(cf, weights_only=True)
        all_mel.append(d['mel'])
        all_on.append(d['onset'].permute(0, 2, 1))   # [N, T, 88]
        all_off.append(d['offset'].permute(0, 2, 1))
        all_fr.append(d['frame'].permute(0, 2, 1))
        all_vel.append(d['velocity'].permute(0, 2, 1))

    val_mel_list, val_on_list, val_off_list, val_fr_list, val_vel_list = [], [], [], [], []
    for cf in val_chunk_files:
        d = torch.load(cf, weights_only=True)
        val_mel_list.append(d['mel'])
        val_on_list.append(d['onset'].permute(0, 2, 1))
        val_off_list.append(d['offset'].permute(0, 2, 1))
        val_fr_list.append(d['frame'].permute(0, 2, 1))
        val_vel_list.append(d['velocity'].permute(0, 2, 1))

    train_mel = torch.cat(all_mel, dim=0)
    train_on = torch.cat(all_on, dim=0)
    train_off = torch.cat(all_off, dim=0)
    train_fr = torch.cat(all_fr, dim=0)
    train_vel = torch.cat(all_vel, dim=0)
    del all_mel, all_on, all_off, all_fr, all_vel

    val_mel = torch.cat(val_mel_list, dim=0)
    val_on = torch.cat(val_on_list, dim=0)
    val_off = torch.cat(val_off_list, dim=0)
    val_fr = torch.cat(val_fr_list, dim=0)
    val_vel = torch.cat(val_vel_list, dim=0)
    del val_mel_list, val_on_list, val_off_list, val_fr_list, val_vel_list

    print(f"  Train: {train_mel.shape[0]} segs, Val: {val_mel.shape[0]} segs ({time.time()-t0:.1f}s)")

    train_ds = TensorDataset(train_mel, train_on, train_off, train_fr, train_vel)
    val_ds = TensorDataset(val_mel, val_on, val_off, val_fr, val_vel)

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=0, pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                            num_workers=0, pin_memory=True)

    # Model
    model = TranscriptionCRNN(n_mels=N_MELS, n_pitches=N_PITCHES).to(device)
    params = sum(p.numel() for p in model.parameters())
    print(f"Model params: {params:,}")

    # Optimizer with cosine annealing
    optimizer = AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=NUM_EPOCHS, eta_min=1e-5)

    # Loss functions
    bce_loss = nn.BCEWithLogitsLoss()
    mse_loss = nn.MSELoss()

    # AMP
    scaler = GradScaler("cuda")

    # Resume
    start_epoch = 0
    best_val_loss = float("inf")
    ckpt_path = os.path.join(CHECKPOINT_DIR, "best_supervised.pt")
    latest_path = os.path.join(CHECKPOINT_DIR, "latest_supervised.pt")
    if os.path.exists(latest_path):
        try:
            ckpt = torch.load(latest_path, map_location=device, weights_only=False)
            model.load_state_dict(ckpt["model"], strict=False)
            optimizer.load_state_dict(ckpt["optimizer"])
            start_epoch = ckpt.get("epoch", 0) + 1
            best_val_loss = ckpt.get("best_val_loss", float("inf"))
            print(f"Resumed from epoch {start_epoch}")
        except Exception as e:
            print(f"Could not resume: {e}")

    # Loss weights (onset is most important for transcription)
    W_ONSET = 5.0
    W_OFFSET = 1.0
    W_FRAME = 1.0
    W_VEL = 0.5

    print(f"\n{'='*60}")
    print(f"Supervised CRNN Training: epoch {start_epoch} -> {start_epoch + NUM_EPOCHS}")
    print(f"Batch: {BATCH_SIZE}, LR: 1e-3 -> 1e-5 (cosine)")
    print(f"Loss weights: onset={W_ONSET} offset={W_OFFSET} frame={W_FRAME} vel={W_VEL}")
    print(f"Batches/epoch: {len(train_loader)}")
    print(f"{'='*60}")

    for epoch in range(start_epoch, start_epoch + NUM_EPOCHS):
        model.train()
        epoch_loss = 0.0
        epoch_onset_loss = 0.0
        epoch_frame_loss = 0.0
        epoch_batches = 0
        epoch_start = time.time()

        for batch_idx, (mel, onset, offset, frame, velocity) in enumerate(train_loader):
            mel = mel.to(device, non_blocking=True)
            onset = onset.to(device, non_blocking=True)
            offset = offset.to(device, non_blocking=True)
            frame = frame.to(device, non_blocking=True)
            velocity = velocity.to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)

            with autocast(device_type="cuda"):
                pred_onset, pred_offset, pred_frame, pred_vel = model(mel)

                loss_onset = bce_loss(pred_onset, onset)
                loss_offset = bce_loss(pred_offset, offset)
                loss_frame = bce_loss(pred_frame, frame)
                # Velocity: only on active frames, apply sigmoid first
                pred_vel_sig = torch.sigmoid(pred_vel)
                loss_vel = mse_loss(pred_vel_sig * frame, velocity * frame)

                loss = (W_ONSET * loss_onset + W_OFFSET * loss_offset +
                       W_FRAME * loss_frame + W_VEL * loss_vel)

            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            scaler.step(optimizer)
            scaler.update()

            epoch_loss += loss.item()
            epoch_onset_loss += loss_onset.item()
            epoch_frame_loss += loss_frame.item()
            epoch_batches += 1

            if (batch_idx + 1) % 20 == 0:
                gpu, _, _ = get_gpu_util()
                elapsed = time.time() - epoch_start
                print(f"  E{epoch+1} batch {batch_idx+1}/{len(train_loader)} "
                      f"Loss:{epoch_loss/epoch_batches:.4f} "
                      f"Onset:{epoch_onset_loss/epoch_batches:.4f} "
                      f"GPU:{gpu:.0f}% Time:{elapsed:.0f}s")

        scheduler.step()
        avg_loss = epoch_loss / max(epoch_batches, 1)
        avg_onset = epoch_onset_loss / max(epoch_batches, 1)
        avg_frame = epoch_frame_loss / max(epoch_batches, 1)

        # Validation
        model.eval()
        val_losses = []
        with torch.no_grad():
            for mel, onset, offset, frame, velocity in val_loader:
                mel = mel.to(device, non_blocking=True)
                onset = onset.to(device, non_blocking=True)
                offset = offset.to(device, non_blocking=True)
                frame = frame.to(device, non_blocking=True)
                velocity = velocity.to(device, non_blocking=True)
                with autocast(device_type="cuda"):
                    pred_onset, pred_offset, pred_frame, pred_vel = model(mel)
                    loss = (W_ONSET * bce_loss(pred_onset, onset) +
                           W_OFFSET * bce_loss(pred_offset, offset) +
                           W_FRAME * bce_loss(pred_frame, frame) +
                           W_VEL * mse_loss(torch.sigmoid(pred_vel) * frame, velocity * frame))
                val_losses.append(loss.item())

        avg_val = np.mean(val_losses) if val_losses else float("inf")
        epoch_time = time.time() - epoch_start
        gpu, _, _ = get_gpu_util()
        lr = optimizer.param_groups[0]['lr']

        print(f"\nEpoch {epoch+1}: Loss:{avg_loss:.4f} (onset:{avg_onset:.4f} frame:{avg_frame:.4f}) "
              f"Val:{avg_val:.4f} LR:{lr:.6f} Time:{epoch_time:.0f}s GPU:{gpu:.0f}%")
        print("-" * 60)

        if avg_val < best_val_loss:
            best_val_loss = avg_val
            torch.save({
                "epoch": epoch,
                "model": model.state_dict(),
                "best_val_loss": best_val_loss,
            }, ckpt_path)
            print(f"  -> Best model saved (val={avg_val:.4f})")

        torch.save({
            "epoch": epoch,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "best_val_loss": best_val_loss,
        }, latest_path)

    print(f"\nTraining complete! Best val: {best_val_loss:.4f}")


if __name__ == "__main__":
    train()
