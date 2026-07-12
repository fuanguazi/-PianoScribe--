"""
Step 2: Train from precomputed .pt chunks.
Since all mel+labels are already computed, training should be very fast
and GPU utilization should be near 100%.
"""
import os
import sys
import time
import random
import subprocess
import gc

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.amp import autocast, GradScaler
from torch.utils.data import Dataset, DataLoader, TensorDataset, ConcatDataset
from torch.optim import AdamW
from torch.optim.lr_scheduler import OneCycleLR

from config import (
    N_MELS, N_PITCHES, BATCH_SIZE, LEARNING_RATE, NUM_EPOCHS,
    CHECKPOINT_DIR, EXPORT_DIR, DATA_DIR,
    FOCAL_ALPHA, FOCAL_GAMMA, SEGMENT_FRAMES,
    LOSS_WEIGHT_ONSET, LOSS_WEIGHT_OFFSET, LOSS_WEIGHT_VELOCITY,
)
from model import TranscriptionNet

PRECOMPUTE_DIR = os.path.join(DATA_DIR, "precomputed_chunks")

BATCH_SIZE = 128
GRAD_ACCUM = 2


class ChunkDataset(Dataset):
    """Loads precomputed chunks on demand."""
    def __init__(self, chunk_dir):
        self.chunk_files = sorted([
            os.path.join(chunk_dir, f) for f in os.listdir(chunk_dir) if f.endswith('.pt')
        ])
        self.data = None
        self.current_chunk = -1
        print(f"  Found {len(self.chunk_files)} chunks in {chunk_dir}")

    def load_chunk(self, idx):
        if self.current_chunk == idx:
            return
        # Free previous chunk
        if self.data is not None:
            del self.data
            gc.collect()
        self.data = torch.load(self.chunk_files[idx], weights_only=True)
        self.current_chunk = idx
        n = self.data['mel'].shape[0]
        print(f"  Loaded chunk {idx+1}/{len(self.chunk_files)}: {n} segments")

    def __len__(self):
        # Total segments across all chunks
        total = 0
        for cf in self.chunk_files:
            d = torch.load(cf, weights_only=True)
            total += d['mel'].shape[0]
            del d
        return total


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

    # Find precomputed chunks
    train_dir = os.path.join(PRECOMPUTE_DIR, "train")
    val_dir = os.path.join(PRECOMPUTE_DIR, "val")

    train_chunk_files = sorted([
        os.path.join(train_dir, f) for f in os.listdir(train_dir) if f.endswith('.pt')
    ])
    val_chunk_files = sorted([
        os.path.join(val_dir, f) for f in os.listdir(val_dir) if f.endswith('.pt')
    ])

    if not train_chunk_files:
        print("ERROR: No precomputed data found! Run precompute_v5.py first.")
        return

    print(f"Train chunks: {len(train_chunk_files)}, Val chunks: {len(val_chunk_files)}")

    # Count total segments
    total_train = 0
    for cf in train_chunk_files:
        d = torch.load(cf, weights_only=True)
        total_train += d['mel'].shape[0]
        del d
    print(f"Total train segments: {total_train}")

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

    # Estimate steps per epoch
    steps_per_chunk = total_train // len(train_chunk_files) // BATCH_SIZE
    total_steps = len(train_chunk_files) * steps_per_chunk

    print(f"\n{'='*80}")
    print(f"Training from epoch {start_epoch} to {start_epoch + NUM_EPOCHS}")
    print(f"Batch: {BATCH_SIZE}, Accum: {GRAD_ACCUM}, Effective: {BATCH_SIZE*GRAD_ACCUM}")
    print(f"Chunks: {len(train_chunk_files)}, ~{steps_per_chunk} steps/chunk")
    print(f"{'='*80}")

    for epoch in range(start_epoch, start_epoch + NUM_EPOCHS):
        model.train()
        epoch_loss = 0.0
        epoch_batches = 0
        epoch_start = time.time()

        # Shuffle chunk order each epoch
        chunk_order = list(range(len(train_chunk_files)))
        random.shuffle(chunk_order)

        scheduler = OneCycleLR(optimizer, max_lr=LEARNING_RATE, epochs=1,
                              steps_per_epoch=max(total_steps, 1), pct_start=0.1)

        for chunk_i, chunk_idx in enumerate(chunk_order):
            # Load chunk
            chunk_data = torch.load(train_chunk_files[chunk_idx], weights_only=True)
            mel_t = chunk_data['mel']
            on_t = chunk_data['on']
            off_t = chunk_data['off']
            vel_t = chunk_data['vel']
            chunk_ds = TensorDataset(mel_t, on_t, off_t, vel_t)

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

            # Free chunk
            del chunk_data, chunk_ds, chunk_loader
            gc.collect()

            if (chunk_i + 1) % 3 == 0:
                gpu, mem_used, mem_total = get_gpu_util()
                elapsed = time.time() - epoch_start
                print(f"  E{epoch+1} chunk {chunk_i+1}/{len(train_chunk_files)} "
                      f"Loss:{epoch_loss/max(epoch_batches,1):.4f} "
                      f"GPU:{gpu:.0f}% VRAM:{mem_used:.0f}/{mem_total:.0f}MB "
                      f"Time:{elapsed:.0f}s")

        avg_train = epoch_loss / max(epoch_batches, 1)

        # Validation
        model.eval()
        val_loss = 0.0
        vb = 0
        with torch.no_grad():
            for vcf in val_chunk_files:
                vd = torch.load(vcf, weights_only=True)
                val_ds = TensorDataset(vd['mel'], vd['on'], vd['off'], vd['vel'])
                val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                                        num_workers=0, pin_memory=True)
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
                del vd, val_ds, val_loader

        avg_val = val_loss / max(vb, 1)
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
