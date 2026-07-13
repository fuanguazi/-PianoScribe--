# PianoScribe

专业AI钢琴乐谱生成器 - Powered by TRAE

## 简介

PianoScribe 是一款基于深度学习的钢琴乐谱转录桌面应用，能够将任意音频文件自动转化为专业级钢琴乐谱（PDF/MIDI），并支持交互式播放与难度分析。

## 核心功能

- **AI 音源分离** - 基于 Mel-Band RoFormer (pymss) 自动从混合音频中提取钢琴音轨
- **深度学习转录** - Transkun (CRNN) + Basic Pitch (ONNX) 双模型架构，音符 F1 > 0.96
- **专业乐谱排版** - 通过 LilyPond 生成出版级质量乐谱，支持多声部、力度记号
- **交互式播放** - 内置 FluidR3_GM 高品质音色库 (141MB)，支持原始力度/统一音量模式
- **难度分析** - 自动评定入门/进阶/高级/大师等级
- **节拍追踪** - 精准 BPM 检测，支持渐快渐慢识别

## 下载与安装

**无需安装 Python 或任何依赖！** 直接下载安装包即可使用。

1. 从 [GitHub Releases](../../releases) 下载最新 `PianoScribe_Setup.exe`
2. 双击运行，选择安装目录
3. 安装完成后桌面会自动生成快捷方式

安装包已内置 Python 运行环境、FluidSynth、LilyPond 等所有必要组件，开箱即用。

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.11 | 核心语言 |
| PySide6 / Qt | 桌面 GUI |
| Transkun CRNN | 音符转录 |
| Basic Pitch ONNX | 音高估计 |
| LilyPond 2.24 | 乐谱排版 |
| FluidSynth + FluidR3_GM | 音频合成 |
| pymss (Mel-Band RoFormer) | 音源分离 |
| PyInstaller | 打包分发 |

## 使用指南

1. **加载音频** - 点击首页的"选择音频文件"按钮，选择 MP3/WAV/FLAC 等音频文件
2. **音源分离** - 应用会自动从混合音频中分离出钢琴音轨
3. **AI 转录** - 自动将钢琴音轨转录为 MIDI 音符
4. **查看乐谱** - 切换到"分析"标签页查看生成的乐谱
5. **播放** - 点击播放按钮，可切换原始力度/统一音量模式
6. **难度分析** - 查看曲目难度评级
7. **导出** - 支持导出 PDF 乐谱和 MIDI 文件

## 从源码运行（开发者）

如果想从源码运行或参与开发：

```bash
git clone https://github.com/fuanguazi/-PianoScribe--.git
cd -PianoScribe--

# 创建虚拟环境
conda create -n pianoscribe python=3.11
conda activate pianoscribe

# 安装依赖
pip install -r app/requirements.txt

# 运行
python app/piano_app.py
```

### 环境要求

- **操作系统**: Windows 10 / 11（64位）
- **Python**: 3.10 或 3.11
- **GPU**: NVIDIA CUDA 显卡（可选，CPU 也可运行）
- **硬盘**: 至少 10 GB 可用空间

### GPU 加速

如果有 NVIDIA GPU：

```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
```

### FluidSynth

音频合成需要 FluidSynth。可以从 https://github.com/FluidSynth/fluidsynth/releases 下载，或将 DLL 放在项目根目录。

## 常见问题

### Q: 转录速度很慢
如果有 NVIDIA GPU，在软件的"性能与模型"对话框中启用 CUDA 加速。

### Q: 乐谱显示不完整
这是正常现象——多页乐谱可以通过翻页按钮切换，或调整窗口大小。

### Q: 音源分离失败
确保 pymss 已安装。可尝试在"性能与模型"对话框切换 CPU 模式。

---

Powered by [TRAE](https://www.trae.ai/)
