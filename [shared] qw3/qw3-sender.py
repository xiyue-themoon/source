#!/usr/bin/env python3
"""
qw3-sender.py — 往 qw3-out 写消息（云端→Builder）

用法：
  python3 qw3-sender.py task --phase execute "用PyTorch实现线性回归"
  python3 qw3-sender.py reply "好的，试 pip install"
  python3 qw3-sender.py raw '{"type":"heartbeat","from":"pioneer","to":"builder","content":"ping"}'
  python3 qw3-sender.py --help
"""

import sys
import os
import json
import time
import argparse

FIFO_OUT = "/tmp/qw3-out"


def ensure_fifo():
    """检查 FIFO 是否存在"""
    if not os.path.exists(FIFO_OUT):
        print(f"[qw3-sender] ❌ FIFO {FIFO_OUT} 不存在，先跑 setup-fifo.sh", file=sys.stderr)
        sys.exit(1)
    if not os.access(FIFO_OUT, os.W_OK):
        print(f"[qw3-sender] ❌ 无写入权限: {FIFO_OUT}", file=sys.stderr)
        sys.exit(1)


def send(data: dict):
    """写入一条消息到 FIFO（带 5s 超时）"""
    ensure_fifo()
    line = json.dumps(data, ensure_ascii=False) + "\n"

    # 用线程 + 超时避免 FIFO 永久阻塞
    import threading

    result = {"ok": False, "error": ""}

    def _write():
        try:
            with open(FIFO_OUT, "w") as fifo:
                fifo.write(line)
                fifo.flush()
            result["ok"] = True
        except OSError as e:
            result["error"] = str(e)

    t = threading.Thread(target=_write, daemon=True)
    t.start()
    t.join(timeout=5.0)

    if t.is_alive():
        # 超时了，线程还在阻塞
        print(f"[qw3-sender] ❌ 超时：Builder 未连接（FIFO qw3-out 无读端）", file=sys.stderr)
        sys.exit(1)
    if not result["ok"]:
        print(f"[qw3-sender] ❌ 写入失败: {result['error']}", file=sys.stderr)
        sys.exit(1)
    print(f"[qw3-sender] ✅ 已发送: {data['type']} → Builder", flush=True)


def cmd_task(args):
    """发送任务"""
    send({
        "type": "task",
        "from": "pioneer",
        "to": "builder",
        "phase": args.phase or "execute",
        "content": args.text,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    })


def cmd_reply(args):
    """回复阻塞"""
    send({
        "type": "reply",
        "from": "pioneer",
        "to": "builder",
        "content": args.text,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    })


def cmd_heartbeat(args):
    """发送心跳"""
    send({
        "type": "heartbeat",
        "from": "pioneer",
        "to": "builder",
        "content": "ping",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    })


def cmd_raw(args):
    """发送原始 JSON"""
    try:
        data = json.loads(args.json)
        send(data)
    except json.JSONDecodeError as e:
        print(f"[qw3-sender] ❌ JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="qw3 sender — 发消息给 Builder")
    sub = parser.add_subparsers(dest="cmd")

    # task
    p_task = sub.add_parser("task", help="派任务")
    p_task.add_argument("--phase", "-p", default="execute", help="阶段 (plan/execute/review)")
    p_task.add_argument("text", help="任务内容")

    # reply
    p_reply = sub.add_parser("reply", help="回复阻塞")
    p_reply.add_argument("text", help="回复内容")

    # heartbeat
    sub.add_parser("heartbeat", help="发心跳")

    # raw
    p_raw = sub.add_parser("raw", help="发原始 JSON")
    p_raw.add_argument("json", help="JSON 字符串")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    handlers = {
        "task": cmd_task,
        "reply": cmd_reply,
        "heartbeat": cmd_heartbeat,
        "raw": cmd_raw,
    }
    handlers[args.cmd](args)
