"""
content_detector.py — Headroom 式的智能内容类型检测

核心逻辑：
  输入一段文本 → 检测内容类型 → 返回 DetectionResult
  支持的类型: JSON / 代码 / 日志 / 搜索结果 / 纯文本

用法:
    >>> from content_detector import detect_content_type, ContentType
    >>> result = detect_content_type('{"key": "value"}')
    >>> result.content_type
    <ContentType.JSON_OBJECT: 'json_object'>
    >>> result.confidence
    0.95
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ContentType(str, Enum):
    """内容类型枚举"""

    JSON_ARRAY = "json_array"
    JSON_OBJECT = "json_object"
    SOURCE_CODE = "source_code"
    LOG_OUTPUT = "log_output"
    SEARCH_RESULTS = "search_results"
    DIFF_OUTPUT = "diff_output"
    PLAIN_TEXT = "plain_text"


@dataclass
class DetectionResult:
    """检测结果"""

    content_type: ContentType
    confidence: float  # 0.0 ~ 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.confidence > 0.5


# ─── 正则模式 ─────────────────────────────────────────────────

# JSON 行首检测
_JSON_OBJECT_START = re.compile(r"^\s*\{")
_JSON_ARRAY_START = re.compile(r"^\s*\[")

# 文件:行: 模式（grep/ripgrep 结果）
_SEARCH_RESULT_PATTERN = re.compile(r"^.+\.\w+:\d+:", re.MULTILINE)

# 日志级别标记
_LOG_LEVELS = {"INFO", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL", "DEBUG", "TRACE"}
_LOG_LINE_PATTERN = re.compile(
    r"^\s*(\d{4}[-/]\d{2}[-/]\d{2}"   # 日期开头: 2024-01-01
    r"|\d{2}:\d{2}:\d{2}"              # 时间开头: 14:30:00
    r"|\[(INFO|WARN|ERROR|DEBUG|FATAL|TRACE|CRITICAL)\]"  # [级别]
    r")",
    re.MULTILINE,
)

# 代码特征
_CODE_KEYWORDS = {
    "def ", "class ", "import ", "from ", "return ",
    "if __name__", "async def", "fn ", "func ", "pub fn",
    "func ", "function ", "var ", "let ", "const ",
    "package ", "package ", "using ", "namespace ",
}

# shebang
_SHEBANG_PATTERN = re.compile(r"^#!\s*\S+", re.MULTILINE)

# diff 标记
_DIFF_PATTERN = re.compile(r"^diff --git|^--- a/|^\+\+\+ b/|^@@ -\d+,\d+ +\d+,\d+ @@", re.MULTILINE)

# HTML 标记
_HTML_TAG_PATTERN = re.compile(r"^<(html|!DOCTYPE|div|span|table|head|body)", re.MULTILINE)


# ─── 检测函数 ─────────────────────────────────────────────────


def _is_json(content: str) -> DetectionResult | None:
    """尝试解析 JSON，返回检测结果或 None"""
    stripped = content.strip()
    if not stripped:
        return None

    # 快速行首检测（避免对大文本 try json.loads）
    first_line = stripped.split("\n", 1)[0].strip()
    is_obj = bool(_JSON_OBJECT_START.match(first_line))
    is_arr = bool(_JSON_ARRAY_START.match(first_line))

    if not is_obj and not is_arr:
        return None

    # 实际解析验证
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, RecursionError):
        return None

    if isinstance(parsed, list):
        return DetectionResult(
            content_type=ContentType.JSON_ARRAY,
            confidence=0.95,
            metadata={"length": len(parsed)},
        )
    elif isinstance(parsed, dict):
        return DetectionResult(
            content_type=ContentType.JSON_OBJECT,
            confidence=0.95,
            metadata={"keys": list(parsed.keys())},
        )
    return None


def _is_code(content: str) -> DetectionResult | None:
    """检测是否为源代码"""
    lines = content.split("\n")
    non_empty = [l.strip() for l in lines if l.strip()]
    if not non_empty:
        return None

    # 快速：含 shebang → 确定是代码
    if _SHEBANG_PATTERN.search(content):
        return DetectionResult(
            content_type=ContentType.SOURCE_CODE,
            confidence=0.98,
            metadata={"language": "detected_by_shebang"},
        )

    code_line_count = 0
    checked = min(len(non_empty), 30)

    for line in non_empty[:checked]:
        stripped = line.strip()
        # 代码关键词（strip 后匹配，兼容缩进）
        if any(stripped.startswith(kw) for kw in _CODE_KEYWORDS):
            code_line_count += 1

    code_ratio = code_line_count / checked if checked > 0 else 0

    if code_ratio >= 0.4:
        return DetectionResult(
            content_type=ContentType.SOURCE_CODE,
            confidence=min(0.95, 0.5 + code_ratio * 0.5),
            metadata={"code_line_ratio": code_ratio},
        )
    elif code_ratio >= 0.2:
        return DetectionResult(
            content_type=ContentType.SOURCE_CODE,
            confidence=0.6,
            metadata={"code_line_ratio": code_ratio, "borderline": True},
        )
    return None


def _is_log(content: str) -> DetectionResult | None:
    """检测是否为日志输出"""
    lines = content.split("\n")
    non_empty = [l.strip() for l in lines if l.strip()]
    if len(non_empty) < 3:
        return None

    checked = min(len(non_empty), 50)
    log_matches = 0

    for line in non_empty[:checked]:
        # 行首含日志级别
        first_token = line.strip().split()[0] if line.strip().split() else ""
        first_token_clean = first_token.strip("[]")
        if first_token_clean in _LOG_LEVELS:
            log_matches += 1
            continue
        # 日志行模式（时间/函数开头）
        if _LOG_LINE_PATTERN.search(line):
            log_matches += 1

    log_ratio = log_matches / checked if checked > 0 else 0

    if log_ratio >= 0.6:
        return DetectionResult(
            content_type=ContentType.LOG_OUTPUT,
            confidence=min(0.95, 0.5 + log_ratio * 0.5),
            metadata={"log_line_ratio": log_ratio},
        )
    elif log_ratio >= 0.3:
        return DetectionResult(
            content_type=ContentType.LOG_OUTPUT,
            confidence=0.55,
            metadata={"log_line_ratio": log_ratio, "borderline": True},
        )
    return None


def _is_diff(content: str) -> DetectionResult | None:
    """检测是否为 git diff"""
    if _DIFF_PATTERN.search(content):
        return DetectionResult(
            content_type=ContentType.DIFF_OUTPUT,
            confidence=0.95,
        )
    return None


def _is_search_result(content: str) -> DetectionResult | None:
    """检测是否为 grep/ripgrep 搜索结果"""
    lines = content.split("\n")
    non_empty = [l.strip() for l in lines if l.strip()]
    if len(non_empty) < 3:
        return None

    checked = min(len(non_empty), 30)
    matches = sum(1 for l in non_empty[:checked] if _SEARCH_RESULT_PATTERN.search(l))
    match_ratio = matches / checked if checked > 0 else 0

    if match_ratio >= 0.6:
        return DetectionResult(
            content_type=ContentType.SEARCH_RESULTS,
            confidence=min(0.95, 0.5 + match_ratio * 0.5),
            metadata={"search_line_ratio": match_ratio},
        )
    return None


def _is_html(content: str) -> DetectionResult | None:
    """检测是否为 HTML（兜底但标记）"""
    if _HTML_TAG_PATTERN.search(content):
        return DetectionResult(
            content_type=ContentType.PLAIN_TEXT,
            confidence=0.4,
            metadata={"html_detected": True, "note": "HTML 检测到但无专用压缩器，做纯文本处理"},
        )
    return None


# ─── 公共入口 ─────────────────────────────────────────────────


def detect_content_type(content: str) -> DetectionResult:
    """检测内容类型，按优先级返回最可能的类型

    检测顺序（高 → 低）：
        JSON → SOURCE_CODE → LOG → DIFF → SEARCH → HTML → PLAIN_TEXT
    """
    if not content or not content.strip():
        return DetectionResult(ContentType.PLAIN_TEXT, 0.0)

    # 按优先级依次检测，第一个高置信度的结果就是答案
    detectors = [
        ("json", _is_json),
        ("diff", _is_diff),
        ("code", _is_code),
        ("log", _is_log),
        ("search", _is_search_result),
        ("html", _is_html),
    ]

    for name, detector in detectors:
        result = detector(content)
        if result and result.confidence >= 0.6:
            return result

    # 兜底：对低置信度结果选最高分的
    best: DetectionResult | None = None
    for name, detector in detectors:
        result = detector(content)
        if result and (best is None or result.confidence > best.confidence):
            best = result

    if best and best.confidence > 0:
        return best

    return DetectionResult(ContentType.PLAIN_TEXT, 0.5)


# ─── 工具函数 ─────────────────────────────────────────────────


def is_mixed_content(content: str) -> bool:
    """检测是否为混合内容（含多种类型）"""
    indicators = {
        "has_json": bool(_JSON_OBJECT_START.search(content) or _JSON_ARRAY_START.search(content)),
        "has_code_fences": bool(re.search(r"^```\w*$", content, re.MULTILINE)),
        "has_log_lines": bool(_LOG_LINE_PATTERN.search(content)),
        "has_search_lines": bool(_SEARCH_RESULT_PATTERN.search(content)),
    }
    return sum(indicators.values()) >= 2


def split_into_sections(content: str) -> list[dict[str, Any]]:
    """将混合内容拆分为带类型的段落

    返回: [{"type": ContentType, "content": str, "metadata": {}}, ...]
    """
    # 简单实现：按 ``` 代码块和空行分段检测
    sections = []
    current_block: list[str] = []
    in_code_fence = False
    fence_language = ""

    for line in content.split("\n"):
        # 代码块边界
        fence_match = re.match(r"^```(\w*)", line)
        if fence_match is not None:
            if current_block:
                block = "\n".join(current_block)
                result = detect_content_type(block)
                sections.append({
                    "type": result.content_type,
                    "content": block,
                    "metadata": result.metadata,
                })
                current_block = []

            in_code_fence = not in_code_fence
            fence_language = fence_match.group(1) if in_code_fence else ""
            if fence_language:
                # 代码块本身也作为一个 section
                sections.append({
                    "type": ContentType.SOURCE_CODE,
                    "content": f"```{fence_language}",
                    "metadata": {"language": fence_language, "is_fence": True},
                })
            continue

        if in_code_fence:
            current_block.append(line)
            continue

        current_block.append(line)

    # 最后一段
    if current_block:
        block = "\n".join(current_block)
        if block.strip() or in_code_fence:
            # in_code_fence=True 表示 fence 未关闭 → 仍然作为代码段 flush
            result = detect_content_type(block) if not in_code_fence else DetectionResult(ContentType.SOURCE_CODE, 0.7, {"language": fence_language, "note": "unclosed_fence"})
            sections.append({
                "type": result.content_type,
                "content": block,
                "metadata": result.metadata,
            })

    return sections


# ─── 快速测试入口 ───────────────────────────────────────────

if __name__ == "__main__":
    test_cases = [
        ("JSON 数组", '[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]'),
        ("JSON 对象", '{"status": "ok", "code": 200}'),
        ("Python 代码", 'def hello():\n    """Say hello"""\n    print("hello world")'),
        ("日志", "2024-01-01 10:00:00 [INFO] Server started\n2024-01-01 10:00:01 [ERROR] DB timeout"),
        ("搜索结果", "src/main.py:42: def hello()\nsrc/utils.py:10: def helper()"),
        ("git diff", "diff --git a/main.py b/main.py\n--- a/main.py\n+++ b/main.py\n@@ -1,3 +1,4 @@"),
        ("纯文本", "Hello, this is a plain text message that doesn't match any special format."),
        ("混合内容", "Here is some text\n```python\ndef foo():\n    pass\n```\nAnd more text"),
    ]

    print("=" * 60)
    print("ContentDetector 测试结果")
    print("=" * 60)

    for name, content in test_cases:
        result = detect_content_type(content)
        print(f"\n📝 {name}")
        print(f"   → {result.content_type.value} (置信度: {result.confidence:.2f})")
        if result.metadata:
            print(f"     元数据: {result.metadata}")
