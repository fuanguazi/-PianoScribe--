# PianoScribe

专业AI钢琴乐谱生成器 - Powered by TRAE Work

## 简介

PianoScribe 是一款基于深度学习的钢琴乐谱转录桌面应用，能够将任意音频文件自动转化为专业级钢琴乐谱（PDF/MIDI），并支持交互式播放与难度分析。

## 核心功能

- **AI 音源分离** - 基于 Mel-Band RoFormer (pymss) 自动从混合音频中提取钢琴音轨
- **深度学习转录** - Transkun (CRNN) + Basic Pitch (ONNX) 双模型架构，音符 F1 > 0.96
- **专业乐谱排版** - 通过 LilyPond 生成出版级质量乐谱，支持多声部、力度记号
- **交互式播放** - 内置 FluidR3_GM 高品质音色库 (141MB)，支持原始力度/统一音量模式
- **难度分析** - 自动评定入门/进阶/高级/大师等级
- **节拍追踪** - 精准 BPM 检测，支持渐快渐慢识别

## 工作流程

1. 加载音频文件（MP3/WAV/FLAC/OGG/M4A）
2. AI 音源分离（Mel-Band RoFormer）
3. 神经网络转录（Transkun CRNN + Basic Pitch ONNX）
4. 乐谱生成与播放（LilyPond + FluidSynth）

## 技术栈

| 技术 | 用途 |
|------|------|
| Python | 核心语言 |
| PySide6 / Qt | 桌面 GUI |
| Transkun CRNN | 音符转录 |
| Basic Pitch ONNX | 音高估计 |
| LilyPond | 乐谱排版 |
| FluidSynth + FluidR3_GM | 音频合成 |
| pymss | 音源分离 |
| PyInstaller | 打包分发 |

## 项目结构

```
PianoScribe/
 src/                          # 源代码
    piano_app.py              # 主应用（PySide6 GUI）
    split_transcribe_merge.py # 分离+转录+合并流水线
    separate_and_transcribe.py# 音源分离与转录
    transcribe_bytedance.py   # Transkun 转录引擎
    synthesize_wav.py         # 音频合成
    clean_midi.py             # MIDI 清洗
    config.py                 # 配置
    model.py                  # CRNN 模型定义
    create_icon.py            # 图标生成脚本
    build_installer.py        # 安装器构建脚本
    pianoscribe.spec          # PyInstaller 打包配置
    requirements.txt          # Python 依赖
    ...                       # 其他源码
 assets/                       # 资源文件
    pianoscribe_icon.ico/.png # 应用图标
    FluidR3_GM.sf2            # 高品质音色库 (141MB)
    FluidR3_GM.7z             # 音色库压缩包
    transcription_crnn.onnx   # ONNX 转录模型
    lilypond.zip              # LilyPond 安装包
    vexflow.js                # 乐谱渲染引擎
 checkpoints/                  # 模型权重
 dist/                         # PyInstaller 构建产物
 PianoScribe_Setup/            # 安装器
 lilypond-2.24.4/              # LilyPond 安装目录
 logs/                         # 运行日志
 docs/
    index.html                # 产品展示页面
 .gitignore
 LICENSE
 README.md
```

## 环境要求

- Python 3.11+
- CUDA 兼容 GPU（推荐，CPU 也可运行）
- Windows 10/11

## 安装与运行

```
bash
# 克隆仓库
git clone https://github.com/your-username/PianoScribe.git
cd PianoScribe

# 安装依赖
pip install -r src/requirements.txt

# 安装 FluidSynth（音频合成需要）
# 下载: https://github.com/FluidSynth/fluidsynth/releases

# 安装 LilyPond（乐谱排版需要）
# 下载: https://lilypond.org/download.html

# 运行应用
python src/piano_app.py
```

## 下载

预编译安装包请前往 [GitHub Releases](../../releases) 页面下载。

## 协议

本项目采用 CC BY-NC-ND 4.0 协议开源，仅供个人学习非商用使用；任何商业用途、二次转载分发必须提前联系作者取得书面授权。

---

Powered by [TRAE Work](https://www.trae.ai/)