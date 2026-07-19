#!/bin/bash
# 系统持续监测脚本 — 重启后 30s 间隔采样，默认 8 轮（~4 分钟）
# 输出到 $HOME/health-monitor-$(date +%Y%m%d-%H%M%S).log
#
# 监测项：GPU 温度/VRAM/利用率、Ollama、GitHub、SSH→Pioneer、Hermes CLI
#
# 用法：
#   bash /c/Users/m2214/health-monitor.sh            # 默认 8 轮
#   SAMPLES=20 bash /c/Users/m2214/health-monitor.sh  # 自定义轮数
#
# Windows 注意：
#   - nvidia-smi 必须全路径 /c/Windows/System32/nvidia-smi.exe
#   - 字段名 utilization.gpu 不是 utilization.gpu.gpu（陷阱！）

LOGFILE="$HOME/health-monitor-$(date +%Y%m%d-%H%M%S).log"
INTERVAL=30
SAMPLES=${SAMPLES:-8}  # 默认 ~4 分钟

echo "Health Monitor — $(date '+%Y-%m-%d %H:%M:%S')" > "$LOGFILE"
echo "Interval: ${INTERVAL}s  Samples: ${SAMPLES}" >> "$LOGFILE"
echo "────────────────────────────────────────" >> "$LOGFILE"

for ((i=1; i<=SAMPLES; i++)); do
  TS=$(date '+%H:%M:%S')

  # GPU — 全路径调用，tr -d '\r' 去掉 Windows 换行污染
  GPU_LINE=$(/c/Windows/System32/nvidia-smi.exe --query-gpu=temperature.gpu,memory.used,utilization.gpu --format=csv,noheader 2>&1 | tr -d '\r')
  GPU_TEMP=$(echo "$GPU_LINE" | cut -d, -f1 | xargs)
  GPU_MEM=$(echo "$GPU_LINE" | cut -d, -f2 | xargs)
  GPU_UTIL=$(echo "$GPU_LINE" | cut -d, -f3 | xargs)

  # Ollama ping（API 层检查，不止是进程活着）
  OLLAMA_OK=$(curl -s --connect-timeout 3 http://localhost:11434/api/tags 2>&1 | head -1 | grep -c 'models' 2>/dev/null)
  OLLAMA_STATUS=$([ "$OLLAMA_OK" -gt 0 ] 2>/dev/null && echo "✅" || echo "❌")

  # Network: GitHub
  GH_OK=$(curl -s --connect-timeout 5 -o /dev/null -w "%{http_code}" https://api.github.com 2>/dev/null)
  GH_STATUS=$([ "$GH_OK" = "200" ] && echo "✅" || echo "❌($GH_OK)")

  # Network: SSH Pioneer
  SSH_OK=$(ssh -o ConnectTimeout=5 -o BatchMode=yes ubuntu@43.139.75.69 "echo pong" 2>/dev/null)
  SSH_STATUS=$([ "$SSH_OK" = "pong" ] && echo "✅" || echo "❌")

  # Hermes CLI
  HERMES_OK=$(hermes --version 2>&1 | head -1 | grep -c 'v0')
  HERMES_STATUS=$([ "$HERMES_OK" -gt 0 ] && echo "✅" || echo "❌")

  echo "[$TS] GPU:${GPU_TEMP}°C VRAM:${GPU_MEM}MiB Util:${GPU_UTIL}% | Ollama:${OLLAMA_STATUS} GitHub:${GH_STATUS} SSH:${SSH_STATUS} Hermes:${HERMES_STATUS}" >> "$LOGFILE"

  echo "[$i/$SAMPLES] $TS — GPU ${GPU_TEMP}°C ${GPU_MEM}MiB Util ${GPU_UTIL}% — Ollama${OLLAMA_STATUS} GH${GH_STATUS} SSH${SSH_STATUS}" >&2

  if [ "$i" -lt "$SAMPLES" ]; then
    sleep "$INTERVAL"
  fi
done

echo "────────────────────────────────────────" >> "$LOGFILE"
echo "Done: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOGFILE"

echo "" >&2
echo "=== SUMMARY ===" >&2
echo "Log: $LOGFILE" >&2
head -1 "$LOGFILE" >&2
grep -E '^\[.*\] GPU:' "$LOGFILE" | head -5 >&2
echo "..." >&2
grep -E '^\[.*\] GPU:' "$LOGFILE" | tail -3 >&2
