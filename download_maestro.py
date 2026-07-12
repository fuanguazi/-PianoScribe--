"""
Download MAESTRO v2.0.0 (full version with real piano recordings + MIDI)
Then organize into train/validation splits with audio+MIDI pairs.
"""
import os
import sys
import json
import zipfile
import shutil
import subprocess

DATA_DIR = r"D:\PianoTraining\data"
MAESTRO_URL = "https://storage.googleapis.com/magentadata/datasets/maestro/v2.0.0/maestro-v2.0.0.zip"
MAESTRO_ZIP = os.path.join(DATA_DIR, "maestro-v2.0.0.zip")
MAESTRO_DIR = os.path.join(DATA_DIR, "maestro-v2.0.0")


def download_with_progress(url: str, dest: str):
    """Download file with progress using requests."""
    try:
        import requests
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
        import requests

    if os.path.exists(dest):
        existing_size = os.path.getsize(dest)
        headers = {"Range": f"bytes={existing_size}-"}
        resp = requests.get(url, headers=headers, stream=True, timeout=30)
        if resp.status_code == 416:
            print(f"File already complete: {dest}")
            return
        elif resp.status_code == 206:
            mode = "ab"
            total = int(resp.headers.get("content-length", 0)) + existing_size
            print(f"Resuming download from {existing_size / 1024**3:.1f} GB")
        else:
            mode = "wb"
            total = int(resp.headers.get("content-length", 0))
            existing_size = 0
    else:
        import requests
        resp = requests.get(url, stream=True, timeout=30)
        mode = "wb"
        total = int(resp.headers.get("content-length", 0))
        existing_size = 0

    downloaded = existing_size
    chunk_size = 1024 * 1024  # 1MB chunks
    with open(dest, mode) as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded / total * 100
                    gb = downloaded / 1024**3
                    total_gb = total / 1024**3
                    print(f"\r  Progress: {pct:.1f}% ({gb:.1f}/{total_gb:.1f} GB)", end="", flush=True)
    print(f"\n  Download complete: {dest}")


def organize_maestro():
    """Organize MAESTRO into train/validation with audio+MIDI pairs."""
    metadata_path = os.path.join(MAESTRO_DIR, "maestro-v2.0.0.json")
    if not os.path.exists(metadata_path):
        print(f"ERROR: Metadata not found at {metadata_path}")
        return

    with open(metadata_path, "r") as f:
        metadata = json.load(f)

    train_dir = os.path.join(DATA_DIR, "train")
    val_dir = os.path.join(DATA_DIR, "validation")
    os.makedirs(train_dir, exist_ok=True)
    os.makedirs(val_dir, exist_ok=True)

    train_count = 0
    val_count = 0

    for entry in metadata:
        split = entry.get("split", "")
        midi_filename = entry.get("midi_filename", "")
        audio_filename = entry.get("audio_filename", "")

        if not midi_filename or not audio_filename:
            continue

        midi_src = os.path.join(MAESTRO_DIR, midi_filename)
        audio_src = os.path.join(MAESTRO_DIR, audio_filename)

        if not os.path.exists(midi_src) or not os.path.exists(audio_src):
            continue

        base_name = os.path.splitext(os.path.basename(audio_filename))[0]
        base_name = base_name.replace(" ", "_").replace("'", "")

        if split == "train":
            dest_dir = train_dir
            train_count += 1
        elif split in ("validation", "test"):
            dest_dir = val_dir
            val_count += 1
        else:
            continue

        midi_dest = os.path.join(dest_dir, base_name + ".mid")
        audio_dest = os.path.join(dest_dir, base_name + ".wav")

        if not os.path.exists(midi_dest):
            shutil.copy2(midi_src, midi_dest)
        if not os.path.exists(audio_dest):
            shutil.copy2(audio_src, audio_dest)

    print(f"Organized: {train_count} train, {val_count} validation pairs")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Step 1: Download
    if not os.path.exists(MAESTRO_DIR):
        if not os.path.exists(MAESTRO_ZIP):
            print(f"Downloading MAESTRO v2.0.0 (full version with real piano audio)...")
            print(f"URL: {MAESTRO_URL}")
            print("This is ~120 GB, will take a while...")
            download_with_progress(MAESTRO_URL, MAESTRO_ZIP)

        # Step 2: Extract
        print(f"\nExtracting {MAESTRO_ZIP}...")
        with zipfile.ZipFile(MAESTRO_ZIP, "r") as zf:
            total = len(zf.namelist())
            for i, name in enumerate(zf.namelist()):
                if i % 100 == 0:
                    print(f"\r  Extracting: {i}/{total} files", end="", flush=True)
                zf.extract(name, DATA_DIR)
        print(f"\n  Extraction complete")

    # Step 3: Organize
    print("\nOrganizing into train/validation splits...")
    organize_maestro()

    # Step 4: Clean up zip to save space
    if os.path.exists(MAESTRO_ZIP):
        zip_size = os.path.getsize(MAESTRO_ZIP) / 1024**3
        print(f"\nMAESTRO zip file: {zip_size:.1f} GB")
        print("You can delete it after organizing: del D:\\PianoTraining\\data\\maestro-v2.0.0.zip")

    print("\nDone! Next step: python precompute.py")


if __name__ == "__main__":
    main()
