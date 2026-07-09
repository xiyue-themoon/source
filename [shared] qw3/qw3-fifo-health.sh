#!/usr/bin/env bash
# qw3-fifo-health.sh — FIFO + Listener 保活检查
# cron 每 5 分钟检查一次
# 用法: cron 设置 */5 * * * * bash ~/.hermes/scripts/qw3-fifo-health.sh

set -euo pipefail

FIFO_IN="/tmp/qw3-in"
FIFO_OUT="/tmp/qw3-out"
PID_FILE="/tmp/qw3-listener.pid"
LISTENER="/home/ubuntu/.hermes/scripts/qw3-listener.py"

# 1. 检查 FIFO 是否存在
NEED_FIFO=false
for f in "$FIFO_IN" "$FIFO_OUT"; do
    if [ ! -p "$f" ]; then
        echo "[qw3-health] ⚠️  FIFO 缺失: $f"
        NEED_FIFO=true
    fi
done

if $NEED_FIFO; then
    bash /home/ubuntu/.hermes/scripts/setup-fifo.sh
    echo "[qw3-health] ✅ FIFO 已重建"
fi

# 2. 检查 listener 是否活着
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        # 活着，没问题
        exit 0
    fi
fi

# 3. listener 死了，重启
echo "[qw3-health] ⚠️  Listener 不在运行，重启..."
python3 "$LISTENER" --daemon
sleep 1
python3 "$LISTENER" --status
