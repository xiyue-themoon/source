#!/usr/bin/env python3
"""smart-truncate v3 性能基准测试

覆盖所有核心场景，测量处理时间、压缩率和峰值内存，
生成可读的对齐表格报告。

用法:
    python3 benchmark.py
    python3 benchmark.py --quick   # 快速模式：跳过 5000 条的大测试
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from typing import Any

# ── 尝试导入 tracemalloc（需要用户手动传 PYTHONTRACEMALLOC=1 环境变量） ──
_TM_AVAILABLE = False

try:
    import tracemalloc

    _TM_AVAILABLE = True
except ImportError:
    pass

# ── 导入被测模块 ────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from content_router import ContentRouter, ContentRouterConfig, smart_truncate, RouteResult
from content_detector import detect_content_type, ContentType
from smart_crusher import SmartCrusher, SmartCrusherConfig, CrushResult

# ═══════════════════════════════════════════════════════════════════
# 全局配置
# ═══════════════════════════════════════════════════════════════════

WARMUP_RUNS = 3
BENCH_RUNS = 5
DANGER_THRESHOLD_MS = 500  # 超过 500ms 标记为危险

# 颜色标记（ANSI，终端友好）
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

# ═══════════════════════════════════════════════════════════════════
# 数据生成器
# ═══════════════════════════════════════════════════════════════════


def generate_logs_json(n: int) -> str:
    """生成 n 条 JSON 日志（模拟 tool 返回的 JSON 数组）"""
    levels = ["INFO", "WARN", "ERROR", "DEBUG", "FATAL"]
    msgs = [
        "Server started",
        "DB timeout after 30s",
        "Request processed",
        "Memory usage high",
        "Health check passed",
        "Pool exhausted",
        "Connection established",
        "Cache miss for key user:{}",
        "Auth failed for user {}",
        "Task completed in {}ms",
    ]
    items = []
    for i in range(n):
        items.append(
            {
                "level": random.choice(levels),
                "msg": random.choice(msgs).format(random.randint(1, 999)),
                "pid": random.randint(1000, 9999),
                "timestamp": f"2024-01-01T10:00:{i:02d}",
                "duration_ms": random.randint(1, 5000),
            }
        )
    return json.dumps(items)


def generate_log_text(n: int) -> str:
    """生成 n 行文本日志"""
    lines = []
    for i in range(n):
        level = "ERROR" if i % 7 == 0 else "WARN" if i % 13 == 0 else "INFO"
        lines.append(
            f"2024-01-01 10:00:{i:02d} [{level}] Process #{i}: operation completed in {i*10}ms"
        )
    return "\n".join(lines)


def generate_search_output(n: int) -> str:
    """生成 n 行搜索结果（grep/ripgrep 格式）"""
    lines = []
    for i in range(n):
        lines.append(f"src/main.py:{i*10+1}: def handle_request_{i}(data): pass")
    return "\n".join(lines)


def generate_small_output(n: int) -> str:
    """生成 n 行短输出（应被透传跳过）"""
    lines = []
    for i in range(n):
        lines.append(f"Short line {i}: all systems nominal.")
    return "\n".join(lines)


def generate_mixed_content(json_items: int = 50, log_lines: int = 100) -> str:
    """生成混合内容（Markdown + 代码块 + JSON + 日志）"""
    return (
        "# Analysis Report\n\n"
        "## Overview\n"
        f"The system processed {1000} requests with {5} errors.\n\n"
        "## Configuration\n"
        "```python\n"
        "DEBUG = True\n"
        "MAX_RETRIES = 3\n"
        "TIMEOUT = 30\n"
        "```\n\n"
        "## Results (JSON)\n"
        "```json\n"
        f"{generate_logs_json(json_items)}\n"
        "```\n\n"
        "## Raw Logs\n"
        f"{generate_log_text(log_lines)}\n\n"
        "## Conclusion\n"
        "All tests passed with minor warnings.\n"
    )


def generate_messages_list(n_tool: int, log_lines_per_msg: int) -> list[dict[str, Any]]:
    """生成带 tool 消息的 messages 列表（模拟 Pipeline 集成）"""
    msgs = []
    for i in range(n_tool):
        msgs.append(
            {
                "role": "tool",
                "content": generate_log_text(log_lines_per_msg),
            }
        )
    # 在末尾放一些 user/assistant 消息，方便测试 protect_recent
    msgs.append({"role": "user", "content": "分析最近的错误日志"})
    msgs.append({"role": "assistant", "content": "正在分析中..."})
    msgs.append({"role": "tool", "content": "extra tool near end"})
    msgs.append({"role": "tool", "content": "another tool near end"})
    return msgs


# ═══════════════════════════════════════════════════════════════════
# 测量工具
# ═══════════════════════════════════════════════════════════════════


def bench(
    name: str,
    fn,
    data: Any,
    warmup: int = WARMUP_RUNS,
    runs: int = BENCH_RUNS,
) -> dict[str, Any]:
    """执行基准测试，返回测量结果字典。

    测量指标：
      - avg_time_ms: 平均处理时间（毫秒）
      - min_time_ms / max_time_ms: 最小/最大时间
      - original_size: 原始数据大小（字节/行数）
      - result_size: 结果数据大小
      - compression_ratio: 压缩率（结果/原始）
      - peak_memory_kb: 峰值内存（kibibytes），仅当 tracemalloc 可用
    """
    # ── warmup ──
    for _ in range(warmup):
        _ = fn(data)

    # ── measure time ──
    times = []
    final_result = None
    peak_memory_kb = 0

    for i in range(runs):
        if _TM_AVAILABLE:
            tracemalloc.start()

        t0 = time.perf_counter()
        final_result = fn(data)
        t = time.perf_counter() - t0

        if _TM_AVAILABLE:
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak_memory_kb = max(peak_memory_kb, peak / 1024)

        times.append(t)

    avg_ms = (sum(times) / len(times)) * 1000
    min_ms = min(times) * 1000
    max_ms = max(times) * 1000

    # ── compute sizes ──
    original_size = len(data) if isinstance(data, (str, bytes)) else len(str(data))
    result_text = ""
    if isinstance(final_result, RouteResult):
        result_text = final_result.compressed
    elif isinstance(final_result, CrushResult):
        result_text = final_result.compressed
    elif isinstance(final_result, tuple) and len(final_result) == 2:
        result_text = final_result[0]
    elif isinstance(final_result, str):
        result_text = final_result
    else:
        result_text = str(final_result)

    result_size = len(result_text)
    compression_ratio = result_size / original_size if original_size > 0 else 1.0

    return {
        "name": name,
        "avg_ms": avg_ms,
        "min_ms": min_ms,
        "max_ms": max_ms,
        "original_size": original_size,
        "result_size": result_size,
        "compression_ratio": compression_ratio,
        "peak_memory_kb": peak_memory_kb,
    }


def bench_router(name: str, content: str, **kwargs: Any) -> dict[str, Any]:
    """对 ContentRouter.route() 做基准测试"""
    router = ContentRouter()
    return bench(name, lambda d: router.route(d, **kwargs), content)


def bench_crusher(name: str, content: str) -> dict[str, Any]:
    """对 SmartCrusher.crush() 做基准测试"""
    crusher = SmartCrusher()
    return bench(name, lambda d: crusher.crush(d), content)


def bench_smart_truncate(name: str, text: str, ct: ContentType) -> dict[str, Any]:
    """对 smart_truncate() 做基准测试"""
    return bench(name, lambda d: smart_truncate(d, ct)[0], text)


def bench_original_head_tail(name: str, text: str, head: int, tail: int) -> dict[str, Any]:
    """模拟 v2 原版 head/tail 截断"""

    def head_tail(d: str) -> str:
        lines = d.split("\n")
        total = len(lines)
        max_l = 80
        if total <= max_l:
            return d
        h = lines[:head]
        t = lines[-tail:] if tail > 0 else []
        omitted = total - head - tail
        sep = f"\n... [skipped {omitted} lines] ...\n"
        return "\n".join(h) + sep + "\n".join(t)

    return bench(name, head_tail, text)


def bench_pipeline(name: str, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
    """对 ContentRouter.apply() (pipeline) 做基准测试"""
    router = ContentRouter()

    def do_apply(d: list[dict]) -> Any:
        return router.apply(d, **kwargs)

    return bench(name, do_apply, messages)


# ═══════════════════════════════════════════════════════════════════
# 评级
# ═══════════════════════════════════════════════════════════════════


def rate(avg_ms: float) -> str:
    """根据处理时间返回评级标记"""
    if avg_ms < 10:
        return f"{GREEN}⭐ 优秀{RESET}"
    elif avg_ms < 100:
        return f"{GREEN}✅ 通过{RESET}"
    elif avg_ms < DANGER_THRESHOLD_MS:
        return f"{YELLOW}⚠️  偏慢{RESET}"
    else:
        return f"{RED}🚨 危险{RESET}"


def rate_bool(ok: bool) -> str:
    return f"{GREEN}是{RESET}" if ok else f"{RED}否{RESET}"


# ═══════════════════════════════════════════════════════════════════
# 报告输出
# ═══════════════════════════════════════════════════════════════════


def print_header(title: str) -> None:
    """打印分组标题"""
    print(f"\n{BOLD}{CYAN}{'─' * 78}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 78}{RESET}")


def print_row(
    name: str,
    avg_ms: float,
    min_ms: float,
    max_ms: float,
    orig: int,
    result: int,
    ratio: float,
    mem: float,
    rating: str,
) -> None:
    """打印单行结果（对齐表格）"""
    orig_str = f"{orig:,}"
    result_str = f"{result:,}"
    ratio_pct = f"{ratio*100:.1f}%"

    print(
        f"  {name:<32s} "
        f"{avg_ms:>7.2f}ms "
        f"({min_ms:>6.2f}~{max_ms:>6.2f})  "
        f"{orig_str:>8s}→{result_str:>8s}  "
        f"{ratio_pct:>6s}  "
        f"{mem:>5.0f}KB  "
        f"{rating}"
    )


def print_table_header() -> None:
    print(
        f"  {'场景':<32s} {'平均 ms':>7s} {'(最小 ~ 最大)':>16s}  "
        f"{'原始大小':<16s} {'压缩率':>6s}  "
        f"{'内存':>5s}  {'评级'}"
    )
    print(f"  {'─' * 32} {'─' * 24} {'─' * 22} {'─' * 6} {'─' * 5} {'─' * 8}")


# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════


def run_all_benchmarks(quick: bool = False) -> list[dict[str, Any]]:
    """运行所有基准测试，返回结果列表"""
    results: list[dict[str, Any]] = []

    random.seed(42)  # 确定性的测试数据

    # ─── 场景 1: 大 JSON 日志压缩 ───────────────────────────────────
    print_header("场景 1: 大 JSON 日志压缩 (SmartCrusher)")

    json_sizes = [50, 200, 1000]
    if not quick:
        json_sizes.append(5000)

    for n in json_sizes:
        data = generate_logs_json(n)
        r = bench_crusher(f"JSON {n}条", data)
        results.append(r)
        print_row(
            r["name"],
            r["avg_ms"],
            r["min_ms"],
            r["max_ms"],
            r["original_size"],
            r["result_size"],
            r["compression_ratio"],
            r["peak_memory_kb"],
            rate(r["avg_ms"]),
        )

    # ─── 场景 2: 大文本日志截断 ───────────────────────────────────
    print_header("场景 2: 大文本日志截断 (smart_truncate LOG_OUTPUT)")

    for n in [200, 1000, 5000]:
        data = generate_log_text(n)
        r = bench_smart_truncate(f"文本日志 {n}行", data, ContentType.LOG_OUTPUT)
        results.append(r)
        print_row(
            r["name"],
            r["avg_ms"],
            r["min_ms"],
            r["max_ms"],
            r["original_size"],
            r["result_size"],
            r["compression_ratio"],
            r["peak_memory_kb"],
            rate(r["avg_ms"]),
        )

    # ─── 场景 3: 搜索输出 ─────────────────────────────────────────
    print_header("场景 3: 搜索输出截断 (smart_truncate SEARCH_RESULTS)")

    for n in [100, 500]:
        data = generate_search_output(n)
        r = bench_smart_truncate(f"搜索结果 {n}行", data, ContentType.SEARCH_RESULTS)
        results.append(r)
        print_row(
            r["name"],
            r["avg_ms"],
            r["min_ms"],
            r["max_ms"],
            r["original_size"],
            r["result_size"],
            r["compression_ratio"],
            r["peak_memory_kb"],
            rate(r["avg_ms"]),
        )

    # ─── 场景 4: 小输出透传 ──────────────────────────────────────
    print_header("场景 4: 小输出透传 (应 SKIP)")

    for n in [10, 30, 50]:
        data = generate_small_output(n)
        r = bench_router(f"短文本 {n}行", data)
        results.append(r)
        # 小输出期望不修改
        was_modified = r["compression_ratio"] < 1.0
        skip_ok = not was_modified
        rating_str = f"{GREEN}✅ SKIP{RESET}" if skip_ok else f"{YELLOW}⚠️  MODIFIED{RESET}"
        print_row(
            r["name"],
            r["avg_ms"],
            r["min_ms"],
            r["max_ms"],
            r["original_size"],
            r["result_size"],
            r["compression_ratio"],
            r["peak_memory_kb"],
            rating_str,
        )

    # ─── 场景 5: 混合内容 ────────────────────────────────────────
    print_header("场景 5: 混合内容 (Markdown + 代码块 + JSON + 日志)")

    mixed = generate_mixed_content(json_items=50, log_lines=100)
    r = bench_router("混合内容", mixed)
    results.append(r)
    print_row(
        r["name"],
        r["avg_ms"],
        r["min_ms"],
        r["max_ms"],
        r["original_size"],
        r["result_size"],
        r["compression_ratio"],
        r["peak_memory_kb"],
        rate(r["avg_ms"]),
    )

    # ─── 场景 6: Pipeline 集成 ────────────────────────────────────
    print_header("场景 6: Pipeline 集成 (ContentRouter.apply)")

    msgs = generate_messages_list(n_tool=10, log_lines_per_msg=200)
    r = bench_pipeline("Pipeline 10条消息", msgs, target_role="tool")
    results.append(r)
    print_row(
        r["name"],
        r["avg_ms"],
        r["min_ms"],
        r["max_ms"],
        r["original_size"],
        r["result_size"],
        r["compression_ratio"],
        r["peak_memory_kb"],
        rate(r["avg_ms"]),
    )

    # ─── 场景 7: v2 vs v3 对比 ────────────────────────────────────
    print_header("场景 7: v2 (head/tail) vs v3 (smart_truncate) 对比")

    comparison_data = [
        ("日志", generate_log_text(500), ContentType.LOG_OUTPUT, 20, 15),
        ("搜索", generate_search_output(500), ContentType.SEARCH_RESULTS, 20, 15),
        ("代码", generate_log_text(500), ContentType.SOURCE_CODE, 20, 15),
    ]

    for label, data, ct, head, tail in comparison_data:
        # v2: 原版 head/tail
        r_v2 = bench_original_head_tail(f"v2 {label}截断", data, head, tail)
        results.append(r_v2)
        print_row(
            r_v2["name"],
            r_v2["avg_ms"],
            r_v2["min_ms"],
            r_v2["max_ms"],
            r_v2["original_size"],
            r_v2["result_size"],
            r_v2["compression_ratio"],
            r_v2["peak_memory_kb"],
            rate(r_v2["avg_ms"]),
        )

        # v3: smart_truncate
        r_v3 = bench_smart_truncate(f"v3 {label}截断", data, ct)
        results.append(r_v3)
        print_row(
            r_v3["name"],
            r_v3["avg_ms"],
            r_v3["min_ms"],
            r_v3["max_ms"],
            r_v3["original_size"],
            r_v3["result_size"],
            r_v3["compression_ratio"],
            r_v3["peak_memory_kb"],
            rate(r_v3["avg_ms"]),
        )

    return results


# ═══════════════════════════════════════════════════════════════════
# 汇总与建议
# ═══════════════════════════════════════════════════════════════════


def print_summary(results: list[dict[str, Any]]) -> None:
    """打印汇总报告"""
    print(f"\n{BOLD}{'═' * 78}{RESET}")
    print(f"{BOLD}  性能基准测试总结{RESET}")
    print(f"{BOLD}{'═' * 78}{RESET}")

    # ── 统计 ──
    total_tests = len(results)
    dangerous = [r for r in results if r["avg_ms"] >= DANGER_THRESHOLD_MS]
    slow = [r for r in results if 100 <= r["avg_ms"] < DANGER_THRESHOLD_MS]
    good = [r for r in results if 10 <= r["avg_ms"] < 100]
    excellent = [r for r in results if r["avg_ms"] < 10]

    print(f"\n  总测试数: {total_tests}")
    print(f"  {GREEN}⭐ 优秀  (< 10ms):   {len(excellent)}{RESET}")
    print(f"  {GREEN}✅ 通过  (< 100ms):  {len(good)}{RESET}")
    print(f"  {YELLOW}⚠️  偏慢  (< 500ms): {len(slow)}{RESET}")
    print(f"  {RED}🚨 危险  (>= 500ms): {len(dangerous)}{RESET}")

    # ── 最慢的前 5 个 ──
    if results:
        sorted_by_time = sorted(results, key=lambda r: r["avg_ms"], reverse=True)
        print(f"\n  {BOLD}最慢的 5 个测试:{RESET}")
        for r in sorted_by_time[:5]:
            flag = "🚨" if r["avg_ms"] >= DANGER_THRESHOLD_MS else ""
            print(
                f"    {flag} {r['name']:<38s}  "
                f"{r['avg_ms']:>7.2f}ms  "
                f"(压缩率: {r['compression_ratio']*100:.1f}%)"
            )

    # ── 危险项警告 ──
    if dangerous:
        print(f"\n  {RED}🚨 警告: 以下场景超过 {DANGER_THRESHOLD_MS}ms 阈值，在 terminal pipe 中可能造成卡顿！{RESET}")
        for r in dangerous:
            print(f"     - {r['name']}: {r['avg_ms']:.2f}ms")
        print(f"  {YELLOW}  建议: 优化算法或降低该场景的默认处理规模。{RESET}")

    # ── 内存统计 ──
    if _TM_AVAILABLE:
        mem_results = [r for r in results if r["peak_memory_kb"] > 0]
        if mem_results:
            max_mem = max(mem_results, key=lambda r: r["peak_memory_kb"])
            print(f"\n  {BOLD}内存使用:{RESET}")
            print(f"    峰值: {max_mem['peak_memory_kb']:.0f}KB  ({max_mem['name']})")
            avg_mem = sum(r["peak_memory_kb"] for r in mem_results) / len(mem_results)
            print(f"    平均: {avg_mem:.0f}KB")
    else:
        print(f"\n  {YELLOW}  提示: 设置 PYTHONTRACEMALLOC=1 环境变量可启用内存追踪。{RESET}")

    # ── 建议 ──
    print(f"\n  {BOLD}建议:{RESET}")
    if dangerous:
        print(f"    🔧 对 5000+ 条目的 JSON 压缩场景，考虑使用分块处理或异步策略。")
    if slow:
        print(f"    💡 偏慢场景可考虑减少 max_items_after_crush 或增大 min_tokens_to_crush 阈值。")

    avg_overall = sum(r["avg_ms"] for r in results) / len(results) if results else 0
    print(f"\n  📊 全部测试平均耗时: {avg_overall:.2f}ms")

    print(f"\n{BOLD}{'═' * 78}{RESET}\n")


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════


def main() -> None:
    quick = "--quick" in sys.argv

    print(f"{BOLD}")
    print("  ╔══════════════════════════════════════════════════════════════╗")
    print("  ║       smart-truncate v3 性能基准测试                          ║")
    print("  ║       Hermes Agent — Headroom 压缩模块                        ║")
    print("  ╚══════════════════════════════════════════════════════════════╝")
    print(f"{RESET}")

    print(f"  预热次数: {WARMUP_RUNS}  |  测量次数: {BENCH_RUNS}  |  危险阈值: {DANGER_THRESHOLD_MS}ms")
    print(f"  内存追踪: {'✅ 已启用' if _TM_AVAILABLE else '⚠️  未启用 (设置 PYTHONTRACEMALLOC=1)'}")
    if quick:
        print(f"  ⚡ 快速模式: 跳过 5000 条大测试")
    print()

    print_table_header()

    # ── 运行所有测试 ──
    t_start = time.perf_counter()
    results = run_all_benchmarks(quick=quick)
    t_total = time.perf_counter() - t_start

    # ── 打印汇总 ──
    print_summary(results)
    print(f"  基准测试总耗时: {t_total:.2f}s")


if __name__ == "__main__":
    main()
