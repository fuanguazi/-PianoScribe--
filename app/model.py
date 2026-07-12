"""CRNN model and Discriminator for adversarial piano transcription training."""
import torch
import torch.nn as nn
import torch.nn.functional as F


class ConvBlock(nn.Module):
    """Conv block: Conv2d -> BN -> ReLU -> MaxPool"""

    def __init__(self, in_ch, out_ch, kernel_size=(3, 3), padding=(1, 1)):
        super().__init__()
        self.conv = nn.Conv2d(in_ch, out_ch, kernel_size, padding=padding)
        self.bn = nn.BatchNorm2d(out_ch)
        self.relu = nn.ReLU()
        self.pool = nn.MaxPool2d((2, 1))  # Pool along frequency (H dim in NCHW)

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        x = self.relu(x)
        x = self.pool(x)
        return x


class TranscriptionCRNN(nn.Module):
    """CRNN model for piano transcription (similar to ByteDance approach)."""

    def __init__(self, n_mels=229, n_pitches=88):
        super().__init__()
        self.n_mels = n_mels
        self.n_pitches = n_pitches

        # Conv feature extractor
        self.conv1 = ConvBlock(1, 32)
        self.conv2 = ConvBlock(32, 64)
        self.conv3 = ConvBlock(64, 128)
        self.conv4 = ConvBlock(128, 192)
        self.conv5 = ConvBlock(192, 256)

        # Calculate freq dimension after 5 pool layers: n_mels -> n_mels/32
        freq_dim = n_mels // (2 ** 5)  # After 5 MaxPool(2,1) on frequency

        # Bidirectional GRU
        self.gru = nn.GRU(
            input_size=256 * freq_dim,
            hidden_size=128,
            num_layers=2,
            batch_first=True,
            bidirectional=True,
        )

        # Output heads (no sigmoid - use BCEWithLogitsLoss for AMP safety)
        fc_in = 128 * 2  # bidirectional
        self.onset_head = nn.Linear(fc_in, n_pitches)
        self.offset_head = nn.Linear(fc_in, n_pitches)
        self.frame_head = nn.Linear(fc_in, n_pitches)
        self.velocity_head = nn.Linear(fc_in, n_pitches)

    def forward(self, mel):
        """
        Args:
            mel: [B, n_mels, T] mel spectrogram
        Returns:
            onset, offset, frame, velocity: each [B, T, 88]
        """
        # mel: [B, n_mels, T]
        x = mel.unsqueeze(1)  # [B, 1, n_mels, T]
        x = self.conv1(x)
        x = self.conv2(x)
        x = self.conv3(x)
        x = self.conv4(x)
        x = self.conv5(x)  # [B, 256, freq_dim, T]

        # Reshape for GRU: [B, T, 256*freq_dim]
        B, C, F_dim, T = x.shape
        x = x.permute(0, 3, 1, 2).reshape(B, T, C * F_dim)

        # GRU
        x, _ = self.gru(x)  # [B, T, 256]

        # Output heads
        onset = self.onset_head(x)  # [B, T, 88]
        offset = self.offset_head(x)
        frame = self.frame_head(x)
        velocity = self.velocity_head(x)

        return onset, offset, frame, velocity


class Discriminator(nn.Module):
    """Discriminator for adversarial training on piano roll outputs.

    Takes a piano roll [B, 88, T] and classifies real vs fake.
    Uses adaptive pooling to handle variable T dimensions.
    """

    def __init__(self, n_pitches=88):
        super().__init__()
        self.n_pitches = n_pitches

        self.conv1 = nn.Conv2d(1, 32, (3, 3), padding=(1, 1))
        self.conv2 = nn.Conv2d(32, 64, (3, 3), padding=(1, 1))
        self.conv3 = nn.Conv2d(64, 128, (3, 3), padding=(1, 1))
        self.bn1 = nn.BatchNorm2d(32)
        self.bn2 = nn.BatchNorm2d(64)
        self.bn3 = nn.BatchNorm2d(128)
        self.pool = nn.MaxPool2d((2, 2))
        self.relu = nn.ReLU()

        # Adaptive pool to fixed spatial size regardless of input T
        self.adaptive_pool = nn.AdaptiveAvgPool2d((11, 4))

        self.fc = nn.Sequential(
            nn.Linear(128 * 11 * 4, 512),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(512, 1),
        )

    def forward(self, piano_roll):
        """
        Args:
            piano_roll: [B, 88, T] binary/soft piano roll
        Returns:
            logits: [B, 1] real vs fake score (before sigmoid for BCEWithLogitsLoss)
        """
        x = piano_roll.unsqueeze(1)  # [B, 1, 88, T]
        x = self.pool(self.relu(self.bn1(self.conv1(x))))
        x = self.pool(self.relu(self.bn2(self.conv2(x))))
        x = self.pool(self.relu(self.bn3(self.conv3(x))))
        x = self.adaptive_pool(x)  # [B, 128, 11, 4]
        x = x.reshape(x.shape[0], -1)  # [B, 128*11*4]
        return self.fc(x)
