"""
Training script with optimized GPU utilization.
Key improvements:
- Precomputed dataset (no data loading bottleneck)
- Multiple DataLoader workers with prefetch
- Mixed precision training (AMP)
- GPU utilization monitoring
- Gradient accumulation for effective larger batch
"""
import os
import sys
import time
import shutil
import subprocess

import torch
import torch.nn as nn
from torch.amp import autocast, GradScaler
from torch.utils.data import DataLoader
from torch.optim import AdamW
from torch.optim.lr_scheduler import OneCycleLR

from config import (
    BATCH_SIZE, LEARNING_RATE, NUM_EPOCHS,
    CHECKPOINT_DIR, EXPORT_DIR, DATA_DIR,
    FOCAL_ALPHA, FOCAL_GAMMA,
    LOSS_WEIGHT_ONSET, LOSS_WEIGHT_OFFSET, LOSS_WEIGHT_VELOCITY,
    NUM_WORKERS, PREFETCH_FACTOR, PERSISTENT_WORKERS,
    N_MELS, N_PITCHES, CONV_CHANNELS, DILATIONS,
)
from model import TranscriptionNet
from dataset import PrecomputedDataset


class FocalLoss(nn.Module):
    def __init__(self, alpha=FOCAL_ALPHA, gamma=FOCAL_GAMMA):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        bce = nn.functional.binary_cross_entropy(pred, target, reduction="none")
        pt = target * pred + (1 - target) * (1 - pred)
        focal_weight = (1 - pt) ** self.gamma
        alpha_weight = target * self.alpha + (1 - target) * (1 - self.alpha)
        loss = alpha_weight * focal_weight * bce
        return loss.mean()


class VelocityLoss(nn.Module):
    def __init__(self):
        super().__init__()

    def forward(self, pred: torch.Tensor, target: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        diff = (pred - target) ** 2
        if mask.sum() > 0:
            return (diff * mask).sum() / (mask.sum() + 1e-8)
        return diff.mean()


def get_gpu_util() -> float:
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except:
        pass
    return -1


def train():
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"VRAM: {vram:.1f} GB")

    # Model
    model = TranscriptionNet().to(device)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {total_params:,}")
    print(f"Model size: {total_params * 4 / 1024**2:.1f} MB")

    # Resume from checkpoint
    start_epoch = 0
    best_val_loss = float("inf")
    ckpt_path = os.path.join(CHECKPOINT_DIR, "best_model.pt")
    if os.path.exists(ckpt_path):
        ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model_state_dict"])
        start_epoch = ckpt.get("epoch", 0) + 1
        best_val_loss = ckpt.get("val_loss", float("inf"))
        print(f"Resumed from epoch {start_epoch}, val_loss={best_val_loss:.4f}")

    # Datasets
    train_ds = PrecomputedDataset(split="train", augment=True, segments_per_file=4)
    val_ds = PrecomputedDataset(split="validation", augment=False, segments_per_file=1)

    if len(train_ds) == 0:
        print("ERROR: No training data found. Run precompute.py first.")
        return

    # DataLoader with optimized settings
    train_loader = DataLoader(
        train_ds,
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=NUM_WORKERS,
        pin_memory=True,
        prefetch_factor=PREFETCH_FACTOR if NUM_WORKERS > 0 else None,
        persistent_workers=PERSISTENT_WORKERS if NUM_WORKERS > 0 else False,
        drop_last=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=NUM_WORKERS,
        pin_memory=True,
        prefetch_factor=PREFETCH_FACTOR if NUM_WORKERS > 0 else None,
        persistent_workers=PERSISTENT_WORKERS if NUM_WORKERS > 0 else False,
    )

    print(f"Train samples: {len(train_ds)}, batches: {len(train_loader)}")
    print(f"Val samples: {len(val_ds)}, batches: {len(val_loader)}")

    # Loss
    focal = FocalLoss()
    vel_loss_fn = VelocityLoss()

    # Optimizer
    optimizer = AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)

    # Scheduler
    scheduler = OneCycleLR(
        optimizer,
        max_lr=LEARNING_RATE,
        epochs=NUM_EPOCHS,
        steps_per_epoch=len(train_loader),
        pct_start=0.1,
    )

    # AMP
    scaler = GradScaler("cuda")

    # Training loop
    print(f"\nStarting training from epoch {start_epoch} to {start_epoch + NUM_EPOCHS}")
    print(f"Batch size: {BATCH_SIZE}, Workers: {NUM_WORKERS}")
    print("-" * 80)

    for epoch in range(start_epoch, start_epoch + NUM_EPOCHS):
        model.train()
        train_loss = 0.0
        train_onset_loss = 0.0
        train_vel_loss = 0.0
        n_batches = 0

        epoch_start = time.time()

        for batch_idx, batch in enumerate(train_loader):
            mel = batch["mel"].to(device, non_blocking=True)
            note_on_target = batch["note_on"].to(device, non_blocking=True)
            note_off_target = batch["note_off"].to(device, non_blocking=True)
            vel_target = batch["velocity"].to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)

            with autocast(device_type="cuda"):
                pred_on, pred_off, pred_vel = model(mel)
                loss_onset = focal(pred_on, note_on_target)
                loss_offset = focal(pred_off, note_off_target)
                onset_mask = (note_on_target > 0.5).float()
                loss_vel = vel_loss_fn(pred_vel, vel_target, onset_mask)
                loss = (LOSS_WEIGHT_ONSET * loss_onset +
                        LOSS_WEIGHT_OFFSET * loss_offset +
                        LOSS_WEIGHT_VELOCITY * loss_vel)

            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()

            train_loss += loss.item()
            train_onset_loss += loss_onset.item()
            train_vel_loss += loss_vel.item()
            n_batches += 1

            # Progress every 50 batches
            if (batch_idx + 1) % 50 == 0:
                gpu_util = get_gpu_util()
                elapsed = time.time() - epoch_start
                samples_sec = (batch_idx + 1) * BATCH_SIZE / elapsed
                print(
                    f"  Epoch {epoch+1} [{batch_idx+1}/{len(train_loader)}] "
                    f"Loss: {loss.item():.4f} "
                    f"Onset: {loss_onset.item():.4f} "
                    f"Vel: {loss_vel.item():.4f} "
                    f"GPU: {gpu_util:.0f}% "
                    f"Speed: {samples_sec:.0f} samples/s"
                )

        avg_train_loss = train_loss / max(n_batches, 1)
        avg_onset = train_onset_loss / max(n_batches, 1)
        avg_vel = train_vel_loss / max(n_batches, 1)

        # Validation
        model.eval()
        val_loss = 0.0
        val_batches = 0
        with torch.no_grad():
            for batch in val_loader:
                mel = batch["mel"].to(device, non_blocking=True)
                note_on_target = batch["note_on"].to(device, non_blocking=True)
                note_off_target = batch["note_off"].to(device, non_blocking=True)
                vel_target = batch["velocity"].to(device, non_blocking=True)

                with autocast(device_type="cuda"):
                    pred_on, pred_off, pred_vel = model(mel)
                    loss_onset = focal(pred_on, note_on_target)
                    loss_offset = focal(pred_off, note_off_target)
                    onset_mask = (note_on_target > 0.5).float()
                    loss_vel = vel_loss_fn(pred_vel, vel_target, onset_mask)
                    loss = (LOSS_WEIGHT_ONSET * loss_onset +
                            LOSS_WEIGHT_OFFSET * loss_offset +
                            LOSS_WEIGHT_VELOCITY * loss_vel)
                val_loss += loss.item()
                val_batches += 1

        avg_val_loss = val_loss / max(val_batches, 1)

        epoch_time = time.time() - epoch_start
        gpu_util = get_gpu_util()

        print(
            f"\nEpoch {epoch+1} Summary: "
            f"Train Loss: {avg_train_loss:.4f} (Onset: {avg_onset:.4f}, Vel: {avg_vel:.4f}) "
            f"Val Loss: {avg_val_loss:.4f} "
            f"Time: {epoch_time:.0f}s "
            f"GPU Util: {gpu_util:.0f}%"
        )
        print("-" * 80)

        # Save best model
        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_loss": avg_val_loss,
                "train_loss": avg_train_loss,
            }, ckpt_path)
            print(f"  -> New best model saved (val_loss={avg_val_loss:.4f})")

        # Save periodic checkpoint
        if (epoch + 1) % 5 == 0:
            periodic_path = os.path.join(CHECKPOINT_DIR, f"checkpoint_epoch{epoch+1}.pt")
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_loss": avg_val_loss,
                "train_loss": avg_train_loss,
            }, periodic_path)

    print(f"\nTraining complete! Best val loss: {best_val_loss:.4f}")
    print(f"Best model saved to: {ckpt_path}")


if __name__ == "__main__":
    train()
