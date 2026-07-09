#!/usr/bin/env python3
"""
memory-scorer.py — 知识管理评分/精简/扩容工具

用法:
  python3 memory-scorer.py score <FILE>        # 评分统计
  python3 memory-scorer.py prune <FILE> <LIMIT> # 模拟精简
  python3 memory-scorer.py expand <FILE>        # 建议扩容值
  python3 memory-scorer.py drift <FILE>         # 计算偏移量

功能:
  - 解析 [分数] 标记的知识条目
  - 统计各 tier 数量/大小
  - 模拟精简并计算 Drift
  - 给出扩容建议

兼容: Linux / Windows (Python 3)
"""

import re
import sys
import os
import math

# 评分定义
TIERS = {
    "P0": {"min": 18, "max": 27, "weight": 27, "label": "P0 — 核心"},
    "P1": {"min": 9, "max": 17, "weight": 13, "label": "P1 — 重要"},
    "P2": {"min": 1, "max": 8, "weight": 4, "label": "P2 — 通用"},
}

LIMIT_STEP = 200


class MemoryEntry:
    """一条知识条目"""

    def __init__(self, text: str, score: int, line_num: int):
        self.text = text
        self.score = score
        self.line_num = line_num
        self.chars = len(text)

        if score >= 18:
            self.tier = "P0"
        elif score >= 9:
            self.tier = "P1"
        else:
            self.tier = "P2"

    def weighted_chars(self) -> int:
        return self.chars * TIERS[self.tier]["weight"]


def parse_entries(filepath: str) -> list[MemoryEntry]:
    """解析文件中的所有 [分数] 条目"""
    entries = []
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    current_entry = ""
    current_score = 0
    current_line = 0
    in_entry = False

    for i, line in enumerate(lines, 1):
        # 匹配 [数字] 开头的条目
        m = re.match(r"^\[(\d+)\]\s+(.*)", line)
        if m:
            # 保存上一条
            if in_entry and current_entry.strip():
                entries.append(MemoryEntry(current_entry.strip(), current_score, current_line))

            current_score = int(m.group(1))
            current_entry = f"[{current_score}] {m.group(2)}"
            current_line = i
            in_entry = True
        elif in_entry:
            # 多行条目继续累积
            if line.strip():
                current_entry += "\n" + line.rstrip()

    # 最后一条
    if in_entry and current_entry.strip():
        entries.append(MemoryEntry(current_entry.strip(), current_score, current_line))

    return entries


def get_stats(entries: list[MemoryEntry]) -> dict:
    """获取统计信息"""
    stats = {
        "total_entries": len(entries),
        "total_chars": sum(e.chars for e in entries),
        "total_weighted_chars": sum(e.weighted_chars() for e in entries),
    }

    for tier in ["P0", "P1", "P2"]:
        tier_entries = [e for e in entries if e.tier == tier]
        stats[tier] = {
            "count": len(tier_entries),
            "chars": sum(e.chars for e in tier_entries),
            "weighted_chars": sum(e.weighted_chars() for e in tier_entries),
        }

    return stats


def cmd_score(filepath: str):
    """评分统计"""
    if not os.path.exists(filepath):
        print(f"❌ 文件不存在: {filepath}")
        return 1

    entries = parse_entries(filepath)
    if not entries:
        print(f"⚠️  未找到带 [分数] 标记的条目")
        return 0

    stats = get_stats(entries)

    print(f"📊 知识评分统计 — {os.path.basename(filepath)}")
    print(f"══════════════════════════════════")
    print(f"总条目: {stats['total_entries']} | 总字符: {stats['total_chars']}")
    print(f"总加权字符: {stats['total_weighted_chars']}")
    print()

    for tier in ["P0", "P1", "P2"]:
        t = stats[tier]
        info = TIERS[tier]
        bar = "█" * min(t["count"], 40) if t["count"] > 0 else ""
        pct = (t["chars"] / stats["total_chars"] * 100) if stats["total_chars"] > 0 else 0
        print(f"  {info['label']:15s}  {t['count']:3d} 条  {t['chars']:6d} chars  ({pct:4.1f}%)  {bar}")

    print()

    # P0 扩容建议
    p0_chars = stats["P0"]["chars"]
    suggested = math.ceil(p0_chars * 1.3 / LIMIT_STEP) * LIMIT_STEP
    print(f"📈 P0 总大小: {p0_chars} chars")
    print(f"   扩容建议: {suggested} (P0×1.3, step={LIMIT_STEP})")
    return 0


def cmd_prune(filepath: str, limit: int):
    """模拟精简（仅报告，不实际修改文件）"""
    if not os.path.exists(filepath):
        print(f"❌ 文件不存在: {filepath}")
        return 1

    entries = parse_entries(filepath)
    if not entries:
        print(f"⚠️  未找到带 [分数] 标记的条目")
        return 0

    current = sum(e.chars for e in entries)
    if current <= limit:
        print(f"✅ 当前 {current} chars ≤ 限制 {limit} chars，无需精简")
        return 0

    # 按分数升序排列
    sorted_entries = sorted(entries, key=lambda e: e.score)

    # 计算需要精简的数量
    target = current - limit
    removed_chars = 0
    removed_entries = []
    kept_entries = list(entries)

    for e in sorted_entries:
        if removed_chars >= target:
            break
        # 不要删 P0
        if e.tier == "P0":
            continue
        removed_chars += e.chars
        removed_entries.append(e)
        kept_entries.remove(e)

    # 计算 Drift
    if current > 0:
        removed_weighted = sum(e.weighted_chars() for e in removed_entries)
        total_weighted = sum(e.weighted_chars() for e in entries)
        drift = removed_weighted / total_weighted * 100
    else:
        drift = 0

    print(f"🔍 精简模拟 — {os.path.basename(filepath)}")
    print(f"══════════════════════════════════")
    print(f"当前: {current} chars | 目标: ≤ {limit} chars")
    print(f"需精简: {target} chars")
    print()
    print(f"📤 移除 {len(removed_entries)} 条 ({removed_chars} chars):")

    for e in removed_entries:
        tier_name = e.tier
        text_preview = e.text[:60].replace("\n", " ")
        print(f"   [{e.score}] {tier_name}  {text_preview}...")
        if len(e.text) > 60:
            print(f"           ...(+{len(e.text)-60} chars)")

    print()

    if drift < 5:
        level = "🟢 安全"
    elif drift < 15:
        level = "🟡 警告"
    else:
        level = "🔴 临界"

    remaining = sum(e.chars for e in kept_entries)
    print(f"📉 Drift: {drift:.1f}% → {level}")
    print(f"   精简后: {remaining} chars (目标 {limit})")
    print(f"   剩余 P0: {sum(1 for e in kept_entries if e.tier == 'P0')} 条")
    print(f"   剩余 P1: {sum(1 for e in kept_entries if e.tier == 'P1')} 条")
    print(f"   剩余 P2: {sum(1 for e in kept_entries if e.tier == 'P2')} 条")

    if drift >= 15:
        print()
        print("⚠️  Drift > 15%，建议人工审查后再执行精简")
        print("   或考虑扩容而非精简")

    return 0


def cmd_expand(filepath: str):
    """建议扩容值"""
    if not os.path.exists(filepath):
        print(f"❌ 文件不存在: {filepath}")
        return 1

    entries = parse_entries(filepath)
    if not entries:
        print(f"⚠️  未找到带 [分数] 标记的条目")
        return 0

    stats = get_stats(entries)
    p0_chars = stats["P0"]["chars"]
    current_total = stats["total_chars"]

    suggested = math.ceil(p0_chars * 1.3 / LIMIT_STEP) * LIMIT_STEP

    print(f"📐 扩容建议 — {os.path.basename(filepath)}")
    print(f"══════════════════════════════════")
    print(f"当前总大小: {current_total} chars")
    print(f"P0 总大小:  {p0_chars} chars")
    print()
    print(f"建议扩容: {suggested} chars")
    print(f"  (P0×1.3={p0_chars*1.3:.0f}, 取整到 {LIMIT_STEP})")
    print()
    print(f"当前各 tier 占比:")
    for tier in ["P0", "P1", "P2"]:
        t = stats[tier]
        info = TIERS[tier]
        pct = (t["chars"] / current_total * 100) if current_total > 0 else 0
        print(f"  {info['label']:15s}  {t['count']:3d} 条  {t['chars']:6d} chars  ({pct:4.1f}%)")

    return 0


def cmd_drift(filepath: str):
    """计算当前文件的偏移量"""
    if not os.path.exists(filepath):
        print(f"❌ 文件不存在: {filepath}")
        return 1

    entries = parse_entries(filepath)
    if not entries:
        print(f"⚠️  未找到带 [分数] 标记的条目，无法计算偏移")
        return 0

    stats = get_stats(entries)
    total_weighted = stats["total_weighted_chars"]

    print(f"📏 偏移量计算 — {os.path.basename(filepath)}")
    print(f"══════════════════════════════════")
    print(f"总条目: {stats['total_entries']} 条 | 总加权: {total_weighted}")
    print()

    for tier in ["P0", "P1", "P2"]:
        t = stats[tier]
        info = TIERS[tier]
        w = info["weight"]
        wpct = (t["weighted_chars"] / total_weighted * 100) if total_weighted > 0 else 0
        print(f"  {info['label']:15s}  w={w:2d} | {t['count']:3d}条 × {t['chars']:6d}c = {t['weighted_chars']:8d}  ({wpct:4.1f}%)")

    print()
    print("当前 Drift = 0.0%（无精简操作发生）")
    print("使用 `prune` 命令模拟精简后查看预期 Drift")
    return 0


def print_usage():
    print("用法: python3 memory-scorer.py <命令> [参数]")
    print()
    print("命令:")
    print("  score <FILE>         评分统计")
    print("  prune <FILE> <LIMIT> 模拟精简（不实际修改文件）")
    print("  expand <FILE>        扩容建议")
    print("  drift <FILE>         偏移量计算")
    print()
    print("示例:")
    print("  python3 memory-scorer.py score ~/.hermes/memories/MEMORY.md")
    print("  python3 memory-scorer.py prune ~/.hermes/memories/USER.md 1375")
    print("  python3 memory-scorer.py expand ~/.hermes/memories/USER.md")
    print("  python3 memory-scorer.py drift ~/.hermes/memories/MEMORY.md")


def main():
    if len(sys.argv) < 2:
        print_usage()
        return 1

    cmd = sys.argv[1]

    if cmd in ("score", "expand", "drift"):
        if len(sys.argv) < 3:
            print(f"❌ 需要指定文件路径")
            print(f"用法: python3 memory-scorer.py {cmd} <FILE>")
            return 1
        filepath = os.path.expanduser(sys.argv[2])

        if cmd == "score":
            return cmd_score(filepath)
        elif cmd == "expand":
            return cmd_expand(filepath)
        elif cmd == "drift":
            return cmd_drift(filepath)

    elif cmd == "prune":
        if len(sys.argv) < 4:
            print("❌ 需要指定文件路径和目标限制")
            print("用法: python3 memory-scorer.py prune <FILE> <LIMIT>")
            return 1
        filepath = os.path.expanduser(sys.argv[2])
        try:
            limit = int(sys.argv[3])
        except ValueError:
            print(f"❌ LIMIT 必须为数字: {sys.argv[3]}")
            return 1
        return cmd_prune(filepath, limit)

    else:
        print(f"❌ 未知命令: {cmd}")
        print()
        print_usage()
        return 1


if __name__ == "__main__":
    sys.exit(main())
