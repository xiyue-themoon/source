#!/usr/bin/env python3
"""
smart-truncate v3 CLI — 兼容 v2 接口的内容感知智能截断

内部使用 ContentRouter 做智能路由（JSON 压缩/日志截断/搜索结果截断等），
同时完全兼容 v2 的 CLI 参数接口，方便替换到 Hermes 生产环境。

用法:
  cat output.txt | python3 cli.py
  python3 cli.py --file output.txt
  python3 cli.py --v3 --file output.txt          # 启用 v3 智能压缩
  python3 cli.py --v3 --json < output.txt        # JSON 统计输出
"""

import argparse
import json
import sys
import os

# 添加项目目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from content_router import ContentRouter, ContentRouterConfig, smart_truncate
from content_detector import detect_content_type, ContentType


def main():
    parser = argparse.ArgumentParser(
        description="智能内容截断 v3 — 兼容 v2 CLI 接口"
    )

    # ── 原有 v2 参数（完全兼容）───────────────────────────
    parser.add_argument("--file", "-f", help="从文件读取（默认从 stdin）")
    parser.add_argument("--head", type=int, default=20, help="保留前 N 行")
    parser.add_argument("--tail", type=int, default=15, help="保留后 N 行")
    parser.add_argument("--max", type=int, default=80, help="透传阈值（行数）")
    parser.add_argument("--exit-code", type=int, default=0, help="命令退出码")
    parser.add_argument("--cmd", nargs="*", help="触发该输出的命令（如 git diff）")
    parser.add_argument(
        "--force", action="store_true", help="强制截断，跳过所有保护"
    )
    parser.add_argument(
        "--json", "-j", action="store_true", help="输出 JSON 统计信息到 stderr"
    )

    # ── v3 新标志 ────────────────────────────────────────
    parser.add_argument(
        "--v3", action="store_true", help="启用 v3 内容感知智能压缩"
    )

    args = parser.parse_args()

    # ── 读取输入 ─────────────────────────────────────────
    if args.file:
        with open(args.file, "r") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    # ── v2 兼容模式（默认）───────────────────────────────
    if not args.v3:
        # 输出提示（仅在使用中才提示，避免静默使用时遗漏）
        if args.force or args.json or args.file:
            # 用户有明确意图（force/json/file），仍然提示
            pass
        print(
            "💡 加 --v3 启用内容感知智能压缩（省 45-70% token）",
            file=sys.stderr,
        )

        # 使用 v3 的 smart_truncate（内容类型感知的 fallback 截断）
        detection = detect_content_type(text)
        result, stats = smart_truncate(
            text=text,
            content_type=detection.content_type,
            head_lines=args.head,
            tail_lines=args.tail,
            max_lines=args.max,
        )

        sys.stdout.write(result)

        if args.json:
            # 输出与 v2 兼容的统计信息，附加 v3 特有字段
            v3_stats = {
                "original_lines": stats.get("original_lines", len(text.splitlines())),
                "reduced_lines": stats.get("kept_lines", len(text.splitlines())),
                "ratio": (
                    stats.get("kept_lines", 0) / stats.get("original_lines", 1)
                    if stats.get("original_lines", 0) > 0
                    else 1.0
                ),
                "truncated": stats.get("strategy", "") != "no_truncation_needed",
                "strategy": stats.get("strategy", "smart_truncate"),
                "content_type": detection.content_type.value,
                "confidence": detection.confidence,
                "failure_aware": stats.get("failure_aware", False),
                "exit_code": args.exit_code,
            }
            print(json.dumps(v3_stats, ensure_ascii=False), file=sys.stderr)

        sys.exit(0)

    # ── v3 模式：使用 ContentRouter 智能压缩 ─────────────
    # 如果用户显式指定 --head/--tail/--max，配置 ContentRouter
    config = None
    if args.head != 20 or args.tail != 15 or args.max != 80:
        config = ContentRouterConfig(
            smart_truncate_config={
                "head_lines": args.head,
                "tail_lines": args.tail,
                "max_lines": args.max,
            }
        )

    router = ContentRouter(config=config)
    route_result = router.route(text)

    sys.stdout.write(route_result.compressed)

    if args.json:
        original_lines = len(text.splitlines())
        compressed_lines = len(route_result.compressed.splitlines())
        stats = {
            "strategy": route_result.strategy_used,
            "was_modified": route_result.was_modified,
            "content_type": route_result.content_type,
            "original_bytes": len(text),
            "compressed_bytes": len(route_result.compressed),
            "saved_bytes": len(text) - len(route_result.compressed),
            "original_lines": original_lines,
            "compressed_lines": compressed_lines,
            "saved_lines": original_lines - compressed_lines,
            "compression_ratio": (
                round(compressed_lines / original_lines, 3)
                if original_lines > 0
                else 1.0
            ),
            "exit_code": args.exit_code,
            **route_result.metadata,
        }
        print(json.dumps(stats, ensure_ascii=False), file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
