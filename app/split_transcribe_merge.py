"""Split audio into vocals + accompaniment, transcribe separately, merge.

Pipeline v16:
1. Audio separation via pymss Python API (3-tier fallback):
   a. Mel-Band RoFormer (big_beta7) — SOTA vocal quality
   b. BS-RoFormer (HyperACE v2) — equally SOTA, alternative architecture
   c. SCNet (scnet_checkpoint_musdb18) — fast fallback, ~2x faster than RoFormer
2. Transkun: transcribe accompaniment (instrument.wav) → accompaniment.mid
3. Basic Pitch: transcribe vocals (vocals.wav) → vocals.mid (fallback: SwiftF0 → CREPE)
4. Smart merge: dual-track output (Accompaniment + Vocals), normalize velocities
5. Post-merge cleaning: apply conservative 8-step filter
"""
import os
import sys
import argparse
import subprocess
import shutil
import numpy as np
import pretty_midi
from collections import Counter
import logging
from datetime import datetime

# Setup logging
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, f'transcribe_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

# Only setup if not already configured
if not logging.getLogger('transcribe').handlers:
    _handler = logging.FileHandler(_LOG_FILE, encoding='utf-8')
    _handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'))
    _logger = logging.getLogger('transcribe')
    _logger.setLevel(logging.DEBUG)
    _logger.addHandler(_handler)
    # Also add stream handler for console output
    _stream = logging.StreamHandler()
    _stream.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s'))
    _logger.addHandler(_stream)
else:
    _logger = logging.getLogger('transcribe')

# Silence noisy third-party loggers
for _noisy in ['numba', 'numba.core', 'numba.core.byteflow', 'numba.core.interpreter',
               'librosa', 'torch', 'urllib3', 'matplotlib', 'PIL']:
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = _logger


def _auto_device(purpose=None):
    """Auto-detect best available device, possibly overridden by user settings.

    Args:
        purpose: 'separation' / 'transcription' / None.
            If a settings override exists for that purpose it wins;
            otherwise we fall through to torch-based auto-detection.
    """
    if purpose is not None:
        try:
            import app_settings
            choice = app_settings.get_device_for(purpose)
            if choice == 'cuda':
                return 'cuda'
            if choice == 'cpu':
                return 'cpu'
            # 'auto' → fall through to detection below
        except Exception as e:
            logger.debug(f"[Settings] failed to read device settings: {e}")
    try:
        import torch
        return 'cuda' if torch.cuda.is_available() else 'cpu'
    except ImportError:
        return 'cpu'


def detect_glissandi(notes, threshold_semitones=5, threshold_time=0.3):
    """检测滑音：两个音符之间音高差>threshold_semitones且间隔<threshold_time秒。
    在这两个音符之间插入pitch bend事件标记。
    """
    glissandi = []
    sorted_notes = sorted(notes, key=lambda n: n.start)
    for i in range(len(sorted_notes) - 1):
        curr = sorted_notes[i]
        next_n = sorted_notes[i + 1]
        pitch_diff = abs(next_n.pitch - curr.pitch)
        time_gap = next_n.start - curr.end
        if pitch_diff >= threshold_semitones and time_gap < threshold_time:
            glissandi.append({
                'start_pitch': curr.pitch,
                'end_pitch': next_n.pitch,
                'start_time': curr.end,
                'end_time': next_n.start,
                'semitones': pitch_diff
            })
    return glissandi


def _separate_with_pymss(audio_path, output_dir, model_name, sep_subdir,
                         skip_if_exists=True, inference_params=None,
                         download_source=None):
    """Generic helper: separate audio into vocals + instrumental using a pymss catalog model.

    Args:
        audio_path: Input audio file path
        output_dir: Output base directory (will create sep_subdir under it)
        model_name: pymss catalog model name (e.g. "big_beta7", "scnet_checkpoint_musdb18")
        sep_subdir: Subdirectory name under output_dir (e.g. "separated_melbandroformer")
        skip_if_exists: If True, reuse existing separated stems instead of re-running
        inference_params: optional dict {chunk_size, batch_size, overlap_size} (samples)
            forwarded to MSSeparator.from_model_name. None = use pymss defaults.
        download_source: 'modelscope' / 'hf-mirror' / 'auto' / None.
            'auto'/None = try _DOWNLOAD_SOURCES in order.

    Returns:
        (vocals_path, instrument_path) on success, (None, None) on failure.
        instrument_path is the "_other.wav" file produced by pymss for vocal models.
    """
    import glob

    audio_name = os.path.splitext(os.path.basename(audio_path))[0]
    sep_dir = os.path.join(output_dir, sep_subdir)
    vocals_path = os.path.join(sep_dir, f"{audio_name}_vocals.wav")
    # pymss vocal models emit stems {vocals, other}; "other" is the instrumental.
    instrument_path = os.path.join(sep_dir, f"{audio_name}_instrument.wav")
    other_path = os.path.join(sep_dir, f"{audio_name}_other.wav")

    if skip_if_exists:
        if os.path.exists(vocals_path) and (
            os.path.exists(instrument_path) or os.path.exists(other_path)
        ):
            logger.info(f"[{model_name}] Already separated, skipping: {vocals_path}")
            actual = instrument_path if os.path.exists(instrument_path) else other_path
            return vocals_path, actual

    logger.info(f"[{model_name}] Separating: {audio_path}")
    os.makedirs(sep_dir, exist_ok=True)

    try:
        from pymss import MSSeparator
    except ImportError:
        logger.error(
            f"[{model_name}] pymss not installed. "
            "Install with: pip install \"pymss>=2.0.9\""
        )
        return None, None

    # Resolve download source list. If user picked a specific source in settings,
    # only try that one; otherwise try the full fallback chain.
    if download_source and download_source != 'auto':
        sources_to_try = (download_source,)
    else:
        sources_to_try = _DOWNLOAD_SOURCES

    device = _auto_device('separation')
    last_error = None
    for source in sources_to_try:
        try:
            logger.info(f"[{model_name}] Trying source={source}")
            kwargs = dict(
                download=True,
                device=device,
                output_format="wav",
                store_dirs=sep_dir,
                source=source,
            )
            if inference_params:
                kwargs['inference_params'] = inference_params
            with MSSeparator.from_model_name(model_name, **kwargs) as separator:
                separator.process_folder(audio_path)
            last_error = None
            break
        except Exception as e:
            last_error = e
            logger.warning(f"[{model_name}] source={source} failed: {e}")
            continue
    if last_error is not None:
        logger.error(f"[{model_name}] All download sources failed: {last_error}")
        return None, None

    if not os.path.exists(vocals_path):
        # Fall back to glob search in case pymss wrote to a different filename pattern
        candidates = glob.glob(os.path.join(sep_dir, f"{audio_name}_*.wav"))
        vocals_candidates = [c for c in candidates if "_vocals" in c]
        if not vocals_candidates:
            logger.error(f"[{model_name}] vocals.wav not produced in {sep_dir}")
            return None, None
        vocals_path = vocals_candidates[0]

    actual_instrument = instrument_path if os.path.exists(instrument_path) else other_path
    if not os.path.exists(actual_instrument):
        candidates = glob.glob(os.path.join(sep_dir, f"{audio_name}_*.wav"))
        for c in candidates:
            if "_vocals" not in c:
                actual_instrument = c
                break

    if not os.path.exists(actual_instrument):
        logger.error(f"[{model_name}] instrumental stem not produced in {sep_dir}")
        return None, None

    logger.info(f"[{model_name}] Done: vocals={vocals_path}, instr={actual_instrument}")
    return vocals_path, actual_instrument


# Download sources tried in order. ModelScope is the pymss default but its
# CDN is occasionally unstable (broken-pipe mid-download); hf-mirror (a
# HuggingFace mirror) is the fallback. Both host the same model files
# under baicai1145/pymss.
_DOWNLOAD_SOURCES = ("modelscope", "hf-mirror")

# Catalog of fallback models. Ordered by preference (best quality first,
# fastest as last-resort). All three are invoked through the pymss Python API.
_SEPARATION_MODELS = (
    # (model_name, sep_subdir, display_label)
    ("big_beta7",                  "separated_melbandroformer", "Mel-Band RoFormer"),
    ("bs_roformer_voc_hyperacev2", "separated_bsroformer",     "BS-RoFormer"),
    ("scnet_checkpoint_musdb18",   "separated_scnet",          "SCNet"),
)


def separate_audio(audio_path, output_dir, skip_if_exists=True):
    """Separate audio into vocals and instrumental via pymss Python API.

    3-tier fallback chain (all models loaded through pymss catalog):
      1. Mel-Band RoFormer (big_beta7)       — SOTA vocal quality
      2. BS-RoFormer (HyperACE v2)           — equally SOTA, alternative architecture
      3. SCNet (scnet_checkpoint_musdb18)    — fast fallback, ~2x faster than RoFormer

    User settings can override:
      - sep.model_name         which model is tried first (rest stay as fallback)
      - sep.source             'auto' / 'modelscope' / 'hf-mirror'
      - sep.inference.*        forwarded as pymss inference_params (samples)

    Each model auto-downloads on first use (download=True). If pymss is not
    installed, returns (None, None) after logging a clear install hint.

    Returns:
        (vocals_path, instrument_path) or (None, None) if all models fail.
    """
    # Read user overrides from settings (best-effort; fall back to defaults).
    user_model = None
    user_source = 'auto'
    inf_params = None
    try:
        import app_settings
        user_model = app_settings.get_separation_model()
        user_source = app_settings.get_separation_source()
        inf_params = app_settings.get_separation_inference_params()
    except Exception as e:
        logger.debug(f"[Settings] failed to read sep settings (using defaults): {e}")

    # Build model order: user's pick first (dedup), rest as fallback.
    all_models = list(_SEPARATION_MODELS)
    if user_model:
        for i, (name, _subdir, _label) in enumerate(all_models):
            if name == user_model:
                if i > 0:
                    all_models.insert(0, all_models.pop(i))
                break

    for model_name, sep_subdir, label in all_models:
        vocals, instrument = _separate_with_pymss(
            audio_path, output_dir, model_name, sep_subdir, skip_if_exists,
            inference_params=inf_params,
            download_source=user_source,
        )
        if vocals is not None and instrument is not None:
            return vocals, instrument
        logger.warning(f"[{label}] Falling back to next model...")

    logger.error(
        "[Audio Separation] All 3 pymss models failed. "
        "Verify: pip install \"pymss>=2.0.9\" and that the audio file is readable."
    )
    return None, None


# ============================================================
# 模式2：4-stem 细化分离 + 4 音轨转录 + 合并
# ============================================================

def separate_audio_stems(audio_path, output_dir, skip_if_exists=True):
    """使用 pymss 4-stem 模型将音频分离为 vocals/drums/bass/other 四个音轨。

    一次分离即可得到 4 个音轨（比"先分离伴奏再细化"质量更高、速度更快）。
    使用 Mel-Band RoFormer 4-stem large 模型。

    Returns:
        dict: {'vocals': path, 'drums': path, 'bass': path, 'other': path}
        失败时返回 None。
    """
    import glob

    audio_name = os.path.splitext(os.path.basename(audio_path))[0]
    sep_dir = os.path.join(output_dir, "separated_4stems")
    stems = {}
    for stem in ('vocals', 'drums', 'bass', 'other'):
        stems[stem] = os.path.join(sep_dir, f"{audio_name}_{stem}.wav")

    if skip_if_exists and all(os.path.exists(p) for p in stems.values()):
        logger.info(f"[4-Stem] Already separated, skipping: {sep_dir}")
        return stems

    logger.info(f"[4-Stem] Separating into 4 stems: {audio_path}")
    os.makedirs(sep_dir, exist_ok=True)

    # pymss 4-stem 模型（一次分离出 vocals/drums/bass/other）
    cmd = [
        "pymss", "infer", "mel_band_roformer_4stems_large_ver1",
        "-i", audio_path,
        "-o", sep_dir,
        "--device", _auto_device('separation'),
        "--format", "wav"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        logger.error("[4-Stem] pymss not found. Please install: pip install pymss")
        return None
    if result.returncode != 0:
        logger.error(f"[4-Stem] Error: {result.stderr}")
        # 回退到 Demucs 4-stem
        logger.warning("[4-Stem] Falling back to Demucs htdemucs...")
        return _separate_stems_demucs(audio_path, output_dir, skip_if_exists)

    # pymss 4-stem 输出文件名可能是 {audio_name}_{stem}.wav 或 {stem}.wav
    # 查找实际输出文件
    for stem in ('vocals', 'drums', 'bass', 'other'):
        if not os.path.exists(stems[stem]):
            # 搜索匹配的文件
            candidates = glob.glob(os.path.join(sep_dir, f"*{stem}*.wav"))
            if candidates:
                stems[stem] = candidates[0]
            else:
                logger.warning(f"[4-Stem] Stem file not found: {stem}")
                stems[stem] = None  # 标记为缺失，调用方可判断

    # 检查是否至少有一个 stem 可用
    available = {k: v for k, v in stems.items() if v is not None}
    if not available:
        logger.error("[4-Stem] No stem files were found at all.")
        return None

    logger.info(f"[4-Stem] Done: {sep_dir}")
    return stems


def _separate_stems_demucs(audio_path, output_dir, skip_if_exists=True):
    """回退方案：使用 Demucs htdemucs 分离 4 个音轨。"""
    audio_name = os.path.splitext(os.path.basename(audio_path))[0]
    sep_dir = os.path.join(output_dir, "separated", "htdemucs", audio_name)
    stems = {
        'vocals': os.path.join(sep_dir, "vocals.wav"),
        'drums': os.path.join(sep_dir, "drums.wav"),
        'bass': os.path.join(sep_dir, "bass.wav"),
        'other': os.path.join(sep_dir, "other.wav"),
    }
    if skip_if_exists and all(os.path.exists(p) for p in stems.values()):
        logger.info(f"[Demucs 4-Stem] Already separated, skipping")
        return stems

    logger.info(f"[Demucs 4-Stem] Separating: {audio_path}")
    cmd = [
        sys.executable, "-m", "demucs",
        "-o", os.path.join(output_dir, "separated"),
        audio_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        logger.error("[Demucs 4-Stem] demucs not found.")
        return None
    if result.returncode != 0:
        logger.error(f"[Demucs 4-Stem] Error: {result.stderr}")
        return None

    logger.info(f"[Demucs 4-Stem] Done: {sep_dir}")
    return stems


def transcribe_stems(stems, work_dir, audio_name, sensitivity, denoise_mode='off'):
    """转录 4 个音轨为 MIDI，灵敏度参数同步。

    - vocals → Basic Pitch（人声参数：onset/frame/min_note_length）
    - other  → Transkun（伴奏参数：accomp_sensitivity）
    - drums  → Basic Pitch（伴奏灵敏度映射 onset）
    - bass   → Basic Pitch（伴奏灵敏度映射 onset）

    Returns:
        dict: {'vocals': mid_path, 'other': mid_path, 'drums': mid_path, 'bass': mid_path}
    """
    results = {}

    # --- vocals: Basic Pitch 人声转录 ---
    vocal_mid = os.path.join(work_dir, f"{audio_name}_vocals.mid")
    if os.path.exists(vocal_mid):
        logger.info(f"[Stems] Vocals MIDI exists, skipping")
        results['vocals'] = vocal_mid
    else:
        result = transcribe_vocals(
            stems['vocals'], vocal_mid,
            onset_threshold=sensitivity['vocal_onset_threshold'],
            frame_threshold=sensitivity['vocal_frame_threshold'],
            minimum_note_length=sensitivity['vocal_min_note_length'],
        )
        results['vocals'] = result if result else None

    # --- other: Transkun 伴奏转录 ---
    other_mid = os.path.join(work_dir, f"{audio_name}_other.mid")
    if os.path.exists(other_mid):
        logger.info(f"[Stems] Other MIDI exists, skipping")
        results['other'] = other_mid
    else:
        result = transcribe_accompaniment(
            stems['other'], other_mid,
            sensitivity=sensitivity['accomp_sensitivity'],
        )
        results['other'] = result if result else None

    # --- drums: Basic Pitch 鼓转录 ---
    # 鼓使用较高 onset 灵敏度（映射自 accomp_sensitivity）
    # accomp_sensitivity 0-100 → onset 0.3-0.7（高灵敏度→低阈值）
    drums_onset = 0.7 - (sensitivity['accomp_sensitivity'] / 100.0) * 0.4
    drums_mid = os.path.join(work_dir, f"{audio_name}_drums.mid")
    if os.path.exists(drums_mid):
        logger.info(f"[Stems] Drums MIDI exists, skipping")
        results['drums'] = drums_mid
    else:
        result = transcribe_vocals(
            stems['drums'], drums_mid,
            onset_threshold=drums_onset,
            frame_threshold=0.3,
            minimum_note_length=40,  # 鼓音符通常较短
        )
        results['drums'] = result if result else None

    # --- bass: Basic Pitch 贝斯转录 ---
    bass_onset = 0.7 - (sensitivity['accomp_sensitivity'] / 100.0) * 0.4
    bass_mid = os.path.join(work_dir, f"{audio_name}_bass.mid")
    if os.path.exists(bass_mid):
        logger.info(f"[Stems] Bass MIDI exists, skipping")
        results['bass'] = bass_mid
    else:
        result = transcribe_vocals(
            stems['bass'], bass_mid,
            onset_threshold=bass_onset,
            frame_threshold=0.3,
            minimum_note_length=60,
        )
        results['bass'] = result if result else None

    return results


def merge_midi_4stems(stem_mids, output_mid):
    """合并 4 个音轨 MIDI 为多轨 MIDI。

    每个音轨一个 track，program 分别为：
      - other  → Piano (program 0)
      - vocals → Piano (Vocal) (program 0, name 标记)
      - bass   → Bass (program 32, Acoustic Bass)
      - drums  → Drums (channel 9, program 0)

    Args:
        stem_mids: dict {'vocals': path, 'other': path, 'drums': path, 'bass': path}
        output_mid: 输出 MIDI 路径
    """
    logger.info(f"[Merge 4-Stem] Merging: {stem_mids}")

    merged = pretty_midi.PrettyMIDI()

    track_configs = [
        ('other',  'Piano',          0, False),
        ('vocals', 'Piano (Vocal)',  0, False),
        ('bass',   'Bass',          32, False),
        ('drums',  'Drums',          0, True),   # channel 9 = drums
    ]

    for stem_name, inst_name, program, is_drum in track_configs:
        mid_path = stem_mids.get(stem_name)
        if not mid_path or not os.path.exists(mid_path):
            logger.warning(f"[Merge 4-Stem] {stem_name} MIDI missing, skipping")
            continue
        try:
            src = pretty_midi.PrettyMIDI(mid_path)
        except Exception as e:
            logger.error(f"[Merge 4-Stem] Failed to read {stem_name}: {e}")
            continue

        inst = pretty_midi.Instrument(program=program, name=inst_name, is_drum=is_drum)
        for src_inst in src.instruments:
            for note in src_inst.notes:
                pitch = max(21, min(108, note.pitch))
                inst.notes.append(pretty_midi.Note(
                    velocity=note.velocity,
                    pitch=pitch,
                    start=note.start,
                    end=note.end,
                ))
        merged.instruments.append(inst)
        logger.info(f"[Merge 4-Stem] {stem_name}: {len(inst.notes)} notes")

    merged.write(output_mid)
    logger.info(f"[Merge 4-Stem] Done: {output_mid}")
    return output_mid


def transcribe_accompaniment(audio_path, output_mid, device=None, sensitivity=50):
    """Use Transkun to transcribe accompaniment (piano/instrumental).

    Args:
        audio_path: 输入音频路径
        output_mid: 输出 MIDI 路径
        device: 计算设备（None=自动检测）
        sensitivity: 灵敏度 0-100（默认 50）。
            映射到 transkun 的 --segmentHopSize：0→8s（粗），50→4s（中），100→2s（细）。
            注意必须同时传 --segmentSize=16，否则触发 transkun 2.0.x 的
            None-segmentSize bug（transcribe.py L732 only fills defaults
            when both --segmentHopSize and --segmentSize are absent）。

    Note: transkun 是端到端模型，hop 主要影响推理粒度和速度，对识别质量的
    影响相对有限。要真正调整"识别多少音符"，应配合后处理（见
    clean_accompaniment_strict 的 min_duration_ms / max_polyphony 等参数）。
    """
    if os.path.exists(output_mid):
        logger.info(f"[Transkun] Already exists, skipping: {output_mid}")
        return output_mid

    if device is None:
        device = _auto_device('transcription')

    # Map sensitivity 0-100 to segmentHopSize (8s→2s).
    # Always pass --segmentSize=16 to avoid transkun None-segmentSize bug.
    if sensitivity <= 50:
        hop = 8.0 - (8.0 - 4.0) * (sensitivity / 50.0)  # 8→4
    else:
        hop = 4.0 - (4.0 - 2.0) * ((sensitivity - 50) / 50.0)  # 4→2

    logger.info(f"[Transkun] Transcribing (device={device}, sensitivity={sensitivity}, hop={hop}s): {audio_path}")
    cmd = ["transkun", audio_path, output_mid, "--device", device,
           "--segmentHopSize", f"{hop}", "--segmentSize", "16"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        logger.error("[Transkun] transkun not found. Please install: pip install transkun")
        return None
    if result.returncode != 0:
        logger.error(f"[Transkun] Error: {result.stderr}")
        return None

    logger.info(f"[Transkun] Done: {output_mid}")
    return output_mid


def transcribe_vocals(audio_path, output_mid, onset_threshold=0.5,
                      frame_threshold=0.3, minimum_note_length=80):
    """v24: Basic Pitch ONNX 人声转录（Spotify 开源，业界认证）.

    Args:
        audio_path: 输入音频路径
        output_mid: 输出 MIDI 路径
        onset_threshold: onset 灵敏度（越低越灵敏，0.3-0.8，默认 0.5）
        frame_threshold: frame 阈值（越低越灵敏，0.1-0.6，默认 0.3）
        minimum_note_length: 最短音符时长（ms，默认 80）

    使用 Spotify Basic Pitch + ONNX Runtime：
    1. Basic Pitch (ICASSP 2022): 端到端音符检测
    2. ONNX Runtime: 跨平台推理后端
    """
    return _transcribe_vocals_basic_pitch(
        audio_path, output_mid,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=minimum_note_length,
    )


# ============================================================
# v24: Basic Pitch ONNX（Spotify 开源，业界认证人声转录）
# ============================================================

def _transcribe_vocals_basic_pitch(audio_path, output_mid,
                                  onset_threshold=0.5,
                                  frame_threshold=0.3,
                                  minimum_note_length=80):
    """Basic Pitch ONNX 人声转录 — Spotify 端到端音符检测（原始 v15 实现）.

    使用 Spotify Basic Pitch (ICASSP 2022) 深度学习模型进行端到端
    音频→MIDI 转录。与 F0 估计方法（SwiftF0/CREPE）不同，Basic Pitch
    直接从频谱图预测音符的 onset、offset 和音高，对人声更鲁棒。

    Args:
        audio_path: 输入音频路径
        output_mid: 输出 MIDI 路径
        onset_threshold: onset 灵敏度（越低越灵敏，0.3-0.8，默认 0.5）
        frame_threshold: frame 阈值（越低越灵敏，0.1-0.6，默认 0.3）
        minimum_note_length: 最短音符时长（ms，默认 80）

    优势：
    - 端到端音符检测（onset + offset + pitch 在一个模型内）
    - 更好的音符边界检测（针对人声）
    - 内置 pitch bend（颤音）检测
    - 不需要手动 onset 检测 + F0 + 分段流水线
    """
    from basic_pitch.inference import predict as bp_predict
    from basic_pitch import ICASSP_2022_MODEL_PATH

    logger.info(
        f"[BasicPitch] Transcribing vocals (ONNX): {audio_path} | "
        f"onset={onset_threshold:.2f}, frame={frame_threshold:.2f}, "
        f"min_len={minimum_note_length}ms"
    )

    try:
        model_output, midi_data, note_events = bp_predict(
            audio_path=audio_path,
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            onset_threshold=onset_threshold,        # onset 灵敏度（越低越灵敏）
            frame_threshold=frame_threshold,        # frame 阈值
            minimum_note_length=minimum_note_length,  # 最短音符时长(ms)
            minimum_frequency=65.0,     # ~C2，覆盖低音
            maximum_frequency=1046.5,   # ~C6，覆盖大多数演唱范围
            melodia_trick=True,         # 更好的单声部旋律提取
        )
    except Exception as e:
        logger.error(f"[BasicPitch] Prediction failed: {e}")
        return None

    # 使用 Basic Pitch 直接输出的 PrettyMIDI 对象
    # 它已包含正确的 pitch、onset、offset、velocity 和 pitch bends
    n_notes = sum(len(inst.notes) for inst in midi_data.instruments)
    n_bends = sum(len(inst.pitch_bends) for inst in midi_data.instruments)

    if n_notes == 0:
        logger.warning("[BasicPitch] No notes detected")
        midi_data.write(output_mid)
        return output_mid

    # 归一化：确保所有音高在有效 MIDI 范围内
    # 设置 instrument name 与下游流水线一致
    for inst in midi_data.instruments:
        inst.name = "Piano (Vocal)"
        inst.program = 0
        for note in inst.notes:
            note.pitch = max(21, min(108, note.pitch))
        # 限制 pitch bend 在标准 MIDI 范围内（-8192 到 8191）
        # Basic Pitch 可能产生超出此范围的值
        for pb in inst.pitch_bends:
            pb.pitch = max(-8192, min(8191, pb.pitch))

    # Basic Pitch 已包含 pitch bend 检测，跳过额外的滑音检测
    midi_data.write(output_mid)

    logger.info(f"[BasicPitch] Done: {output_mid} ({n_notes} notes, {n_bends} pitch bends)")
    return output_mid


def merge_midi_smart(accomp_mid, vocal_mid, output_mid):
    """Smart merge: output dual-track MIDI (Accompaniment + Vocals).
    No overlap resolution needed since tracks are separate.
    Velocity normalization: accomp mean=60, vocal mean=80.
    Glissandi pitch_bend preserved in vocal track."""
    logger.info(f"[Merge] Smart merging (dual-track): {accomp_mid} + {vocal_mid}")

    try:
        accomp_midi = pretty_midi.PrettyMIDI(accomp_mid)
        vocal_midi = pretty_midi.PrettyMIDI(vocal_mid)
    except Exception as e:
        logger.error(f"[Merge] Failed to read MIDI files: {e}")
        return None

    # Collect all notes from both sources
    accomp_notes = []
    for inst in accomp_midi.instruments:
        for n in inst.notes:
            accomp_notes.append({
                'pitch': n.pitch,
                'start': n.start,
                'end': n.end,
                'velocity': n.velocity,
            })

    vocal_notes = []
    for inst in vocal_midi.instruments:
        for n in inst.notes:
            vocal_notes.append({
                'pitch': max(21, min(108, n.pitch)),
                'start': n.start,
                'end': n.end,
                'velocity': n.velocity,
            })

    # Remove duplicate vocal notes (same pitch, overlapping time)
    if vocal_notes:
        vocal_notes.sort(key=lambda n: (n['pitch'], n['start']))
        deduped = [vocal_notes[0]]
        for n in vocal_notes[1:]:
            prev = deduped[-1]
            if (n['pitch'] == prev['pitch'] and
                n['start'] < prev['end'] and
                n['end'] - prev['start'] < 0.5):
                # Keep the longer/stronger note
                if (n['end'] - n['start']) > (prev['end'] - prev['start']):
                    deduped[-1] = n
            else:
                deduped.append(n)
        vocal_notes = deduped
        logger.info(f"  Vocal dedup: {len(vocal_notes)} notes after removing overlaps")

    logger.info(f"  Accompaniment notes: {len(accomp_notes)}")
    logger.info(f"  Vocal notes: {len(vocal_notes)}")

    # --- Velocity normalization ---
    if accomp_notes:
        accomp_vels = [n['velocity'] for n in accomp_notes]
        accomp_mean = np.mean(accomp_vels)
        accomp_std = np.std(accomp_vels)
    else:
        accomp_mean, accomp_std = 64, 20

    if vocal_notes:
        vocal_vels = [n['velocity'] for n in vocal_notes]
        vocal_mean = np.mean(vocal_vels)
        vocal_std = np.std(vocal_vels)
    else:
        vocal_mean, vocal_std = 64, 20

    # Target: accompaniment centered at 60, vocal louder at 80
    accomp_target_mean = 60
    accomp_target_std = 20
    vocal_target_mean = 80
    vocal_target_std = 18

    for n in accomp_notes:
        if accomp_std > 0:
            n['velocity'] = int(np.clip(
                accomp_target_mean + (n['velocity'] - accomp_mean) / accomp_std * accomp_target_std,
                25, 105
            ))
        else:
            n['velocity'] = accomp_target_mean

    for n in vocal_notes:
        if vocal_std > 0:
            n['velocity'] = int(np.clip(
                vocal_target_mean + (n['velocity'] - vocal_mean) / vocal_std * vocal_target_std,
                35, 115
            ))
        else:
            n['velocity'] = vocal_target_mean

    # --- Create output MIDI with two tracks ---
    merged_midi = pretty_midi.PrettyMIDI()

    # Track 0: Accompaniment
    accomp_inst = pretty_midi.Instrument(program=0, name="Accompaniment")
    for n in accomp_notes:
        note = pretty_midi.Note(
            velocity=n['velocity'],
            pitch=n['pitch'],
            start=n['start'],
            end=n['end']
        )
        accomp_inst.notes.append(note)
    accomp_inst.notes.sort(key=lambda n: n.start)

    # Track 1: Vocals
    vocal_inst = pretty_midi.Instrument(program=0, name="Vocals")
    for n in vocal_notes:
        note = pretty_midi.Note(
            velocity=n['velocity'],
            pitch=n['pitch'],
            start=n['start'],
            end=n['end']
        )
        vocal_inst.notes.append(note)
    vocal_inst.notes.sort(key=lambda n: n.start)

    # Copy pitch_bend events from vocal MIDI (glissandi) into vocal track
    for inst in vocal_midi.instruments:
        for pb in inst.pitch_bends:
            vocal_inst.pitch_bends.append(pretty_midi.PitchBend(pitch=pb.pitch, time=pb.time))
    vocal_inst.pitch_bends.sort(key=lambda pb: pb.time)
    if vocal_inst.pitch_bends:
        logger.info(f"  Copied {len(vocal_inst.pitch_bends)} pitch_bend events (glissandi) to vocal track")

    merged_midi.instruments.append(accomp_inst)
    merged_midi.instruments.append(vocal_inst)
    merged_midi.write(output_mid)

    total_notes = len(accomp_notes) + len(vocal_notes)
    logger.info(f"[Merge] Done: {output_mid} ({len(accomp_notes)} accomp + {len(vocal_notes)} vocal = {total_notes} notes)")
    return output_mid


def _find_audio_for_midi_global(midi_path):
    """Try to find the original audio file corresponding to a MIDI file.

    Searches in multiple locations:
    1. Same directory with common audio extensions
    2. separated_bsroformer directory for _instrument.wav
    3. Parent directory with common audio extensions
    """
    base = os.path.splitext(midi_path)[0]
    midi_dir = os.path.dirname(midi_path)
    parent_dir = os.path.dirname(midi_dir)

    candidates = []

    # 1. Same directory, same base name with audio extensions
    for ext in ['.wav', '.mp3', '.m4a', '.flac']:
        candidates.append(base + ext)

    # 2. separated_bsroformer directory
    for sep_subdir in ['separated_bsroformer', os.path.join('separated', 'htdemucs')]:
        sep_dir = os.path.join(parent_dir, sep_subdir) if parent_dir else os.path.join(midi_dir, sep_subdir)
        if os.path.isdir(sep_dir):
            for f in os.listdir(sep_dir):
                if f.endswith('.wav') and ('instrument' in f.lower() or 'no_vocals' in f.lower()):
                    candidates.append(os.path.join(sep_dir, f))

    # 3. Parent directory with audio extensions (original input file)
    midi_basename = os.path.splitext(os.path.basename(midi_path))[0]
    # Strip common suffixes like _piano, _merged, _cleaned
    for suffix in ['_piano', '_merged', '_cleaned', '_transkun']:
        if midi_basename.endswith(suffix):
            midi_basename = midi_basename[:-len(suffix)]
            break
    for ext in ['.wav', '.mp3', '.m4a', '.flac']:
        candidates.append(os.path.join(parent_dir, midi_basename + ext))
        candidates.append(os.path.join(midi_dir, midi_basename + ext))

    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def clean_accompaniment_strict(input_path, output_path,
                                removal_threshold=0.25,
                                min_duration_ms=80,
                                chord_strictness=0.25,
                                max_jump_semitones=12,
                                max_polyphony=6,
                                original_audio_path=None):
    """Intelligent denoising for accompaniment MIDI based on music theory.

    Args:
        input_path: Path to input MIDI file.
        output_path: Path to write cleaned MIDI file.
        removal_threshold: Notes with composite score below this are removed (0.0-0.5).
        min_duration_ms: Notes shorter than this (ms) are removed.
        chord_strictness: Higher values require stricter chord conformity (0.0-1.0).
        max_jump_semitones: Interval jumps larger than this are treated as noise.
        max_polyphony: Chords with more simultaneous notes than this are thinned.
        original_audio_path: Optional path to original audio file for spectral
            verification. If None, will attempt auto-detection.

    5-step algorithm inspired by D3RM (Discrete Denoising Diffusion Refinement):
      Step 1: Build piano-roll matrix (time × pitch)
      Step 2: Spectral energy verification (STFT, optional if audio exists)
      Step 3: Music theory constraints (chord detection, key detection, voice leading)
      Step 4: Temporal consistency (repeated pattern detection, rhythmic quantization)
      Step 5: Composite scoring + iterative denoising (up to 3 iterations)
    """

    # ============================================================
    # Helper: Krumhansl-Schmuckler key-finding algorithm
    # ============================================================
    _KEY_PROFILES = {
        'major': [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
        'minor': [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    }
    _NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

    def _detect_key(pitch_classes_weighted):
        """Krumhansl-Schmuckler key-finding.
        pitch_classes_weighted: array of length 12, weighted by velocity.
        Returns (key_name, correlation, is_major).
        """
        if np.sum(pitch_classes_weighted) < 1e-6:
            return ('C', 0.0, True)

        distribution = pitch_classes_weighted / np.sum(pitch_classes_weighted)
        best_key = 'C'
        best_corr = -1.0
        best_is_major = True

        for mode_name, profile in _KEY_PROFILES.items():
            profile_arr = np.array(profile, dtype=float)
            profile_mean = np.mean(profile_arr)
            profile_centered = profile_arr - profile_mean
            profile_norm = np.linalg.norm(profile_centered)

            for shift in range(12):
                rotated = np.roll(distribution, -shift)
                rotated_mean = np.mean(rotated)
                rotated_centered = rotated - rotated_mean
                rotated_norm = np.linalg.norm(rotated_centered)

                if profile_norm < 1e-9 or rotated_norm < 1e-9:
                    corr = 0.0
                else:
                    corr = np.dot(profile_centered, rotated_centered) / (profile_norm * rotated_norm)

                if corr > best_corr:
                    best_corr = corr
                    best_key = _NOTE_NAMES[shift]
                    best_is_major = (mode_name == 'major')

        return (best_key, best_corr, best_is_major)

    def _get_key_scale_notes(key_name, is_major):
        """Return set of pitch classes (0-11) in the given key/scale."""
        root = _NOTE_NAMES.index(key_name)
        if is_major:
            intervals = [0, 2, 4, 5, 7, 9, 11]  # major scale
        else:
            intervals = [0, 2, 3, 5, 7, 8, 10]   # natural minor scale
        return set((root + iv) % 12 for iv in intervals)

    # ============================================================
    # Helper: Chord detection
    # ============================================================
    # Common chord interval patterns (semitones from root)
    _CHORD_PATTERNS = {
        'major':      {0, 4, 7},
        'minor':      {0, 3, 7},
        'dim':        {0, 3, 6},
        'aug':        {0, 4, 8},
        'sus2':       {0, 2, 7},
        'sus4':       {0, 5, 7},
        'dom7':       {0, 4, 7, 10},
        'maj7':       {0, 4, 7, 11},
        'min7':       {0, 3, 7, 10},
        'dim7':       {0, 3, 6, 9},
        'hdim7':      {0, 3, 6, 10},
        'min_maj7':   {0, 3, 7, 11},
        'aug7':       {0, 4, 8, 10},
    }

    def _notes_form_chord(pitch_classes_set):
        """Check if a set of pitch classes (0-11) forms a common chord.
        Returns (is_chord, chord_name) or (False, None).
        """
        if len(pitch_classes_set) < 2:
            return (True, 'single')  # single note is always ok

        pc_list = sorted(pitch_classes_set)
        n_pc = len(pc_list)

        # For each possible root, check if intervals match a chord pattern
        for root in pc_list:
            intervals = set((pc - root) % 12 for pc in pc_list)
            for chord_name, pattern in _CHORD_PATTERNS.items():
                if intervals == pattern:
                    return (True, chord_name)
                # Also allow subset match for 3-note subsets of 4-note chords
                if n_pc == 3 and intervals.issubset(pattern) and len(intervals) >= 2:
                    return (True, f'{chord_name}_subset')

        # Check if any 3-4 note subset forms a chord (for larger clusters)
        if n_pc >= 4:
            from itertools import combinations
            for size in [4, 3]:
                for subset in combinations(pc_list, size):
                    subset_set = set(subset)
                    for root in subset_set:
                        intervals = set((pc - root) % 12 for pc in subset_set)
                        for chord_name, pattern in _CHORD_PATTERNS.items():
                            if intervals == pattern:
                                return (True, f'{chord_name}_partial')

        return (False, None)

    # ============================================================
    # Helper: Spectral energy verification
    # ============================================================
    def _verify_spectral_energy(notes, audio_path):
        """Check if each note's fundamental frequency has energy in the STFT.
        Returns dict: note_index -> spectral_score (0.0 to 1.0).
        """
        spectral_scores = {}
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=22050, mono=True)
            # STFT with decent frequency resolution
            n_fft = 4096
            hop_length = 512
            S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length))
            freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

            for i, note in enumerate(notes):
                midi_freq = 440.0 * (2.0 ** ((note.pitch - 69) / 12.0))
                # Find frequency bin closest to fundamental
                freq_bin = np.argmin(np.abs(freqs - midi_freq))
                # Time frame range for this note
                start_frame = max(0, int(note.start * sr / hop_length))
                end_frame = min(S.shape[1], int(note.end * sr / hop_length) + 1)
                if start_frame >= end_frame:
                    start_frame = max(0, end_frame - 1)

                # Energy at fundamental and nearby bins (±1 bin for slight detuning)
                if freq_bin > 0 and freq_bin < S.shape[0] - 1:
                    fund_energy = np.mean(S[freq_bin-1:freq_bin+2, start_frame:end_frame])
                elif freq_bin == 0:
                    fund_energy = np.mean(S[0:2, start_frame:end_frame])
                else:
                    fund_energy = np.mean(S[-2:, start_frame:end_frame])

                # Average energy across all frequencies in same time window (background)
                avg_energy = np.mean(S[:, start_frame:end_frame]) + 1e-10

                # Ratio of fundamental energy to average
                ratio = fund_energy / avg_energy
                if ratio > 2.0:
                    spectral_scores[i] = 1.0
                elif ratio > 1.0:
                    spectral_scores[i] = 0.7
                elif ratio > 0.5:
                    spectral_scores[i] = 0.4
                else:
                    spectral_scores[i] = 0.1

        except Exception as e:
            logger.warning(f"  [Spectral] Skipping spectral verification: {e}")

        return spectral_scores

    # ============================================================
    # Helper: Try to find audio file from MIDI path
    # ============================================================
    def _find_audio_for_midi(midi_path):
        """Try to find the original audio file corresponding to this MIDI."""
        base = os.path.splitext(midi_path)[0]
        midi_dir = os.path.dirname(midi_path)
        parent_dir = os.path.dirname(midi_dir)
        candidates = []
        # Same directory, look for common audio names
        for ext in ['.wav', '.mp3', '.m4a', '.flac']:
            # Try: base_name + ext
            candidates.append(base + ext)
            # Try: look in separated directories
            for sep_subdir in ['separated_bsroformer', os.path.join('separated', 'htdemucs')]:
                sep_dir = os.path.join(parent_dir, sep_subdir) if parent_dir else os.path.join(midi_dir, sep_subdir)
                if os.path.isdir(sep_dir):
                    for f in os.listdir(sep_dir):
                        if f.endswith(ext) and ('instrument' in f.lower() or 'no_vocals' in f.lower()):
                            candidates.append(os.path.join(sep_dir, f))

        # Also try parent directory with stripped suffixes
        midi_basename = os.path.splitext(os.path.basename(midi_path))[0]
        for suffix in ['_transkun', '_cleaned', '_merged', '_piano']:
            if midi_basename.endswith(suffix):
                midi_basename = midi_basename[:-len(suffix)]
                break
        for ext in ['.wav', '.mp3', '.m4a', '.flac']:
            candidates.append(os.path.join(parent_dir, midi_basename + ext))
            candidates.append(os.path.join(midi_dir, midi_basename + ext))

        for c in candidates:
            if os.path.exists(c):
                return c
        return None

    # ============================================================
    # Main algorithm
    # ============================================================
    try:
        midi = pretty_midi.PrettyMIDI(input_path)
    except Exception as e:
        logger.error(f"[CleanMid] Failed to read MIDI: {e}")
        return
    total_before = sum(len(inst.notes) for inst in midi.instruments)

    for inst in midi.instruments:
        notes = sorted(inst.notes, key=lambda n: n.start)
        if not notes:
            continue

        n_notes = len(notes)
        logger.info(f"\n  [Smart Denoise] Processing {n_notes} notes...")

        # Pre-compute arrays
        starts = np.array([n.start for n in notes])
        ends = np.array([n.end for n in notes])
        pitches = np.array([n.pitch for n in notes])
        velocities = np.array([n.velocity for n in notes])
        durations = ends - starts

        # ============================================================
        # Step 1: Build piano-roll matrix (time × pitch)
        # ============================================================
        TIME_RES = 0.05  # 50ms per column
        MIN_PITCH = 21
        MAX_PITCH = 108
        N_PITCHES = MAX_PITCH - MIN_PITCH + 1

        piece_end = ends[-1] + 1.0
        n_time_bins = int(np.ceil(piece_end / TIME_RES))

        # Piano roll: each cell = max velocity for notes active at that time
        piano_roll = np.zeros((N_PITCHES, n_time_bins), dtype=np.float32)
        note_to_bins = []  # For each note, list of (pitch_idx, time_bin) it occupies

        for i in range(n_notes):
            pitch_idx = pitches[i] - MIN_PITCH
            start_bin = max(0, int(starts[i] / TIME_RES))
            end_bin = min(n_time_bins, int(np.ceil(ends[i] / TIME_RES)))
            for t in range(start_bin, end_bin):
                piano_roll[pitch_idx, t] = max(piano_roll[pitch_idx, t], velocities[i])
            note_to_bins.append((pitch_idx, start_bin, end_bin))

        logger.info(f"  [Step 1] Piano roll: {N_PITCHES} pitches × {n_time_bins} time bins "
              f"(resolution={TIME_RES*1000:.0f}ms)")

        # ============================================================
        # Step 2: Spectral energy verification (optional)
        # ============================================================
        spectral_scores = {}
        audio_path = original_audio_path if original_audio_path and os.path.exists(original_audio_path) else None
        if audio_path is None:
            audio_path = _find_audio_for_midi(input_path)
        if audio_path:
            logger.info(f"  [Step 2] Found audio: {audio_path}")
            spectral_scores = _verify_spectral_energy(notes, audio_path)
            if spectral_scores:
                avg_spec = np.mean(list(spectral_scores.values()))
                low_spec_count = sum(1 for v in spectral_scores.values() if v < 0.3)
                logger.info(f"  [Step 2] Spectral verification: avg score={avg_spec:.3f}, "
                      f"{low_spec_count} notes with low spectral energy")
        else:
            logger.info(f"  [Step 2] No audio file found, skipping spectral verification")

        # ============================================================
        # Step 3: Music theory constraints
        # ============================================================

        # --- 3a: Key detection (Krumhansl-Schmuckler) ---
        pitch_classes_weighted = np.zeros(12)
        for i in range(n_notes):
            pc = pitches[i] % 12
            pitch_classes_weighted[pc] += velocities[i] * durations[i]

        key_name, key_corr, is_major = _detect_key(pitch_classes_weighted)
        scale_notes = _get_key_scale_notes(key_name, is_major)
        mode_str = 'major' if is_major else 'minor'
        logger.info(f"  [Step 3a] Detected key: {key_name} {mode_str} "
              f"(correlation={key_corr:.3f})")

        # Compute key conformity score for each note
        key_scores = np.zeros(n_notes)
        for i in range(n_notes):
            pc = pitches[i] % 12
            if pc in scale_notes:
                key_scores[i] = 1.0
            else:
                # Chromatic notes: not always noise, could be passing tones
                # Give partial score based on whether neighbors are in-key
                key_scores[i] = 0.4

        in_key_count = int(np.sum(key_scores >= 1.0))
        logger.info(f"  [Step 3a] Key conformity: {in_key_count}/{n_notes} notes in key "
              f"({in_key_count/n_notes*100:.1f}%)")

        # --- 3b: Chord detection ---
        # Group notes that sound simultaneously (within 50ms window)
        CHORD_WINDOW = 0.05  # 50ms
        chord_groups = []  # list of lists of note indices
        current_group = [0]
        for i in range(1, n_notes):
            if starts[i] - starts[current_group[0]] <= CHORD_WINDOW:
                current_group.append(i)
            else:
                chord_groups.append(current_group)
                current_group = [i]
        chord_groups.append(current_group)

        chord_scores = np.ones(n_notes)  # default: all notes are fine
        chord_labels = {}
        n_chord_groups = 0
        n_non_chord_notes = 0

        for group in chord_groups:
            if len(group) < 2:
                continue
            pitch_classes = set(pitches[i] % 12 for i in group)
            is_chord, chord_name = _notes_form_chord(pitch_classes)
            if is_chord:
                n_chord_groups += 1
                for i in group:
                    chord_labels[i] = chord_name
                    chord_scores[i] = 1.0
            else:
                # Not a standard chord - find which notes are "outliers"
                # Strategy: try removing each note and see if the rest form a chord
                if len(group) >= 3:
                    from itertools import combinations
                    best_subset = None
                    best_chord_name = None
                    for size in range(len(group) - 1, 2, -1):
                        for subset in combinations(group, size):
                            subset_pc = set(pitches[i] % 12 for i in subset)
                            is_sub_chord, sub_name = _notes_form_chord(subset_pc)
                            if is_sub_chord:
                                best_subset = set(subset)
                                best_chord_name = sub_name
                                break
                        if best_subset is not None:
                            break

                    if best_subset is not None:
                        for i in group:
                            if i in best_subset:
                                chord_scores[i] = 1.0
                                chord_labels[i] = best_chord_name
                            else:
                                chord_scores[i] = 0.3
                                n_non_chord_notes += 1
                    else:
                        # No good subset found; penalize all slightly
                        for i in group:
                            chord_scores[i] = 0.6
                else:
                    # 2-note group that's not a chord interval
                    for i in group:
                        chord_scores[i] = 0.7

        logger.info(f"  [Step 3b] Chord detection: {n_chord_groups} chord groups, "
              f"{n_non_chord_notes} non-chord outlier notes")

        # --- 3c: Voice leading (melodic interval check) ---
        voice_leading_scores = np.ones(n_notes)
        # Group notes by pitch proximity into "voices" (simple greedy approach)
        # Then check interval jumps within each voice
        MAX_JUMP = max_jump_semitones  # Use parameter (default: octave = reasonable max jump)
        n_large_jumps = 0

        for i in range(1, n_notes):
            # Find the closest previous note in time
            interval = abs(int(pitches[i] - pitches[i - 1]))
            if interval > MAX_JUMP:
                voice_leading_scores[i] = 0.1   # Stricter: was 0.3
                n_large_jumps += 1
            elif interval > 7:
                voice_leading_scores[i] = 0.4   # Stricter: was 0.6
            else:
                voice_leading_scores[i] = 1.0

        logger.info(f"  [Step 3c] Voice leading: {n_large_jumps} notes with large jumps (>{MAX_JUMP} semitones)")

        # ============================================================
        # Step 4: Temporal consistency
        # ============================================================

        # --- 4a: Repeated pattern detection ---
        # Slice piano roll into 2-second windows and compute similarity
        PATTERN_WINDOW_SEC = 2.0
        pattern_window_bins = int(PATTERN_WINDOW_SEC / TIME_RES)
        n_windows = max(1, n_time_bins // pattern_window_bins)

        if n_windows >= 2:
            # Create window vectors (flatten pitch×time for each window)
            window_vectors = []
            for w in range(n_windows):
                start_col = w * pattern_window_bins
                end_col = min((w + 1) * pattern_window_bins, n_time_bins)
                window_data = piano_roll[:, start_col:end_col].flatten()
                window_vectors.append(window_data)

            # Compute pairwise cosine similarity
            window_matrix = np.array(window_vectors)
            window_norms = np.linalg.norm(window_matrix, axis=1, keepdims=True) + 1e-10
            window_matrix_normed = window_matrix / window_norms
            similarity_matrix = window_matrix_normed @ window_matrix_normed.T

            # For each window, find the max similarity to another window (excluding self)
            pattern_scores_bins = np.zeros(n_time_bins)
            for w in range(n_windows):
                sims = similarity_matrix[w].copy()
                sims[w] = 0  # exclude self
                max_sim = np.max(sims)
                start_col = w * pattern_window_bins
                end_col = min((w + 1) * pattern_window_bins, n_time_bins)
                pattern_scores_bins[start_col:end_col] = max_sim

            # Map pattern scores back to notes
            pattern_scores = np.zeros(n_notes)
            for i in range(n_notes):
                _, start_bin, end_bin = note_to_bins[i]
                if end_bin > start_bin:
                    pattern_scores[i] = np.mean(pattern_scores_bins[start_bin:end_bin])
                else:
                    pattern_scores[i] = 0.5

            avg_pattern_sim = np.mean(pattern_scores)
            high_pattern_count = int(np.sum(pattern_scores > 0.5))
            logger.info(f"  [Step 4a] Repeated patterns: avg similarity={avg_pattern_sim:.3f}, "
                  f"{high_pattern_count} notes in repeated sections")
        else:
            pattern_scores = np.ones(n_notes) * 0.5
            logger.info(f"  [Step 4a] Piece too short for pattern detection")

        # --- 4b: Rhythmic quantization ---
        # Estimate tempo from note onset intervals
        if n_notes >= 2:
            onset_intervals = np.diff(starts)
            # Filter out very short and very long intervals
            valid_intervals = onset_intervals[(onset_intervals > 0.05) & (onset_intervals < 2.0)]
            if len(valid_intervals) > 10:
                # Cluster intervals to find the most common one (likely beat or subdivision)
                from collections import Counter
                # Quantize to nearest 10ms for clustering
                quantized_intervals = np.round(valid_intervals * 100).astype(int)
                interval_counts = Counter(quantized_intervals.tolist())
                most_common_interval_ms = interval_counts.most_common(1)[0][0]
                estimated_beat_sec = most_common_interval_ms / 100.0

                # 16th note grid = beat / 4
                sixteenth_note_sec = estimated_beat_sec / 4.0
                if sixteenth_note_sec < 0.05:
                    sixteenth_note_sec = 0.05  # minimum 50ms
            else:
                sixteenth_note_sec = 0.125  # default: 120 BPM 16th note
                estimated_beat_sec = 0.5
        else:
            sixteenth_note_sec = 0.125
            estimated_beat_sec = 0.5

        # Compute quantization error for each note
        rhythm_scores = np.zeros(n_notes)
        n_off_grid = 0
        for i in range(n_notes):
            # Distance to nearest 16th note grid
            grid_pos = starts[i] / sixteenth_note_sec
            nearest_grid = round(grid_pos)
            offset = abs(grid_pos - nearest_grid) * sixteenth_note_sec
            # Normalize: offset relative to 16th note duration
            offset_ratio = offset / sixteenth_note_sec
            if offset_ratio < 0.15:
                rhythm_scores[i] = 1.0
            elif offset_ratio < 0.3:
                rhythm_scores[i] = 0.7
            elif offset_ratio < 0.5:
                rhythm_scores[i] = 0.4
            else:
                rhythm_scores[i] = 0.2
                n_off_grid += 1

        logger.info(f"  [Step 4b] Rhythmic quantization: 16th note={sixteenth_note_sec*1000:.0f}ms "
              f"(beat={estimated_beat_sec*1000:.0f}ms), {n_off_grid} notes off-grid")

        # ============================================================
        # Step 5: Composite scoring + iterative denoising
        # ============================================================

        # Score weights (adjusted: increased chord weight, decreased key weight,
        # added polyphony dimension)
        # W_VOICE and W_CHORD are now responsive to the parameters:
        # - When max_jump_semitones is low (strict), voice leading matters more
        # - When chord_strictness is high, chord conformity matters more
        W_SPECTRAL = 0.15
        W_KEY = 0.05       # Reduced: 97% in-key means low discriminative power
        W_VOICE = max(0.20, 0.30 - 0.01 * max_jump_semitones)  # Scale inversely with max_jump
        W_CHORD = max(0.15, chord_strictness * 0.40)            # Scale with chord_strictness
        W_PATTERN = 0.10
        W_RHYTHM = 0.10
        W_VELOCITY = 0.05  # Reduced to make room for polyphony
        W_DURATION = 0.05  # Reduced to make room for polyphony
        W_POLYPHONY = 0.10  # New: penalize overly dense simultaneous notes

        # Pre-compute velocity and duration scores (these don't change across iterations)
        global_median_vel = np.median(velocities) if n_notes > 0 else 64
        velocity_scores = np.clip(velocities / (global_median_vel + 1e-6), 0, 2) / 2.0

        duration_scores = np.zeros(n_notes)
        for i in range(n_notes):
            dur_ms = durations[i] * 1000
            if dur_ms < min_duration_ms * 0.375:  # ~30ms for default 80ms
                duration_scores[i] = 0.1
            elif dur_ms < min_duration_ms * 0.75:  # ~60ms for default 80ms
                duration_scores[i] = 0.4
            elif dur_ms <= 500:
                duration_scores[i] = 1.0
            else:
                duration_scores[i] = 0.9

        # Iterative denoising
        MAX_ITERATIONS = 3
        REMOVAL_THRESHOLD = removal_threshold  # Use parameter
        alive = np.ones(n_notes, dtype=bool)  # which notes are still alive

        for iteration in range(MAX_ITERATIONS):
            alive_indices = np.where(alive)[0]
            n_alive = len(alive_indices)
            if n_alive == 0:
                break

            # Recompute context-dependent scores on alive notes
            alive_starts = starts[alive]
            alive_ends = ends[alive]
            alive_pitches = pitches[alive]

            # --- Recompute chord scores for alive notes ---
            alive_chord_scores = np.ones(n_alive)
            alive_chord_groups = []
            current_group = [0]
            for idx in range(1, n_alive):
                if alive_starts[idx] - alive_starts[current_group[0]] <= CHORD_WINDOW:
                    current_group.append(idx)
                else:
                    alive_chord_groups.append(current_group)
                    current_group = [idx]
            alive_chord_groups.append(current_group)

            for group in alive_chord_groups:
                if len(group) < 2:
                    continue
                pitch_classes = set(alive_pitches[i] % 12 for i in group)
                is_chord, chord_name = _notes_form_chord(pitch_classes)
                if not is_chord and len(group) >= 3:
                    from itertools import combinations
                    best_subset = None
                    for size in range(len(group) - 1, 2, -1):
                        for subset in combinations(group, size):
                            subset_pc = set(alive_pitches[i] % 12 for i in subset)
                            is_sub_chord, _ = _notes_form_chord(subset_pc)
                            if is_sub_chord:
                                best_subset = set(subset)
                                break
                        if best_subset is not None:
                            break
                    if best_subset is not None:
                        for i in group:
                            if i not in best_subset:
                                alive_chord_scores[i] = 0.3
                    else:
                        for i in group:
                            alive_chord_scores[i] = 0.6
                elif not is_chord:
                    for i in group:
                        alive_chord_scores[i] = 0.7

            # --- Recompute voice leading scores for alive notes ---
            alive_voice_scores = np.ones(n_alive)
            for idx in range(1, n_alive):
                interval = abs(int(alive_pitches[idx] - alive_pitches[idx - 1]))
                if interval > MAX_JUMP:
                    alive_voice_scores[idx] = 0.1   # Stricter: was 0.3
                elif interval > 7:
                    alive_voice_scores[idx] = 0.4   # Stricter: was 0.6

            # --- Recompute pattern scores for alive notes ---
            # Rebuild piano roll with only alive notes
            alive_roll = np.zeros((N_PITCHES, n_time_bins), dtype=np.float32)
            for idx in range(n_alive):
                orig_i = alive_indices[idx]
                pitch_idx, start_bin, end_bin = note_to_bins[orig_i]
                for t in range(start_bin, end_bin):
                    alive_roll[pitch_idx, t] = max(alive_roll[pitch_idx, t], velocities[orig_i])

            if n_windows >= 2:
                alive_window_vectors = []
                for w in range(n_windows):
                    start_col = w * pattern_window_bins
                    end_col = min((w + 1) * pattern_window_bins, n_time_bins)
                    window_data = alive_roll[:, start_col:end_col].flatten()
                    alive_window_vectors.append(window_data)

                alive_window_matrix = np.array(alive_window_vectors)
                alive_norms = np.linalg.norm(alive_window_matrix, axis=1, keepdims=True) + 1e-10
                alive_normed = alive_window_matrix / alive_norms
                alive_sim = alive_normed @ alive_normed.T

                alive_pattern_bins = np.zeros(n_time_bins)
                for w in range(n_windows):
                    sims = alive_sim[w].copy()
                    sims[w] = 0
                    max_sim = np.max(sims)
                    start_col = w * pattern_window_bins
                    end_col = min((w + 1) * pattern_window_bins, n_time_bins)
                    alive_pattern_bins[start_col:end_col] = max_sim

                alive_pattern_scores = np.zeros(n_alive)
                for idx in range(n_alive):
                    orig_i = alive_indices[idx]
                    _, start_bin, end_bin = note_to_bins[orig_i]
                    if end_bin > start_bin:
                        alive_pattern_scores[idx] = np.mean(alive_pattern_bins[start_bin:end_bin])
                    else:
                        alive_pattern_scores[idx] = 0.5
            else:
                alive_pattern_scores = np.ones(n_alive) * 0.5

            # --- Compute polyphony scores for alive notes ---
            # Penalize notes in overly dense time windows (>6 simultaneous notes)
            POLYPHONY_THRESHOLD = max_polyphony  # Use parameter
            alive_polyphony_scores = np.ones(n_alive)
            # Group alive notes by time proximity
            alive_sorted_by_start = sorted(range(n_alive), key=lambda idx: alive_starts[idx])
            for idx_pos, idx in enumerate(alive_sorted_by_start):
                note_start = alive_starts[idx]
                note_end = alive_ends[idx]
                # Count how many other alive notes overlap with this note
                overlap_count = 0
                for other_idx in alive_sorted_by_start:
                    if other_idx == idx:
                        continue
                    # Check overlap: other note starts before this note ends,
                    # and other note ends after this note starts
                    if alive_starts[other_idx] < note_end and alive_ends[other_idx] > note_start:
                        overlap_count += 1
                if overlap_count > POLYPHONY_THRESHOLD:
                    alive_polyphony_scores[idx] = 0.2   # Heavy penalty for very dense
                elif overlap_count > POLYPHONY_THRESHOLD - 2:
                    alive_polyphony_scores[idx] = 0.6   # Moderate penalty

            # --- Compute composite score with veto mechanism ---
            composite = np.zeros(n_alive)
            for idx in range(n_alive):
                orig_i = alive_indices[idx]
                score = 0.0
                s_spectral = spectral_scores.get(orig_i, 0.5)
                s_key = key_scores[orig_i]
                s_chord = alive_chord_scores[idx]
                s_voice = alive_voice_scores[idx]
                s_pattern = alive_pattern_scores[idx]
                s_rhythm = rhythm_scores[orig_i]
                s_velocity = velocity_scores[orig_i]
                s_duration = duration_scores[orig_i]
                s_polyphony = alive_polyphony_scores[idx]

                score += W_SPECTRAL * s_spectral
                score += W_KEY * s_key
                score += W_CHORD * s_chord
                score += W_VOICE * s_voice
                score += W_PATTERN * s_pattern
                score += W_RHYTHM * s_rhythm
                score += W_VELOCITY * s_velocity
                score += W_DURATION * s_duration
                score += W_POLYPHONY * s_polyphony

                # Veto mechanism: if any critical dimension is very low, penalize heavily
                # This prevents high scores in other dimensions from masking noise
                low_dims = 0
                if s_chord < 0.3:
                    low_dims += 1  # Not part of any chord
                if s_voice < 0.3:
                    low_dims += 1  # Large interval jump
                if s_polyphony < 0.3:
                    low_dims += 1  # Too many simultaneous notes
                if s_spectral < 0.3:
                    low_dims += 1  # No spectral energy at this pitch

                if low_dims >= 2:
                    score *= 0.3  # Multiple red flags → heavy penalty
                elif low_dims == 1:
                    score *= 0.6  # One red flag → moderate penalty

                composite[idx] = score

            # --- Remove notes below threshold ---
            to_remove = composite < REMOVAL_THRESHOLD
            n_removed_this_iter = int(np.sum(to_remove))

            if n_removed_this_iter == 0:
                logger.info(f"  [Step 5] Iteration {iteration + 1}: No notes removed, stopping")
                break

            # Mark removed notes
            for idx in np.where(to_remove)[0]:
                alive[alive_indices[idx]] = False

            avg_removed_score = np.mean(composite[to_remove])
            if np.any(~to_remove):
                avg_kept_score = np.mean(composite[~to_remove])
            else:
                avg_kept_score = 0.0
            logger.info(f"  [Step 5] Iteration {iteration + 1}: Removed {n_removed_this_iter} notes "
                  f"(avg score: removed={avg_removed_score:.3f}, kept={avg_kept_score:.3f})")

        # ============================================================
        # Post-processing: merge close notes on same pitch
        # ============================================================
        kept_notes = [notes[i] for i in range(n_notes) if alive[i]]

        if kept_notes:
            # Merge close notes on same pitch
            pitch_notes = {}
            for n in kept_notes:
                pitch_notes.setdefault(n.pitch, []).append(n)

            merged = []
            for pitch, pnotes in pitch_notes.items():
                pnotes_sorted = sorted(pnotes, key=lambda n: n.start)
                group = [pnotes_sorted[0]]
                for n in pnotes_sorted[1:]:
                    prev = group[-1]
                    if n.start - prev.end < min_duration_ms / 1000.0:  # Use parameter for gap tolerance
                        prev.end = max(prev.end, n.end)
                        prev.velocity = max(prev.velocity, n.velocity)
                    else:
                        group.append(n)
                merged.extend(group)
            kept_notes = merged

        # Remove duplicate notes on same pitch too close in time
        if kept_notes:
            kept_notes.sort(key=lambda n: (n.pitch, n.start))
            after_dedup = [kept_notes[0]]
            for n in kept_notes[1:]:
                prev = after_dedup[-1]
                if n.pitch == prev.pitch and n.start - prev.start < 0.15:
                    if n.velocity > prev.velocity:
                        after_dedup[-1] = n
                else:
                    after_dedup.append(n)
            kept_notes = after_dedup

        # --- Print final statistics ---
        total_removed = n_notes - len(kept_notes)
        logger.info(f"\n  [Smart Denoise] Summary:")
        logger.info(f"    Key: {key_name} {'major' if is_major else 'minor'} (corr={key_corr:.3f})")
        logger.info(f"    Notes: {n_notes} -> {len(kept_notes)} (removed {total_removed})")
        if spectral_scores:
            spec_removed = sum(1 for i in range(n_notes) if not alive[i] and spectral_scores.get(i, 0.5) < 0.3)
            logger.info(f"    Spectral energy: {spec_removed} removed due to low spectral energy")
        logger.info(f"    Chord outliers: {n_non_chord_notes} non-chord notes identified")
        logger.info(f"    Voice leading: {n_large_jumps} large interval jumps")
        logger.info(f"    Rhythm: {n_off_grid} notes off-grid")

        inst.notes = kept_notes

    total_after = sum(len(inst.notes) for inst in midi.instruments)
    midi.write(output_path)
    logger.info(f"[Accomp Clean] {total_before} -> {total_after} notes (removed {total_before - total_after})")
    logger.info(f"[Accomp Clean] Saved to: {output_path}")


def clean_midi_post(input_path, output_path, original_audio_path=None):
    """Post-merge cleaning: conservative filtering + harmonic ghost removal.

    Args:
        input_path: Path to input MIDI file.
        output_path: Path to write cleaned MIDI file.
        original_audio_path: Optional path to original audio file for RMS-based
            gap verification. If None, will attempt auto-detection.
    """
    try:
        midi = pretty_midi.PrettyMIDI(input_path)
    except Exception as e:
        logger.error(f"[CleanPost] Failed to read MIDI: {e}")
        return
    total_before = sum(len(inst.notes) for inst in midi.instruments)

    for inst in midi.instruments:
        notes = sorted(inst.notes, key=lambda n: (n.pitch, n.start))

        # === Step 0: Harmonic ghost note filtering ===
        # Remove notes that are likely overtones of a simultaneously sounding
        # lower note. E.g. if C3 and C4 start at the same time and C4 is much
        # weaker, C4 is likely a 2nd harmonic ghost.
        notes_sorted = sorted(notes, key=lambda n: n.start)
        after_harmonic = []
        for i, note in enumerate(notes_sorted):
            is_ghost = False
            for j, other in enumerate(notes_sorted):
                if i == j:
                    continue
                # Must start at roughly the same time (within 30ms)
                if abs(note.start - other.start) > 0.03:
                    continue
                # The candidate ghost must be HIGHER pitch
                if note.pitch <= other.pitch:
                    continue
                # The candidate ghost must be WEAKER
                if note.velocity >= other.velocity * 0.6:
                    continue
                # Check if pitch is an integer harmonic (octave, 5th, etc.)
                semitone_diff = note.pitch - other.pitch
                # Common harmonic intervals: 12 (octave), 19 (octave+5th),
                # 24 (2 octaves), 7 (5th), 28 (2 oct+4th)
                harmonic_intervals = [12, 19, 24, 7, 28, 31, 36]
                if semitone_diff in harmonic_intervals:
                    is_ghost = True
                    break
            if not is_ghost:
                after_harmonic.append(note)
        removed_harmonic = len(notes_sorted) - len(after_harmonic)
        if removed_harmonic > 0:
            logger.info(f"  [Harmonic filter] Removed {removed_harmonic} ghost notes")
        notes = after_harmonic

        # Group by pitch
        pitch_notes = {}
        for n in notes:
            pitch_notes.setdefault(n.pitch, []).append(n)

        cleaned = []
        # Step 1: Merge close notes on same pitch (conservative: only merge <50ms gap)
        for pitch, pnotes in pitch_notes.items():
            merged = [pnotes[0]]
            for n in pnotes[1:]:
                prev = merged[-1]
                if n.start - prev.end < 0.05:  # 50ms gap tolerance
                    prev.end = max(prev.end, n.end)
                    prev.velocity = max(prev.velocity, n.velocity)
                else:
                    merged.append(n)

            # Step 2: Filter by duration and velocity (very conservative)
            for n in merged:
                duration = n.end - n.start
                if duration < 0.04:  # 40ms minimum (was 30ms)
                    continue
                if n.velocity < 10:  # Very low threshold
                    continue
                cleaned.append(n)

        # Step 2.5: Absorb short notes that differ from time-neighbors
        # If a note is <60ms and its pitch differs from both time-neighbors, it's an artifact
        if cleaned:
            cleaned.sort(key=lambda n: n.start)
            after_absorb = []
            for i, n in enumerate(cleaned):
                duration = n.end - n.start
                if duration < 0.06:  # 60ms - short note
                    # Find time neighbors (closest notes in time, regardless of pitch)
                    prev_note = None
                    next_note = None
                    for j in range(i - 1, -1, -1):
                        if cleaned[j].end <= n.start:
                            prev_note = cleaned[j]
                            break
                    for j in range(i + 1, len(cleaned)):
                        if cleaned[j].start >= n.end:
                            next_note = cleaned[j]
                            break
                    # If both neighbors exist and this note differs from both by >2 semitones
                    if (prev_note is not None and next_note is not None and
                            abs(n.pitch - prev_note.pitch) > 2 and
                            abs(n.pitch - next_note.pitch) > 2):
                        continue  # Skip this artifact
                after_absorb.append(n)
            removed_absorb = len(cleaned) - len(after_absorb)
            if removed_absorb > 0:
                logger.info(f"  [Short note absorb] Removed {removed_absorb} artifact notes")
            cleaned = after_absorb

        # Step 3: Rapid repeat filtering (very conservative: 30ms window, >5 repeats)
        if cleaned:
            pitch_notes_cleaned = {}
            for n in cleaned:
                pitch_notes_cleaned.setdefault(n.pitch, []).append(n)

            after_rapid = []
            for pitch, pnotes in pitch_notes_cleaned.items():
                pnotes_sorted = sorted(pnotes, key=lambda n: n.start)
                kept = [pnotes_sorted[0]]
                for n in pnotes_sorted[1:]:
                    window_s = n.start - 0.03  # 30ms (was 50ms)
                    recent_count = sum(1 for k in kept
                                       if k.start >= window_s and k.pitch == pitch)
                    if recent_count < 5:  # Allow more repeats (was 3)
                        kept.append(n)
                after_rapid.extend(kept)
            cleaned = after_rapid

        # Step 4: Pitch distribution filtering (very conservative)
        if cleaned:
            total_count = len(cleaned)
            pitch_counter = Counter(n.pitch for n in cleaned)
            rare_threshold = max(1, int(total_count * 0.0005))  # Lower threshold (was 0.001)
            avg_velocity = np.mean([n.velocity for n in cleaned])

            after_pitch = []
            for n in cleaned:
                freq = pitch_counter[n.pitch]
                # Only remove if very rare AND very weak
                if freq < rare_threshold and n.velocity < avg_velocity * 0.5:  # (was < avg)
                    continue
                after_pitch.append(n)
            cleaned = after_pitch

        # Step 5: Simultaneous note limit (generous: 12 notes max)
        if cleaned:
            sorted_by_start = sorted(cleaned, key=lambda n: n.start)
            groups = []
            current_group = [sorted_by_start[0]]
            for n in sorted_by_start[1:]:
                if n.start - current_group[0].start < 0.01:
                    current_group.append(n)
                else:
                    groups.append(current_group)
                    current_group = [n]
            groups.append(current_group)

            after_simultaneous = []
            for group in groups:
                if len(group) > 12:  # 12 max (was 8)
                    group_sorted = sorted(group, key=lambda n: n.velocity, reverse=True)
                    group = group_sorted[:12]
                after_simultaneous.extend(group)
            cleaned = after_simultaneous

        # Step 6: Remove isolated weak notes (only very weak: velocity < 15)
        if cleaned:
            all_starts = np.array([n.start for n in cleaned])
            all_velocities = np.array([n.velocity for n in cleaned])

            after_energy = []
            for i, n in enumerate(cleaned):
                if n.velocity < 15:  # Only very weak notes (was 20-40 range)
                    window_start = n.start - 0.1
                    window_end = n.start + 0.1
                    left = np.searchsorted(all_starts, window_start)
                    right = np.searchsorted(all_starts, window_end)
                    has_strong = any(all_velocities[j] > 50
                                     for j in range(left, right) if j != i)
                    if not has_strong:
                        continue
                after_energy.append(n)
            cleaned = after_energy

        # Step 7: Remove truly isolated notes (only if completely alone in 200ms)
        if cleaned:
            all_starts = sorted([n.start for n in cleaned])
            final = []
            for n in cleaned:
                nearby = sum(1 for s in all_starts
                             if abs(s - n.start) < 0.2 and s != n.start)  # 200ms (was 100ms)
                if nearby >= 1:
                    final.append(n)
            cleaned = final
        else:
            cleaned = cleaned

        # Step 8: Silence gap protection - prevent over-cleaning in dense sections
        # If there's a gap >1s with no notes at all, it's likely a false silence
        # caused by over-aggressive cleaning. Restore some notes from the original.
        # BUT: only restore if the gap region actually has audio energy (not true silence).
        if cleaned:
            cleaned.sort(key=lambda n: n.start)
            gaps = []
            for i in range(1, len(cleaned)):
                gap_start = cleaned[i-1].end
                gap_end = cleaned[i].start
                gap_duration = gap_end - gap_start
                if gap_duration > 2.0:  # 2s gap = suspicious silence
                    gaps.append((gap_start, gap_end, gap_duration))

            # If we found suspicious gaps, check if original notes existed there
            if gaps:
                # Try to load original audio for RMS verification
                gap_audio_path = original_audio_path
                if gap_audio_path is None:
                    gap_audio_path = _find_audio_for_midi_global(input_path)
                gap_audio_data = None
                gap_sr = None
                gap_rms_median = None
                if gap_audio_path and os.path.exists(gap_audio_path):
                    try:
                        import librosa
                        gap_y, gap_sr = librosa.load(gap_audio_path, sr=22050, mono=True)
                        # Compute global RMS median for threshold
                        hop = 512
                        rms_frames = librosa.feature.rms(y=gap_y, hop_length=hop, frame_length=hop*4)[0]
                        gap_rms_median = np.median(rms_frames)
                        gap_audio_data = gap_y
                        logger.info(f"  [Gap protection] Loaded audio for RMS check: {gap_audio_path}, "
                                    f"global RMS median={gap_rms_median:.6f}")
                    except Exception as e:
                        logger.warning(f"  [Gap protection] Could not load audio for RMS check: {e}")

                original_notes_sorted = sorted(notes_sorted, key=lambda n: n.start)
                for gap_start, gap_end, gap_duration in gaps:
                    # Check RMS energy in the gap region
                    should_restore = False
                    if gap_audio_data is not None and gap_sr is not None and gap_rms_median is not None:
                        import librosa
                        start_sample = int(gap_start * gap_sr)
                        end_sample = int(gap_end * gap_sr)
                        start_sample = max(0, min(start_sample, len(gap_audio_data)))
                        end_sample = max(0, min(end_sample, len(gap_audio_data)))
                        if end_sample > start_sample:
                            gap_segment = gap_audio_data[start_sample:end_sample]
                            gap_rms = np.sqrt(np.mean(gap_segment ** 2))
                            # If gap RMS is above 20% of global median, there's real audio there
                            rms_threshold = gap_rms_median * 0.70
                            if gap_rms >= rms_threshold:
                                should_restore = True
                                logger.info(f"  [Gap protection] Gap {gap_duration:.1f}s has RMS={gap_rms:.6f} "
                                            f"(threshold={rms_threshold:.6f}), will restore")
                            else:
                                logger.info(f"  [Gap protection] Gap {gap_duration:.1f}s is true silence "
                                            f"(RMS={gap_rms:.6f} < threshold={rms_threshold:.6f}), skipping")
                        else:
                            logger.info(f"  [Gap protection] Gap {gap_duration:.1f}s out of audio range, skipping")
                    else:
                        # No audio available: only restore short gaps (<2s)
                        # Short gaps are more likely to be caused by over-cleaning
                        if gap_duration < 2.0:
                            should_restore = True
                            logger.info(f"  [Gap protection] No audio for RMS check, restoring short gap ({gap_duration:.1f}s < 2s)")
                        else:
                            logger.info(f"  [Gap protection] No audio for RMS check, skipping long gap ({gap_duration:.1f}s >= 2s)")

                    if should_restore:
                        # Find original notes in this gap region
                        gap_notes = [n for n in original_notes_sorted
                                     if n.start >= gap_start - 0.1 and n.start <= gap_end + 0.1]
                        if gap_notes:
                            # Restore the strongest notes from the gap (up to 3)
                            gap_notes.sort(key=lambda n: n.velocity, reverse=True)
                            restored = gap_notes[:3]
                            cleaned.extend(restored)
                            logger.info(f"  [Gap protection] Restored {len(restored)} notes in {gap_duration:.1f}s silence gap")

            cleaned.sort(key=lambda n: n.start)

        inst.notes = cleaned

    total_after = sum(len(inst.notes) for inst in midi.instruments)
    midi.write(output_path)
    logger.info(f"[Clean] {total_before} -> {total_after} notes (removed {total_before - total_after})")
    logger.info(f"[Clean] Saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Split + Transcribe + Smart Merge pipeline v3")
    parser.add_argument("audio", help="Input audio file (wav/mp3/m4a)")
    parser.add_argument("--output", help="Output MIDI file", default=None)
    parser.add_argument("--device", default=None, help="Device for Transkun (cuda/cpu, default: auto)")
    parser.add_argument("--workdir", default=None, help="Working directory for intermediate files")
    parser.add_argument("--skip-separation", action="store_true")
    parser.add_argument("--vocals", default=None, help="Path to pre-separated vocals.wav")
    parser.add_argument("--accomp", default=None, help="Path to pre-separated no_vocals.wav")
    parser.add_argument("--no-clean", action="store_true", help="Skip post-merge cleaning")
    parser.add_argument("--vocal-only", action="store_true", help="Only output vocal MIDI")
    parser.add_argument("--accomp-only", action="store_true", help="Only output accompaniment MIDI")
    args = parser.parse_args()

    if args.output is None:
        args.output = args.audio.rsplit('.', 1)[0] + "_piano.mid"

    if args.workdir is None:
        args.workdir = os.path.dirname(args.audio)

    # Step 0: Convert m4a to wav if needed
    audio_path = args.audio
    if audio_path.lower().endswith(('.m4a', '.aac', '.ogg', '.flac', '.wma')):
        import tempfile
        wav_path = os.path.join(args.workdir,
                                os.path.splitext(os.path.basename(audio_path))[0] + ".wav")
        if not os.path.exists(wav_path):
            logger.info(f"[Convert] Converting {audio_path} to WAV...")
            try:
                import pydub
                seg = pydub.AudioSegment.from_file(audio_path)
                seg.export(wav_path, format="wav")
            except ImportError:
                # Fallback to ffmpeg
                cmd = ["ffmpeg", "-y", "-i", audio_path, "-ar", "22050", "-ac", "1", wav_path]
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True)
                except FileNotFoundError:
                    logger.error("[Convert] ffmpeg not found. Please install ffmpeg.")
                    return
                if result.returncode != 0:
                    logger.error(f"[Convert] Error: {result.stderr}")
                    return
            logger.info(f"[Convert] Done: {wav_path}")
        else:
            logger.info(f"[Convert] Already exists: {wav_path}")
        audio_path = wav_path

    # Step 1: Separate
    if args.vocals and args.accomp:
        vocals_path = args.vocals
        accomp_path = args.accomp
        logger.info(f"[Skip] Using pre-separated files")
    elif args.skip_separation:
        audio_name = os.path.splitext(os.path.basename(audio_path))[0]
        sep_dir = os.path.join(args.workdir, "separated", "htdemucs", audio_name)
        vocals_path = os.path.join(sep_dir, "vocals.wav")
        accomp_path = os.path.join(sep_dir, "no_vocals.wav")
        if not os.path.exists(vocals_path):
            logger.error(f"Error: {vocals_path} not found.")
            return
    else:
        vocals_path, accomp_path = separate_audio(audio_path, args.workdir)
        if not vocals_path:
            logger.error("Error: Separation failed")
            return

    # Vocal-only mode
    if args.vocal_only:
        vocal_mid = os.path.join(args.workdir,
                                 os.path.splitext(os.path.basename(audio_path))[0] + "_vocal.mid")
        result = transcribe_vocals(vocals_path, vocal_mid)
        if result:
            logger.info(f"\nVocal-only output: {vocal_mid}")
        else:
            logger.error("Error: Vocal transcription failed")
        return

    # Step 2: Transcribe accompaniment with Transkun
    accomp_mid = os.path.join(args.workdir, "accomp_transkun.mid")
    result = transcribe_accompaniment(accomp_path, accomp_mid, args.device)
    if not result:
        logger.error("Error: Accompaniment transcription failed")
        return

    # Step 2.5: Strict clean accompaniment
    accomp_cleaned = accomp_mid.replace('.mid', '_cleaned.mid')
    clean_accompaniment_strict(accomp_mid, accomp_cleaned, original_audio_path=accomp_path)
    accomp_mid = accomp_cleaned

    # Accomp-only mode
    if args.accomp_only:
        shutil.copy(accomp_mid, args.output)
        logger.info(f"\nAccomp-only output: {args.output}")
        return

    # Step 3: Transcribe vocals
    vocal_mid = os.path.join(args.workdir, "vocals_basic_pitch.mid")
    result = transcribe_vocals(vocals_path, vocal_mid)
    if not result:
        logger.warning("Warning: Vocal transcription failed, outputting accompaniment only")
        shutil.copy(accomp_mid, args.output)
        logger.info(f"Output: {args.output}")
        return

    # Step 4: Smart merge
    merged_mid = args.output if args.no_clean else args.output.replace('.mid', '_merged.mid')
    merge_midi_smart(accomp_mid, vocal_mid, merged_mid)

    # Step 5: Post-merge cleaning
    if not args.no_clean:
        clean_midi_post(merged_mid, args.output, original_audio_path=audio_path)
        # Remove intermediate merged file
        if os.path.exists(merged_mid) and merged_mid != args.output:
            os.remove(merged_mid)

    logger.info(f"\nFinal output: {args.output}")


if __name__ == "__main__":
    main()