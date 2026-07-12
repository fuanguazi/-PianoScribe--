"""Export trained CRNN model weights as JSON for TypeScript inference."""
import os
import sys
import json
import argparse

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(__file__))
from config import N_MELS, N_PITCHES, CHECKPOINT_DIR, EXPORT_DIR
from model import TranscriptionCRNN


def export_weights_json(checkpoint_path=None, output_path=None):
    """Export model weights as JSON for TypeScript/JavaScript inference.

    Args:
        checkpoint_path: Path to model checkpoint. Defaults to best_model.pt.
        output_path: Path to save JSON file. Defaults to export/model_weights.json.
    """
    if checkpoint_path is None:
        checkpoint_path = os.path.join(CHECKPOINT_DIR, "best_model.pt")
    if output_path is None:
        output_path = os.path.join(EXPORT_DIR, "model_weights.json")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    device = torch.device("cpu")

    # Load model
    model = TranscriptionCRNN(n_mels=N_MELS, n_pitches=N_PITCHES)
    if os.path.exists(checkpoint_path):
        ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
        if "generator" in ckpt:
            model.load_state_dict(ckpt["generator"])
        else:
            model.load_state_dict(ckpt)
        print(f"Loaded checkpoint: {checkpoint_path}")
    else:
        print(f"WARNING: Checkpoint not found at {checkpoint_path}, using random weights")

    model.eval()

    # Extract weights
    weights_dict = {}
    for name, param in model.named_parameters():
        key = name.replace(".", "/")
        weights_dict[key] = param.detach().numpy().tolist()

    # Also save model architecture info
    arch_info = {
        "model_type": "TranscriptionCRNN",
        "n_mels": N_MELS,
        "n_pitches": N_PITCHES,
        "num_parameters": sum(p.numel() for p in model.parameters()),
    }

    output = {
        "architecture": arch_info,
        "weights": weights_dict,
    }

    # Save JSON
    print(f"Saving weights JSON to: {output_path}")
    with open(output_path, "w") as f:
        json.dump(output, f)

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Saved! File size: {file_size_mb:.1f} MB")
    print(f"Number of parameters: {arch_info['num_parameters']:,}")

    # Also save a smaller version with float16 for web deployment
    output_path_fp16 = output_path.replace(".json", "_fp16.json")
    weights_fp16 = {}
    for name, param in model.named_parameters():
        key = name.replace(".", "/")
        weights_fp16[key] = param.detach().half().numpy().astype(np.float16).tolist()

    output_fp16 = {
        "architecture": arch_info,
        "weights": weights_fp16,
    }

    with open(output_path_fp16, "w") as f:
        json.dump(output_fp16, f)

    file_size_fp16_mb = os.path.getsize(output_path_fp16) / (1024 * 1024)
    print(f"FP16 weights saved to: {output_path_fp16} ({file_size_fp16_mb:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export model weights as JSON")
    parser.add_argument("--checkpoint", type=str, default=None, help="Path to model checkpoint")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file path")
    args = parser.parse_args()

    export_weights_json(args.checkpoint, args.output)
