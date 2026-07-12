import os
import random
import torch
import torch.nn.functional as F
import numpy as np
import torchaudio
import pretty_midi
from torch.utils.data import Dataset

from config import (
    SAMPLE_RATE, N_FFT, HOP_SIZE, N_MELS, MEL_FMIN, MEL_FMAX,
    MIDI_MIN, MIDI_MAX, N_PITCHES, FRAME_RATE,
    SEGMENT_SECONDS, SEGMENT_SAMPLES, SEGMENT_FRAMES, DATA_DIR,
)


def midi_to_labels(
    midi_path: str, duration: float, frame_rate: float = FRAME_RATE
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n_frames = int(duration * frame_rate) + 1
    note_on = np.zeros((N_PITCHES, n_frames), dtype=np.float32)
    note_off = np.zeros((N_PITCHES, n_frames), dtype=np.float32)
    velocity = np.zeros((N_PITCHES, n_frames), dtype=np.float32)

    pm = pretty_midi.PrettyMIDI(midi_path)
    for instrument in pm.instruments:
        if instrument.is_drum:
            continue
        for note in instrument.notes:
            pitch = note.pitch
            if pitch < MIDI_MIN or pitch > MIDI_MAX:
                continue
            pitch_idx = pitch - MIDI_MIN
            start_frame = max(0, min(int(note.start * frame_rate), n_frames - 1))
            end_frame = max(0, min(int(note.end * frame_rate), n_frames - 1))
            note_on[pitch_idx, start_frame] = 1.0
            note_off[pitch_idx, end_frame] = 1.0
            vel = note.velocity / 127.0
            velocity[pitch_idx, start_frame : end_frame + 1] = np.maximum(
                velocity[pitch_idx, start_frame : end_frame + 1], vel
            )
    return note_on, note_off, velocity


class PrecomputedDataset(Dataset):
    """
    Loads precomputed mel+labels from .pt files.
    Each file contains the full song; we randomly crop segments.
    """
    def __init__(
        self,
        data_dir: str = DATA_DIR,
        split: str = "train",
        segment_frames: int = SEGMENT_FRAMES,
        augment: bool = True,
        segments_per_file: int = 4,  # 每首歌采样4段
    ):
        self.data_dir = data_dir
        self.split = split
        self.segment_frames = segment_frames
        self.augment = augment and (split == "train")
        self.segments_per_file = segments_per_file
        self.cache_dir = os.path.join(data_dir, split, "_precomputed")
        self.index: list[str] = []
        self._build_index()

    def _build_index(self):
        if not os.path.exists(self.cache_dir):
            print(f"Warning: {self.cache_dir} does not exist.")
            return
        for f in sorted(os.listdir(self.cache_dir)):
            if f.endswith(".pt"):
                full_path = os.path.join(self.cache_dir, f)
                try:
                    data = torch.load(full_path, map_location="cpu", weights_only=True)
                    if data["mel"].shape[-1] >= self.segment_frames:
                        self.index.append(full_path)
                    # else: skip too short files
                except Exception:
                    try:
                        os.remove(full_path)
                    except:
                        pass
        print(f"Found {len(self.index)} valid precomputed {self.split} files")

    def __len__(self) -> int:
        return len(self.index) * self.segments_per_file

    def __getitem__(self, idx: int) -> dict:
        file_idx = idx % len(self.index)
        data = torch.load(self.index[file_idx], map_location="cpu", weights_only=True)
        mel = data["mel"]
        note_on = data["note_on"]
        note_off = data["note_off"]
        velocity = data["velocity"]

        n_frames = mel.shape[-1]

        if self.augment:
            max_start = max(0, n_frames - self.segment_frames)
            start = random.randint(0, max_start)
        else:
            start = max(0, (n_frames - self.segment_frames) // 2)

        end = start + self.segment_frames
        if end > n_frames:
            pad = end - n_frames
            mel = F.pad(mel, (0, pad))
            note_on = F.pad(note_on, (0, pad))
            note_off = F.pad(note_off, (0, pad))
            velocity = F.pad(velocity, (0, pad))

        mel_seg = mel[:, start:end]
        on_seg = note_on[:, start:end]
        off_seg = note_off[:, start:end]
        vel_seg = velocity[:, start:end]

        # Data augmentation
        if self.augment:
            # Gain variation
            if random.random() < 0.3:
                gain = random.uniform(0.7, 1.3)
                mel_seg = mel_seg * gain
            # Pitch shift (mel bin shift)
            if random.random() < 0.2:
                shift = random.randint(-3, 3)
                if shift != 0:
                    mel_seg = torch.roll(mel_seg, shift, dims=0)
                    on_seg = torch.roll(on_seg, shift, dims=0)
                    off_seg = torch.roll(off_seg, shift, dims=0)
                    vel_seg = torch.roll(vel_seg, shift, dims=0)
                    if shift > 0:
                        mel_seg[:shift, :] = 0
                        on_seg[:shift, :] = 0
                        off_seg[:shift, :] = 0
                        vel_seg[:shift, :] = 0
                    else:
                        mel_seg[shift:, :] = 0
                        on_seg[shift:, :] = 0
                        off_seg[shift:, :] = 0
                        vel_seg[shift:, :] = 0
            # Time mask
            if random.random() < 0.15:
                mask_len = random.randint(1, 20)
                mask_start = random.randint(0, self.segment_frames - mask_len)
                mel_seg[:, mask_start:mask_start + mask_len] = 0

        return {
            "mel": mel_seg,
            "note_on": on_seg,
            "note_off": off_seg,
            "velocity": vel_seg,
        }
