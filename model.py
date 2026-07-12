import math
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np

from config import (
    N_FFT, HOP_SIZE, N_MELS, SAMPLE_RATE, N_PITCHES,
    MEL_FMIN, MEL_FMAX, CONV_CHANNELS, DILATIONS, NUM_RES_STAGES,
    ONNX_INPUT_NAME, ONNX_OUTPUT_NAMES,
)


class DilatedResBlock(nn.Module):
    """Dilated residual block with pre-activation."""
    def __init__(self, channels: int, dilations: list[int]):
        super().__init__()
        self.layers = nn.ModuleList()
        for d in dilations:
            padding = d * (3 - 1) // 2
            self.layers.append(nn.Sequential(
                nn.BatchNorm1d(channels),
                nn.ReLU(inplace=True),
                nn.Conv1d(channels, channels, 3, padding=padding, dilation=d),
                nn.BatchNorm1d(channels),
                nn.ReLU(inplace=True),
                nn.Conv1d(channels, channels, 1),
            ))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for layer in self.layers:
            x = x + layer(x)
        return x


class FreqAttention(nn.Module):
    """Lightweight frequency attention: learns which mel bins matter."""
    def __init__(self, n_mels: int, reduction: int = 8):
        super().__init__()
        mid = max(n_mels // reduction, 8)
        self.fc = nn.Sequential(
            nn.AdaptiveAvgPool1d(1),
            nn.Flatten(),
            nn.Linear(n_mels, mid),
            nn.ReLU(inplace=True),
            nn.Linear(mid, n_mels),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, c, t = x.shape
        w = self.fc(x).view(b, c, 1)
        return x * w


class TranscriptionNet(nn.Module):
    """
    Piano transcription network with 3 residual stages + frequency attention.
    ~5M parameters for high accuracy.
    """
    def __init__(self, n_mels: int = N_MELS, n_pitches: int = N_PITCHES):
        super().__init__()
        ch = CONV_CHANNELS  # [192, 384, 512]

        # Frontend: mel -> ch[0]
        self.frontend = nn.Sequential(
            nn.Conv1d(n_mels, ch[0], 7, padding=3),
            nn.BatchNorm1d(ch[0]),
            nn.ReLU(inplace=True),
            FreqAttention(ch[0]),
            nn.Conv1d(ch[0], ch[0], 3, padding=1),
            nn.BatchNorm1d(ch[0]),
            nn.ReLU(inplace=True),
        )

        # Stage 1: ch[0] with dilations
        self.res1 = DilatedResBlock(ch[0], DILATIONS)

        # Transition 1 -> ch[1]
        self.trans1 = nn.Sequential(
            nn.Conv1d(ch[0], ch[1], 1),
            nn.BatchNorm1d(ch[1]),
            nn.ReLU(inplace=True),
        )

        # Stage 2: ch[1] with dilations
        self.res2 = DilatedResBlock(ch[1], DILATIONS)

        # Transition 2 -> ch[2]
        self.trans2 = nn.Sequential(
            nn.Conv1d(ch[1], ch[2], 1),
            nn.BatchNorm1d(ch[2]),
            nn.ReLU(inplace=True),
        )

        # Stage 3: ch[2] with dilations
        self.res3 = DilatedResBlock(ch[2], DILATIONS)

        # Output heads
        self.note_on_head = nn.Sequential(
            nn.Conv1d(ch[2], ch[2] // 2, 1),
            nn.ReLU(inplace=True),
            nn.Conv1d(ch[2] // 2, n_pitches, 1),
            nn.Sigmoid(),
        )
        self.note_off_head = nn.Sequential(
            nn.Conv1d(ch[2], ch[2] // 2, 1),
            nn.ReLU(inplace=True),
            nn.Conv1d(ch[2] // 2, n_pitches, 1),
            nn.Sigmoid(),
        )
        self.velocity_head = nn.Sequential(
            nn.Conv1d(ch[2], ch[2] // 2, 1),
            nn.ReLU(inplace=True),
            nn.Conv1d(ch[2] // 2, n_pitches, 1),
            nn.Sigmoid(),
        )

    def forward(self, mel_spec: torch.Tensor):
        x = self.frontend(mel_spec)
        x = self.res1(x)
        x = self.trans1(x)
        x = self.res2(x)
        x = self.trans2(x)
        x = self.res3(x)
        note_on = self.note_on_head(x)
        note_off = self.note_off_head(x)
        velocity = self.velocity_head(x)
        return note_on, note_off, velocity


class STFTLayer(nn.Module):
    def __init__(self, n_fft: int = N_FFT, hop_length: int = HOP_SIZE):
        super().__init__()
        self.n_fft = n_fft
        self.hop_length = hop_length
        window = torch.hann_window(n_fft)
        n_bins = n_fft // 2 + 1
        freqs = torch.arange(n_bins).float()
        times = torch.arange(n_fft).float()
        angles = 2.0 * math.pi * freqs.unsqueeze(1) * times.unsqueeze(0) / n_fft
        cos_basis = torch.cos(angles) * window.unsqueeze(0)
        sin_basis = torch.sin(angles) * window.unsqueeze(0)
        self.register_buffer("cos_weight", cos_basis.unsqueeze(1))
        self.register_buffer("sin_weight", sin_basis.unsqueeze(1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        real = F.conv1d(x, self.cos_weight, stride=self.hop_length)
        imag = F.conv1d(x, self.sin_weight, stride=self.hop_length)
        magnitude = (real * real + imag * imag).sqrt()
        return magnitude


class MelFilterbankLayer(nn.Module):
    def __init__(self, n_fft=N_FFT, n_mels=N_MELS, sample_rate=SAMPLE_RATE,
                 fmin=MEL_FMIN, fmax=MEL_FMAX):
        super().__init__()
        n_bins = n_fft // 2 + 1
        mel_fb = self._create_mel_filterbank(n_bins, n_mels, sample_rate, fmin, fmax)
        self.register_buffer("mel_fb", torch.from_numpy(mel_fb).float())

    def _create_mel_filterbank(self, n_bins, n_mels, sr, fmin, fmax):
        def hz2mel(hz): return 2595.0 * math.log10(1.0 + hz / 700.0)
        def mel2hz(mel): return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)
        mel_min, mel_max = hz2mel(fmin), hz2mel(fmax)
        mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
        hz_points = np.array([mel2hz(m) for m in mel_points])
        bin_points = np.floor((N_FFT + 1) * hz_points / sr).astype(int)
        fb = np.zeros((n_mels, n_bins))
        for i in range(n_mels):
            left, center, right = bin_points[i], bin_points[i+1], bin_points[i+2]
            for j in range(left, center):
                if j < n_bins and center > left:
                    fb[i, j] = (j - left) / (center - left)
            for j in range(center, right):
                if j < n_bins and right > center:
                    fb[i, j] = (right - j) / (right - center)
        return fb

    def forward(self, magnitude: torch.Tensor) -> torch.Tensor:
        return torch.matmul(self.mel_fb, magnitude)


class ONNXExportModel(nn.Module):
    def __init__(self, transcription_net: TranscriptionNet):
        super().__init__()
        self.stft = STFTLayer()
        self.mel_fb = MelFilterbankLayer()
        self.net = transcription_net

    def forward(self, audio: torch.Tensor):
        magnitude = self.stft(audio)
        mel = self.mel_fb(magnitude)
        mel = torch.log(mel + 1e-7)
        mel = mel - mel.mean(dim=-1, keepdim=True)
        mel_std = mel.std(dim=-1, keepdim=True)
        mel_std = torch.clamp(mel_std, min=1e-5)
        mel = mel / mel_std
        note_on, note_off, velocity = self.net(mel)
        return note_on, note_off, velocity


if __name__ == "__main__":
    model = TranscriptionNet()
    total_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {total_params:,}")
    print(f"Model size (float32): {total_params * 4 / 1024 / 1024:.1f} MB")

    mel = torch.randn(2, N_MELS, 250)
    note_on, note_off, vel = model(mel)
    print(f"Input mel shape: {mel.shape}")
    print(f"Output note_on shape: {note_on.shape}")
    print(f"Output note_off shape: {note_off.shape}")
    print(f"Output velocity shape: {vel.shape}")
