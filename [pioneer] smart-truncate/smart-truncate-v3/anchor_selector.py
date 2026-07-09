#!/usr/bin/env python3
"""
AnchorSelector — 智能锚点选择器

根据数据模式（搜索/日志/时序/通用）和用户查询关键词，
智能选择数组中的锚点索引，确保压缩后的数据具有代表性。

核心优化：BatchScorer 预计算全体统计量，避免 O(n²) 重复计算。

参考：Headroom 项目的核心压缩模块（纯 Python 复现版本）。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ═══════════════════════════════════════════════════════════════
# 1. 数据模式枚举
# ═══════════════════════════════════════════════════════════════

class DataPattern(str, Enum):
    SEARCH_RESULTS = "search_results"  # 搜索结果：前面的结果更重要
    LOGS = "logs"                      # 日志：后面的条目（最近）更重要
    TIME_SERIES = "time_series"        # 时间序列：首尾均衡
    GENERIC = "generic"                # 通用：均匀分布


# ═══════════════════════════════════════════════════════════════
# 2. 锚点策略枚举
# ═══════════════════════════════════════════════════════════════

class AnchorStrategy(str, Enum):
    FRONT_HEAVY = "front_heavy"    # 搜索：前50% 中10% 后40%
    BACK_HEAVY = "back_heavy"      # 日志：前20% 中20% 后60%
    BALANCED = "balanced"          # 时序：前45% 中10% 后45%
    DISTRIBUTED = "distributed"    # 通用：前35% 中30% 后35%


# ═══════════════════════════════════════════════════════════════
# 3. 权重数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class AnchorWeights:
    front: float
    middle: float
    back: float

    def normalize(self) -> AnchorWeights:
        total = self.front + self.middle + self.back
        if total == 0:
            return AnchorWeights(1/3, 1/3, 1/3)
        return AnchorWeights(
            front=self.front / total,
            middle=self.middle / total,
            back=self.back / total,
        )


# ═══════════════════════════════════════════════════════════════
# 4. 配置
# ═══════════════════════════════════════════════════════════════

@dataclass
class AnchorConfig:
    # 锚点预算
    anchor_budget_pct: float = 0.75
    min_anchor_slots: int = 3
    max_anchor_slots: int = 100

    # 去重与评分
    dedup_identical_items: bool = True
    use_information_density: bool = True
    candidate_multiplier: int = 3

    # 各模式默认权重
    search_front_weight: float = 0.50
    search_back_weight: float = 0.40
    logs_front_weight: float = 0.20
    logs_back_weight: float = 0.60
    default_front_weight: float = 0.35
    default_middle_weight: float = 0.30
    default_back_weight: float = 0.35

    # 查询关键词
    recency_keywords: list = field(default_factory=lambda: [
        "最近", "最新", "刚刚", "recent", "last", "latest", "new", "current",
    ])
    historical_keywords: list = field(default_factory=lambda: [
        "历史", "所有", "全部", "all", "history", "every", "past", "old",
    ])

    # 关键词偏移幅度
    query_adjustment_magnitude: float = 0.15

    # 性能：超过此条数时跳过信息密度评分（改用均匀采样）
    performance_max_density_items: int = 500


# ═══════════════════════════════════════════════════════════════
# 5. 辅助函数
# ═══════════════════════════════════════════════════════════════

def _safe_serialize(obj: Any) -> str:
    """安全序列化，用于 hash 和比较"""
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError, RecursionError):
        return str(obj)


def _get_field_set(obj: Any) -> set[str]:
    """获取 dict 的 key 集合"""
    return set(obj.keys()) if isinstance(obj, dict) else set()


def compute_item_hash(item: Any) -> str:
    """MD5 hash 前 16 字符，用于去重"""
    try:
        serialized = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError, RecursionError):
        serialized = str(item)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════
# 6. BatchScorer — 批处理信息密度评分器（高性能）
# ═══════════════════════════════════════════════════════════════
# 预计算全体 items 的统计量，使每个 item 的评分从 O(n) 降为 O(1)

class BatchScorer:
    """批量信息密度评分器

    在 __init__ 中预计算：
    - 全体 items 序列化 → Counter（频率统计）
    - 全体 items 序列化长度 → min/max（长度归一化）
    - 全体 items 字段集 → 常见字段集（结构独特性）

    之后 score(item) 直接查表，O(1)。
    """

    __slots__ = ("_n", "_freq_counter", "_min_len", "_len_range",
                 "_common_field_sets")

    def __init__(self, all_items: list[dict[str, Any]]):
        self._n = len(all_items)
        if self._n == 0:
            self._freq_counter = Counter()
            self._min_len = 0
            self._len_range = 1
            self._common_field_sets = set()
            return

        # 预计算 1：全体序列化 + 频率
        serialized = [_safe_serialize(it) for it in all_items]
        self._freq_counter = Counter(serialized)

        # 预计算 2：长度归一化
        lengths = [len(s) for s in serialized]
        self._min_len = min(lengths)
        max_len = max(lengths)
        self._len_range = max_len - self._min_len if max_len > self._min_len else 1

        # 预计算 3：常见字段集（占 80% 的字段集）
        field_sets = [_get_field_set(it) for it in all_items]
        fs_counter: Counter[frozenset] = Counter()
        for fs in field_sets:
            if fs:
                fs_counter[frozenset(fs)] += 1
        self._common_field_sets = self._compute_common(fs_counter)

    @staticmethod
    def _compute_common(counter: Counter[frozenset]) -> set[frozenset]:
        """取占 80% 份额的字段集"""
        if not counter:
            return set()
        total = sum(counter.values())
        cum = 0.0
        result: set[frozenset] = set()
        for fs, count in counter.most_common():
            result.add(fs)
            cum += count / total
            if cum >= 0.8:
                break
        return result

    def score(self, item: dict[str, Any]) -> float:
        """计算单个 item 的信息密度评分 [0, 1]"""
        if self._n == 0:
            return 0.0

        item_str = _safe_serialize(item)

        # 值独特性 40%
        freq = self._freq_counter.get(item_str, 0)
        value_u = 1.0 - (freq / self._n)

        # 内容长度 30%
        item_len = len(item_str)
        length_score = (item_len - self._min_len) / self._len_range

        # 结构独特性 30%
        item_fs = _get_field_set(item)
        if item_fs and self._common_field_sets:
            min_jaccard = 1.0
            for cfs in self._common_field_sets:
                union = len(item_fs | cfs)
                intersection = len(item_fs & cfs)
                js = intersection / union if union > 0 else 0.0
                if js < min_jaccard:
                    min_jaccard = js
            structure_u = 1.0 - min_jaccard
        elif item_fs:
            structure_u = 1.0
        else:
            structure_u = 0.0

        return value_u * 0.4 + length_score * 0.3 + structure_u * 0.3


# ═══════════════════════════════════════════════════════════════
# 7. AnchorSelector — 锚点选择器主类
# ═══════════════════════════════════════════════════════════════

class AnchorSelector:
    """智能锚点选择器

    使用方式:
        selector = AnchorSelector()
        anchors = selector.select_anchors(
            items=data, max_items=10,
            pattern=DataPattern.LOGS, query="找出错误"
        )
    """

    _PATTERN_STRATEGY = {
        DataPattern.SEARCH_RESULTS: AnchorStrategy.FRONT_HEAVY,
        DataPattern.LOGS: AnchorStrategy.BACK_HEAVY,
        DataPattern.TIME_SERIES: AnchorStrategy.BALANCED,
        DataPattern.GENERIC: AnchorStrategy.DISTRIBUTED,
    }

    def __init__(self, config: AnchorConfig | None = None):
        self.config = config or AnchorConfig()

    # ── 预算 ──────────────────────────────────────────────────

    def calculate_anchor_budget(self, array_size: int, max_items: int) -> int:
        """计算锚点预算：clamp(max_items * 0.75, 3, 100)"""
        cf = self.config
        raw = int(max_items * cf.anchor_budget_pct)
        budget = max(cf.min_anchor_slots, min(raw, cf.max_anchor_slots))
        return min(budget, array_size)

    # ── 策略 ──────────────────────────────────────────────────

    def get_strategy_for_pattern(self, pattern: DataPattern) -> AnchorStrategy:
        return self._PATTERN_STRATEGY.get(pattern, AnchorStrategy.DISTRIBUTED)

    def get_base_weights_for_strategy(self, strategy: AnchorStrategy) -> AnchorWeights:
        cf = self.config
        if strategy == AnchorStrategy.FRONT_HEAVY:
            m = max(0.0, 1.0 - cf.search_front_weight - cf.search_back_weight)
            return AnchorWeights(cf.search_front_weight, m, cf.search_back_weight).normalize()
        elif strategy == AnchorStrategy.BACK_HEAVY:
            m = max(0.0, 1.0 - cf.logs_front_weight - cf.logs_back_weight)
            return AnchorWeights(cf.logs_front_weight, m, cf.logs_back_weight).normalize()
        elif strategy == AnchorStrategy.BALANCED:
            return AnchorWeights(0.45, 0.10, 0.45).normalize()
        else:  # DISTRIBUTED
            return AnchorWeights(cf.default_front_weight, cf.default_middle_weight, cf.default_back_weight).normalize()

    # ── Query 权重调整 ───────────────────────────────────────

    def adjust_weights_for_query(self, base: AnchorWeights, query: str | None) -> AnchorWeights:
        if not query:
            return base
        q = query.lower()
        m = self.config.query_adjustment_magnitude
        f, mid, b = base.front, base.middle, base.back

        has_recency = any(kw in q for kw in self.config.recency_keywords)
        has_hist = any(kw in q for kw in self.config.historical_keywords)

        if has_recency and not has_hist:
            f = max(0.0, f - m)
            b = min(1.0, b + m)
        elif has_hist and not has_recency:
            f = min(1.0, f + m)
            b = max(0.0, b - m)

        return AnchorWeights(f, mid, b).normalize()

    # ── 主入口 ───────────────────────────────────────────────

    def select_anchors(
        self,
        items: list[dict[str, Any]],
        max_items: int,
        pattern: DataPattern,
        query: str | None = None,
    ) -> set[int]:
        """选择锚点索引

        流程：预算 → 策略 → 权重 → 区域划分 → 去重 → 精选

        Args:
            items: 原始数组
            max_items: 目标保留数
            pattern: 数据模式
            query: 用户查询（可选，用于权重偏移）

        Returns:
            锚点索引集合
        """
        array_size = len(items)
        if array_size == 0:
            return set()
        if array_size <= max_items:
            return set(range(array_size))

        # 预算
        budget = self.calculate_anchor_budget(array_size, max_items)
        if budget <= 0:
            return set()

        # 策略 → 权重
        strategy = self.get_strategy_for_pattern(pattern)
        weights = self.adjust_weights_for_query(
            self.get_base_weights_for_strategy(strategy), query
        )

        # 区域划分
        f_slots = max(1, int(budget * weights.front))
        b_slots = max(1, int(budget * weights.back))
        m_slots = max(0, budget - f_slots - b_slots)

        # 冗余处理：避免超过总预算
        total = f_slots + b_slots + m_slots
        if total > budget:
            m_slots = max(0, m_slots - (total - budget))

        anchors: set[int] = set()
        seen_hashes: set[str] = set()

        # 前部：位置均匀
        if f_slots > 0:
            front_end = min(f_slots * 5, array_size // 2)
            anchors.update(
                self._pick_evenly(0, front_end, f_slots, items, seen_hashes)
            )

        # 后部：位置均匀
        if b_slots > 0:
            back_start = max(array_size - b_slots * 2, (2 * array_size) // 3)
            anchors.update(
                self._pick_evenly(back_start, array_size, b_slots, items, seen_hashes)
            )

        # 中部：信息密度评分精选（大数组时降级为均匀采样）
        if m_slots > 0:
            mid_start = min(len(anchors), array_size - b_slots - 1)
            mid_end = array_size - b_slots

            if mid_end > mid_start:
                if array_size > self.config.performance_max_density_items:
                    # 大数组 → 均匀采样（避免 O(n²) 瓶颈）
                    anchors.update(
                        self._pick_evenly(mid_start, mid_end, m_slots, items, seen_hashes)
                    )
                else:
                    # 小数组 → 信息密度评分
                    anchors.update(
                        self._pick_by_density(mid_start, mid_end, m_slots, items, seen_hashes)
                    )

        return anchors

    # ── 内部：均匀采样 ──────────────────────────────────────

    def _pick_evenly(
        self, start: int, end: int, n: int,
        items: list, seen: set[str]
    ) -> set[int]:
        """从 [start, end) 中均匀选 n 个索引"""
        region = end - start
        if region <= 0 or n <= 0:
            return set()
        result: set[int] = set()
        if n >= region:
            for i in range(start, end):
                if self._dedup_check(items, i, seen):
                    result.add(i)
            return result
        step = region / (n + 1)
        for k in range(n):
            idx = start + min(int((k + 1) * step), region - 1)
            if self._dedup_check(items, idx, seen):
                result.add(idx)
            else:
                # 遇到重复，尝试附近偏移
                for off in [1, -1, 2, -2]:
                    alt = idx + off
                    if start <= alt < end and self._dedup_check(items, alt, seen):
                        result.add(alt)
                        break
        return result

    # ── 内部：信息密度精选 ──────────────────────────────────

    def _pick_by_density(
        self, start: int, end: int, n: int,
        items: list, seen: set[str]
    ) -> set[int]:
        """从 [start, end) 中选信息密度最高的 n 个索引

        策略：先用比默认更大的候选池均匀采样，
        再额外加入所有含异常值的条目（ERROR/FATAL/CRITICAL 等），
        确保关键信息不会被均匀采样遗漏。
        """
        region = end - start
        if region <= 0 or n <= 0:
            return set()

        # 候选池 = n * multiplier（用双倍 multiplier 增强覆盖）
        pool_size = min(n * self.config.candidate_multiplier * 2, region)
        if pool_size <= 0:
            return set()

        # 均匀选候选
        step = region / (pool_size + 1)
        candidate_indices: set[int] = set()
        for k in range(pool_size):
            idx = start + min(int((k + 1) * step), region - 1)
            if self._dedup_check(items, idx, seen, check_only=True):
                candidate_indices.add(idx)

        # 额外加入异常值条目（ERROR/FATAL/CRITICAL/level 高频词）
        # 这些条目通常信息密度高但可能卡在候选间隔中
        anomaly_keywords = {"error", "fatal", "critical", "fail", "exception", "oom", "timeout"}
        for idx in range(start, end):
            item = items[idx]
            if isinstance(item, dict):
                val_str = str(item).lower()
                if any(kw in val_str for kw in anomaly_keywords):
                    if self._dedup_check(items, idx, seen, check_only=True):
                        candidate_indices.add(idx)

        if not candidate_indices:
            return set()

        # 用 BatchScorer 批量评分
        region_items = items[start:end]
        scorer = BatchScorer(region_items)
        scored = [(idx, scorer.score(items[idx])) for idx in candidate_indices]
        scored.sort(key=lambda x: x[1], reverse=True)

        result: set[int] = set()
        for idx, _ in scored[:n]:
            if self._dedup_check(items, idx, seen):
                result.add(idx)
        return result

    # ── 内部：去重检查 ──────────────────────────────────────

    def _dedup_check(
        self, items: list, idx: int, seen: set[str],
        check_only: bool = False
    ) -> bool:
        if not self.config.dedup_identical_items:
            return True
        if idx < 0 or idx >= len(items):
            return False
        item = items[idx]
        if not isinstance(item, dict):
            return True
        h = compute_item_hash(item)
        if h in seen:
            return False
        if not check_only:
            seen.add(h)
        return True


# ═══════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time

    print("=" * 60)
    print("AnchorSelector 测试")
    print("=" * 60)

    selector = AnchorSelector()

    # 测试 1：日志模式
    print("\n📋 测试 1: LOGS 模式 + query 偏移")
    logs = [{'level': 'ERROR' if i % 5 == 0 else 'INFO' if i % 3 == 0 else 'WARN',
             'msg': f'Event {i}', 'pid': 1000 + i}
            for i in range(100)]
    anchors = selector.select_anchors(logs, max_items=10, pattern=DataPattern.LOGS, query="找出最近错误")
    kept = [logs[i] for i in sorted(anchors)]
    errors = sum(1 for x in kept if x['level'] == 'ERROR')
    print(f"  100 条 → {len(kept)} 锚点, 含 ERROR {errors} 条")

    # 测试 2：搜索模式
    print("\n📋 测试 2: SEARCH_RESULTS 模式")
    results = [{'title': f'Doc {i}', 'score': 100 - i, 'url': f'/page/{i}'} for i in range(50)]
    anchors = selector.select_anchors(results, max_items=8, pattern=DataPattern.SEARCH_RESULTS)
    print(f"  50 条 → {len(anchors)} 锚点")
    print(f"  前 3 索引: {sorted(anchors)[:3]}")

    # 测试 3：去重
    print("\n📋 测试 3: 去重")
    dupes = [{'id': 1, 'val': 'a'}, {'id': 2, 'val': 'b'}, {'id': 1, 'val': 'a'}]
    anchors = selector.select_anchors(dupes, max_items=2, pattern=DataPattern.GENERIC)
    print(f"  3 条(含 1 重复) → {len(anchors)} 锚点")

    # 测试 4：边界—小数组
    print("\n📋 测试 4: 小数组（≤ max_items, 全保留）")
    small = [{'x': i} for i in range(5)]
    anchors = selector.select_anchors(small, max_items=10, pattern=DataPattern.GENERIC)
    print(f"  5 条 → {len(anchors)} 锚点（应全保）")

    # 测试 5：性能—1000 条
    print("\n📋 测试 5: 性能—1000 条")
    big = [{'level': 'INFO' if i % 5 else 'ERROR', 'msg': f'event_{i}', 'pid': i}
           for i in range(1000)]
    t0 = time.perf_counter()
    anchors = selector.select_anchors(big, max_items=15, pattern=DataPattern.LOGS)
    dt = (time.perf_counter() - t0) * 1000
    print(f"  1000 条 → {len(anchors)} 锚点 | {dt:.1f}ms")

    # 测试 6：性能—5000 条
    print("\n📋 测试 6: 性能—5000 条（大数组降级模式）")
    huge = [{'level': 'INFO' if i % 10 else 'ERROR', 'msg': f'event_{i}'}
            for i in range(5000)]
    t0 = time.perf_counter()
    anchors = selector.select_anchors(huge, max_items=15, pattern=DataPattern.LOGS)
    dt = (time.perf_counter() - t0) * 1000
    print(f"  5000 条 → {len(anchors)} 锚点 | {dt:.1f}ms")

    print("\n✅ 全部完成")
