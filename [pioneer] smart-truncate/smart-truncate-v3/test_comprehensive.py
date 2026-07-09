#!/usr/bin/env python3
"""smart-truncate v3 完整压缩测试 + 回归验证"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from content_router import ContentRouter

router = ContentRouter()
print("=" * 60)
print("📊 smart-truncate v3 压缩测试报告")
print("=" * 60)

# ── 测试 1: JSON 日志压缩 ──
print("\n1️⃣ JSON 日志工具输出压缩")
logs = []
for i in range(60):
    if i == 3:
        logs.append({"level": "FATAL", "msg": "OOM killer triggered, process 1234 killed", "pid": 1234})
    elif i == 15:
        logs.append({"level": "ERROR", "msg": "DB connection pool exhausted after 30s timeout", "pid": 5678})
    elif i == 28:
        logs.append({"level": "ERROR", "msg": "Disk I/O error on /dev/sda1", "pid": 9012})
    elif i == 42:
        logs.append({"level": "CRITICAL", "msg": "Out of memory: killed process nginx", "pid": 3456})
    elif i % 3 == 0:
        logs.append({"level": "INFO", "msg": f"Request processed in {i*5}ms", "pid": 1000+i})
    elif i % 3 == 1:
        logs.append({"level": "WARN", "msg": f"Memory usage at {50+i}%", "pid": 1000+i})
    else:
        logs.append({"level": "INFO", "msg": "Health check passed", "pid": 1000+i})

content = json.dumps(logs)
orig_n = len(logs)
orig_c = len(content)

result = router.route(content)
kept = json.loads(result.compressed)
real = [x for x in kept if not x.get("__ccr_sentinel") and not x.get("_ccr_placeholder")]
new_c = len(result.compressed)

errors_kept = sum(1 for x in real if x.get("level") in ("ERROR","FATAL","CRITICAL"))
total_err = sum(1 for x in logs if x.get("level") in ("ERROR","FATAL","CRITICAL"))

print(f"  原始: {orig_n} 条, {orig_c} 字符")
print(f"  压缩: {len(real)} 条, {new_c} 字符")
print(f"  省: {orig_c - new_c} 字符 ({100 - 100*new_c//orig_c}%)")
print(f"  ERROR/CRITICAL: {errors_kept}/{total_err} 保留 ({100*errors_kept//total_err if total_err else 0}%)")
print(f"  策略: {result.strategy_used}")

# ── 测试 2: 文本日志 ──
print("\n2️⃣ 文本日志截断")
lines = []
for i in range(200):
    level = "ERROR" if i % 7 == 0 else "WARN" if i % 13 == 0 else "INFO"
    lines.append(f"2024-01-01 10:00:{i:02d} [{level}] line {i}")
text = "\n".join(lines)
orig_n2 = len(lines)
orig_c2 = len(text)

result = router.route(text)
new_n2 = len(result.compressed.splitlines())
new_c2 = len(result.compressed)

print(f"  原始: {orig_n2} 行, {orig_c2} 字符")
print(f"  压缩: {new_n2} 行, {new_c2} 字符")
print(f"  省: {orig_c2 - new_c2} 字符 ({100 - 100*new_c2//orig_c2}%)")
print(f"  策略: {result.strategy_used}")

# ── 测试 3: Python 代码 ──
print("\n3️⃣ Python 代码压缩")
code = '''import os
import sys
import json
from pathlib import Path
from pathlib import PurePath

def calculate_average(data):
    """Calculate the average of a list of numbers.

    Args:
        data: List of numeric values

    Returns:
        The arithmetic mean of the input values
    """
    # TODO: handle empty list case
    if not data:
        return 0
    total = sum(data)
    count = len(data)
    return total / count


class DataProcessor:
    """Processes and analyzes data sets."""
    def __init__(self, config_path):
        # FIXME: validate config_path exists
        self.config_path = config_path
        self.data = []

    def load(self):
        """Load data from the configured path."""
        pass
'''
result = router.route(code)
orig_c3 = len(code)
new_c3 = len(result.compressed)
print(f"  原始: {orig_c3} 字符")
print(f"  压缩: {new_c3} 字符")
print(f"  省: {orig_c3 - new_c3} 字符 ({100 - 100*new_c3//orig_c3}%)")
print(f"  策略: {result.strategy_used}")

# ── 测试 4: Pipeline 集成 ──
print("\n4️⃣ Pipeline 集成 (10 条消息, protect_recent=2)")
msgs = [
    {"role": "system", "content": "You are a DevOps assistant."},
    {"role": "user", "content": "检查服务器日志"},
]
for j in range(4):
    logs = [{"level": "ERROR" if i%5==0 else "INFO", "msg": f"event_{j}_{i}", "pid": i}
            for i in range(30)]
    msgs.append({"role": "tool", "content": json.dumps(logs)})
    msgs.append({"role": "assistant", "content": f"检查结果: 发现 {j} 个问题"})

import time
t0 = time.perf_counter()
pipe_result = router.apply(msgs, protect_recent=2)
dt = (time.perf_counter() - t0) * 1000

total_orig = sum(len(m.get("content","")) for m in msgs if m["role"]=="tool")
total_new = sum(len(m.get("content","")) for m in pipe_result.messages if m["role"]=="tool")

print(f"  耗时: {dt:.1f}ms")
print(f"  tool 消息: {pipe_result.stats.get('target_messages', 0)} 条")
print(f"  压缩: {pipe_result.stats.get('crushed', 0)} 条")
print(f"  省 bytes: {pipe_result.stats.get('bytes_saved', 0)}")
print(f"  tool 总字符: {total_orig} → {total_new}")

# ── 测试 5: 性能 ──
print("\n5️⃣ 性能: 大数组 1000 条")
big = [{"level": "INFO" if i%10 else "ERROR", "msg": f"x{i}"} for i in range(1000)]
t0 = time.perf_counter()
for _ in range(3):
    router.route(json.dumps(big))
dt = (time.perf_counter() - t0) / 3 * 1000
result = router.route(json.dumps(big))
kept = json.loads(result.compressed)
real = [x for x in kept if not x.get("__ccr_sentinel")]
print(f"  平均: {dt:.1f}ms | 1000→{len(real)} 条 | 策略: {result.strategy_used}")

print("\n" + "=" * 60)
print("✅ 全部测试完成")
