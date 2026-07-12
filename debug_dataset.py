import os
import torch
from dataset import PrecomputedDataset

# Check what _build_index finds
cache_dir = os.path.join(r"D:\PianoTraining\data\train\_precomputed")
files = os.listdir(cache_dir)
pt_files = [f for f in files if f.endswith('.pt')]
print(f"Total .pt files in cache_dir: {len(pt_files)}")

if pt_files:
    first = os.path.join(cache_dir, pt_files[0])
    print(f"First file: {first}")
    try:
        data = torch.load(first, map_location="cpu", weights_only=True)
        mel = data["mel"]
        print(f"mel shape: {mel.shape}")
        print(f"mel frames: {mel.shape[-1]}")
        print(f"SEGMENT_FRAMES from config: 250")
        print(f"Is mel frames >= 250? {mel.shape[-1] >= 250}")
    except Exception as e:
        print(f"Error loading: {e}")

# Now try the dataset
ds = PrecomputedDataset(split="train", segment_frames=250)
print(f"\nDataset length: {len(ds)}")
print(f"Index length: {len(ds.index)}")
