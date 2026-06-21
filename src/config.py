"""Configuration for piano transcription training."""
import os

# Audio / feature parameters
SAMPLE_RATE = 16000
N_FFT = 2048
HOP_SIZE = 512
N_MELS = 229  # ByteDance model uses 229 mel bins
MEL_FMIN = 30.0
MEL_FMAX = 8000.0
MIDI_MIN = 21
MIDI_MAX = 108
N_PITCHES = 88
FRAME_RATE = SAMPLE_RATE / HOP_SIZE  # ~31.25 fps

# Training
BATCH_SIZE = 128
LEARNING_RATE = 1e-3
NUM_EPOCHS = 100
SEGMENT_SECONDS = 8
SEGMENT_SAMPLES = int(SEGMENT_SECONDS * SAMPLE_RATE)
SEGMENT_FRAMES = int(SEGMENT_SECONDS * FRAME_RATE)

# Paths
DATA_DIR = r"D:\PianoTraining\data"
CHECKPOINT_DIR = r"D:\PianoTraining\app\checkpoints"
EXPORT_DIR = r"D:\PianoTraining\app\export"
MAESTRO_DIR = os.path.join(DATA_DIR, "maestro-v3.0.0")
PRECOMPUTE_DIR = os.path.join(DATA_DIR, "precomputed_v6")

# Adversarial training
DISCRIMINATOR_LR = 1e-5  # Much lower than generator to prevent D from dominating
GENERATOR_LR = 5e-4
LAMBDA_ADV = 0.5  # Increase adversarial weight
LAMBDA_SUPERVISED = 1.0

# Ensure directories exist
for d in [DATA_DIR, CHECKPOINT_DIR, EXPORT_DIR, PRECOMPUTE_DIR]:
    os.makedirs(d, exist_ok=True)
