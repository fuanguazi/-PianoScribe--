import math

# ===== Audio Parameters =====
SAMPLE_RATE = 16000       # 降到16kHz，减少计算量，钢琴主要频率在8kHz以下
N_FFT = 2048
HOP_SIZE = 512
N_MELS = 224              # 更精细的mel分辨率
MEL_FMIN = 30.0
MEL_FMAX = 8000.0
MIDI_MIN = 21
MIDI_MAX = 108
N_PITCHES = MIDI_MAX - MIDI_MIN + 1  # 88
FRAME_RATE = SAMPLE_RATE / HOP_SIZE   # 31.25 fps

# ===== Training Parameters =====
BATCH_SIZE = 64           # RTX 4090 16GB，64 batch足够
LEARNING_RATE = 1e-3
NUM_EPOCHS = 50
SEGMENT_SECONDS = 8       # 更长片段=更多上下文
SEGMENT_SAMPLES = int(SEGMENT_SECONDS * SAMPLE_RATE)
SEGMENT_FRAMES = int(SEGMENT_SECONDS * FRAME_RATE)

# ===== Model Architecture (更大更深) =====
CONV_CHANNELS = [192, 384, 512]  # 3层，更宽
DILATIONS = [1, 2, 4, 8, 16, 32]  # 6层膨胀，更大感受野
NUM_RES_STAGES = 3                  # 3个残差阶段

# ===== Loss Parameters =====
FOCAL_ALPHA = 0.25
FOCAL_GAMMA = 2.0
LOSS_WEIGHT_ONSET = 5.0
LOSS_WEIGHT_OFFSET = 1.0
LOSS_WEIGHT_VELOCITY = 1.0

# ===== Paths =====
CHECKPOINT_DIR = r"D:\PianoTraining\checkpoints"
EXPORT_DIR = r"D:\PianoTraining\export"
DATA_DIR = r"D:\PianoTraining\data"

# ===== ONNX Export =====
ONNX_INPUT_NAME = "input"
ONNX_OUTPUT_NAMES = ["note_on", "note_off", "velocity"]

# ===== Data Loading =====
NUM_WORKERS = 0            # Windows多进程DataLoader有已知问题，设为0
PREFETCH_FACTOR = 4        # 预取4个batch
PERSISTENT_WORKERS = True   # 保持worker进程存活

# ===== Disk Space Control =====
MIN_FREE_GB = 10           # 最低保留磁盘空间
PRECOMPUTE_BATCH = 50      # 每批预计算50个文件后检查磁盘
