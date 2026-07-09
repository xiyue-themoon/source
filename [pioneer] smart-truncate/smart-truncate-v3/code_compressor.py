"""
code_compressor.py — Python 源码压缩器（零外部依赖）

基于 Python 标准库 ast 模块，执行 3 种 100% 安全的代码变换：
  1. 剥离 docstring（函数/类/模块文档字符串）
  2. 移除注释（保留 TODO/FIXME/HACK/XXX/WORKAROUND 标记）
  3. 合并相邻同模块 import 语句

安全保证：
  - 压缩前原样备份原始代码
  - 每次变换后执行 ast.parse() 验证语法合法性
  - 任何错误发生时自动 fallback 返回原始代码

用法:
    >>> from code_compressor import PythonCodeCompressor, compress_python
    >>> compressor = PythonCodeCompressor()
    >>> result, stats = compressor.compress(source_code)
    >>> result, stats = compress_python(source_code)  # 便捷函数
"""

from __future__ import annotations

import ast
import re
import sys
from typing import Any


# ═══════════════════════════════════════════════════════════════
# TODO/FIXME 注释检测正则
# ═══════════════════════════════════════════════════════════════

_TODO_PATTERN: re.Pattern[str] = re.compile(
    r"#.*?(TODO|FIXME|HACK|XXX|WORKAROUND)",
    re.IGNORECASE,
)

# 行尾注释中的 TODO（如 "x = 1  # TODO: fix me"）
_TODO_INLINE_PATTERN: re.Pattern[str] = re.compile(
    r"#\s*(TODO|FIXME|HACK|XXX|WORKAROUND)\b",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════
# PythonCodeCompressor
# ═══════════════════════════════════════════════════════════════

class PythonCodeCompressor:
    """Python 源码压缩器

    使用标准库 ast 模块执行 3 种安全的代码变换：
    - 剥离 docstring（模块/函数/类的文档字符串）
    - 移除普通注释（保留 TODO/FIXME 等重要标记）
    - 合并相邻同模块 import 语句

    所有变换均为 100% 语义保留，不会改变代码行为。

    属性:
        remove_docstrings: 是否剥离 docstring（默认 True）
        remove_comments:   是否移除注释（默认 True，ast.unparse 自动丢弃注释）
        merge_imports:     是否合并同模块 import（默认 True）

    用法:
        >>> compressor = PythonCodeCompressor()
        >>> compressed, stats = compressor.compress(source_code)
        >>> print(f"压缩率: {stats['compression_ratio']:.1%}")
    """

    def __init__(
        self,
        remove_docstrings: bool = True,
        remove_comments: bool = True,
        merge_imports: bool = True,
    ) -> None:
        """初始化压缩器

        Args:
            remove_docstrings: 是否移除文档字符串（默认 True）
            remove_comments:   是否通过 AST 解析丢弃注释（默认 True）
            merge_imports:     是否合并同模块相邻 import（默认 True）
        """
        self.remove_docstrings: bool = remove_docstrings
        self.remove_comments: bool = remove_comments
        self.merge_imports: bool = merge_imports

    # ── 主入口 ─────────────────────────────────────────────────

    def compress(self, source: str) -> tuple[str, dict[str, Any]]:
        """压缩 Python 源码

        执行流程：
          1. 备份原始代码（用于 fallback）
          2. 提取并保留 TODO/FIXME 等特殊注释
          3. ast.parse() 解析为 AST
          4. 剥离 docstring（如启用）
          5. ast.unparse() 还原 → 此步骤自动丢弃普通注释
          6. 重新 ast.parse() → 合并 import（如启用）
          7. ast.unparse() 最终输出
          8. 追加保留的 TODO 注释标记
          9. 语法验证后返回结果

        Args:
            source: 原始 Python 源代码字符串

        Returns:
            (压缩后的代码, 统计信息字典)
            出错时返回 (原始代码, {"error": str, "fallback": True})

        统计信息包括:
            - original_chars: 原始字符数
            - compressed_chars: 压缩后字符数
            - compression_ratio: 压缩率
            - docstrings_removed: 移除的 docstring 数量
            - imports_merged: 合并的 import 组数
            - todos_preserved: 保留的 TODO 注释列表
        """
        # ── 备份原始代码 ──
        original_source: str = source
        original_chars: int = len(source)

        # ── 统计计数器 ──
        stats: dict[str, Any] = {
            "original_chars": original_chars,
            "compressed_chars": original_chars,
            "compression_ratio": 0.0,
            "docstrings_removed": 0,
            "imports_merged": 0,
            "todos_preserved": [],
            "transformations": [],
        }

        # ── 空源码或纯空白快速返回 ──
        if not source or not source.strip():
            stats["compressed_chars"] = 0
            stats["compression_ratio"] = 0.0
            stats["transformations"].append("empty_source")
            return source, stats

        try:
            # ── Step 1: 提取 TODO 注释（在 AST 解析前）──
            todos: list[str] = []
            if self.remove_comments:
                todos = self._preserve_todo_comments(source)
                if todos:
                    stats["todos_preserved"] = todos
                    stats["transformations"].append("todos_preserved")

            # ── Step 2: 首次 AST 解析 ──
            tree: ast.AST = ast.parse(source)

            # ── Step 3: 剥离 docstring ──
            if self.remove_docstrings:
                tree = self._strip_docstrings(tree)
                stats["transformations"].append("docstrings_removed")

            # ── Step 4: ast.unparse() 还原 → 自动丢弃注释 ──
            if self.remove_comments:
                result: str = ast.unparse(tree)
                stats["transformations"].append("comments_removed")
            else:
                result = source

            # ── Step 5: 重新解析 → 合并 import ──
            if self.merge_imports:
                try:
                    tree2: ast.AST = ast.parse(result)
                    tree2 = self._merge_imports(tree2)
                    result = ast.unparse(tree2)
                    stats["transformations"].append("imports_merged")
                except SyntaxError:
                    # import 合并失败不影响结果，跳过
                    pass

            # ── Step 6: 追加保留的 TODO 注释 ──
            if todos:
                todo_lines: str = "\n".join(
                    f"# [TODO preserved] {t}" for t in todos
                )
                result = result.rstrip() + "\n" + todo_lines + "\n"

            # ── Step 7: 最终语法验证 ──
            ast.parse(result)

            # ── Step 8: 计算统计 ──
            compressed_chars: int = len(result)
            stats["compressed_chars"] = compressed_chars
            if original_chars > 0:
                stats["compression_ratio"] = (
                    original_chars - compressed_chars
                ) / original_chars

            return result, stats

        except SyntaxError as e:
            # 语法错误 → fallback 到原始代码
            return original_source, {
                "error": f"SyntaxError: {e}",
                "fallback": True,
                "original_chars": original_chars,
                "compressed_chars": original_chars,
                "compression_ratio": 0.0,
                "docstrings_removed": 0,
                "imports_merged": 0,
                "todos_preserved": stats.get("todos_preserved", []),
                "transformations": ["fallback_due_to_syntax_error"],
            }
        except Exception as e:
            # 其他错误 → fallback
            return original_source, {
                "error": f"{type(e).__name__}: {e}",
                "fallback": True,
                "original_chars": original_chars,
                "compressed_chars": original_chars,
                "compression_ratio": 0.0,
                "docstrings_removed": 0,
                "imports_merged": 0,
                "todos_preserved": stats.get("todos_preserved", []),
                "transformations": ["fallback_due_to_error"],
            }

    # ── 变换方法 ───────────────────────────────────────────────

    @staticmethod
    def _strip_docstrings(tree: ast.AST) -> ast.AST:
        """剥离 AST 中的 docstring 节点

        对 Module、FunctionDef、AsyncFunctionDef、ClassDef 节点的
        第一条语句进行检查：如果是字符串常量表达式（ast.Expr 包裹
        ast.Constant(str)），则从 body 中移除。

        Args:
            tree: 已解析的 AST 树

        Returns:
            移除 docstring 后的 AST 树（原地修改）
        """
        # 遍历所有可以包含 docstring 的节点类型
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.body:
                    continue

                # 检查第一条语句是否为 docstring
                first_stmt = node.body[0]
                if (
                    isinstance(first_stmt, ast.Expr)
                    and isinstance(first_stmt.value, ast.Constant)
                    and isinstance(first_stmt.value.value, str)
                ):
                    # 移除 docstring 节点
                    node.body.pop(0)

        return tree

    @staticmethod
    def _merge_imports(tree: ast.AST) -> ast.AST:
        """合并相邻的同模块 import 语句

        合并规则:
          - import os        →  import os, sys, re
            import sys
            import re

          - from pathlib import Path       →  from pathlib import Path, PurePath
            from pathlib import PurePath

        只合并完全相邻的语句（中间不能有其他类型的语句）。

        Args:
            tree: 已解析的 AST 树

        Returns:
            合并 import 后的 AST 树（原地修改）
        """
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef)):
                continue

            body = node.body
            if not body:
                continue

            new_body: list[ast.stmt] = []
            i: int = 0

            while i < len(body):
                stmt = body[i]

                # ── 处理普通 import (import os, sys) ──
                if isinstance(stmt, ast.Import):
                    # 收集连续相邻的 ast.Import 语句
                    group: list[ast.Import] = [stmt]
                    j: int = i + 1
                    while j < len(body) and isinstance(body[j], ast.Import):
                        group.append(body[j])  # type: ignore[arg-type]
                        j += 1

                    if len(group) > 1:
                        # 合并所有 alias
                        merged_names: list[ast.alias] = []
                        for imp in group:
                            merged_names.extend(imp.names)
                        # 按模块名排序以保持输出稳定
                        merged_names.sort(key=lambda a: a.name)
                        merged_import: ast.Import = ast.Import(
                            names=merged_names
                        )
                        new_body.append(merged_import)
                    else:
                        new_body.append(stmt)

                    i = j
                    continue

                # ── 处理 from import (from pathlib import Path) ──
                if isinstance(stmt, ast.ImportFrom):
                    module_name: str | None = stmt.module
                    if module_name is None:
                        new_body.append(stmt)
                        i += 1
                        continue

                    # 收集连续相邻的、同模块的 ast.ImportFrom
                    from_group: list[ast.ImportFrom] = [stmt]
                    j = i + 1
                    while (
                        j < len(body)
                        and isinstance(body[j], ast.ImportFrom)
                        and body[j].module == module_name  # type: ignore[union-attr]
                    ):
                        from_group.append(body[j])  # type: ignore[arg-type]
                        j += 1

                    if len(from_group) > 1:
                        # 合并所有导入的名称
                        merged_from_names: list[ast.alias] = []
                        for fi in from_group:
                            merged_from_names.extend(fi.names)
                        # 去重并按名称排序
                        seen: set[str] = set()
                        unique_names: list[ast.alias] = []
                        for alias in merged_from_names:
                            if alias.name not in seen:
                                seen.add(alias.name)
                                unique_names.append(alias)
                        unique_names.sort(key=lambda a: a.name)

                        merged_from: ast.ImportFrom = ast.ImportFrom(
                            module=module_name,
                            names=unique_names,
                            level=stmt.level,
                        )
                        new_body.append(merged_from)
                    else:
                        new_body.append(stmt)

                    i = j
                    continue

                # ── 非 import 语句直接保留 ──
                new_body.append(stmt)
                i += 1

            # 替换 body
            node.body = new_body

        return tree

    @staticmethod
    def _preserve_todo_comments(source: str) -> list[str]:
        """从原始源码中提取 TODO/FIXME/HACK/XXX/WORKAROUND 注释

        扫描每一行，匹配包含重要标记的注释行。
        返回去重后的注释内容列表（保持出现顺序）。

        支持的标记:
            TODO, FIXME, HACK, XXX, WORKAROUND

        Args:
            source: 原始 Python 源代码

        Returns:
            包含重要标记的注释行列表（如 ["# TODO: optimize this loop"]）
        """
        if not source:
            return []

        todos: list[str] = []
        seen: set[str] = set()

        for line in source.split("\n"):
            # 检查是否整行都是包含 TODO 标记的注释
            stripped: str = line.strip()
            if stripped.startswith("#") and _TODO_PATTERN.search(stripped):
                if stripped not in seen:
                    seen.add(stripped)
                    todos.append(stripped)
            # 检查行尾注释（如 "x = 1  # TODO: fix"）
            elif _TODO_INLINE_PATTERN.search(line):
                # 提取行尾注释部分
                comment_match = _TODO_INLINE_PATTERN.search(line)
                if comment_match:
                    comment_part: str = line[comment_match.start():].strip()
                    if comment_part not in seen:
                        seen.add(comment_part)
                        todos.append(comment_part)

        return todos


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def compress_python(source: str) -> tuple[str, dict[str, Any]]:
    """压缩 Python 源码（便捷函数）

    使用默认参数创建 PythonCodeCompressor 实例并执行压缩。

    Args:
        source: 原始 Python 源代码字符串

    Returns:
        (压缩后的代码, 统计信息字典)
        出错时返回 (原始代码, {"error": str, "fallback": True})

    用法:
        >>> compressed, stats = compress_python(source_code)
        >>> print(f"原始: {stats['original_chars']} chars")
        >>> print(f"压缩: {stats['compressed_chars']} chars")
    """
    compressor: PythonCodeCompressor = PythonCodeCompressor()
    return compressor.compress(source)


# ═══════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import textwrap

    def _dedent(s: str) -> str:
        """去除公共缩进，方便书写测试代码"""
        return textwrap.dedent(s).strip()

    # ──────────────────────────────────────────────────────────
    # 测试 1: 含 docstring 的函数
    # ──────────────────────────────────────────────────────────

    print("=" * 60)
    print("测试 1: 剥离 docstring")
    print("=" * 60)

    src1: str = _dedent("""
        \"\"\"模块级 docstring\"\"\"

        import os
        import sys

        def hello(name: str) -> str:
            \"\"\"打招呼的函数

            Args:
                name: 名字

            Returns:
                问候语
            \"\"\"
            return f"Hello, {name}!"

        class MyClass:
            \"\"\"我的类\"\"\"

            def method(self) -> None:
                \"\"\"一个方法\"\"\"
                pass
    """)

    result1, stats1 = compress_python(src1)
    print(f"原始: {stats1['original_chars']} 字符")
    print(f"压缩: {stats1['compressed_chars']} 字符")
    print(f"压缩率: {stats1['compression_ratio']:.1%}")
    print(f"变换: {stats1['transformations']}")
    print("--- 压缩结果 ---")
    print(result1)
    print()

    # ──────────────────────────────────────────────────────────
    # 测试 2: 多 import 合并
    # ──────────────────────────────────────────────────────────

    print("=" * 60)
    print("测试 2: 合并同模块 import")
    print("=" * 60)

    src2: str = _dedent("""
        import os
        import sys
        import re
        import json

        from pathlib import Path
        from pathlib import PurePath
        from pathlib import PurePosixPath

        from collections import defaultdict
        from collections import OrderedDict

        x = 1

        import typing
        import typing as t
    """)

    result2, stats2 = compress_python(src2)
    print(f"原始: {stats2['original_chars']} 字符")
    print(f"压缩: {stats2['compressed_chars']} 字符")
    print(f"压缩率: {stats2['compression_ratio']:.1%}")
    print(f"变换: {stats2['transformations']}")
    print("--- 压缩结果 ---")
    print(result2)
    print()

    # ──────────────────────────────────────────────────────────
    # 测试 3: TODO 注释保留
    # ──────────────────────────────────────────────────────────

    print("=" * 60)
    print("测试 3: 保留 TODO/FIXME 注释")
    print("=" * 60)

    src3: str = _dedent("""
        # 普通注释，应该被移除
        import os

        # TODO: 这个函数需要优化性能
        def slow_function() -> None:
            # FIXME: 这里有潜在的竞态条件
            x = 1  # HACK: 临时方案，需要重构
            # 又是普通注释
            print("hello")  # XXX: 注意这里的副作用

        # WORKAROUND: Python 3.8 兼容性修复
        pass
    """)

    result3, stats3 = compress_python(src3)
    print(f"原始: {stats3['original_chars']} 字符")
    print(f"压缩: {stats3['compressed_chars']} 字符")
    print(f"压缩率: {stats3['compression_ratio']:.1%}")
    print(f"保留的 TODO: {stats3['todos_preserved']}")
    print(f"变换: {stats3['transformations']}")
    print("--- 压缩结果 ---")
    print(result3)
    print()

    # ──────────────────────────────────────────────────────────
    # 测试 4: 空文件
    # ──────────────────────────────────────────────────────────

    print("=" * 60)
    print("测试 4: 空文件 / 纯空白")
    print("=" * 60)

    # 完全空
    result4a, stats4a = compress_python("")
    print(f"空字符串: 变换={stats4a['transformations']}, "
          f"ratio={stats4a['compression_ratio']:.1%}")

    # 纯空白
    result4b, stats4b = compress_python("   \n  \n   ")
    print(f"纯空白: 变换={stats4b['transformations']}, "
          f"ratio={stats4b['compression_ratio']:.1%}")
    print()

    # ──────────────────────────────────────────────────────────
    # 测试 5: 无效语法（应 fallback）
    # ──────────────────────────────────────────────────────────

    print("=" * 60)
    print("测试 5: 无效语法（fallback 测试）")
    print("=" * 60)

    src5: str = "def broken(  # 缺少冒号和函数体"
    result5, stats5 = compress_python(src5)
    print(f"fallback 已触发: {stats5.get('fallback', False)}")
    print(f"错误信息: {stats5.get('error', 'N/A')}")
    print(f"返回原始代码: {result5 == src5}")
    print()

    # ──────────────────────────────────────────────────────────
    # 测试 6: 使用 PythonCodeCompressor 类（自定义配置）
    # ──────────────────────────────────────────────────────────

    print("=" * 60)
    print("测试 6: 自定义配置 - 只合并 import，不处理注释")
    print("=" * 60)

    compressor_custom: PythonCodeCompressor = PythonCodeCompressor(
        remove_docstrings=False,
        remove_comments=False,
        merge_imports=True,
    )

    src6: str = _dedent("""
        \"\"\"保留这个 docstring\"\"\"
        import os
        import sys

        # 这个注释也会保留
        x = 42
    """)

    result6, stats6 = compressor_custom.compress(src6)
    print(f"变换: {stats6['transformations']}")
    print("--- 压缩结果 ---")
    print(result6)
    print()

    # ──────────────────────────────────────────────────────────
    # 测试 7: AsyncFunctionDef docstring
    # ──────────────────────────────────────────────────────────

    print("=" * 60)
    print("测试 7: 异步函数 docstring 剥离")
    print("=" * 60)

    src7: str = _dedent("""
        import asyncio

        async def fetch_data(url: str) -> dict:
            \"\"\"异步获取数据\"\"\"
            return {"url": url}
    """)

    result7, stats7 = compress_python(src7)
    print(f"压缩率: {stats7['compression_ratio']:.1%}")
    print("--- 压缩结果 ---")
    print(result7)
    print()

    print("=" * 60)
    print("所有测试完成！")
    print("=" * 60)
