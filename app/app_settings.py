"""PianoScribe 持久化设置：跨平台 JSON 存储 + 深合并默认值。

设置文件位置：
  - Linux:   ~/.config/pianoscribe/settings.json
  - macOS:   ~/Library/Application Support/pianoscribe/settings.json
  - Windows: %APPDATA%/pianoscribe/settings.json

调用方：
  cfg = load_settings()           # 永远返回完整 dict（缺失的 key 自动补默认）
  save_settings(cfg)              # 写入磁盘（atomic rename）
  get('sf2.program', 0)           # 点路径取值
  set_many({'sf2.program': 40})   # 批量更新并保存
"""
import os
import json
import tempfile
import copy
import sys
import threading


# ============================================================
# 默认值
# ============================================================
DEFAULTS = {
    "sf2": {
        "selected_path": "",   # 空字符串 = 自动检测
        "program": 0,          # 0 = Acoustic Grand Piano
        "preset": "auto",      # auto / fluidr3 / generaluser / musescore / ...
    },
    "device": {
        "separation": "auto",     # auto / cuda / cpu
        "transcription": "auto",  # auto / cuda / cpu
    },
    "sep": {
        "model_name": "big_beta7",  # big_beta7 / bs_roformer_voc_hyperacev2 / scnet_checkpoint_musdb18
        "source": "auto",           # auto / modelscope / hf-mirror
        "inference": {
            "chunk_size": 8,         # 1-32（秒数，乘 60000 转 samples）
            "batch_size": 2,          # 1-16
            "overlap_size": 0.25,     # 0.1-0.75（chunk_size 的比例）
        },
    },
    "sensitivity": {
        "vocal_onset": 50,       # 30-80（除 100 得 threshold）
        "vocal_frame": 30,        # 10-60
        "vocal_minlen": 80,      # 40-200 ms
        "accomp_sens": 50,       # 0-100
        "accomp_min_dur": 80,    # 40-300 ms
        "accomp_max_poly": 6,    # 2-10
    },
    "denoise": {
        "threshold": 25,           # 0-50（除 100 得 removal_threshold）
        "min_duration_ms": 80,      # 20-200
        "chord_strictness": 25,     # 0-100（除 100）
        "max_jump": 12,             # 6-24 半音
        "max_polyphony": 6,         # 2-10
    },
    "audio": {
        "sample_rate": 44100,    # 22050 / 44100 / 48000
        "gain": 0.5,              # 0.1-1.0
        "reverb": {
            "active": True,
            "room_size": 0.7,     # 0-1
        },
    },
}


# ============================================================
# 路径
# ============================================================
def get_settings_path():
    """返回当前平台的 settings.json 绝对路径（不保证目录存在）。"""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "pianoscribe", "settings.json")


def _ensure_dir(path):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


# ============================================================
# 深合并
# ============================================================
def _deep_merge(base, override):
    """递归合并 override 到 base（返回新 dict，不修改入参）。

    override 的非 dict 值直接覆盖；dict 值递归合并；
    base 有但 override 没有的 key 保留 base 的值。
    """
    result = copy.deepcopy(base)
    if not isinstance(override, dict):
        return result
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


# ============================================================
# 加载 / 保存
# ============================================================
_cache = None  # 进程内缓存，避免每次读盘
_cache_lock = threading.Lock()


def load_settings(force_reload=False):
    """加载 settings.json，与 DEFAULTS 深合并后返回完整 dict。

    Args:
        force_reload: True 时强制读盘（绕过缓存）

    Returns:
        完整 settings dict，永远包含所有 key（缺失的用 DEFAULTS 补齐）
    """
    global _cache
    with _cache_lock:
        if _cache is not None and not force_reload:
            return _cache

        path = get_settings_path()
        stored = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                if not isinstance(stored, dict):
                    stored = {}
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                stored = {}

        merged = _deep_merge(DEFAULTS, stored)
        _cache = merged
        return merged


def save_settings(settings_dict):
    """原子写入 settings.json（先写临时文件再 rename）。"""
    global _cache
    path = get_settings_path()
    _ensure_dir(path)

    # 原子写入：先写临时文件，再 rename
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), suffix=".tmp", prefix="settings_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings_dict, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        # 临时文件清理
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    with _cache_lock:
        _cache = copy.deepcopy(settings_dict)


def get(key_path, default=None):
    """点路径取值，如 get('sf2.program', 0)。"""
    cfg = load_settings()
    parts = key_path.split(".")
    cur = cfg
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur


def set_many(updates):
    """批量更新：updates = {'sf2.program': 40, 'audio.gain': 0.6}。"""
    cfg = load_settings(force_reload=True)
    for path, val in updates.items():
        parts = path.split(".")
        cur = cfg
        for p in parts[:-1]:
            if p not in cur or not isinstance(cur[p], dict):
                cur[p] = {}
            cur = cur[p]
        cur[parts[-1]] = val
    save_settings(cfg)
    return cfg


def reset_to_defaults():
    """重置为默认值并保存。"""
    save_settings(copy.deepcopy(DEFAULTS))
    return DEFAULTS


# ============================================================
# 便捷访问器
# ============================================================
def get_soundfont_path():
    """返回用户选的 SF2 路径（空字符串 = 自动检测）。"""
    return get("sf2.selected_path", "")


def get_instrument_program():
    """返回乐器 program（0-127）。"""
    return int(get("sf2.program", 0))


def get_device_for(purpose):
    """purpose: 'separation' / 'transcription'。返回 'auto'/'cuda'/'cpu'。"""
    return get(f"device.{purpose}", "auto")


def get_separation_model():
    """返回用户选的分离模型 catalog name。"""
    return get("sep.model_name", "big_beta7")


def get_separation_source():
    """返回下载源偏好：'auto' / 'modelscope' / 'hf-mirror'。"""
    return get("sep.source", "auto")


def get_separation_inference_params():
    """返回 pymss inference_params（已转换成 samples）。

    pymss 期望：
      chunk_size: int (samples)
      batch_size: int
      overlap_size: int (samples)
    """
    cfg = load_settings()
    inf = cfg.get("sep", {}).get("inference", {})
    chunk_s = int(inf.get("chunk_size", 8))
    batch = int(inf.get("batch_size", 2))
    overlap_ratio = float(inf.get("overlap_size", 0.25))
    # 1 秒 = 44100 samples（pymss 默认采样率）
    chunk_samples = chunk_s * 44100
    overlap_samples = int(chunk_samples * overlap_ratio)
    return {
        "chunk_size": chunk_samples,
        "batch_size": batch,
        "overlap_size": overlap_samples,
    }


def get_audio_settings():
    """返回音频输出设置 dict。"""
    return load_settings().get("audio", {})


def get_sensitivity_defaults():
    """返回灵敏度区的默认值 dict（启动时加载到滑块）。"""
    return load_settings().get("sensitivity", {})


def get_denoise_defaults():
    """返回降噪区的默认值 dict。"""
    return load_settings().get("denoise", {})
