"""One-click pipeline: precompute -> train -> export -> test.

Usage:
    python run_all.py --maestro_dir D:\\PianoTraining\\data\\maestro-v3.0.0
    python run_all.py --skip_precompute
    python run_all.py --skip_train --test_audio path/to/audio.wav
"""
import os
import sys
import argparse
import time

sys.path.insert(0, os.path.dirname(__file__))

from config import CHECKPOINT_DIR, EXPORT_DIR, PRECOMPUTE_DIR, MAESTRO_DIR


def run_step(name, func, *args, **kwargs):
    """Run a pipeline step with timing and error handling."""
    print(f"\n{'='*70}")
    print(f"  STEP: {name}")
    print(f"{'='*70}")
    t0 = time.time()
    try:
        result = func(*args, **kwargs)
        elapsed = time.time() - t0
        print(f"  {name} completed in {elapsed:.1f}s")
        return result
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  {name} FAILED after {elapsed:.1f}s: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="One-click piano transcription training pipeline")
    parser.add_argument("--maestro_dir", type=str, default=MAESTRO_DIR,
                        help="MAESTRO dataset directory")
    parser.add_argument("--precompute_dir", type=str, default=PRECOMPUTE_DIR,
                        help="Precomputed data directory")
    parser.add_argument("--skip_precompute", action="store_true",
                        help="Skip precomputation step")
    parser.add_argument("--skip_train", action="store_true",
                        help="Skip training step")
    parser.add_argument("--skip_export", action="store_true",
                        help="Skip export step")
    parser.add_argument("--skip_test", action="store_true",
                        help="Skip test step")
    parser.add_argument("--test_audio", type=str, default=None,
                        help="Audio file for testing (required if not skipping test)")
    parser.add_argument("--device", type=str, default="cuda",
                        help="Device: cuda or cpu")
    args = parser.parse_args()

    total_t0 = time.time()

    # Step 1: Precompute
    if not args.skip_precompute:
        from train_adversarial import precompute_maestro
        run_step(
            "Precompute MAESTRO data",
            precompute_maestro,
            args.maestro_dir,
            args.precompute_dir,
        )
    else:
        print("\nSkipping precomputation step.")

    # Step 2: Train
    if not args.skip_train:
        from train_adversarial import train as train_fn

        class TrainArgs:
            pass
        train_args = TrainArgs()
        train_args.maestro_dir = args.maestro_dir
        train_args.precompute_dir = args.precompute_dir

        run_step("Adversarial training", train_fn, train_args)
    else:
        print("\nSkipping training step.")

    # Step 3: Export ONNX
    if not args.skip_export:
        from export_onnx import export_onnx
        run_step("Export to ONNX", export_onnx)
    else:
        print("\nSkipping ONNX export step.")

    # Step 3b: Export weights JSON
    if not args.skip_export:
        from export_weights import export_weights_json
        run_step("Export weights as JSON", export_weights_json)

    # Step 4: Test
    if not args.skip_test:
        if args.test_audio:
            from test_model import test_model
            run_step(
                "Test model",
                test_model,
                args.test_audio,
                device=args.device,
                compare_bytedance=True,
            )
        else:
            print("\nSkipping test step (no --test_audio provided).")
    else:
        print("\nSkipping test step.")

    total_elapsed = time.time() - total_t0
    print(f"\n{'='*70}")
    print(f"  Pipeline complete! Total time: {total_elapsed:.1f}s")
    print(f"{'='*70}")
    print(f"\nOutputs:")
    print(f"  Checkpoints: {CHECKPOINT_DIR}")
    print(f"  Exports:     {EXPORT_DIR}")


if __name__ == "__main__":
    main()
