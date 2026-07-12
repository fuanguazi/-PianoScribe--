#!/usr/bin/env bash
# PianoScribe 启动脚本（Ubuntu / Linux）
# 用法：双击运行，或终端 bash run_pianoscribe.sh
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/app"
cd "$APP_DIR"

# 用系统 Python3 启动（依赖已通过 pip3 install --break-system-packages 装好）
exec python3 piano_app.py "$@"
