"""Export trained CRNN model to ONNX format for mobile deployment."""
import os
import sys
import argparse

import torch
import torch.onnx

sys.path.insert(0, os.path.dirname(__file__))
from config import N_MELS, N_PITCHES, SEGMENT_FRAMES, CHECKPOINT_DIR, EXPORT_DIR
from model import TranscriptionCRNN


def export_onnx(checkpoint_path=None, output_path=None, opset_version=14):
    """Export the TranscriptionCRNN model to ONNX format.

    Args:
        checkpoint_path: Path to model checkpoint. Defaults to best_model.pt.
        output_path: Path to save ONNX file. Defaults to export/transcription_crnn.onnx.
        opset_version: ONNX opset version.
    """
    if checkpoint_path is None:
        checkpoint_path = os.path.join(CHECKPOINT_DIR, "best_model.pt")
    if output_path is None:
        output_path = os.path.join(EXPORT_DIR, "transcription_crnn.onnx")

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

    model.to(device)
    model.eval()

    # Create dummy input
    dummy_mel = torch.randn(1, N_MELS, SEGMENT_FRAMES, device=device)

    # Export
    print(f"Exporting to ONNX (opset {opset_version})...")
    torch.onnx.export(
        model,
        dummy_mel,
        output_path,
        export_params=True,
        opset_version=opset_version,
        do_constant_folding=True,
        input_names=["mel"],
        output_names=["onset", "offset", "frame", "velocity"],
        dynamic_axes={
            "mel": {0: "batch_size", 2: "time_steps"},
            "onset": {0: "batch_size", 1: "time_steps"},
            "offset": {0: "batch_size", 1: "time_steps"},
            "frame": {0: "batch_size", 1: "time_steps"},
            "velocity": {0: "batch_size", 1: "time_steps"},
        },
    )

    print(f"ONNX model saved to: {output_path}")

    # Verify
    try:
        import onnx
        onnx_model = onnx.load(output_path)
        onnx.checker.check_model(onnx_model)
        print("ONNX model verified successfully!")
    except ImportError:
        print("onnx package not installed, skipping verification")
    except Exception as e:
        print(f"ONNX verification warning: {e}")

    # Test with onnxruntime
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(output_path)
        mel_input = dummy_mel.numpy()
        outputs = sess.run(None, {"mel": mel_input})
        print(f"ONNX Runtime test passed!")
        print(f"  Output shapes: onset={outputs[0].shape}, offset={outputs[1].shape}, "
              f"frame={outputs[2].shape}, velocity={outputs[3].shape}")
    except ImportError:
        print("onnxruntime not installed, skipping runtime test")
    except Exception as e:
        print(f"ONNX Runtime test warning: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export CRNN model to ONNX")
    parser.add_argument("--checkpoint", type=str, default=None, help="Path to model checkpoint")
    parser.add_argument("--output", type=str, default=None, help="Output ONNX file path")
    parser.add_argument("--opset", type=int, default=14, help="ONNX opset version")
    args = parser.parse_args()

    export_onnx(args.checkpoint, args.output, args.opset)
