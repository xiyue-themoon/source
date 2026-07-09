#!/usr/bin/env bash
# qw3.v4 FIFO 管道初始化
# 用法: bash setup-fifo.sh
# 效果: 创建 /tmp/{qw3-in,qw3-out}，权限 666，任何人可读写

set -euo pipefail

FIFO_DIR="/tmp"
IN="${FIFO_DIR}/qw3-in"
OUT="${FIFO_DIR}/qw3-out"

echo "[setup-fifo] 检查现有管道..."

for f in "$IN" "$OUT"; do
    if [ -p "$f" ]; then
        echo "[setup-fifo]  已存在: $f"
    else
        echo "[setup-fifo]  创建: $f"
        sudo mkfifo -m 666 "$f"
    fi
done

# 冗余确保权限
sudo chmod 666 "$IN" "$OUT"
echo "[setup-fifo] 权限确认:"
ls -la "$IN" "$OUT"

echo "[setup-fifo] ✅ /tmp/qw3-in 和 /tmp/qw3-out 就绪"
