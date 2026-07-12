import os
import sys
import shutil
import numpy as np
import pretty_midi
import soundfile as sf
from tqdm import tqdm

SAMPLE_RATE = 22050

def midi_to_audio(midi_path: str, output_path: str, sr: int = SAMPLE_RATE) -> bool:
    try:
        pm = pretty_midi.PrettyMIDI(midi_path)
        audio = pm.synthesize(fs=sr)
        if audio.ndim > 1:
            audio = audio.mean(axis=0)
        peak = np.max(np.abs(audio))
        if peak > 1e-7:
            audio = audio / peak
        sf.write(output_path, audio, sr)
        return True
    except Exception as e:
        return False

def process_maestro(data_dir: str, output_dir: str):
    raw_dir = os.path.join(data_dir, "_raw_midi", "maestro-v3.0.0")
    if not os.path.exists(raw_dir):
        raw_dir2 = os.path.join(data_dir, "_raw_midi")
        if os.path.exists(raw_dir2):
            raw_dir = raw_dir2
        else:
            print(f"ERROR: {raw_dir} not found.")
            return

    midi_files = []
    for root, dirs, files in os.walk(raw_dir):
        for f in files:
            if f.lower().endswith((".mid", ".midi")):
                midi_files.append(os.path.join(root, f))
    midi_files.sort()

    print(f"Found {len(midi_files)} MIDI files")

    n_total = len(midi_files)
    n_train = int(n_total * 0.9)
    n_val = n_total - n_train

    train_files = midi_files[:n_train]
    val_files = midi_files[n_train:]

    print(f"Train: {len(train_files)}, Validation: {len(val_files)}")

    for split_name, file_list in [("train", train_files), ("validation", val_files)]:
        split_dir = os.path.join(output_dir, split_name)
        os.makedirs(split_dir, exist_ok=True)
        print(f"\nProcessing {split_name} ({len(file_list)} files)...")

        success = 0
        failed = 0

        for midi_path in tqdm(file_list, desc=f"Synthesizing {split_name}"):
            base = os.path.splitext(os.path.basename(midi_path))[0]
            dest_audio = os.path.join(split_dir, base + ".wav")
            dest_midi = os.path.join(split_dir, base + ".mid")

            if not os.path.exists(dest_midi):
                try:
                    shutil.copy2(midi_path, dest_midi)
                except:
                    failed += 1
                    continue

            if not os.path.exists(dest_audio):
                if midi_to_audio(midi_path, dest_audio):
                    success += 1
                else:
                    failed += 1
                    try:
                        if os.path.exists(dest_midi):
                            os.remove(dest_midi)
                    except:
                        pass
            else:
                success += 1

        print(f"  {split_name}: {success} synthesized, {failed} failed")

    print("\nAudio synthesis complete!")
    print(f"Output directory: {output_dir}")

if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "data")
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "data")
    process_maestro(data_dir, output_dir)
