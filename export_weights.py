"""Export model weights as JSON for TypeScript inference fallback."""
import os
import json
import base64
import struct
import torch
from config import (
    CHECKPOINT_DIR, EXPORT_DIR, N_MELS, N_PITCHES,
    CONV_CHANNELS, DILATIONS,
)
from model import TranscriptionNet


def tensor_to_b64(t: torch.Tensor) -> str:
    arr = t.detach().cpu().numpy().astype("float32")
    raw = arr.tobytes()
    return base64.b64encode(raw).decode("ascii")


def export_weights():
    device = torch.device("cpu")
    ckpt_path = os.path.join(CHECKPOINT_DIR, "best_model.pt")
    if not os.path.exists(ckpt_path):
        print("ERROR: No checkpoint found.")
        return

    net = TranscriptionNet()
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    net.load_state_dict(ckpt["model_state_dict"])
    net.eval()

    weights = {}
    for name, param in net.state_dict().items():
        weights[name] = {
            "shape": list(param.shape),
            "data": tensor_to_b64(param),
        }

    output = {
        "version": 2,
        "n_mels": N_MELS,
        "n_pitches": N_PITCHES,
        "channels": CONV_CHANNELS,
        "dilations": DILATIONS,
        "num_res_stages": 3,
        "weights": weights,
    }

    out_path = os.path.join(EXPORT_DIR, "piano_weights.json")
    with open(out_path, "w") as f:
        json.dump(output, f)

    size_mb = os.path.getsize(out_path) / 1024**2
    print(f"Exported: {out_path} ({size_mb:.1f} MB)")
    print(f"Total weight keys: {len(weights)}")


if __name__ == "__main__":
    export_weights()
