"""
smart_crusher.py — JSON 数组结构化压缩器

Headroom 核心模块：对 JSON 数组做锚点压缩。
工作流程：
  1. 判断是否为 JSON（对接 ContentDetector）
  2. 判断是否为数组 + 长度足够
  3. 用 AnchorSelector 选锚点
  4. 只保留锚点条目
  5. 可选：CCR sentinel 标记（轻量可逆）

依赖：
  - content_detector.py（同级目录）
  - anchor_selector.py（同级目录，即将就绪）

用法:
    >>> from smart_crusher import SmartCrusher, SmartCrusherConfig
    >>> crusher = SmartCrusher()
    >>> result = crusher.crush('[{"id":1},{"id":2},{"id":3}]')
    >>> result.was_modified
    False
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ─── 导入同级模块 ──────────────────────────────────────────────

from content_detector import detect_content_type, ContentType

# anchor_selector 降级定义
try:
    from anchor_selector import AnchorSelector, DataPattern, AnchorConfig
except ImportError:
    AnchorSelector = None
    AnchorConfig = None

    class DataPattern(str, Enum):
        LOGS = "logs"
        SEARCH_RESULTS = "search_results"
        TIME_SERIES = "time_series"
        GENERIC = "generic"

# CCR 可选导入
try:
    from ccr_lite import get_default_store, store_dropped_items
    _CCR_AVAILABLE = True
except ImportError:
    _CCR_AVAILABLE = False


# ─── Sentinel 标记（CCR 轻量可逆） ─────────────────────────────

# 压缩后的数组前缀标记，方便下游识别「这是被 crush 过的」
# 格式: [{"__ccr_sentinel": true, "original_length": N, "strategy": "..."}, ...]
CCR_SENTINEL_KEY = "__ccr_sentinel"
CCR_SENTINEL_MARKER = "ccr_v1"


# ─── 配置 ──────────────────────────────────────────────────────

@dataclass
class SmartCrusherConfig:
    """SmartCrusher 压缩器配置

    控制压缩行为的阈值和开关。
    """

    # 至少 N 个条目才触发模式检测和压缩分析
    min_items_to_analyze: int = 5

    # 原数组 JSON 字符串至少 N 个 token（=字符数/4 粗略估计）才触发压缩
    min_tokens_to_crush: int = 200

    # 压缩后最多保留 N 个条目
    max_items_after_crush: int = 15

    # 是否去重完全相同的条目（dict/list 逐项比较）
    dedup_identical_items: bool = True

    # 是否启用 CCR sentinel 标记（在压缩结果前插入标记条目）
    ccr_enabled: bool = True


# ─── 结果类型 ──────────────────────────────────────────────────

@dataclass
class CrushResult:
    """单次 crush() 调用的结果"""

    # 压缩后的 JSON 字符串（可能未修改）
    compressed: str

    # 原始 JSON 字符串（透传保留，方便做 diff）
    original: str

    # 是否实际发生了修改
    was_modified: bool

    # 使用的策略名称
    strategy: str = "none"

    # 额外元数据（原始条目数、保留条目数、DataPattern 等）
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        mod = "✓" if self.was_modified else "✗"
        return (
            f"CrushResult(modified={mod}, strategy={self.strategy}, "
            f"meta={self.metadata})"
        )


@dataclass
class TransformResult:
    """pipeline 集成用的变换结果

    兼容 Headroom pipeline 的 transform 输出格式。
    """

    # 变换后的消息列表（messages 格式）
    messages: list[dict[str, Any]]

    # 是否发生了任何修改
    was_modified: bool

    # 压缩统计摘要
    stats: dict[str, Any] = field(default_factory=dict)

    # 每个 tool_result 的 crush 结果（仅对被处理的消息）
    crush_results: list[CrushResult] = field(default_factory=list)

    def __repr__(self) -> str:
        mod = "✓" if self.was_modified else "✗"
        return f"TransformResult(modified={mod}, messages={len(self.messages)}, stats={self.stats})"


# ─── 模式检测 ──────────────────────────────────────────────────

# 日志级别关键词
_LOG_LEVEL_KEYWORDS: set[str] = {
    "error", "warn", "warning", "info", "debug", "trace",
    "fatal", "critical", "notice", "alert", "emergency",
}

# 排序/相关性关键词
_RELEVANCE_KEYS: set[str] = {
    "score", "relevance", "rank", "rating", "similarity",
    "confidence", "probability", "weight",
}

# 时间戳键名
_TIME_KEYS: set[str] = {
    "timestamp", "time", "date", "datetime", "created_at",
    "updated_at", "modified_at", "ts", "event_time",
}


def _item_has_key(item: dict[str, Any], keys: set[str]) -> bool:
    """检查 dict 是否包含任意一个指定键"""
    return bool(keys & set(item.keys()))


def _item_value_contains_any(item: dict[str, Any], key: str, keywords: set[str]) -> bool:
    """检查 dict 中某个键的值（字符串形式）是否包含关键词"""
    val = item.get(key)
    if val is None:
        return False
    val_str = str(val).lower()
    return any(kw in val_str for kw in keywords)


def detect_pattern(items: list[dict[str, Any]]) -> DataPattern:
    """检测 JSON 数组的 DataPattern

    基于 Headroom 一致的模式检测逻辑：

    - 所有 item 都含 "level" 或 "severity" 键且值含 ERROR/INFO 等 → LOGS
    - 所有 item 都含 "score" 或 "relevance" 等排序相关键 → SEARCH_RESULTS
    - 所有 item 都含 "timestamp" 或 "time" 或 "date" 键 → TIME_SERIES
    - 其他 → GENERIC

    Args:
        items: 已解析的 JSON 数组（list[dict]）

    Returns:
        检测到的 DataPattern
    """
    if not items:
        return DataPattern.GENERIC

    # 只检查 dict 类型的 item；混合类型跳过
    dict_items: list[dict[str, Any]] = [it for it in items if isinstance(it, dict)]
    if not dict_items:
        return DataPattern.GENERIC

    total = len(dict_items)

    # ── 检测 LOGS ──
    log_count = 0
    for item in dict_items:
        if _item_has_key(item, {"level", "severity"}):
            # 还需要值包含日志级别关键词
            for k in ("level", "severity"):
                if k in item and _item_value_contains_any(item, k, _LOG_LEVEL_KEYWORDS):
                    log_count += 1
                    break
    if total > 0 and log_count / total >= 0.7:
        return DataPattern.LOGS

    # ── 检测 SEARCH_RESULTS ──
    search_count = sum(
        1 for it in dict_items if _item_has_key(it, _RELEVANCE_KEYS)
    )
    if total > 0 and search_count / total >= 0.7:
        return DataPattern.SEARCH_RESULTS

    # ── 检测 TIME_SERIES ──
    time_count = sum(
        1 for it in dict_items if _item_has_key(it, _TIME_KEYS)
    )
    if total > 0 and time_count / total >= 0.7:
        return DataPattern.TIME_SERIES

    return DataPattern.GENERIC


# ─── SmartCrusher 主类 ─────────────────────────────────────────

class SmartCrusher:
    """JSON 数组压缩器

    对 JSON 数组做锚点压缩：检测模式 → 选锚点 → 只保留锚点条目。

    用法:
        crusher = SmartCrusher(config=SmartCrusherConfig(max_items_after_crush=10))
        result = crusher.crush(large_json_array_string)
    """

    def __init__(self, config: SmartCrusherConfig | None = None) -> None:
        self.config = config or SmartCrusherConfig()

        # 尝试实例化 AnchorSelector（如果可用）
        self._selector: Any = None
        if AnchorSelector is not None:
            self._selector = AnchorSelector()

    # ── 核心 crush ──────────────────────────────────────────

    def crush(self, content: str) -> CrushResult:
        """对一段 JSON 数组字符串执行压缩

        Args:
            content: 原始内容字符串（期望是 JSON 数组）

        Returns:
            CrushResult 包含压缩结果和元数据
        """
        original = content

        # Step 1: 判断是否为 JSON
        detection = detect_content_type(content)
        if detection.content_type not in (ContentType.JSON_ARRAY, ContentType.JSON_OBJECT):
            return CrushResult(
                compressed=original,
                original=original,
                was_modified=False,
                strategy="skip_non_json",
                metadata={"reason": f"not JSON: {detection.content_type.value}"},
            )

        # Step 2: 解析 JSON
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, RecursionError) as e:
            return CrushResult(
                compressed=original,
                original=original,
                was_modified=False,
                strategy="skip_parse_error",
                metadata={"reason": f"JSON parse error: {e}"},
            )

        # Step 3: 判断是否为数组
        if not isinstance(parsed, list):
            return CrushResult(
                compressed=original,
                original=original,
                was_modified=False,
                strategy="skip_not_array",
                metadata={"reason": f"not an array, got {type(parsed).__name__}"},
            )

        items: list[Any] = parsed
        original_length = len(items)

        # Step 4: 长度检查
        if original_length < self.config.min_items_to_analyze:
            return CrushResult(
                compressed=original,
                original=original,
                was_modified=False,
                strategy="skip_too_few_items",
                metadata={
                    "original_length": original_length,
                    "min_required": self.config.min_items_to_analyze,
                },
            )

        # Step 5: token 量检查（粗略：字符数 / 4 ≈ token 数）
        estimated_tokens = len(content) // 4
        if estimated_tokens < self.config.min_tokens_to_crush:
            return CrushResult(
                compressed=original,
                original=original,
                was_modified=False,
                strategy="skip_too_few_tokens",
                metadata={
                    "estimated_tokens": estimated_tokens,
                    "min_required": self.config.min_tokens_to_crush,
                    "original_length": original_length,
                },
            )

        # Step 6: 去重（如果启用）
        dedup_applied = False
        if self.config.dedup_identical_items and len(items) > 1:
            items_deduped = self._dedup_items(items)
            if len(items_deduped) < len(items):
                dedup_applied = True
                items = items_deduped

        # Step 7: 检测 DataPattern
        dict_items = [it for it in items if isinstance(it, dict)]
        pattern = detect_pattern(dict_items)

        # Step 8: 选锚点
        max_items = min(self.config.max_items_after_crush, len(items))

        # 去重后已经足够短，且去重是唯一的修改
        if len(items) <= max_items:
            if dedup_applied:
                # 仅做了去重，也算修改
                compressed_str = json.dumps(items, ensure_ascii=False)
                return CrushResult(
                    compressed=compressed_str,
                    original=original,
                    was_modified=True,
                    strategy="dedup_only",
                    metadata={
                        "original_length": original_length,
                        "current_length": len(items),
                        "pattern": pattern.value,
                        "dedup_applied": True,
                    },
                )
            # 本来就短，无需任何操作
            compressed_str = json.dumps(items, ensure_ascii=False)
            return CrushResult(
                compressed=compressed_str,
                original=original,
                was_modified=False,
                strategy="skip_already_short",
                metadata={
                    "original_length": original_length,
                    "current_length": len(items),
                    "max_allowed": max_items,
                    "pattern": pattern.value,
                },
            )

        anchor_indices: set[int] = self._select_anchors(items, max_items, pattern)

        # Step 9: 只保留锚点条目
        kept_items: list[Any] = [items[i] for i in sorted(anchor_indices)]

        # Step 9.5: 将丢弃的条目存入 CCR 存储（支持可逆展开）
        ccr_batch_key: str | None = None
        if self.config.ccr_enabled and _CCR_AVAILABLE:
            try:
                dropped_map = store_dropped_items(items, anchor_indices)
                if dropped_map:
                    # 用所有丢弃条目 hash 的联合值作为 batch key
                    batch_input = ":".join(sorted(dropped_map.values()))
                    ccr_batch_key = hashlib.md5(batch_input.encode()).hexdigest()[:16]
                    # 存储 batch → dropped_map 映射
                    get_default_store().put(
                        f"batch_{ccr_batch_key}",
                        [{"indices": list(dropped_map.keys()), "hashes": list(dropped_map.values())}],
                    )
            except Exception:
                pass  # CCR 存储失败不影响主流程

        # Step 10: 可选 CCR sentinel 标记
        if self.config.ccr_enabled:
            kept_items = self._apply_ccr_sentinel(
                kept_items, original_length, pattern, ccr_batch_key
            )

        compressed_str = json.dumps(kept_items, ensure_ascii=False)

        return CrushResult(
            compressed=compressed_str,
            original=original,
            was_modified=True,
            strategy=f"crush_{pattern.value}",
            metadata={
                "original_length": original_length,
                "kept_length": len(kept_items),
                "compression_ratio": round(len(kept_items) / original_length, 3) if original_length else 0,
                "pattern": pattern.value,
                "dedup_applied": dedup_applied,
                "ccr_enabled": self.config.ccr_enabled,
            },
        )

    # ── 去重 ─────────────────────────────────────────────────

    @staticmethod
    def _dedup_items(items: list[Any]) -> list[Any]:
        """去重完全相同的条目（保持顺序）"""
        seen: set[str] = set()
        result: list[Any] = []
        for item in items:
            # 用 JSON 序列化字符串做 hash（稳定、可比较）
            try:
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError, RecursionError):
                # 不可序列化的对象，保留
                result.append(item)
                continue
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    # ── 锚点选择 ─────────────────────────────────────────────

    def _select_anchors(
        self,
        items: list[Any],
        max_items: int,
        pattern: DataPattern,
    ) -> set[int]:
        """选择锚点索引

        优先使用 AnchorSelector，降级使用均匀采样。
        """
        if self._selector is not None:
            # 使用 AnchorSelector（传入 query=None，不做语义锚点）
            try:
                return self._selector.select_anchors(
                    items=items,
                    max_items=max_items,
                    pattern=pattern,
                    query=None,
                )
            except Exception:
                pass  # 降级

        # 降级策略：均匀采样
        return self._uniform_sampling(len(items), max_items)

    @staticmethod
    def _uniform_sampling(total: int, max_items: int) -> set[int]:
        """均匀采样索引，确保不超过 max_items"""
        if total <= max_items:
            return set(range(total))

        # 始终保留首尾
        indices: set[int] = {0, total - 1}

        # 在中间均匀选 max_items - 2 个
        inner_slots = max_items - 2
        if inner_slots > 0:
            step = total / (inner_slots + 1)
            for i in range(1, inner_slots + 1):
                idx = int(i * step)
                if 0 < idx < total - 1:
                    indices.add(idx)

        return indices

    # ── CCR Sentinel ─────────────────────────────────────────

    @staticmethod
    def _apply_ccr_sentinel(
        items: list[Any],
        original_length: int,
        pattern: DataPattern,
        batch_key: str | None = None,
    ) -> list[Any]:
        """在压缩结果前插入 CCR sentinel 标记条目"""
        kept_length = len(items)
        dropped_count = max(0, original_length - kept_length)
        sentinel: dict[str, Any] = {
            CCR_SENTINEL_KEY: True,
            "marker": "ccr_v1",
            "original_length": original_length,
            "kept_length": kept_length,
            "dropped_count": dropped_count,
            "strategy": pattern.value,
        }
        if batch_key:
            sentinel["original_hash"] = f"batch_{batch_key}"
        return [sentinel] + items

    # ── Pipeline 集成：apply ─────────────────────────────────

    def apply(
        self,
        messages: list[dict[str, Any]],
        *,
        target_role: str = "tool",
        skip_if_short: bool = True,
    ) -> TransformResult:
        """批量处理消息列表，对符合条件的 tool_result 执行 crush

        遍历 messages，找到 role=tool 的消息，对其 content 做 crush。
        这在 Headroom pipeline 中作为 transform step 使用。

        Args:
            messages: OpenAI 格式的消息列表
            target_role: 要处理的消息角色（默认 "tool"）
            skip_if_short: 跳过内容短的消息（节省开销）

        Returns:
            TransformResult 包含处理后的消息列表和统计信息
        """
        modified_messages = list(messages)  # 浅拷贝，后续替换 content
        crush_results: list[CrushResult] = []
        total_crushed = 0
        total_skipped = 0
        total_bytes_saved = 0

        for i, msg in enumerate(modified_messages):
            if msg.get("role") != target_role:
                continue

            content = msg.get("content", "")
            if not isinstance(content, str):
                continue

            # 可选：跳过短内容
            if skip_if_short and len(content) < 500:
                continue

            result = self.crush(content)
            crush_results.append(result)

            if result.was_modified:
                modified_messages[i] = {**msg, "content": result.compressed}
                total_crushed += 1
                total_bytes_saved += len(result.original) - len(result.compressed)
            else:
                total_skipped += 1

        was_modified = total_crushed > 0

        return TransformResult(
            messages=modified_messages,
            was_modified=was_modified,
            stats={
                "total_messages": len(messages),
                "target_messages": total_crushed + total_skipped,
                "crushed": total_crushed,
                "skipped": total_skipped,
                "bytes_saved": total_bytes_saved,
            },
            crush_results=crush_results,
        )

    # ── 便捷方法 ─────────────────────────────────────────────

    def is_crushable(self, content: str) -> bool:
        """快速判断内容是否值得压缩（注意：实际执行完整压缩，非轻量检查）"""
        result = self.crush(content)
        return result.was_modified

    def estimate_savings(self, content: str) -> dict[str, Any]:
        """估算压缩能节省多少空间（注意：实际执行完整压缩）"""
        result = self.crush(content)
        original_len = len(result.original)
        compressed_len = len(result.compressed)
        return {
            "original_chars": original_len,
            "compressed_chars": compressed_len,
            "saved_chars": original_len - compressed_len,
            "saved_pct": round((1 - compressed_len / original_len) * 100, 1) if original_len else 0,
            "would_crush": result.was_modified,
            "strategy": result.strategy,
        }


# ═══════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("SmartCrusher 测试")
    print("=" * 70)

    crusher = SmartCrusher(
        SmartCrusherConfig(
            min_items_to_analyze=3,
            min_tokens_to_crush=10,
            max_items_after_crush=5,
            dedup_identical_items=True,
            ccr_enabled=True,
        )
    )

    # ── 测试 1: 小数组（不触发压缩） ──────────────────────────
    print("\n── 测试 1: 小数组（不触发压缩）──")
    small_arr = json.dumps([{"id": 1}, {"id": 2}])
    result = crusher.crush(small_arr)
    print(f"  输入: {small_arr}")
    print(f"  结果: {result}")
    assert not result.was_modified, "小数组不应触发压缩"

    # ── 测试 2: 非 JSON 内容 ─────────────────────────────────
    print("\n── 测试 2: 非 JSON 内容 ──")
    plain_text = "This is just plain text, not JSON at all."
    result = crusher.crush(plain_text)
    print(f"  输入: {plain_text}")
    print(f"  结果: {result}")
    assert not result.was_modified
    assert result.strategy == "skip_non_json"

    # ── 测试 3: JSON 对象（非数组） ──────────────────────────
    print("\n── 测试 3: JSON 对象（非数组）──")
    obj = json.dumps({"key": "value", "nested": {"a": 1}})
    result = crusher.crush(obj)
    print(f"  输入: {obj}")
    print(f"  结果: {result}")
    assert not result.was_modified
    assert result.strategy == "skip_not_array"

    # ── 测试 4: 大数组压缩 ───────────────────────────────────
    print("\n── 测试 4: 大数组压缩（GENERIC 模式）──")
    large_arr = json.dumps([{"id": i, "data": f"item_{i}" * 10} for i in range(50)])
    result = crusher.crush(large_arr)
    print(f"  原始长度: {len(large_arr)} 字符, {50} 条目")
    parsed_back = json.loads(result.compressed)
    print(f"  压缩后: {len(result.compressed)} 字符, {len(parsed_back)} 条目")
    print(f"  结果: {result}")
    assert result.was_modified
    assert len(parsed_back) <= 5 + 1  # max_items + CCR sentinel
    assert result.strategy == "crush_generic"

    # ── 测试 5: 去重功能 ─────────────────────────────────────
    print("\n── 测试 5: 去重功能 ──")
    dup_arr = json.dumps([
        {"id": 1, "val": "a"},
        {"id": 1, "val": "a"},
        {"id": 1, "val": "a"},
        {"id": 2, "val": "b"},
        {"id": 1, "val": "a"},
        {"id": 3, "val": "c"},
    ] * 5)  # 大量重复
    result = crusher.crush(dup_arr)
    parsed = json.loads(result.compressed)
    print(f"  原始: 30 条目（大量重复）")
    print(f"  去重+压缩后: {len(parsed)} 条目")
    print(f"  策略: {result.strategy}")
    assert result.was_modified

    # ── 测试 6: LOGS 模式检测 ────────────────────────────────
    print("\n── 测试 6: LOGS 模式检测 ──")
    logs = [
        {"level": "ERROR", "message": "Connection refused", "timestamp": "2024-01-01T00:00:00Z"},
        {"level": "INFO", "message": "Server started", "timestamp": "2024-01-01T00:00:01Z"},
        {"level": "WARN", "message": "High memory usage", "timestamp": "2024-01-01T00:00:02Z"},
        {"level": "ERROR", "message": "Timeout", "timestamp": "2024-01-01T00:00:03Z"},
        {"level": "DEBUG", "message": "Processing request", "timestamp": "2024-01-01T00:00:04Z"},
        {"level": "INFO", "message": "Request completed", "timestamp": "2024-01-01T00:00:05Z"},
        {"level": "ERROR", "message": "Disk full", "timestamp": "2024-01-01T00:00:06Z"},
    ]
    pattern = detect_pattern(logs)
    print(f"  检测模式: {pattern.value}")
    assert pattern == DataPattern.LOGS, f"期望 LOGS，实际 {pattern}"

    # ── 测试 7: SEARCH_RESULTS 模式检测 ──────────────────────
    print("\n── 测试 7: SEARCH_RESULTS 模式检测 ──")
    search = [
        {"title": "Result A", "score": 0.95, "url": "http://a.com"},
        {"title": "Result B", "score": 0.87, "url": "http://b.com"},
        {"title": "Result C", "score": 0.72, "url": "http://c.com"},
        {"title": "Result D", "score": 0.65, "url": "http://d.com"},
        {"title": "Result E", "score": 0.50, "url": "http://e.com"},
    ]
    pattern = detect_pattern(search)
    print(f"  检测模式: {pattern.value}")
    assert pattern == DataPattern.SEARCH_RESULTS, f"期望 SEARCH_RESULTS，实际 {pattern}"

    # ── 测试 8: TIME_SERIES 模式检测 ─────────────────────────
    print("\n── 测试 8: TIME_SERIES 模式检测 ──")
    ts_data = [
        {"timestamp": 1700000000, "value": 42.5},
        {"timestamp": 1700000060, "value": 43.1},
        {"timestamp": 1700000120, "value": 44.0},
        {"timestamp": 1700000180, "value": 43.8},
        {"timestamp": 1700000240, "value": 45.2},
    ]
    pattern = detect_pattern(ts_data)
    print(f"  检测模式: {pattern.value}")
    assert pattern == DataPattern.TIME_SERIES, f"期望 TIME_SERIES，实际 {pattern}"

    # ── 测试 9: estimate_savings ─────────────────────────────
    print("\n── 测试 9: estimate_savings ──")
    big = json.dumps([{"id": i, "x": "y" * 50} for i in range(100)])
    savings = crusher.estimate_savings(big)
    print(f"  原始字符: {savings['original_chars']}")
    print(f"  压缩字符: {savings['compressed_chars']}")
    print(f"  节省: {savings['saved_chars']} 字符 ({savings['saved_pct']}%)")
    assert savings["would_crush"]

    # ── 测试 10: apply (pipeline 集成) ───────────────────────
    print("\n── 测试 10: apply (pipeline 集成) ──")
    msgs = [
        {"role": "user", "content": "Search for error logs"},
        {"role": "assistant", "content": "Let me check..."},
        {
            "role": "tool",
            "content": json.dumps([
                {"level": "ERROR", "msg": f"err_{i}"} for i in range(30)
            ]),
        },
    ]
    transform = crusher.apply(msgs, target_role="tool")
    print(f"  消息数: {transform.stats['total_messages']}")
    print(f"  压缩了: {transform.stats['crushed']} 条")
    print(f"  跳过: {transform.stats['skipped']} 条")
    print(f"  节省: {transform.stats['bytes_saved']} 字节")
    assert transform.was_modified

    # ── 测试 11: CCR sentinel 验证 ───────────────────────────
    print("\n── 测试 11: CCR sentinel 验证 ──")
    arr = json.dumps([{"id": i} for i in range(20)])
    result = crusher.crush(arr)
    parsed = json.loads(result.compressed)
    first = parsed[0] if parsed else {}
    has_sentinel = first.get(CCR_SENTINEL_KEY) if isinstance(first, dict) else False
    print(f"  第一个条目含 CCR sentinel: {has_sentinel}")
    if has_sentinel:
        print(f"  sentinel 内容: original_length={first.get('original_length')}, "
              f"strategy={first.get('strategy')}")
    assert has_sentinel, "CCR sentinel 应存在"

    print("\n" + "=" * 70)
    print("所有测试通过 ✓")
    print("=" * 70)
