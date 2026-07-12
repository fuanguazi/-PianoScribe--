"""Create Transkun-compatible dataset from MAESTRO MIDI + synthesized WAV."""
import os
import sys
import csv
import wave
import pickle
import argparse
import pretty_midi
import numpy as np

# Import Transkun's data parsing
from transkun.Data import parseEventAll


def create_dataset(midi_dir, wav_dir, output_dir, extend_pedal=False):
    """Create Transkun-compatible pickle files."""
    os.makedirs(output_dir, exist_ok=True)

    csv_path = os.path.join(midi_dir, "maestro-v3.0.0.csv")
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found")
        return

    train_entries = []
    val_entries = []
    test_entries = []

    with open(csv_path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            midi_filename = row['midi_filename']
            audio_filename = row['audio_filename']
            split = row['split']

            midi_path = os.path.join(midi_dir, midi_filename)
            # Use synthesized WAV
            wav_filename = midi_filename.replace('.midi', '.wav')
            wav_path = os.path.join(wav_dir, wav_filename)

            if not os.path.exists(midi_path):
                continue
            if not os.path.exists(wav_path):
                continue

            try:
                # Parse MIDI
                midi = pretty_midi.PrettyMIDI(midi_path)
                if len(midi.instruments) == 0:
                    continue

                inst = midi.instruments[0]
                events = parseEventAll(inst.notes, inst.control_changes,
                                       extendSustainPedal=extend_pedal)

                # Get WAV metadata
                with wave.open(wav_path) as wf:
                    fs = wf.getframerate()
                    n_samples = wf.getnframes()
                    n_channel = wf.getnchannels()

                entry = dict(row)  # Copy all CSV fields
                entry['notes'] = events
                entry['fs'] = fs
                entry['nSamples'] = n_samples
                entry['nChannel'] = n_channel
                # Override audio_filename to point to synthesized WAV
                entry['audio_filename'] = wav_filename

                if split == 'train':
                    train_entries.append(entry)
                elif split == 'validation':
                    val_entries.append(entry)
                elif split == 'test':
                    test_entries.append(entry)

            except Exception as e:
                print(f"  Error processing {midi_filename}: {e}")
                continue

    # If no validation, split from train
    if len(val_entries) == 0 and len(train_entries) > 10:
        split_idx = int(len(train_entries) * 0.85)
        val_entries = train_entries[split_idx:]
        train_entries = train_entries[:split_idx]

    print(f"Dataset: train={len(train_entries)}, val={len(val_entries)}, test={len(test_entries)}")

    with open(os.path.join(output_dir, 'train.pickle'), 'wb') as f:
        pickle.dump(train_entries, f, pickle.HIGHEST_PROTOCOL)
    with open(os.path.join(output_dir, 'val.pickle'), 'wb') as f:
        pickle.dump(val_entries, f, pickle.HIGHEST_PROTOCOL)
    with open(os.path.join(output_dir, 'test.pickle'), 'wb') as f:
        pickle.dump(test_entries, f, pickle.HIGHEST_PROTOCOL)

    return output_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--midi-dir", default=r"D:\PianoTraining\data\maestro-v3.0.0")
    parser.add_argument("--wav-dir", default=r"D:\PianoTraining\data\maestro-wav")
    parser.add_argument("--output-dir", default=r"D:\PianoTraining\transkun_dataset")
    args = parser.parse_args()

    create_dataset(args.midi_dir, args.wav_dir, args.output_dir)
