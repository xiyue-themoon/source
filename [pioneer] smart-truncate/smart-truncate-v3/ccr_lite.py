#!/usr/bin/env python3
"""
ccr_lite.py — 轻量级可逆压缩展开模块（CCR-lite）

在 SmartCrusher 压缩后，把被丢弃的原始条目存到本地存储。
需要时（或自动）展开 sentinel 标记，取回原始数据合并回结果。

存储后端：
  - dict（内存，默认） — 轻量，进程结束后丢失
  - sqlite3（持久）    — 跨会话保留，需显式指定

用法:
    >>> from ccr_lite import CCRStore, expand_sentinel
    >>> store = CCRStore(backend="dict")
    >>> # SmartCrusher 压缩时调用
    >>> store.put("hash123", [{"level": "ERROR", "msg": "..."}])
    >>> # 展开 sentinel
    >>> expanded = store.expand_sentinel(compressed_data)
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from typing import Any


# ─── Sentinel 标记常量 ─────────────────────────────────────────
# 与 smart_crusher.py 保持一致

CCR_SENTINEL_KEY = "__ccr_sentinel"
CCR_MARKER = "ccr_v1"


# ─── 工具函数 ──────────────────────────────────────────────────

def is_sentinel(item: Any) -> bool:
    """判断是否为 CCR sentinel 标记条目"""
    return isinstance(item, dict) and item.get(CCR_SENTINEL_KEY) is True


def get_sentinel_hash(item: dict) -> str | None:
    """从 sentinel 条目中提取 original_hash（如果有）"""
    # sentinel 可以带 hash，也可以不带（只做计数标记）
    return item.get("original_hash")


def count_sentinel_dropped(item: dict) -> int:
    """从 sentinel 条目中获取丢弃数量"""
    return item.get("dropped_count", 0)


# ─── CCRStore 存储 ────────────────────────────────────────────

class CCRStore:
    """CCR 轻量存储

    存储压缩时丢弃的原始条目，支持展开回流。

    Args:
        backend: "dict"（内存，默认）或 "sqlite"（持久）
        db_path: sqlite 模式下的数据库路径（默认临时文件）
    """

    def __init__(self, backend: str = "dict", db_path: str | None = None):
        self._backend = backend
        self._db_path = db_path
        self._dict_store: dict[str, list[dict]] = {}
        self._conn: sqlite3.Connection | None = None

        if backend == "sqlite":
            path = db_path or os.path.join(tempfile.gettempdir(), "ccr_store.db")
            self._db_path = path
            self._conn = sqlite3.connect(path)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS ccr_store "
                "(hash_key TEXT PRIMARY KEY, data TEXT)"
            )
            self._conn.commit()

    def put(self, key: str, data: list[dict]) -> None:
        """存储原始条目

        Args:
            key: hash 键（如 compute_item_hash 的结果）
            data: 被丢弃的原始条目列表
        """
        if self._backend == "sqlite" and self._conn:
            try:
                serialized = json.dumps(data, ensure_ascii=False, default=str)
            except (TypeError, ValueError, RecursionError):
                serialized = json.dumps({"__ccr_unserializable": True, "keys": list(data[0].keys()) if data else []})
            self._conn.execute(
                "INSERT OR REPLACE INTO ccr_store (hash_key, data) VALUES (?, ?)",
                (key, serialized),
            )
            self._conn.commit()
        else:
            self._dict_store[key] = data

    def get(self, key: str) -> list[dict] | None:
        """取回原始条目

        Args:
            key: hash 键

        Returns:
            原始条目列表，不存在返回 None
        """
        if self._backend == "sqlite" and self._conn:
            row = self._conn.execute(
                "SELECT data FROM ccr_store WHERE hash_key = ?", (key,)
            ).fetchone()
            if row:
                return json.loads(row[0])
            return None
        else:
            return self._dict_store.get(key)

    def expand_sentinel(self, compressed: list[dict]) -> list[dict]:
        """展开压缩结果中的 sentinel 标记

        遍历 compressed 列表，遇到 __ccr_sentinel 标记时：
        - 如果有 original_hash，从 store 取回原始数据替换 sentinel
        - 如果没有 hash（纯计数标记），插入占位条目

        Args:
            compressed: 含 sentinel 的压缩结果（JSON 数组）

        Returns:
            展开后的完整数据（sentinel 被原始数据替换）
        """
        result: list[dict] = []
        expanded_count = 0

        for item in compressed:
            if not is_sentinel(item):
                result.append(item)
                continue

            # 尝试展开 sentinel
            hash_key = get_sentinel_hash(item)
            if hash_key:
                batch_data = self.get(hash_key)
                if batch_data and isinstance(batch_data, list):
                    # batch_data = [{"indices": [...], "hashes": [...]}]
                    if batch_data and "hashes" in batch_data[0]:
                        # batch key → 逐条取回原始数据
                        all_originals: list[dict] = []
                        for entry in batch_data:
                            for h in entry.get("hashes", []):
                                original = self.get(h)
                                if original:
                                    all_originals.extend(original)
                        if all_originals:
                            result.extend(all_originals)
                            expanded_count += 1
                            continue
                    else:
                        # 直接存了原始数据
                        result.extend(batch_data)
                        expanded_count += 1
                        continue

            # 无法展开：保留 sentinel 或插入占位
            # 插入一个提示条目，表示这部分数据被压缩了
            result.append({
                "_ccr_placeholder": True,
                "note": f"{count_sentinel_dropped(item)} items compressed",
                "original_hash": hash_key,
            })

        return result

    def clear(self) -> None:
        """清空所有存储"""
        if self._backend == "sqlite" and self._conn:
            self._conn.execute("DELETE FROM ccr_store")
            self._conn.commit()
        else:
            self._dict_store.clear()

    @property
    def size(self) -> int:
        """当前存储的条目数"""
        if self._backend == "sqlite" and self._conn:
            row = self._conn.execute("SELECT COUNT(*) FROM ccr_store").fetchone()
            return row[0] if row else 0
        return len(self._dict_store)

    @property
    def keys(self) -> list[str]:
        """所有存储的 key 列表"""
        if self._backend == "sqlite" and self._conn:
            rows = self._conn.execute("SELECT hash_key FROM ccr_store").fetchall()
            return [r[0] for r in rows]
        return list(self._dict_store.keys())

    def close(self) -> None:
        """关闭 sqlite 连接"""
        if self._conn:
            self._conn.close()
            self._conn = None


# ─── 全局单例（方便跨模块共享） ──────────────────────────────

_default_store: CCRStore | None = None


def get_default_store() -> CCRStore:
    """获取全局默认 CCRStore 实例"""
    global _default_store
    if _default_store is None:
        _default_store = CCRStore(backend="dict")
    return _default_store


def reset_default_store() -> None:
    """重置全局默认 CCRStore"""
    global _default_store
    _default_store = None


# ─── 便捷函数 ──────────────────────────────────────────────────

def expand_sentinel(compressed: list[dict], store: CCRStore | None = None) -> list[dict]:
    """展开 sentinel 的便捷函数

    用法:
        >>> from ccr_lite import expand_sentinel
        >>> expanded = expand_sentinel(compressed_data)
    """
    s = store or get_default_store()
    return s.expand_sentinel(compressed)


def store_dropped_items(
    all_items: list[dict],
    kept_indices: set[int],
    store: CCRStore | None = None,
    key_prefix: str = "auto",
) -> dict[int, str]:
    """存储被 SmartCrusher 丢弃的条目

    在锚点选择之后、压缩输出之前调用。
    对每个被丢弃的条目计算 hash 并存入 CCRStore。

    Args:
        all_items: 压缩前的完整条目列表
        kept_indices: 被保留的锚点索引集合
        store: CCRStore 实例（默认使用全局单例）
        key_prefix: hash key 的前缀

    Returns:
        {index: hash_key} 映射，供后续 sentinel 引用
    """
    s = store or get_default_store()
    dropped_map: dict[int, str] = {}

    for idx, item in enumerate(all_items):
        if idx in kept_indices:
            continue
        # 计算 hash key
        try:
            serialized = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError, RecursionError):
            serialized = str(item)
        hash_key = f"{key_prefix}_{hashlib.md5(serialized.encode()).hexdigest()[:16]}"

        # 按 hash 分组存储（相同内容的丢弃条目存一起）
        existing = s.get(hash_key)
        if existing:
            if item not in existing:
                existing.append(item)
                s.put(hash_key, existing)
        else:
            s.put(hash_key, [item])

        dropped_map[idx] = hash_key

    return dropped_map


# ─── 测试用例 ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("CCR-lite 测试")
    print("=" * 60)

    # 测试 1: 基本存储和取回
    print("\n📋 测试 1: 基本存储和取回")
    store = CCRStore(backend="dict")
    store.put("hash_abc", [{"level": "ERROR", "msg": "DB timeout"}])
    data = store.get("hash_abc")
    print(f"  存入→取回: {data} ✅" if data else "  ❌")

    # 测试 2: sentinel 展开
    print("\n📋 测试 2: sentinel 展开")
    store.put("hash_def", [{"level": "INFO", "msg": "line 1"}, {"level": "WARN", "msg": "line 2"}])
    compressed = [
        {"id": 1, "msg": "kept item"},
        {"__ccr_sentinel": True, "original_hash": "hash_def", "dropped_count": 2},
        {"id": 3, "msg": "another kept"},
    ]
    expanded = store.expand_sentinel(compressed)
    print(f"  3 条(含 sentinel) → {len(expanded)} 条")
    for item in expanded:
        print(f"    {item}")
    print("  ✅" if len(expanded) == 4 else "  ❌")

    # 测试 3: store_dropped_items 便捷函数
    print("\n📋 测试 3: store_dropped_items")
    items = [{"id": i, "val": f"x{i}"} for i in range(5)]
    kept = {0, 4}  # 只保留首尾
    dropped_map = store_dropped_items(items, kept, store, key_prefix="test")
    print(f"  丢弃 {len(dropped_map)} 条, 存储 {store.size} 个 key")
    print(f"  dropped_map: {dropped_map}")
    # 验证取回
    for idx, h in dropped_map.items():
        retrieved = store.get(h)
        print(f"  [{idx}] {h}: {retrieved}")
    print("  ✅")

    # 测试 4: sqlite 后端
    print("\n📋 测试 4: sqlite 后端")
    db_path = os.path.join(tempfile.gettempdir(), "test_ccr.db")
    sql_store = CCRStore(backend="sqlite", db_path=db_path)
    sql_store.put("test_key", [{"msg": "sqlite test"}])
    sql_data = sql_store.get("test_key")
    print(f"  sqlite 存入→取回: {sql_data} ✅" if sql_data else "  ❌")
    sql_store.close()
    # 清理
    try:
        os.unlink(db_path)
    except OSError:
        pass

    # 测试 5: 空 sentinel 处理
    print("\n📋 测试 5: 空 sentinel 展开")
    sentinel_only = [{"__ccr_sentinel": True, "dropped_count": 5, "original_hash": None}]
    expanded = store.expand_sentinel(sentinel_only)
    print(f"  1 sentinel → {len(expanded)} 条 (应为占位)")

    # 测试 6: 全局单例
    print("\n📋 测试 6: 全局单例")
    from ccr_lite import get_default_store
    s1 = get_default_store()
    s2 = get_default_store()
    print(f"  s1 is s2: {s1 is s2} ✅" if s1 is s2 else "  ❌")

    print("\n✅ 全部完成")
