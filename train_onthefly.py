"""
Training script that synthesizes audio on-the-fly from MIDI.
No precomputed .pt files needed - avoids filesystem issues.
"""
import os
import sys
import time
import random
import shutil
import subprocess

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import pretty_midi
import torchaudio
from torch.amp import autocast, GradScaler
from torch.utils.data import Dataset, DataLoader
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

mel_transform = torchaudio.transforms.MelSpectrogram(
    sample_rate=SAMPLE_RATE, n_fft=N_FFT, hop_length=HOP_SIZE,
    n_mels=N_MELS, f_min=MEL_FMIN, f_max=MEL_FMAX,
).to("cuda")


def midi_to_labels(midi_path: str, duration: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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


class OnTheFlyDataset(Dataset):
    """Synthesizes audio from MIDI on-the-fly. No .pt files needed."""

    def __init__(self, midi_files: list[str], segment_frames: int = SEGMENT_FRAMES,
                 augment: bool = True, segments_per_file: int = 3):
        self.midi_files = midi_files
        self.segment_frames = segment_frames
        self.augment = augment
        self.segments_per_file = segments_per_file
        # Pre-scan to find valid files and their durations
        self.valid_files: list[tuple[str, int]] = []  # (path, n_frames)
        print(f"Scanning {len(midi_files)} MIDI files...")
        for mp in midi_files:
            try:
                pm = pretty_midi.PrettyMIDI(mp)
                dur = pm.get_end_time()
                n_frames = int(dur * FRAME_RATE)
                if n_frames >= segment_frames:
                    self.valid_files.append((mp, n_frames))
            except:
                pass
        print(f"Found {len(self.valid_files)} valid files")

    def __len__(self) -> int:
        return len(self.valid_files) * self.segments_per_file

    def __getitem__(self, idx: int) -> dict:
        file_idx = idx % len(self.valid_files)
        midi_path, n_frames = self.valid_files[file_idx]

        # Random segment
        if self.augment:
            start_frame = random.randint(0, max(0, n_frames - self.segment_frames))
        else:
            start_frame = max(0, (n_frames - self.segment_frames) // 2)

        start_time = start_frame / FRAME_RATE
        end_time = (start_frame + self.segment_frames) / FRAME_RATE

        # Synthesize segment
        pm = pretty_midi.PrettyMIDI(midi_path)
        audio = pm.synthesize(fs=SAMPLE_RATE)
        start_sample = int(start_time * SAMPLE_RATE)
        end_sample = int(end_time * SAMPLE_RATE)

        # Pad if needed
        if end_sample > len(audio):
            audio = np.pad(audio, (0, end_sample - len(audio)))
        audio = audio[start_sample:end_sample]

        # Normalize
        peak = np.abs(audio).max()
        if peak > 0:
            audio = audio / peak * 0.9

        # Augment
        if self.augment and random.random() < 0.3:
            audio = audio * random.uniform(0.6, 1.0)

        # Compute mel
        audio_tensor = torch.from_numpy(audio).float().unsqueeze(0)
        mel = mel_transform.cpu()(audio_tensor)
        mel = torch.log(mel + 1e-7)
        mean = mel.mean(dim=-1, keepdim=True)
        std = mel.std(dim=-1, keepdim=True)
        std = torch.clamp(std, min=1e-5)
        mel = (mel - mean) / std
        mel = mel.squeeze(0)

        # Pad/truncate mel to segment_frames
        if mel.shape[-1] < self.segment_frames:
            mel = F.pad(mel, (0, self.segment_frames - mel.shape[-1]))
        else:
            mel = mel[:, :self.segment_frames]

        # Labels
        note_on, note_off, velocity = midi_to_labels(midi_path, end_time)
        s = start_frame
        e = s + self.segment_frames
        if e > note_on.shape[-1]:
            note_on = np.pad(note_on, ((0,0),(0, e - note_on.shape[-1])))
            note_off = np.pad(note_off, ((0,0),(0, e - note_off.shape[-1])))
            velocity = np.pad(velocity, ((0,0),(0, e - velocity.shape[-1])))

        on_seg = note_on[:, s:e]
        off_seg = note_off[:, s:e]
        vel_seg = velocity[:, s:e]

        return {
            "mel": mel,
            "note_on": torch.from_numpy(on_seg),
            "note_off": torch.from_numpy(off_seg),
            "velocity": torch.from_numpy(vel_seg),
        }


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


def get_gpu_util() -> float:
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
                          capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return float(r.stdout.strip())
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

    model = TranscriptionNet().to(device)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {total_params:,}")

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

    # Datasets
    train_ds = OnTheFlyDataset(train_midis, augment=True, segments_per_file=3)
    val_ds = OnTheFlyDataset(val_midis, augment=False, segments_per_file=1)

    if len(train_ds) == 0:
        print("ERROR: No valid training data")
        return

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=0,
                              pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0, pin_memory=True)

    print(f"Train samples: {len(train_ds)}, batches: {len(train_loader)}")
    print(f"Val samples: {len(val_ds)}, batches: {len(val_loader)}")

    # Wrap model to remove sigmoid for training (BCEWithLogits handles it)
    class TrainWrapper(nn.Module):
        def __init__(self, net):
            super().__init__()
            self.net = net
        def forward(self, x):
            # Run full model backbone
            h = self.net.frontend(x)
            h = self.net.res1(h)
            h = self.net.trans1(h)
            h = self.net.res2(h)
            h = self.net.trans2(h)
            h = self.net.res3(h)
            # Output heads without final Sigmoid
            on_logits = self.net.note_on_head[:-1](h)  # Conv+ReLU+Conv (no Sigmoid)
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
        model.load_state_dict(ckpt["model_state_dict"])
        start_epoch = ckpt.get("epoch", 0) + 1
        best_val_loss = ckpt.get("val_loss", float("inf"))
        print(f"Resumed from epoch {start_epoch}, val_loss={best_val_loss:.4f}")

    focal = FocalLoss()
    vel_loss_fn = VelocityLoss()
    optimizer = AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)
    scheduler = OneCycleLR(optimizer, max_lr=LEARNING_RATE, epochs=NUM_EPOCHS,
                          steps_per_epoch=len(train_loader), pct_start=0.1)
    scaler = GradScaler("cuda")

    print(f"\nTraining from epoch {start_epoch} to {start_epoch + NUM_EPOCHS}")
    print(f"Batch size: {BATCH_SIZE}")
    print("-" * 80)

    for epoch in range(start_epoch, start_epoch + NUM_EPOCHS):
        model.train()
        train_loss = 0.0
        n_batches = 0
        epoch_start = time.time()

        for batch_idx, batch in enumerate(train_loader):
            mel = batch["mel"].to(device, non_blocking=True)
            on_t = batch["note_on"].to(device, non_blocking=True)
            off_t = batch["note_off"].to(device, non_blocking=True)
            vel_t = batch["velocity"].to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)

            with autocast(device_type="cuda"):
                pred_on, pred_off, pred_vel = train_model(mel)
                l_on = focal(pred_on, on_t)
                l_off = focal(pred_off, off_t)
                mask = (on_t > 0.5).float()
                l_vel = vel_loss_fn(pred_vel, vel_t, mask)
                loss = LOSS_WEIGHT_ONSET * l_on + LOSS_WEIGHT_OFFSET * l_off + LOSS_WEIGHT_VELOCITY * l_vel

            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()

            train_loss += loss.item()
            n_batches += 1

            if (batch_idx + 1) % 20 == 0:
                gpu = get_gpu_util()
                elapsed = time.time() - epoch_start
                sps = (batch_idx + 1) * BATCH_SIZE / elapsed
                print(f"  E{epoch+1} [{batch_idx+1}/{len(train_loader)}] "
                      f"Loss:{loss.item():.4f} Onset:{l_on.item():.4f} "
                      f"GPU:{gpu:.0f}% Speed:{sps:.0f}sam/s")

        avg_train = train_loss / max(n_batches, 1)

        # Validation
        model.eval()
        val_loss = 0.0
        vb = 0
        with torch.no_grad():
            for batch in val_loader:
                mel = batch["mel"].to(device, non_blocking=True)
                on_t = batch["note_on"].to(device, non_blocking=True)
                off_t = batch["note_off"].to(device, non_blocking=True)
                vel_t = batch["velocity"].to(device, non_blocking=True)
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
        epoch_time = time.time() - epoch_start
        gpu = get_gpu_util()

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
