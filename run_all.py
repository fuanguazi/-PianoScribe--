"""
One-click training pipeline:
1. Download MAESTRO v2.0.0 (real piano recordings + MIDI)
2. Extract and organize
3. Precompute mel+labels (with disk space control)
4. Train model
5. Export ONNX + weights JSON
6. Copy to app assets
"""
import os
import sys
import shutil
import subprocess

DATA_DIR = r"D:\PianoTraining\data"
APP_ASSETS = r"c:\Users\Administrator\Desktop\乐谱生成\assets\models"

def run(cmd: str, desc: str):
    print(f"\n{'='*60}")
    print(f"  STEP: {desc}")
    print(f"{'='*60}")
    ret = subprocess.call(cmd, shell=True, cwd=r"D:\PianoTraining")
    if ret != 0:
        print(f"ERROR: {desc} failed with code {ret}")
        return False
    return True

def main():
    print("Piano Transcription Training Pipeline")
    print("=" * 60)

    # Step 1: Download MAESTRO
    if not os.path.exists(os.path.join(DATA_DIR, "maestro-v2.0.0")):
        print("\n[1/5] Downloading MAESTRO v2.0.0...")
        print("This is ~120 GB. It will take a while.")
        if not run(f'python download_maestro.py', "Download MAESTRO"):
            print("Download failed. You can re-run to resume.")
            return
    else:
        print("\n[1/5] MAESTRO already downloaded, skipping.")

    # Step 2: Precompute
    print("\n[2/5] Precomputing mel spectrograms + labels...")
    if not run(f'python precompute.py', "Precompute"):
        print("Precompute had errors. Check output above.")

    # Step 3: Train
    print("\n[3/5] Training model...")
    if not run(f'python train.py', "Train"):
        print("Training failed.")
        return

    # Step 4: Export ONNX
    print("\n[4/5] Exporting ONNX model...")
    run(f'python export_onnx.py', "Export ONNX")

    # Step 5: Export weights JSON
    print("\n[5/5] Exporting weights JSON...")
    run(f'python export_weights.py', "Export weights")

    # Step 6: Copy to app
    print("\n[6/6] Copying to app assets...")
    os.makedirs(APP_ASSETS, exist_ok=True)
    export_dir = r"D:\PianoTraining\export"
    for f in ["piano_transcription_mel.onnx", "piano_weights.json"]:
        src = os.path.join(export_dir, f)
        if os.path.exists(src):
            dst = os.path.join(APP_ASSETS, f)
            shutil.copy2(src, dst)
            print(f"  Copied: {f} ({os.path.getsize(dst)/1024**2:.1f} MB)")

    print("\n" + "=" * 60)
    print("  PIPELINE COMPLETE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
