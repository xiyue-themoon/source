#!/usr/bin/env python3
"""
qw3-listener.py — 云端 FIFO 监听器
持续读取 /tmp/qw3-in（Builder → Pioneer 通道）
解析 JSON Lines，格式化输出到终端

用法:
  python3 qw3-listener.py            # 前台运行
  python3 qw3-listener.py --daemon   # 后台运行（写 PID 文件）
  python3 qw3-listener.py --stop     # 停止后台进程
  python3 qw3-listener.py --status   # 查看运行状态
"""

import sys
import os
import json
import time
import signal
import atexit
from pathlib import Path

FIFO_IN = "/tmp/qw3-in"
PID_FILE = "/tmp/qw3-listener.pid"
LOG_FILE = "/tmp/qw3-listener.log"


def log(msg: str):
    """写日志文件（后台模式用）"""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


def format_message(data: dict) -> str:
    """格式化 Builder 的消息"""
    msg_type = data.get("type", "unknown")
    sender = data.get("from", "builder")

    if msg_type == "report":
        phase = data.get("phase", "")
        content = data.get("content", "")
        ts = data.get("ts", "")
        return (
            f"\n{'='*50}"
            f"\n📬 [Builder] Phase:{phase}"
            f"\n{content}"
            f"\n{'='*50}"
        )
    elif msg_type == "blocker":
        content = data.get("content", "")
        return (
            f"\n{'⚠️'*20}"
            f"\n🚨 [Builder 阻塞]"
            f"\n{content}"
            f"\n{'⚠️'*20}"
        )
    elif msg_type == "ack":
        return f"\n✅ [Builder ACK] {data.get('content', '')}"
    elif msg_type == "heartbeat":
        # 心跳静默，不输出
        return None
    else:
        return f"\n📩 [{sender}] {json.dumps(data, ensure_ascii=False)}"


def listen_forever():
    """持续监听 FIFO，读取 JSON Lines"""
    # 确保 FIFO 存在
    if not os.path.exists(FIFO_IN):
        log(f"FIFO {FIFO_IN} 不存在，等待创建...")
        print(f"[qw3-listener] 等待 {FIFO_IN} 创建...", file=sys.stderr)

    while not os.path.exists(FIFO_IN):
        time.sleep(1)

    log("开始监听")
    print(f"[qw3-listener] 🟢 监听 {FIFO_IN}", flush=True)

    while True:
        try:
            with open(FIFO_IN, "r") as fifo:
                for line in fifo:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        formatted = format_message(data)
                        if formatted:
                            print(formatted, flush=True)
                            log(f"收到 {data.get('type','?')} from {data.get('from','?')}")
                    except json.JSONDecodeError:
                        print(f"\n[原始消息] {line}", flush=True)
                        log(f"原始消息: {line[:200]}")
        except FileNotFoundError:
            log(f"FIFO 丢失，等待重建...")
            time.sleep(1)
            continue
        except OSError as e:
            log(f"FIFO 读取错误: {e}，5s 后重试")
            time.sleep(5)
            continue


def daemonize():
    """后台运行"""
    pid = os.fork()
    if pid > 0:
        # 父进程退出
        print(f"[qw3-listener] 🟢 后台运行 PID={pid}")
        sys.exit(0)

    # 子进程
    os.setsid()
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # 重定向输出到日志
    sys.stdout = open(LOG_FILE, "a")
    sys.stderr = sys.stdout

    listen_forever()


def stop():
    """停止后台进程"""
    if not os.path.exists(PID_FILE):
        print("[qw3-listener] ❌ 没有运行中的实例")
        return
    with open(PID_FILE) as f:
        pid = int(f.read().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        os.remove(PID_FILE)
        print(f"[qw3-listener] 🛑 已停止 PID={pid}")
    except ProcessLookupError:
        os.remove(PID_FILE)
        print(f"[qw3-listener] ⚠️ PID={pid} 已不存在，清理 PID 文件")


def status():
    """查看状态"""
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            pid = f.read().strip()
        try:
            os.kill(int(pid), 0)
            print(f"[qw3-listener] 🟢 运行中 PID={pid}")
        except ProcessLookupError:
            print(f"[qw3-listener] ⚠️ PID={pid} 已不存在（残留 PID 文件）")
            os.remove(PID_FILE)
    else:
        print("[qw3-listener] ⚫ 未运行")


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        daemonize()
    elif "--stop" in sys.argv:
        stop()
    elif "--status" in sys.argv:
        status()
    else:
        print("[qw3-listener] 前台模式 (Ctrl+C 退出)", flush=True)
        try:
            listen_forever()
        except KeyboardInterrupt:
            print("\n[qw3-listener] 🛑 退出", flush=True)
