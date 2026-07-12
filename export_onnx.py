"""Export trained model to ONNX format."""
import os
import torch
from config import (
    CHECKPOINT_DIR, EXPORT_DIR, ONNX_INPUT_NAME, ONNX_OUTPUT_NAMES,
    N_MELS, N_PITCHES, SAMPLE_RATE,
)
from model import TranscriptionNet, ONNXExportModel


def export_onnx(include_stft: bool = True):
    device = torch.device("cpu")
    ckpt_path = os.path.join(CHECKPOINT_DIR, "best_model.pt")
    if not os.path.exists(ckpt_path):
        print("ERROR: No checkpoint found. Train first.")
        return

    net = TranscriptionNet()
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    net.load_state_dict(ckpt["model_state_dict"])
    net.eval()

    os.makedirs(EXPORT_DIR, exist_ok=True)

    if include_stft:
        model = ONNXExportModel(net)
        model.eval()
        dummy = torch.randn(1, 1, SAMPLE_RATE * 5)
        input_name = ONNX_INPUT_NAME
        onnx_path = os.path.join(EXPORT_DIR, "piano_transcription_full.onnx")
    else:
        model = net
        dummy = torch.randn(1, N_MELS, 250)
        input_name = ONNX_INPUT_NAME
        onnx_path = os.path.join(EXPORT_DIR, "piano_transcription_mel.onnx")

    torch.onnx.export(
        model,
        dummy,
        onnx_path,
        input_names=[input_name],
        output_names=ONNX_OUTPUT_NAMES,
        opset_version=13,
        dynamic_axes={
            input_name: {0: "batch", 2: "time"},
            ONNX_OUTPUT_NAMES[0]: {0: "batch", 2: "time"},
            ONNX_OUTPUT_NAMES[1]: {0: "batch", 2: "time"},
            ONNX_OUTPUT_NAMES[2]: {0: "batch", 2: "time"},
        },
    )

    size_mb = os.path.getsize(onnx_path) / 1024**2
    print(f"Exported: {onnx_path} ({size_mb:.1f} MB)")

    # Also export mel-only version (smaller, for WebView)
    if include_stft:
        mel_path = os.path.join(EXPORT_DIR, "piano_transcription_mel.onnx")
        net.eval()
        dummy_mel = torch.randn(1, N_MELS, 250)
        torch.onnx.export(
            net,
            dummy_mel,
            mel_path,
            input_names=[ONNX_INPUT_NAME],
            output_names=ONNX_OUTPUT_NAMES,
            opset_version=13,
            dynamic_axes={
                ONNX_INPUT_NAME: {0: "batch", 2: "time"},
                ONNX_OUTPUT_NAMES[0]: {0: "batch", 2: "time"},
                ONNX_OUTPUT_NAMES[1]: {0: "batch", 2: "time"},
                ONNX_OUTPUT_NAMES[2]: {0: "batch", 2: "time"},
            },
        )
        mel_size = os.path.getsize(mel_path) / 1024**2
        print(f"Exported: {mel_path} ({mel_size:.1f} MB)")


if __name__ == "__main__":
    export_onnx(include_stft=True)
