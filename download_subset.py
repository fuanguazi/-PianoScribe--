"""
Alternative: Download individual MAESTRO WAV+MIDI files from the web.
Uses the MAESTRO v2.0.0 metadata JSON to get file URLs.
Downloads only a subset to start training quickly.
"""
import os
import sys
import json
import shutil

DATA_DIR = r"D:\PianoTraining\data"

def download_file(url: str, dest: str):
    try:
        import requests
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
        import requests

    if os.path.exists(dest):
        return True
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"  Error downloading {url}: {e}")
        if os.path.exists(dest):
            os.remove(dest)
        return False


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Download metadata first (small file)
    metadata_url = "https://storage.googleapis.com/magentadata/datasets/maestro/v2.0.0/maestro-v2.0.0.json"
    metadata_path = os.path.join(DATA_DIR, "maestro-v2.0.0.json")

    print("Downloading MAESTRO metadata...")
    if not download_file(metadata_url, metadata_path):
        print("Failed to download metadata")
        return

    with open(metadata_path, "r") as f:
        metadata = json.load(f)

    print(f"Total pieces in MAESTRO: {len(metadata)}")

    # Group by split
    train_entries = [e for e in metadata if e["split"] == "train"]
    val_entries = [e for e in metadata if e["split"] in ("validation", "test")]

    print(f"Train pieces: {len(train_entries)}")
    print(f"Validation pieces: {len(val_entries)}")

    # Download subset: first 100 train + 20 validation
    MAX_TRAIN = 100
    MAX_VAL = 20

    train_dir = os.path.join(DATA_DIR, "train")
    val_dir = os.path.join(DATA_DIR, "validation")
    os.makedirs(train_dir, exist_ok=True)
    os.makedirs(val_dir, exist_ok=True)

    base_url = "https://storage.googleapis.com/magentadata/datasets/maestro/v2.0.0/"

    def download_entries(entries, dest_dir, max_count, label):
        downloaded = 0
        skipped = 0
        for entry in entries:
            if downloaded >= max_count:
                break

            audio_url = base_url + entry["audio_filename"]
            midi_url = base_url + entry["midi_filename"]

            base_name = os.path.splitext(os.path.basename(entry["audio_filename"]))[0]
            base_name = base_name.replace(" ", "_").replace("'", "")

            audio_dest = os.path.join(dest_dir, base_name + ".wav")
            midi_dest = os.path.join(dest_dir, base_name + ".mid")

            print(f"  [{downloaded+1}/{max_count}] {base_name}...")

            if download_file(midi_url, midi_dest):
                if download_file(audio_url, audio_dest):
                    downloaded += 1
                    audio_size = os.path.getsize(audio_dest) / 1024**2
                    print(f"    OK ({audio_size:.1f} MB)")
                else:
                    print(f"    Audio download failed")
            else:
                print(f"    MIDI download failed")

        print(f"  {label}: {downloaded} downloaded, {skipped} already existed")
        return downloaded

    print(f"\nDownloading {MAX_TRAIN} train pieces...")
    download_entries(train_entries, train_dir, MAX_TRAIN, "Train")

    print(f"\nDownloading {MAX_VAL} validation pieces...")
    download_entries(val_entries, val_dir, MAX_VAL, "Validation")

    # Check disk
    import shutil
    free_gb = shutil.disk_usage(DATA_DIR).free / 1024**3
    print(f"\nDisk free: {free_gb:.1f} GB")

    print("\nDone! Next step: python precompute.py")


if __name__ == "__main__":
    main()
