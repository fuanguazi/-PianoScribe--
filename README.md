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

## 工作流程

1. 加载音频文件（MP3/WAV/FLAC/OGG/M4A）
2. AI 音源分离（Mel-Band RoFormer）
3. 神经网络转录（Transkun CRNN + Basic Pitch ONNX）
4. 乐谱生成与播放（LilyPond + FluidSynth）

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

## 项目结构

```
PianoScribe/
├── app/                          # 源代码
│   ├── piano_app.py              # 主应用（PySide6 GUI）
│   ├── split_transcribe_merge.py # 分离+转录+合并流水线
│   ├── soundfont_manager.py      # 音色库管理
│   ├── create_icon.py            # 图标生成脚本
│   ├── build_installer.py        # 安装器构建脚本
│   ├── pianoscribe.spec          # PyInstaller 打包配置
│   └── requirements.txt          # Python 依赖
├── assets/                       # 资源文件
│   ├── pianoscribe_icon.ico/.png # 应用图标
│   ├── FluidR3_GM.sf2            # 音色库（141MB，需单独下载）
│   └── transcription_crnn.onnx   # ONNX 转录模型
├── checkpoints/                  # 模型权重（需单独下载）
├── app/lilypond-2.24.4/          # LilyPond 排版引擎
├── .gitignore
├── LICENSE
└── README.md
```

## 环境要求

- **操作系统**: Windows 10 / 11（64位）
- **Python**: 3.10 或 3.11
- **GPU**: NVIDIA CUDA 兼容显卡（推荐，CPU 也可运行但较慢）
- **内存**: 至少 8 GB RAM
- **硬盘**: 至少 5 GB 可用空间

## 安装与运行

### 第一步：克隆仓库

```bash
git clone https://github.com/fuanguazi/-PianoScribe--.git
cd -PianoScribe--
```

### 第二步：创建 Python 虚拟环境

```bash
# 使用 conda（推荐）
conda create -n pianoscribe python=3.11
conda activate pianoscribe

# 或使用 venv
python -m venv venv
venv\Scripts\activate
```

### 第三步：安装 Python 依赖

```bash
pip install -r app/requirements.txt
```

> 如果 pip 安装缓慢，可以使用国内镜像源：
> ```bash
> pip install -r app/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

### 第四步：下载大文件

由于文件大小限制，以下文件需要从 [GitHub Releases](../../releases) 下载：

| 文件 | 大小 | 放置位置 |
|------|------|----------|
| `FluidR3_GM.sf2` | 141 MB | `assets/FluidR3_GM.sf2` |
| `latest.pt` | 64 MB | `checkpoints/latest.pt` |

下载后放到对应目录即可。

### 第五步：安装 FluidSynth

FluidSynth 是音频合成所需的库：

1. 访问 https://github.com/FluidSynth/fluidsynth/releases
2. 下载最新版 `fluidsynth-xxx-win10-x64.zip`
3. 解压到一个文件夹（如 `C:\tools\fluidsynth\`）
4. 将其 `bin` 目录添加到系统 PATH 环境变量
5. 安装 Python 绑定：`pip install pyfluidsynth`

### 第六步：安装 LilyPond

LilyPond 是乐谱排版引擎：

**方式一：使用项目自带的 LilyPond（推荐）**

项目已包含 `app/lilypond-2.24.4/` 目录，无需额外安装。

**方式二：自行安装**

1. 访问 https://lilypond.org/download.html
2. 下载 Windows 版本并安装
3. 将安装目录添加到系统 PATH

### 第七步：运行应用

```bash
python app/piano_app.py
```

## 使用指南

1. **加载音频** - 点击首页的"选择音频文件"按钮，选择 MP3/WAV/FLAC 等音频文件
2. **音源分离** - 应用会自动从混合音频中分离出钢琴音轨
3. **AI 转录** - 自动将钢琴音轨转录为 MIDI 音符
4. **查看乐谱** - 切换到"分析"标签页查看生成的乐谱
5. **播放** - 点击播放按钮，可切换原始力度/统一音量模式
6. **难度分析** - 查看曲目难度评级
7. **导出** - 支持导出 PDF 乐谱和 MIDI 文件

## 常见问题

### Q: 启动时提示找不到 FluidSynth DLL
确保 FluidSynth 已安装，并且其 `bin` 目录已添加到系统 PATH。也可以将 DLL 文件复制到项目根目录。

### Q: 转录速度很慢
如果有 NVIDIA GPU，确保已安装 CUDA 和对应版本的 PyTorch：
```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
```

### Q: 乐谱生成失败
确保 LilyPond 已正确安装，`lilypond` 命令可在终端中执行。项目自带了 `lilypond-2.24.4/` 目录。

### Q: 音源分离失败
确保已安装 pymss 及其依赖。pymss 需要运行在 CPU 或 CUDA 环境下。

## 下载

预编译安装包和大文件请前往 [GitHub Releases](../../releases) 页面下载。

## 协议

本项目采用 CC BY-NC-ND 4.0 协议开源，仅供个人学习非商用使用；任何商业用途、二次转载分发必须提前联系作者取得书面授权。

---

Powered by [TRAE](https://www.trae.ai/)
