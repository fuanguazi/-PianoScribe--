"""Synthesize WAV files from MAESTRO MIDI for Transkun fine-tuning.

Uses pretty_midi's built-in synthesizer (no external dependencies).
Processes in batches to control disk space.
"""
import os
import sys
import argparse
import numpy as np
import pandas as pd


def synthesize_midi_pretty(midi_path, wav_path, sample_rate=44100):
    """Synthesize a MIDI file to WAV using pretty_midi."""
    import pretty_midi

    try:
        midi = pretty_midi.PrettyMIDI(midi_path)
        audio = midi.fluidsynth(fs=sample_rate)
        if audio.ndim == 2:
            audio = audio.mean(axis=0)  # mono
        # Normalize
        max_val = np.abs(audio).max()
        if max_val > 0:
            audio = audio / max_val * 0.9

        import soundfile as sf
        sf.write(wav_path, audio, sample_rate)
        return True
    except Exception as e:
        print(f"  Error: {e}")
        return False


def synthesize_midi_simple(midi_path, wav_path, sample_rate=44100):
    """Synthesize a MIDI file to WAV using simple sine wave synthesis.
    Fallback when fluidsynth is not available.
    """
    import pretty_midi

    try:
        midi = pretty_midi.PrettyMIDI(midi_path)
        duration = midi.get_end_time() + 1.0
        audio = np.zeros(int(duration * sample_rate))

        for instrument in midi.instruments:
            for note in instrument.notes:
                start_sample = int(note.start * sample_rate)
                end_sample = int(note.end * sample_rate)
                if start_sample >= len(audio) or end_sample <= start_sample:
                    continue

                freq = 440.0 * (2.0 ** ((note.pitch - 69) / 12.0))
                t = np.arange(end_sample - start_sample) / sample_rate
                # Simple sine with envelope
                envelope = np.ones(len(t))
                attack = min(int(0.01 * sample_rate), len(t) // 4)
                release = min(int(0.05 * sample_rate), len(t) // 4)
                if attack > 0:
                    envelope[:attack] = np.linspace(0, 1, attack)
                if release > 0:
                    envelope[-release:] = np.linspace(1, 0, release)

                amplitude = note.velocity / 127.0 * 0.3
                signal = amplitude * envelope * np.sin(2 * np.pi * freq * t)

                end_idx = min(end_sample, len(audio))
                audio[start_sample:end_idx] += signal[:end_idx - start_sample]

        # Normalize
        max_val = np.abs(audio).max()
        if max_val > 0:
            audio = audio / max_val * 0.9

        import soundfile as sf
        sf.write(wav_path, audio.astype(np.float32), sample_rate)
        return True
    except Exception as e:
        print(f"  Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--midi-dir", default=r"D:\PianoTraining\data")
    parser.add_argument("--output-dir", default=r"D:\PianoTraining\data\maestro-wav")
    parser.add_argument("--max-files", type=int, default=200)  # Start with 200
    parser.add_argument("--method", default="simple", choices=["fluidsynth", "simple"])
    args = parser.parse_args()

    # Load MAESTRO metadata
    csv_path = os.path.join(args.midi_dir, "maestro-v3.0.0", "maestro-v3.0.0.csv")
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found")
        return

    df = pd.read_csv(csv_path)
    os.makedirs(args.output_dir, exist_ok=True)

    # Process train split
    splits_to_process = ['train']
    if args.max_files > 200:
        splits_to_process.append('validation')

    for split in splits_to_process:
        split_df = df[df['split'] == split]
        if split == 'train':
            count = min(len(split_df), args.max_files) if args.max_files > 0 else len(split_df)
        else:
            count = min(len(split_df), max(args.max_files // 4, 20)) if args.max_files > 0 else len(split_df)

        print(f"\nProcessing {count} {split} MIDI files with {args.method} synthesis...")
        split_df = split_df.head(count)

        synthesize = synthesize_midi_simple if args.method == "simple" else synthesize_midi_pretty

        success = 0
        failed = 0
        for i, (_, row) in enumerate(split_df.iterrows()):
            midi_filename = row['midi_filename']
            midi_path = os.path.join(args.midi_dir, "maestro-v3.0.0", midi_filename)
            wav_filename = midi_filename.replace('.midi', '.wav')
            wav_path = os.path.join(args.output_dir, wav_filename)

            if os.path.exists(wav_path):
                success += 1
                continue

            if not os.path.exists(midi_path):
                failed += 1
                continue

            os.makedirs(os.path.dirname(wav_path), exist_ok=True)

            if synthesize(midi_path, wav_path):
                success += 1
                if (i + 1) % 20 == 0:
                    print(f"  [{i+1}/{count}] {success} OK, {failed} failed")
            else:
                failed += 1

        print(f"  {split} Done: {success} synthesized, {failed} failed")

    # Check disk space
    total_size = 0
    for root, dirs, files in os.walk(args.output_dir):
        for f in files:
            if f.endswith('.wav'):
                total_size += os.path.getsize(os.path.join(root, f))
    print(f"Total WAV size: {total_size / 1024 / 1024:.0f} MB")


if __name__ == "__main__":
    main()
