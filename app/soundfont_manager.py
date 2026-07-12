"""SoundFont 管理：预设列表 + 异步下载 + 校验。

SOUNDFONT_PRESETS 是内置的免费 SoundFont 下载列表。
SoundFontDownloader 是 QObject，在 QThread 里跑，emit progress 信号。

使用方式：
    downloader = SoundFontDownloader()
    downloader.progress.connect(progress_bar.setValue)
    downloader.finished.connect(on_done)
    downloader.start_download(url, dest_path)
"""
import os
import sys
import shutil
import threading
import urllib.request
import urllib.error
from PySide6.QtCore import QObject, Signal


# ============================================================
# 预设 SoundFont 列表
# ============================================================
# 每项：(id, name, size_mb, url, license, redistributable)
# URL 在实现时验证可达性，失效时改这里即可。
SOUNDFONT_PRESETS = [
    {
        "id": "fluidr3_gm",
        "name": "FluidR3_GM",
        "size_mb": 141,
        "url": "https://github.com/FluidSynth/fluidsynth/releases/download/v2.4.6/FluidR3_GM.sf2",
        "license": "MIT",
        "redistributable": True,
        "description": "FluidSynth 官方，均衡稳定",
    },
    {
        "id": "musescore_general",
        "name": "MuseScore_General",
        "size_mb": 213,
        "url": "https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General.sf2",
        "license": "MIT",
        "redistributable": True,
        "description": "MuseScore 官方，质量高",
    },
    {
        "id": "generaluser_gs",
        "name": "GeneralUser GS",
        "size_mb": 30,
        "url": "https://github.com/adius/GeneralUser/releases/download/1.47/GeneralUser.GS.sf2",
        "license": "免费使用",
        "redistributable": True,
        "description": "轻量但质量好，启动快",
    },
    {
        "id": "sgm_v2",
        "name": "SGM-V2.01",
        "size_mb": 235,
        "url": "https://archive.org/download/sgm-v2.01/SGM-V2.01.sf2",
        "license": "免费",
        "redistributable": False,
        "description": "日系明亮风格，适合钢琴",
    },
    {
        "id": "timbres_of_heaven",
        "name": "Timbres Of Heaven",
        "size_mb": 399,
        "url": "https://archive.org/download/timbres-of-heaven-soundfont-3.4/Timbres%20Of%20Heaven%203.4%20final.sf2",
        "license": "免费",
        "redistributable": False,
        "description": "最多力度分层，最真实",
    },
    {
        "id": "arachno",
        "name": "Arachno SoundFont",
        "size_mb": 148,
        "url": "https://archive.org/download/ArachnoSoundFontVersion1.0/Arachno.sf2",
        "license": "免费",
        "redistributable": False,
        "description": "现代有力，适合流行",
    },
    {
        "id": "magicsf",
        "name": "MagicSF Ver2",
        "size_mb": 65,
        "url": "https://archive.org/download/MagicSF_ver2/MagicSF_ver2.sf2",
        "license": "免费",
        "redistributable": False,
        "description": "中等大小，平衡选择",
    },
]


# ============================================================
# 工具：扫描已安装的 SoundFont
# ============================================================
def get_soundfont_dirs():
    """返回应该扫描 .sf2 的目录列表（按优先级）。"""
    dirs = []
    app_dir = os.path.dirname(os.path.abspath(__file__))
    # 1. app/soundfonts/（用户下载的）
    sf_dir = os.path.join(app_dir, "soundfonts")
    if os.path.isdir(sf_dir):
        dirs.append(sf_dir)
    # 2. app 目录本身
    dirs.append(app_dir)
    # 3. pretty_midi 自带的
    try:
        import pretty_midi
        pm_dir = os.path.dirname(pretty_midi.__file__)
        dirs.append(pm_dir)
    except Exception:
        pass
    # 4. FluidSynth 系统目录
    if sys.platform.startswith("win"):
        for d in [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "fluidsynth", "share", "soundfonts"),
            r"C:\Program Files\FluidSynth\share\soundfonts",
            r"C:\Program Files (x86)\FluidSynth\share\soundfonts",
        ]:
            if os.path.isdir(d):
                dirs.append(d)
    else:
        for d in ["/usr/share/soundfonts", "/usr/local/share/soundfonts",
                  os.path.expanduser("~/.local/share/soundfonts")]:
            if os.path.isdir(d):
                dirs.append(d)
    return dirs


def scan_installed_soundfonts():
    """扫描所有 SF2 文件，返回 [{path, name, size_mb}] 列表。"""
    import glob
    seen = set()
    result = []
    for d in get_soundfont_dirs():
        for f in glob.glob(os.path.join(d, "*.sf2")):
            real = os.path.realpath(f)
            if real in seen:
                continue
            seen.add(real)
            try:
                size = os.path.getsize(f) / 1024 / 1024
            except OSError:
                continue
            result.append({
                "path": f,
                "name": os.path.basename(f),
                "size_mb": round(size, 1),
            })
    # 按大小降序（大的通常质量高）
    result.sort(key=lambda x: -x["size_mb"])
    return result


def get_download_dir():
    """返回下载目标目录（自动创建）。"""
    app_dir = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(app_dir, "soundfonts")
    os.makedirs(d, exist_ok=True)
    return d


# ============================================================
# SoundFontDownloader — QThread 异步下载
# ============================================================
class SoundFontDownloader(QObject):
    """在 QThread 里跑的 SoundFont 下载器。

    Signals:
        progress(pct: int, msg: str)  0-100
        finished(path: str)           成功
        failed(error_msg: str)        失败
    """
    progress = Signal(int, str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = threading.Event()
        self._thread = None

    def start_download(self, url, dest_path, filename_label=""):
        """启动异步下载。url 必须是直链 .sf2。"""
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._download_worker,
            args=(url, dest_path, filename_label),
            daemon=True,
        )
        self._thread.start()

    def cancel(self):
        """请求取消（下载循环检查 _cancel）。"""
        self._cancel.set()

    def _download_worker(self, url, dest_path, label):
        """实际下载逻辑（在子线程跑）。"""
        tmp_path = dest_path + ".tmp"
        try:
            self.progress.emit(0, f"连接中: {label or url}")
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "PianoScribe/1.0 (soundfont downloader)"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                # 跟随重定向后的最终 URL
                final_url = resp.geturl()
                total = resp.headers.get("Content-Length")
                total = int(total) if total else None

                # 8KB chunks
                downloaded = 0
                chunk_size = 8192
                with open(tmp_path, "wb") as f:
                    while True:
                        if self._cancel.is_set():
                            f.close()
                            try:
                                os.unlink(tmp_path)
                            except OSError:
                                pass
                            self.failed.emit("已取消下载")
                            return
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = int(downloaded * 100 / total)
                            mb_done = downloaded / 1024 / 1024
                            mb_total = total / 1024 / 1024
                            msg = f"{mb_done:.1f} / {mb_total:.1f} MB ({pct}%)"
                        else:
                            pct = -1
                            mb_done = downloaded / 1024 / 1024
                            msg = f"{mb_done:.1f} MB 下载中"
                        self.progress.emit(pct, msg)

            # 校验文件非空
            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                self.failed.emit("下载完成但文件为空")
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                return

            # 原子 rename
            os.replace(tmp_path, dest_path)
            self.progress.emit(100, "下载完成，校验中...")

            # 校验 SF2
            if verify_sf2(dest_path):
                self.finished.emit(dest_path)
            else:
                try:
                    os.unlink(dest_path)
                except OSError:
                    pass
                self.failed.emit("文件校验失败：不是有效的 SF2 文件")

        except urllib.error.HTTPError as e:
            self.failed.emit(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            self.failed.emit(f"网络错误: {e.reason}")
        except Exception as e:
            self.failed.emit(f"下载失败: {type(e).__name__}: {e}")
            # 清理临时文件
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass


# ============================================================
# SF2 校验
# ============================================================
def verify_sf2(path):
    """尝试用 fluidsynth 加载 SF2，成功返回 True。

    若 fluidsynth 未安装，只检查文件头是否以 'RIFF' 开头（SF2 是 RIFF 格式）。
    """
    if not os.path.exists(path) or os.path.getsize(path) < 1024:
        return False

    # 快速文件头检查
    try:
        with open(path, "rb") as f:
            header = f.read(4)
        if header != b"RIFF":
            return False
    except OSError:
        return False

    # 尝试用 fluidsynth 加载（更严格）
    try:
        import fluidsynth
        synth = fluidsynth.Synth()
        sfid = synth.sfload(path)
        ok = sfid >= 0
        try:
            synth.delete()
        except Exception:
            pass
        return ok
    except ImportError:
        # fluidsynth 未安装，靠文件头检查
        return True
    except Exception:
        return False
