"""
Adversarial training pipeline for piano transcription v2.

Strategy:
1. Use ByteDance's pretrained model to generate high-quality pseudo-labels
   from real audio (domain adaptation)
2. Precompute mel+labels from MAESTRO MIDI (synthesized audio)
3. Train CRNN generator with supervised + adversarial loss
4. Discriminator classifies real vs predicted piano rolls

Chunk-based precompute for memory efficiency.
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
import pretty_midi
import torchaudio
from torch.amp import autocast, GradScaler
from torch.utils.data import Dataset, DataLoader, TensorDataset
from torch.optim import AdamW

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    SAMPLE_RATE, N_FFT, HOP_SIZE, N_MELS, MEL_FMIN, MEL_FMAX,
    MIDI_MIN, MIDI_MAX, N_PITCHES, FRAME_RATE,
    BATCH_SIZE, LEARNING_RATE, NUM_EPOCHS,
    SEGMENT_SECONDS, SEGMENT_SAMPLES, SEGMENT_FRAMES,
    DATA_DIR, CHECKPOINT_DIR, EXPORT_DIR, MAESTRO_DIR, PRECOMPUTE_DIR,
    DISCRIMINATOR_LR, GENERATOR_LR, LAMBDA_ADV, LAMBDA_SUPERVISED,
)
from model import TranscriptionCRNN, Discriminator

CHUNK_SIZE = 100  # MIDI files per chunk
SEGMENTS_TRAIN = 4
SEGMENTS_VAL = 2


def midi_to_labels(midi_path, duration):
    n_frames = int(duration * FRAME_RATE) + 1
    onset = np.zeros((n_frames, N_PITCHES), dtype=np.float32)
    offset = np.zeros((n_frames, N_PITCHES), dtype=np.float32)
    frame = np.zeros((n_frames, N_PITCHES), dtype=np.float32)
    velocity = np.zeros((n_frames, N_PITCHES), dtype=np.float32)

    pm = pretty_midi.PrettyMIDI(midi_path)
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for note in inst.notes:
            p = note.pitch
            if p < MIDI_MIN or p > MIDI_MAX:
                continue
            idx = p - MIDI_MIN
            s = max(0, min(int(round(note.start * FRAME_RATE)), n_frames - 1))
            e = max(0, min(int(round(note.end * FRAME_RATE)), n_frames))
            onset[s, idx] = 1.0
            if e - 1 >= 0:
                offset[e - 1, idx] = 1.0
            frame[s:e, idx] = 1.0
            vel = note.velocity / 127.0
            velocity[s:e, idx] = vel
    return onset, offset, frame, velocity


def precompute_chunk(midi_files, output_path, device, augment, segments_per_file):
    all_mel, all_onset, all_offset, all_frame, all_vel = [], [], [], [], []

    mel_transform = torchaudio.transforms.MelSpectrogram(
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
                gain = random.uniform(0.7, 1.0)
                audio = audio * gain

            duration = len(audio) / SAMPLE_RATE
            audio_t = torch.from_numpy(audio).float().unsqueeze(0).to(device)
            del audio

            with torch.no_grad():
                mel = mel_transform(audio_t)
                mel = torch.log(mel + 1e-7)
                mean = mel.mean(dim=-1, keepdim=True)
                std = mel.std(dim=-1, keepdim=True)
                std = torch.clamp(std, min=1e-5)
                mel = (mel - mean) / std
            mel = mel.squeeze(0).cpu()
            del audio_t, pm

            onset, offset, frame, velocity = midi_to_labels(mp, duration)
            n_frames = min(mel.shape[-1], onset.shape[0])

            for seg in range(segments_per_file):
                if augment:
                    start = random.randint(0, max(0, n_frames - SEGMENT_FRAMES))
                else:
                    if n_frames <= SEGMENT_FRAMES:
                        start = 0
                    else:
                        start = (seg * (n_frames - SEGMENT_FRAMES)) // max(segments_per_file, 1)
                end = start + SEGMENT_FRAMES

                mel_seg = mel[:, start:min(end, n_frames)]
                on_seg = onset[start:min(end, n_frames)]
                off_seg = offset[start:min(end, n_frames)]
                fr_seg = frame[start:min(end, n_frames)]
                vel_seg = velocity[start:min(end, n_frames)]

                if mel_seg.shape[-1] < SEGMENT_FRAMES:
                    pad = SEGMENT_FRAMES - mel_seg.shape[-1]
                    mel_seg = F.pad(mel_seg, (0, pad))
                    on_seg = np.pad(on_seg, ((0, pad), (0, 0)))
                    off_seg = np.pad(off_seg, ((0, pad), (0, 0)))
                    fr_seg = np.pad(fr_seg, ((0, pad), (0, 0)))
                    vel_seg = np.pad(vel_seg, ((0, pad), (0, 0)))

                # Transpose labels: [T, 88] -> [88, T] for consistency
                all_mel.append(mel_seg)
                all_onset.append(torch.from_numpy(on_seg.T.copy()))  # [88, T]
                all_offset.append(torch.from_numpy(off_seg.T.copy()))
                all_frame.append(torch.from_numpy(fr_seg.T.copy()))
                all_vel.append(torch.from_numpy(vel_seg.T.copy()))

        except Exception as e:
            continue

    del mel_transform
    torch.cuda.empty_cache()

    if not all_mel:
        return False

    data = {
        'mel': torch.stack(all_mel),
        'onset': torch.stack(all_onset),
        'offset': torch.stack(all_offset),
        'frame': torch.stack(all_frame),
        'velocity': torch.stack(all_vel),
    }
    torch.save(data, output_path)
    size_mb = os.path.getsize(output_path) / 1024**2
    print(f"  Saved {output_path} ({len(all_mel)} segs, {size_mb:.1f}MB)")

    del data, all_mel, all_onset, all_offset, all_frame, all_vel
    gc.collect()
    return True


def precompute_all():
    """Precompute all MAESTRO data to disk chunks."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Precomputing on {device}")

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

    train_dir = os.path.join(PRECOMPUTE_DIR, "train")
    val_dir = os.path.join(PRECOMPUTE_DIR, "val")
    os.makedirs(train_dir, exist_ok=True)
    os.makedirs(val_dir, exist_ok=True)

    # Train chunks
    train_chunks = [train_midis[i:i+CHUNK_SIZE] for i in range(0, len(train_midis), CHUNK_SIZE)]
    print(f"\n=== Precomputing {len(train_chunks)} train chunks ===")
    t0 = time.time()
    for ci, chunk in enumerate(train_chunks):
        out_path = os.path.join(train_dir, f"chunk_{ci:03d}.pt")
        if os.path.exists(out_path):
            print(f"  Chunk {ci+1}/{len(train_chunks)} exists, skipping")
            continue
        print(f"  Processing chunk {ci+1}/{len(train_chunks)} ({len(chunk)} files)...")
        precompute_chunk(chunk, out_path, device, augment=True, segments_per_file=SEGMENTS_TRAIN)
        elapsed = time.time() - t0
        eta = elapsed / (ci + 1) * (len(train_chunks) - ci - 1)
        print(f"  ETA: {eta:.0f}s")

    # Val chunks
    val_chunks = [val_midis[i:i+CHUNK_SIZE] for i in range(0, len(val_midis), CHUNK_SIZE)]
    print(f"\n=== Precomputing {len(val_chunks)} val chunks ===")
    for ci, chunk in enumerate(val_chunks):
        out_path = os.path.join(val_dir, f"chunk_{ci:03d}.pt")
        if os.path.exists(out_path):
            continue
        precompute_chunk(chunk, out_path, device, augment=False, segments_per_file=SEGMENTS_VAL)

    print("Precomputation done!")


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
        print("ERROR: No precomputed data! Run with --precompute first.")
        return

    print(f"Train chunks: {len(train_chunk_files)}, Val chunks: {len(val_chunk_files)}")

    # === Load ALL data into memory at once ===
    print("Loading all training data into memory...")
    t0 = time.time()
    all_mel, all_on, all_off, all_fr, all_vel = [], [], [], [], []
    for cf in train_chunk_files:
        d = torch.load(cf, weights_only=True)
        all_mel.append(d['mel'])
        all_on.append(d['onset'].permute(0, 2, 1))
        all_off.append(d['offset'].permute(0, 2, 1))
        all_fr.append(d['frame'].permute(0, 2, 1))
        all_vel.append(d['velocity'].permute(0, 2, 1))
    train_mel = torch.cat(all_mel, dim=0)
    train_on = torch.cat(all_on, dim=0)
    train_off = torch.cat(all_off, dim=0)
    train_fr = torch.cat(all_fr, dim=0)
    train_vel = torch.cat(all_vel, dim=0)
    del all_mel, all_on, all_off, all_fr, all_vel
    print(f"  Train: {train_mel.shape[0]} segments loaded in {time.time()-t0:.1f}s")

    print("Loading all validation data into memory...")
    v0 = time.time()
    val_mel_list, val_on_list, val_off_list, val_fr_list, val_vel_list = [], [], [], [], []
    for cf in val_chunk_files:
        d = torch.load(cf, weights_only=True)
        val_mel_list.append(d['mel'])
        val_on_list.append(d['onset'].permute(0, 2, 1))
        val_off_list.append(d['offset'].permute(0, 2, 1))
        val_fr_list.append(d['frame'].permute(0, 2, 1))
        val_vel_list.append(d['velocity'].permute(0, 2, 1))
    val_mel = torch.cat(val_mel_list, dim=0)
    val_on = torch.cat(val_on_list, dim=0)
    val_off = torch.cat(val_off_list, dim=0)
    val_fr = torch.cat(val_fr_list, dim=0)
    val_vel = torch.cat(val_vel_list, dim=0)
    del val_mel_list, val_on_list, val_off_list, val_fr_list, val_vel_list
    print(f"  Val: {val_mel.shape[0]} segments loaded in {time.time()-v0:.1f}s")

    train_ds = TensorDataset(train_mel, train_on, train_off, train_fr, train_vel)
    val_ds = TensorDataset(val_mel, val_on, val_off, val_fr, val_vel)

    # Large batch + pin_memory for max GPU throughput
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=0, pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                            num_workers=0, pin_memory=True)

    # Models
    generator = TranscriptionCRNN(n_mels=N_MELS, n_pitches=N_PITCHES).to(device)
    discriminator = Discriminator(n_pitches=N_PITCHES).to(device)

    g_params = sum(p.numel() for p in generator.parameters())
    d_params = sum(p.numel() for p in discriminator.parameters())
    print(f"Generator params: {g_params:,}")
    print(f"Discriminator params: {d_params:,}")

    # Optimizers
    opt_g = AdamW(generator.parameters(), lr=GENERATOR_LR, weight_decay=1e-4)
    opt_d = AdamW(discriminator.parameters(), lr=DISCRIMINATOR_LR, weight_decay=1e-4)

    # Loss (use BCEWithLogitsLoss for AMP safety)
    bce_logits_loss = nn.BCEWithLogitsLoss()
    mse_loss = nn.MSELoss()

    # AMP
    scaler_g = GradScaler("cuda")
    scaler_d = GradScaler("cuda")

    # Resume
    start_epoch = 0
    best_val_loss = float("inf")
    ckpt_path = os.path.join(CHECKPOINT_DIR, "latest.pt")
    if os.path.exists(ckpt_path):
        try:
            ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
            generator.load_state_dict(ckpt["generator"], strict=False)
            start_epoch = ckpt.get("epoch", 0) + 1
            best_val_loss = ckpt.get("best_val_loss", float("inf"))
            print(f"Resumed from epoch {start_epoch}")
        except Exception as e:
            print(f"Could not resume: {e}")

    print(f"\n{'='*60}")
    print(f"Training from epoch {start_epoch} to {start_epoch + NUM_EPOCHS}")
    print(f"Batch: {BATCH_SIZE}, G_lr: {GENERATOR_LR}, D_lr: {DISCRIMINATOR_LR}")
    print(f"Lambda_sup: {LAMBDA_SUPERVISED}, Lambda_adv: {LAMBDA_ADV}")
    print(f"Train batches/epoch: {len(train_loader)}")
    print(f"{'='*60}")

    for epoch in range(start_epoch, start_epoch + NUM_EPOCHS):
        generator.train()
        discriminator.train()
        epoch_g_loss = 0.0
        epoch_d_loss = 0.0
        epoch_batches = 0
        epoch_start = time.time()

        for batch_idx, (mel, onset, offset, frame, velocity) in enumerate(train_loader):
            mel = mel.to(device, non_blocking=True)
            onset = onset.to(device, non_blocking=True)
            offset = offset.to(device, non_blocking=True)
            frame = frame.to(device, non_blocking=True)
            velocity = velocity.to(device, non_blocking=True)

            # Piano roll for discriminator: [B, 88, T]
            real_pianoroll = frame.permute(0, 2, 1)

            # --- Train Discriminator ---
            opt_d.zero_grad(set_to_none=True)
            with autocast(device_type="cuda"):
                pred_onset, pred_offset, pred_frame, pred_vel = generator(mel)
                pred_frame_sig = torch.sigmoid(pred_frame)
                fake_pianoroll = pred_frame_sig.permute(0, 2, 1).detach()

                d_real = discriminator(real_pianoroll)
                d_fake = discriminator(fake_pianoroll)

                real_label = torch.ones(d_real.shape[0], 1, device=device)
                fake_label = torch.zeros(d_fake.shape[0], 1, device=device)

                d_loss = (F.binary_cross_entropy_with_logits(d_real, real_label) +
                         F.binary_cross_entropy_with_logits(d_fake, fake_label)) / 2.0

            scaler_d.scale(d_loss).backward()
            scaler_d.step(opt_d)
            scaler_d.update()

            # --- Train Generator ---
            opt_g.zero_grad(set_to_none=True)
            with autocast(device_type="cuda"):
                pred_onset, pred_offset, pred_frame, pred_vel = generator(mel)
                pred_frame_sig = torch.sigmoid(pred_frame)
                fake_pianoroll = pred_frame_sig.permute(0, 2, 1)

                # Supervised loss (use BCEWithLogitsLoss)
                loss_onset = bce_logits_loss(pred_onset, onset)
                loss_offset = bce_logits_loss(pred_offset, offset)
                loss_frame = bce_logits_loss(pred_frame, frame)
                pred_vel_sig = torch.sigmoid(pred_vel)
                loss_vel = mse_loss(pred_vel_sig * frame, velocity * frame)
                supervised_loss = loss_onset + loss_offset + loss_frame + loss_vel

                # Adversarial loss
                d_fake_for_g = discriminator(fake_pianoroll)
                adv_loss = F.binary_cross_entropy_with_logits(
                    d_fake_for_g, torch.ones(d_fake_for_g.shape[0], 1, device=device)
                )

                g_loss = LAMBDA_SUPERVISED * supervised_loss + LAMBDA_ADV * adv_loss

            scaler_g.scale(g_loss).backward()
            scaler_g.step(opt_g)
            scaler_g.update()

            epoch_g_loss += g_loss.item()
            epoch_d_loss += d_loss.item()
            epoch_batches += 1

            if (batch_idx + 1) % 20 == 0:
                gpu, mem_used, mem_total = get_gpu_util()
                elapsed = time.time() - epoch_start
                print(f"  E{epoch+1} batch {batch_idx+1}/{len(train_loader)} "
                      f"G:{epoch_g_loss/max(epoch_batches,1):.4f} "
                      f"D:{epoch_d_loss/max(epoch_batches,1):.4f} "
                      f"GPU:{gpu:.0f}% Time:{elapsed:.0f}s")

        avg_g = epoch_g_loss / max(epoch_batches, 1)
        avg_d = epoch_d_loss / max(epoch_batches, 1)

        # Validation
        generator.eval()
        val_losses = []
        with torch.no_grad():
            for mel, onset, offset, frame, velocity in val_loader:
                mel = mel.to(device, non_blocking=True)
                onset = onset.to(device, non_blocking=True)
                offset = offset.to(device, non_blocking=True)
                frame = frame.to(device, non_blocking=True)
                velocity = velocity.to(device, non_blocking=True)
                with autocast(device_type="cuda"):
                    pred_onset, pred_offset, pred_frame, pred_vel = generator(mel)
                    loss = (bce_logits_loss(pred_onset, onset) + bce_logits_loss(pred_offset, offset) +
                           bce_logits_loss(pred_frame, frame) + mse_loss(torch.sigmoid(pred_vel) * frame, velocity * frame))
                val_losses.append(loss.item())

        avg_val = np.mean(val_losses) if val_losses else float("inf")
        epoch_time = time.time() - epoch_start
        gpu, _, _ = get_gpu_util()

        print(f"\nEpoch {epoch+1}: G:{avg_g:.4f} D:{avg_d:.4f} Val:{avg_val:.4f} "
              f"Time:{epoch_time:.0f}s GPU:{gpu:.0f}%")
        print("-" * 60)

        if avg_val < best_val_loss:
            best_val_loss = avg_val
            torch.save({
                "epoch": epoch,
                "generator": generator.state_dict(),
                "discriminator": discriminator.state_dict(),
                "best_val_loss": best_val_loss,
            }, os.path.join(CHECKPOINT_DIR, "best_model.pt"))
            print(f"  -> Best model saved (val={avg_val:.4f})")

        torch.save({
            "epoch": epoch,
            "generator": generator.state_dict(),
            "discriminator": discriminator.state_dict(),
            "opt_g": opt_g.state_dict(),
            "opt_d": opt_d.state_dict(),
            "best_val_loss": best_val_loss,
        }, ckpt_path)

    print(f"\nTraining complete! Best val: {best_val_loss:.4f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--precompute", action="store_true")
    parser.add_argument("--train", action="store_true")
    args = parser.parse_args()

    if args.precompute:
        precompute_all()
    if args.train:
        train()
    if not args.precompute and not args.train:
        print("Use --precompute and/or --train")
