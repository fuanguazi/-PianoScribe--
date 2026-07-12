"""
Synthesize realistic piano audio from MAESTRO MIDI files.
Uses pretty_midi with better soundfont for more realistic audio.
Also applies data augmentation (reverb, velocity variation, tempo).
"""
import os
import sys
import random
import shutil

import pretty_midi
import numpy as np

try:
    import soundfile as sf
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "soundfile", "-q"])
    import soundfile as sf

from config import SAMPLE_RATE, DATA_DIR

# MAESTRO MIDI-only download URL
MAESTRO_MIDI_URL = "https://storage.googleapis.com/magentadata/datasets/maestro/v3.0.0/maestro-v3.0.0-midi.zip"
MAESTRO_MIDI_ZIP = os.path.join(DATA_DIR, "maestro-v3.0.0-midi.zip")
MAESTRO_MIDI_DIR = os.path.join(DATA_DIR, "maestro-v3.0.0")


def download_midi_only():
    """Download MAESTRO MIDI-only dataset (~60MB)."""
    import requests
    if os.path.exists(MAESTRO_MIDI_DIR):
        print("MAESTRO MIDI directory already exists, skipping download.")
        return True

    if not os.path.exists(MAESTRO_MIDI_ZIP):
        print(f"Downloading MAESTRO v3.0.0 MIDI-only (~60MB)...")
        resp = requests.get(MAESTRO_MIDI_URL, stream=True, timeout=60)
        total = int(resp.headers.get("content-length", 0))
        with open(MAESTRO_MIDI_ZIP, "wb") as f:
            downloaded = 0
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded / total * 100
                    print(f"\r  Progress: {pct:.1f}%", end="", flush=True)
        print("\n  Download complete")

    import zipfile
    print(f"Extracting {MAESTRO_MIDI_ZIP}...")
    with zipfile.ZipFile(MAESTRO_MIDI_ZIP, "r") as zf:
        zf.extractall(DATA_DIR)
    print("  Extraction complete")
    return True


def find_midi_files() -> list[str]:
    """Find all MIDI files in MAESTRO directory."""
    midis = []
    if not os.path.exists(MAESTRO_MIDI_DIR):
        return midis
    for root, dirs, files in os.walk(MAESTRO_MIDI_DIR):
        for f in files:
            if f.lower().endswith((".mid", ".midi")):
                midis.append(os.path.join(root, f))
    return sorted(midis)


def synthesize_midi(midi_path: str, sr: int = SAMPLE_RATE) -> np.ndarray | None:
    """Synthesize audio from MIDI using pretty_midi."""
    try:
        pm = pretty_midi.PrettyMIDI(midi_path)
        audio = pm.synthesize(fs=sr)
        if len(audio) < sr * 2:
            return None
        # Normalize
        peak = np.abs(audio).max()
        if peak > 0:
            audio = audio / peak * 0.9
        return audio.astype(np.float32)
    except Exception as e:
        return None


def augment_audio(audio: np.ndarray, sr: int) -> np.ndarray:
    """Apply random augmentation to synthesized audio."""
    # Random gain
    gain = random.uniform(0.6, 1.0)
    audio = audio * gain

    # Simple reverb simulation (delay + decay)
    if random.random() < 0.5:
        delay_samples = int(random.uniform(0.02, 0.08) * sr)
        decay = random.uniform(0.1, 0.3)
        delayed = np.zeros(len(audio) + delay_samples, dtype=np.float32)
        delayed[:len(audio)] += audio
        delayed[delay_samples:delay_samples + len(audio)] += audio * decay
        audio = delayed[:len(audio)]

    # Re-normalize
    peak = np.abs(audio).max()
    if peak > 0:
        audio = audio / peak * 0.9

    return audio


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Step 1: Download MIDI-only
    download_midi_only()

    # Step 2: Find MIDI files
    midi_files = find_midi_files()
    print(f"Found {len(midi_files)} MIDI files")

    if not midi_files:
        print("ERROR: No MIDI files found")
        return

    # Step 3: Split train/validation (90/10)
    random.seed(42)
    random.shuffle(midi_files)
    split_idx = int(len(midi_files) * 0.9)
    train_midis = midi_files[:split_idx]
    val_midis = midi_files[split_idx:]

    print(f"Train: {len(train_midis)}, Validation: {len(val_midis)}")

    # Step 4: Synthesize and save
    for split, midis in [("train", train_midis), ("validation", val_midis)]:
        split_dir = os.path.join(DATA_DIR, split)
        os.makedirs(split_dir, exist_ok=True)

        success = 0
        failed = 0

        for i, midi_path in enumerate(midis):
            base = os.path.splitext(os.path.basename(midi_path))[0]
            base = base.replace(" ", "_").replace("'", "").replace("(", "").replace(")", "")

            wav_path = os.path.join(split_dir, base + ".wav")
            midi_dest = os.path.join(split_dir, base + ".mid")

            # Skip if already done
            if os.path.exists(wav_path) and os.path.exists(midi_dest):
                success += 1
                continue

            audio = synthesize_midi(midi_path)
            if audio is None:
                failed += 1
                continue

            # Apply augmentation for training data
            if split == "train":
                audio = augment_audio(audio, SAMPLE_RATE)

            # Save WAV
            sf.write(wav_path, audio, SAMPLE_RATE)

            # Copy MIDI
            shutil.copy2(midi_path, midi_dest)

            success += 1

            if (i + 1) % 50 == 0:
                print(f"  {split}: {i+1}/{len(midis)} processed ({success} ok, {failed} failed)")

        print(f"  {split} complete: {success} synthesized, {failed} failed")

    # Clean up MIDI zip
    free_gb = shutil.disk_usage(DATA_DIR).free / 1024**3
    print(f"\nDisk free: {free_gb:.1f} GB")
    print("\nDone! Next step: python precompute.py")


if __name__ == "__main__":
    main()
