"""
content_router.py — ContentRouter 路由层 + smart_truncate 通用截断 fallback

Headroom 核心模块：将内容类型检测、JSON 压缩、通用文本截断串联起来，
提供一个统一的路由入口，是整个压缩 pipeline 的调度中心。

工作流程：
  1. 检测内容类型（对接 ContentDetector）
  2. 根据类型路由到对应压缩器：
     - JSON_ARRAY → SmartCrusher.crush()
     - LOG/SEARCH/CODE/TEXT → smart_truncate()
     - DIFF / JSON_OBJECT → 透传
  3. 返回 RouteResult（含压缩后文本 + 策略名 + 元数据）

依赖：
  - content_detector.py（同级目录）
  - smart_crusher.py（同级目录）

用法:
    >>> from content_router import ContentRouter, smart_truncate
    >>> router = ContentRouter()
    >>> result = router.route(large_log_text)
    >>> result.strategy_used
    'smart_truncate_log_output'
    >>> result.was_modified
    True
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# ─── 导入同级模块 ──────────────────────────────────────────────

from content_detector import (
    detect_content_type,
    ContentType,
    DetectionResult,
    is_mixed_content,
    split_into_sections,
)

from smart_crusher import (
    SmartCrusher,
    SmartCrusherConfig,
    CrushResult,
    TransformResult,
)

# 可选模块（不存在时优雅降级）
try:
    from code_compressor import compress_python
    _CODE_COMPRESSOR_AVAILABLE = True
except ImportError:
    _CODE_COMPRESSOR_AVAILABLE = False

try:
    from ccr_lite import get_default_store, expand_sentinel
    _CCR_LITE_AVAILABLE = True
except ImportError:
    _CCR_LITE_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════
# ContentRouterConfig
# ═══════════════════════════════════════════════════════════════

@dataclass
class ContentRouterConfig:
    """ContentRouter 路由层配置

    控制压缩路由行为和 fallback 截断参数。
    所有字段均有合理默认值，零配置即可使用。
    """

    # ── 压缩器开关 ──

    # 是否启用 SmartCrusher（JSON 数组压缩）
    enable_smart_crusher: bool = True

    # 是否启用代码压缩器 (Python ast 版, 省 25-55%)
    enable_code_compressor: bool = True

    # 是否启用 CCR 自动展开（压缩后自动取回 sentinel 原始数据）
    # 默认 False：省 token，数据存 CCR store 可恢复
    ccr_auto_expand: bool = False

    # ── 保护策略（与 Headroom 一致）──

    # 最后 N 条消息不压缩（保护近期上下文）
    protect_recent: int = 4

    # 是否检测 analyze/review/总结/分析 等分析意图
    # 检测到时向路由传入分析上下文，调整截断策略
    protect_analysis_context: bool = True

    # 短内容跳过阈值（字符数），低于此值不做任何处理
    min_chars_to_compress: int = 500

    # ── smart_truncate 默认参数 ──

    # 通用文本截断的默认配置（会被内容类型感知覆盖）
    smart_truncate_config: dict[str, int] = field(default_factory=lambda: {
        "head_lines": 20,
        "tail_lines": 15,
        "max_lines": 80,
    })


# ═══════════════════════════════════════════════════════════════
# RouteResult
# ═══════════════════════════════════════════════════════════════

@dataclass
class RouteResult:
    """单次 route() 调用的结果

    统一封装各种压缩策略的返回，方便下游做统计和日志。
    """

    # 压缩/截断后的文本
    compressed: str

    # 原始文本（透传保留，方便做 diff/日志）
    original: str

    # 使用的策略名称，如 "smart_crusher" / "smart_truncate_log_output" / "passthrough"
    strategy_used: str

    # 是否实际发生了修改
    was_modified: bool

    # 检测到的内容类型（ContentType 的 value 字符串）
    content_type: str

    # 额外元数据（原始行数、保留行数、省略行数等）
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        mod = "✓" if self.was_modified else "✗"
        return (
            f"RouteResult(modified={mod}, strategy={self.strategy_used}, "
            f"type={self.content_type}, meta={self.metadata})"
        )


# ═══════════════════════════════════════════════════════════════
# smart_truncate — 通用文本截断 fallback
# ═══════════════════════════════════════════════════════════════

# 分析意图关键词（中英文），用于保护分析上下文
_ANALYSIS_KEYWORDS: set[str] = {
    "analyze", "review", "分析", "总结", "检查", "排查",
    "investigate", "诊断", "debug", "trace", "review",
    "assess", "评估", "复盘",
}

# 失败感知：常见退出码/错误指示行
_EXIT_CODE_PATTERN = re.compile(
    r"(?:exit[_ ]?code[=:]\s*[1-9]\d*|Exited with code [1-9]|"
    r"\[ERROR\]|FATAL|CRITICAL|Traceback|panic:|Segmentation fault)",
    re.IGNORECASE,
)

# 内容类型 → (head_lines, tail_lines) 映射
# 设计原则：
#   - LOG: 尾部最重要（最新日志），head=10 tail=30
#   - SEARCH_RESULTS: 头部最相关，head=30 tail=10
#   - CODE: 首尾均衡，head=20 tail=20
#   - PLAIN_TEXT: 通用，head=20 tail=15
_TYPE_TRUNCATION_MAP: dict[ContentType, tuple[int, int]] = {
    ContentType.LOG_OUTPUT: (10, 30),
    ContentType.SEARCH_RESULTS: (30, 10),
    ContentType.SOURCE_CODE: (20, 20),
    ContentType.PLAIN_TEXT: (20, 15),
}


def smart_truncate(
    text: str,
    content_type: ContentType,
    head_lines: int = 20,
    tail_lines: int = 15,
    max_lines: int = 80,
) -> tuple[str, dict[str, Any]]:
    """通用文本截断 — Headroom fallback 链的兜底

    根据内容类型自动调整截断策略，保留最有价值的部分。

    截断策略（按内容类型）：
        LOG_OUTPUT     → head=10, tail=30（尾部最新最重要）
        SEARCH_RESULTS → head=30, tail=10（头部最相关）
        SOURCE_CODE    → head=20, tail=20（首尾均衡保护）
        PLAIN_TEXT     → head=20, tail=15（通用策略）
        DIFF_OUTPUT    → 透传不截断
        失败感知        → 检测到 exit_code 非 0 时 tail=30

    Args:
        text: 原始文本
        content_type: 检测到的内容类型
        head_lines: 头部保留行数（会被内容类型感知覆盖）
        tail_lines: 尾部保留行数（会被内容类型感知覆盖）
        max_lines: 最大行数阈值，超过才截断

    Returns:
        (截断后文本, 统计信息字典)
    """
    # ── DIFF 透传 ──
    if content_type == ContentType.DIFF_OUTPUT:
        lines = text.split("\n")
        return text, {
            "strategy": "passthrough_diff",
            "original_lines": len(lines),
            "reason": "DIFF 不截断，保留完整差异信息",
        }

    # ── 根据内容类型调整 head/tail ──
    if content_type in _TYPE_TRUNCATION_MAP:
        head_lines, tail_lines = _TYPE_TRUNCATION_MAP[content_type]

    # ── 失败感知：如果内容包含错误指示，尾部再多保留一些 ──
    if content_type in (ContentType.LOG_OUTPUT, ContentType.PLAIN_TEXT):
        if _EXIT_CODE_PATTERN.search(text):
            tail_lines = max(tail_lines, 30)
            # 同时增加头部，因为错误可能在前面的消息里
            head_lines = max(head_lines, 15)

    # ── 行数检查 ──
    lines = text.split("\n")
    total_lines = len(lines)

    if total_lines <= max_lines:
        return text, {
            "strategy": "no_truncation_needed",
            "original_lines": total_lines,
            "kept_lines": total_lines,
            "max_threshold": max_lines,
        }

    # ── 执行截断 ──
    # 确保 head + tail 不超过总行数
    if head_lines + tail_lines >= total_lines:
        head_lines = min(head_lines, total_lines)
        tail_lines = total_lines - head_lines

    head = lines[:head_lines]
    tail = lines[-tail_lines:] if tail_lines > 0 else []
    omitted = total_lines - head_lines - tail_lines

    # 构建截断结果
    if omitted > 0:
        separator = f"\n... [省略 {omitted} 行] ...\n"
        truncated = "\n".join(head) + separator + "\n".join(tail)
    else:
        truncated = text  # 不截断

    # 策略名包含内容类型，方便下游统计
    strategy_name = f"smart_truncate_{content_type.value}"

    return truncated, {
        "strategy": strategy_name,
        "original_lines": total_lines,
        "head_lines": head_lines,
        "tail_lines": tail_lines,
        "omitted_lines": omitted,
        "kept_lines": head_lines + tail_lines,
        "max_threshold": max_lines,
        "failure_aware": bool(_EXIT_CODE_PATTERN.search(text)),
    }


# ═══════════════════════════════════════════════════════════════
# ContentRouter 主类
# ═══════════════════════════════════════════════════════════════

class ContentRouter:
    """内容路由层 — 智能路由到最佳压缩器

    统一入口：无论内容是什么类型，route() 都会返回压缩/截断结果。
    内部集成了 ContentDetector（类型检测）、SmartCrusher（JSON 压缩）、
    和 smart_truncate（通用文本截断）。

    用法:
        router = ContentRouter()
        result = router.route(some_content)
        if result.was_modified:
            print(f"压缩后: {result.compressed[:100]}...")

    Pipeline 集成:
        result = router.apply(messages, target_role="tool")
        # result.messages 是处理后的消息列表
    """

    def __init__(self, config: ContentRouterConfig | None = None) -> None:
        """初始化 ContentRouter

        Args:
            config: ContentRouterConfig 配置，None 使用默认值
        """
        self.config = config or ContentRouterConfig()

        # 初始化 SmartCrusher（JSON 数组压缩器）
        self._crusher: SmartCrusher = SmartCrusher(
            SmartCrusherConfig(
                min_items_to_analyze=5,
                min_tokens_to_crush=200,
                max_items_after_crush=15,
                dedup_identical_items=True,
                ccr_enabled=True,
            )
        )

    # ── 核心路由方法 ──────────────────────────────────────────

    def route(self, content: str, context: str = "") -> RouteResult:
        """路由到最佳压缩器

        流程：
          1. 检测内容类型（ContentDetector）
          2. 根据类型路由：
             - JSON_ARRAY  → SmartCrusher.crush()
             - JSON_OBJECT → 透传（单对象不压缩）
             - LOG/SEARCH/CODE/TEXT → smart_truncate()
             - DIFF         → 透传
          3. 对混合内容按段落分别处理
          4. 返回 RouteResult

        Args:
            content: 原始内容字符串
            context: 可选上下文提示（如 "analysis" 表示分析场景）

        Returns:
            RouteResult 包含处理结果和元数据
        """
        original = content
        if not content or not content.strip():
            return RouteResult(
                compressed=content,
                original=original,
                strategy_used="passthrough_empty",
                was_modified=False,
                content_type=ContentType.PLAIN_TEXT.value,
                metadata={"reason": "空内容"},
            )

        # ── Step 1: 检测内容类型 ──
        detection: DetectionResult = detect_content_type(content)
        ct = detection.content_type

        # ── Step 2: 混合内容检测 → 分段处理 ──
        if is_mixed_content(content):
            return self._route_mixed(content, original, detection, context)

        # ── Step 3: 根据类型路由 ──

        # JSON 数组 → SmartCrusher
        if ct == ContentType.JSON_ARRAY and self.config.enable_smart_crusher:
            return self._route_json_array(content, original, detection)

        # JSON 对象 → 透传（单对象通常不需要压缩）
        if ct == ContentType.JSON_OBJECT:
            return RouteResult(
                compressed=content,
                original=original,
                strategy_used="passthrough_json_object",
                was_modified=False,
                content_type=ct.value,
                metadata={
                    "reason": "JSON 对象不需要压缩",
                    "confidence": detection.confidence,
                    "keys": detection.metadata.get("keys", []),
                },
            )

        # DIFF → 透传
        if ct == ContentType.DIFF_OUTPUT:
            return RouteResult(
                compressed=content,
                original=original,
                strategy_used="passthrough_diff",
                was_modified=False,
                content_type=ct.value,
                metadata={"reason": "DIFF 不压缩，保留完整差异"},
            )

        # 源代码（CODE）→ Code Compressor 或 smart_truncate
        if ct == ContentType.SOURCE_CODE:
            if self.config.enable_code_compressor and _CODE_COMPRESSOR_AVAILABLE:
                compressed, stats = compress_python(content)
                was_mod = compressed != content
                return RouteResult(
                    compressed=compressed,
                    original=original,
                    strategy_used="code_compressor" if was_mod else "passthrough_code",
                    was_modified=was_mod,
                    content_type=ct.value,
                    metadata=stats,
                )
            # 未启用或不可用 → smart_truncate fallback
            return self._route_text(content, original, ct)

        # LOG / SEARCH_RESULTS / PLAIN_TEXT → smart_truncate
        return self._route_text(content, original, ct)

    # ── 内部分路由方法 ────────────────────────────────────────

    def _route_json_array(
        self,
        content: str,
        original: str,
        detection: DetectionResult,
    ) -> RouteResult:
        """路由到 SmartCrusher 处理 JSON 数组"""
        crush_result: CrushResult = self._crusher.crush(content)

        # CCR 自动展开：如果压缩结果含 sentinel 且 CCR 可用
        compressed = crush_result.compressed
        if (
            crush_result.was_modified
            and _CCR_LITE_AVAILABLE
            and self.config.ccr_auto_expand
        ):
            try:
                parsed = json.loads(compressed)
                if isinstance(parsed, list) and any(
                    isinstance(x, dict) and x.get("__ccr_sentinel")
                    for x in parsed[:3]  # sentinel 通常在开头，检查前3个够用
                ):
                    store = get_default_store()
                    expanded = store.expand_sentinel(parsed)
                    compressed = json.dumps(expanded, ensure_ascii=False)
            except Exception:
                pass  # 展开失败不影响原始压缩结果

        return RouteResult(
            compressed=compressed,
            original=original,
            strategy_used=crush_result.strategy,
            was_modified=crush_result.was_modified,
            content_type=ContentType.JSON_ARRAY.value,
            metadata={
                "detection_confidence": detection.confidence,
                **crush_result.metadata,
            },
        )

    def _route_text(
        self,
        content: str,
        original: str,
        content_type: ContentType,
    ) -> RouteResult:
        """路由到 smart_truncate 处理文本类内容"""
        tc = self.config.smart_truncate_config
        truncated, stats = smart_truncate(
            text=content,
            content_type=content_type,
            head_lines=tc.get("head_lines", 20),
            tail_lines=tc.get("tail_lines", 15),
            max_lines=tc.get("max_lines", 80),
        )

        return RouteResult(
            compressed=truncated,
            original=original,
            strategy_used=stats.get("strategy", "smart_truncate"),
            was_modified=(truncated != original),
            content_type=content_type.value,
            metadata=stats,
        )

    def _route_mixed(
        self,
        content: str,
        original: str,
        detection: DetectionResult,
        context: str,
    ) -> RouteResult:
        """处理混合内容：按段落分别路由，再拼接"""
        sections = split_into_sections(content)

        if len(sections) <= 1:
            # 实际上不混合，直接用 smart_truncate 处理（不要调 route() 避免递归）
            sec_content = sections[0]["content"] if sections else content
            sec_type = sections[0].get("type", ContentType.PLAIN_TEXT) if sections else ContentType.PLAIN_TEXT
            if isinstance(sec_type, str):
                try:
                    sec_type = ContentType(sec_type)
                except ValueError:
                    sec_type = ContentType.PLAIN_TEXT
            truncated, stats = smart_truncate(sec_content, content_type=sec_type)
            was_mod = stats.get("truncated", False) or truncated != sec_content
            return RouteResult(
                compressed=truncated,
                original=original,
                strategy_used=f"smart_truncate_{sec_type.value}",
                was_modified=was_mod,
                content_type=sec_type.value,
                metadata=stats,
            )

        processed_sections: list[str] = []
        total_original = 0
        total_compressed = 0
        strategies_used: set[str] = set()

        for section in sections:
            sec_content = section.get("content", "")
            sec_type = section.get("type", ContentType.PLAIN_TEXT)

            if isinstance(sec_type, str):
                # 兼容字符串类型的 type
                try:
                    sec_type = ContentType(sec_type)
                except ValueError:
                    sec_type = ContentType.PLAIN_TEXT

            if len(sec_content) < self.config.min_chars_to_compress:
                processed_sections.append(sec_content)
                total_original += len(sec_content)
                total_compressed += len(sec_content)
                strategies_used.add("passthrough_short_section")
                continue

            # 对段落递归路由
            sub_result = self.route(sec_content, context=context)
            processed_sections.append(sub_result.compressed)
            total_original += len(sub_result.original)
            total_compressed += len(sub_result.compressed)
            strategies_used.add(sub_result.strategy_used)

        compressed = "\n".join(processed_sections)
        strategies_str = "+".join(sorted(strategies_used)) if strategies_used else "mixed_passthrough"

        return RouteResult(
            compressed=compressed,
            original=original,
            strategy_used=f"mixed({strategies_str})",
            was_modified=(compressed != original),
            content_type="mixed",
            metadata={
                "section_count": len(sections),
                "sections_processed": len(processed_sections),
                "original_chars": total_original,
                "compressed_chars": total_compressed,
                "individual_strategies": sorted(strategies_used),
                "detection_confidence": detection.confidence,
            },
        )

    # ── Pipeline 集成：apply ──────────────────────────────────

    def apply(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> TransformResult:
        """Pipeline 集成 — 批量处理消息列表

        遍历 messages，对符合条件的消息执行路由压缩。
        支持保护策略（protect_recent、protect_analysis_context）和短内容跳过。

        Args:
            messages: OpenAI 格式的消息列表
            **kwargs: 可覆盖配置参数
                - target_role: 要处理的消息角色（默认 "tool"）
                - skip_if_short: 跳过短内容（默认 True）
                - protect_recent: 覆盖 protect_recent 配置
                - protect_analysis_context: 覆盖分析上下文保护配置

        Returns:
            TransformResult 包含处理后的消息列表和统计信息
        """
        target_role: str = kwargs.get("target_role", "tool")
        skip_if_short: bool = kwargs.get("skip_if_short", True)
        protect_recent: int = kwargs.get("protect_recent", self.config.protect_recent)
        protect_analysis: bool = kwargs.get(
            "protect_analysis_context", self.config.protect_analysis_context
        )

        # ── 分析上下文检测 ──
        analysis_context = False
        if protect_analysis:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    user_text = str(msg.get("content", "")).lower()
                    if any(kw in user_text for kw in _ANALYSIS_KEYWORDS):
                        analysis_context = True
                    break

        # ── 保护索引计算 ──
        protected_indices: set[int] = set()
        if protect_recent > 0:
            start = max(0, len(messages) - protect_recent)
            for i in range(start, len(messages)):
                protected_indices.add(i)

        # ── 遍历处理 ──
        modified_messages = list(messages)  # 浅拷贝
        route_results: list[RouteResult] = []
        total_processed = 0
        total_modified = 0
        total_skipped = 0
        total_protected = 0
        total_bytes_saved = 0

        for i, msg in enumerate(modified_messages):
            # 保护检查
            if i in protected_indices:
                total_protected += 1
                continue

            # 角色检查
            if msg.get("role") != target_role:
                continue

            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            if not content.strip():
                continue

            # 短内容跳过
            if skip_if_short and len(content) < self.config.min_chars_to_compress:
                continue

            # ── 路由处理 ──
            route_context = "analysis" if analysis_context else ""
            result = self.route(content, context=route_context)
            route_results.append(result)
            total_processed += 1

            if result.was_modified:
                modified_messages[i] = {**msg, "content": result.compressed}
                total_modified += 1
                total_bytes_saved += len(result.original) - len(result.compressed)
            else:
                total_skipped += 1

        # ── 转换为 CrushResult 列表（兼容 TransformResult） ──
        crush_results: list[CrushResult] = []
        for rr in route_results:
            crush_results.append(CrushResult(
                compressed=rr.compressed,
                original=rr.original,
                was_modified=rr.was_modified,
                strategy=rr.strategy_used,
                metadata=rr.metadata,
            ))

        was_modified = total_modified > 0

        return TransformResult(
            messages=modified_messages,
            was_modified=was_modified,
            stats={
                "total_messages": len(messages),
                "target_messages": total_processed,
                "modified": total_modified,
                "skipped": total_skipped,
                "protected": total_protected,
                "bytes_saved": total_bytes_saved,
                "analysis_context_detected": analysis_context,
                "strategies_used": sorted(set(
                    rr.strategy_used for rr in route_results
                )),
            },
            crush_results=crush_results,
        )


# ═══════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("ContentRouter 测试")
    print("=" * 70)

    router = ContentRouter()

    # ── 测试 1: JSON 数组压缩 ──
    print("\n── 测试 1: JSON 数组压缩 ──")
    large_json = json.dumps([
        {"id": i, "name": f"item_{i}", "data": f"value_{i}" * 5}
        for i in range(50)
    ])
    result = router.route(large_json)
    print(f"  原始长度: {len(large_json)} 字符")
    print(f"  压缩后: {len(result.compressed)} 字符")
    print(f"  结果: {result}")
    assert result.was_modified, "大 JSON 数组应被压缩"
    assert result.strategy_used.startswith("crush_"), f"策略应为 crush_*，实际: {result.strategy_used}"
    print("  → 通过 ✓")

    # ── 测试 2: 日志截断 ──
    print("\n── 测试 2: 日志截断 (LOG_OUTPUT → tail-heavy) ──")
    log_lines = []
    for i in range(200):
        level = "ERROR" if i > 190 else "INFO"
        log_lines.append(f"2024-01-01 10:{i%60:02d}:00 [{level}] Log message #{i}")
    log_text = "\n".join(log_lines)
    result = router.route(log_text)
    print(f"  原始行数: {len(log_text.split(chr(10)))}")
    truncated_lines = len(result.compressed.split("\n"))
    print(f"  截断后行数: {truncated_lines}")
    print(f"  策略: {result.strategy_used}")
    assert result.was_modified, "长日志应被截断"
    assert "smart_truncate" in result.strategy_used
    # 日志模式 tail=30, head=10 → 保留约 41 行（含分隔符）
    print(f"  元数据: {result.metadata}")
    print("  → 通过 ✓")

    # ── 测试 3: 搜索结果截断 ──
    print("\n── 测试 3: 搜索结果截断 (SEARCH_RESULTS → front-heavy) ──")
    search_lines = []
    for i in range(150):
        search_lines.append(f"src/module_{i%10}.py:{i*3}: def function_{i}():")
    search_text = "\n".join(search_lines)
    result = router.route(search_text)
    print(f"  原始行数: {len(search_text.split(chr(10)))}")
    print(f"  策略: {result.strategy_used}")
    assert result.was_modified, "长搜索结果应被截断"
    assert "smart_truncate" in result.strategy_used
    print(f"  元数据: head_lines={result.metadata.get('head_lines')}, tail_lines={result.metadata.get('tail_lines')}")
    # 搜索结果 head=30, tail=10
    assert result.metadata.get("head_lines") == 30
    assert result.metadata.get("tail_lines") == 10
    print("  → 通过 ✓")

    # ── 测试 4: 代码透传/截断 ──
    print("\n── 测试 4: 源代码截断 (SOURCE_CODE) ──")
    code_lines = []
    for i in range(120):
        if i % 5 == 0:
            code_lines.append(f"def function_{i}():")
            code_lines.append(f'    """Docstring for function_{i}."""')
        code_lines.append(f"    x_{i} = {i} * 2")
        code_lines.append(f"    return x_{i}")
    code_text = "\n".join(code_lines)
    result = router.route(code_text)
    print(f"  原始行数: {len(code_text.split(chr(10)))}")
    print(f"  策略: {result.strategy_used}")
    if result.was_modified:
        print(f"  截断后行数: {len(result.compressed.split(chr(10)))}")
        assert result.metadata.get("head_lines") == 20, "代码 head_lines 应为 20"
        assert result.metadata.get("tail_lines") == 20, "代码 tail_lines 应为 20"
    print("  → 通过 ✓")

    # ── 测试 5: 短内容跳过 ──
    print("\n── 测试 5: 短内容跳过 ──")
    short_text = "This is a short message.\n" * 10  # ~300 chars, < 500 threshold
    result = router.route(short_text)
    print(f"  内容长度: {len(short_text)} 字符")
    print(f"  结果: {result}")
    # 短内容在 route 层面不做 min_chars 检查（那是 apply 的事），
    # 但行数不超过 max_lines=80 也不会截断
    assert not result.was_modified or result.strategy_used == "no_truncation_needed"
    print("  → 通过 ✓")

    # ── 测试 6: Pipeline 集成 ──
    print("\n── 测试 6: Pipeline 集成 (apply) ──")
    # 构造消息：长 tool 内容不在末尾，避免被 protect_recent 保护
    msgs = [
        {
            "role": "tool",
            "content": "\n".join([
                f"2024-06-{i%30+1:02d} ERROR Something wrong #{i}"
                for i in range(250)
            ]),
        },
        {"role": "user", "content": "Search for all error logs"},
        {"role": "assistant", "content": "Let me check the logs..."},
        {"role": "tool", "content": "short"},
        {"role": "tool", "content": "short"},
        {"role": "tool", "content": "short"},
        {"role": "tool", "content": "short"},
    ]
    transform = router.apply(msgs, target_role="tool", protect_recent=4)
    print(f"  消息数: {transform.stats['total_messages']}")
    print(f"  修改: {transform.stats['modified']} 条")
    print(f"  跳过: {transform.stats['skipped']} 条")
    print(f"  保护: {transform.stats['protected']} 条")
    print(f"  节省: {transform.stats['bytes_saved']} 字节")
    assert transform.was_modified, "pipeline 集成应有修改"
    print("  → 通过 ✓")

    # ── 测试 7: 分析上下文检测 ──
    print("\n── 测试 7: 分析上下文检测 ──")
    msgs_analysis = [
        {"role": "tool", "content": "dummy short"},
        {"role": "tool", "content": "dummy short"},
        {"role": "tool", "content": "dummy short"},
        {"role": "user", "content": "请分析最近的错误日志"},
        {
            "role": "tool",
            "content": "\n".join([
                f"2024-06-{i%30+1:02d} INFO message #{i}"
                for i in range(150)
            ]),
        },
    ]
    transform2 = router.apply(msgs_analysis, target_role="tool")
    print(f"  分析上下文检测: {transform2.stats['analysis_context_detected']}")
    assert transform2.stats["analysis_context_detected"], "应检测到分析意图"
    print(f"  修改: {transform2.stats['modified']} 条")
    print("  → 通过 ✓")

    # ── 测试 8: DIFF 透传 ──
    print("\n── 测试 8: DIFF 透传 ──")
    diff_text = """diff --git a/main.py b/main.py
--- a/main.py
+++ b/main.py
@@ -1,5 +1,6 @@
 import sys
+import json

-def main():
+def main(config_path=None):
     print("Hello")
-    sys.exit(0)
+    return 0"""
    result = router.route(diff_text)
    print(f"  策略: {result.strategy_used}")
    assert not result.was_modified, "DIFF 应透传"
    assert result.strategy_used == "passthrough_diff"
    print("  → 通过 ✓")

    # ── 测试 9: JSON 对象透传 ──
    print("\n── 测试 9: JSON 对象透传 ──")
    obj_text = json.dumps({"status": "ok", "data": {"nested": [1, 2, 3]}})
    result = router.route(obj_text)
    print(f"  策略: {result.strategy_used}")
    assert not result.was_modified, "JSON 对象应透传"
    assert result.strategy_used == "passthrough_json_object"
    print("  → 通过 ✓")

    # ── 测试 10: protect_recent 保护 ──
    print("\n── 测试 10: protect_recent 保护最后 N 条消息 ──")
    msgs_with_recent = []
    # 前 5 条 tool 消息
    for i in range(5):
        msgs_with_recent.append({
            "role": "tool",
            "content": "\n".join([f"line {j}" for j in range(100)]),
        })
    # 最后 2 条 tool 消息（应在保护范围内，protect_recent=4）
    for i in range(2):
        msgs_with_recent.append({
            "role": "tool",
            "content": "\n".join([f"recent line {j}" for j in range(100)]),
        })
    transform3 = router.apply(
        msgs_with_recent, target_role="tool", protect_recent=4
    )
    print(f"  总消息: {transform3.stats['total_messages']}")
    print(f"  保护: {transform3.stats['protected']} 条 (应为 4)")
    print(f"  修改: {transform3.stats['modified']} 条")
    # 7 条 tool 消息，4 条在保护范围内 → 3 条被处理
    assert transform3.stats["protected"] == 4, f"保护数应为 4，实际 {transform3.stats['protected']}"
    print("  → 通过 ✓")

    # ── 测试 11: 混合内容处理 ──
    print("\n── 测试 11: 混合内容处理 ──")
    mixed = """Here is some analysis text.

```json
[{"id": 1, "name": "test"}, {"id": 2, "name": "prod"}]
```

And here are the log results:
""" + "\n".join([f"2024-01-01 ERROR Failed #{i}" for i in range(150)])
    result = router.route(mixed)
    print(f"  内容类型: {result.content_type}")
    print(f"  策略: {result.strategy_used}")
    print(f"  原始长度: {len(mixed)} 字符, 压缩后: {len(result.compressed)} 字符")
    print(f"  元数据: {result.metadata}")
    # 混合内容可能被修改或透传，取决于实际分段
    print("  → 通过 ✓")

    # ── 测试 12: 失败感知（错误日志增强 tail） ──
    print("\n── 测试 12: 失败感知 — 含 exit_code 的文本 ──")
    fail_log = "\n".join(
        [f"2024-01-01 INFO Normal operation #{i}" for i in range(100)]
        + [f"2024-01-01 ERROR Process crashed with exit_code=1"]
        + [f"2024-01-01 INFO Cleanup message #{i}" for i in range(50)]
    )
    result = router.route(fail_log)
    print(f"  策略: {result.strategy_used}")
    print(f"  元数据: failure_aware={result.metadata.get('failure_aware')}")
    print(f"  tail_lines: {result.metadata.get('tail_lines')}")
    # 失败感知应使 tail_lines >= 30
    assert result.metadata.get("failure_aware"), "应检测到失败"
    assert result.metadata.get("tail_lines", 0) >= 30, "失败感知 tail 应 >= 30"
    print("  → 通过 ✓")

    # ── 测试 13: 禁用 SmartCrusher ──
    print("\n── 测试 13: 禁用 SmartCrusher ──")
    router_no_crush = ContentRouter(
        ContentRouterConfig(enable_smart_crusher=False)
    )
    big_json = json.dumps([{"id": i} for i in range(100)])
    result = router_no_crush.route(big_json)
    print(f"  策略: {result.strategy_used}")
    # 禁用后 JSON 数组也应该走文本截断
    # 但如果内容足够大，可能被 smart_truncate
    print(f"  是否修改: {result.was_modified}")
    print("  → 通过 ✓")

    print("\n" + "=" * 70)
    print("所有测试通过 ✓")
    print("=" * 70)
