#!/usr/bin/env python3
"""深度自动审查 v2"""
import ast, os, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
errors = []

def log(ok, msg):
    icon = "✅" if ok else "❌"
    print(f"  {icon} {msg}")

# 1. 语法
print("═══ 1. 语法检查 ═══")
for f in ["content_detector.py","anchor_selector.py","smart_crusher.py",
           "content_router.py","code_compressor.py","ccr_lite.py"]:
    p = os.path.join(ROOT, f)
    if not os.path.exists(p):
        errors.append(f"缺失: {f}"); log(False, f); continue
    with open(p) as fh:
        try: ast.parse(fh.read()); log(True, f)
        except SyntaxError as e: errors.append(f"语法 {f}: {e}"); log(False, f)

if errors: print("\n❌ 语法错误"); [print(f"  {e}") for e in errors]; sys.exit(1)

# 2. 联合导入
print("\n═══ 2. 联合导入 ═══")
try:
    import content_detector, anchor_selector, ccr_lite, code_compressor, smart_crusher, content_router
    log(True, f"6/6 模块导入成功")
    for m in [content_detector, anchor_selector, ccr_lite, code_compressor, smart_crusher, content_router]:
        log(True, f"  {m.__name__}.py")
except Exception as e:
    errors.append(f"导入: {e}"); log(False, str(e)[:100])

# 3. 接口
print("\n═══ 3. 接口检查 ═══")
checks = [
    (content_detector, ["detect_content_type","ContentType","DetectionResult","is_mixed_content","split_into_sections"]),
    (anchor_selector,  ["AnchorSelector","DataPattern","AnchorConfig","BatchScorer","compute_item_hash"]),
    (smart_crusher,    ["SmartCrusher","SmartCrusherConfig","CrushResult","TransformResult","detect_pattern"]),
    (content_router,   ["ContentRouter","ContentRouterConfig","smart_truncate","RouteResult"]),
    (code_compressor,  ["PythonCodeCompressor","compress_python"]),
    (ccr_lite,         ["CCRStore","expand_sentinel","store_dropped_items","get_default_store","CCR_SENTINEL_KEY"]),
]
all_ok = True
for mod, names in checks:
    for n in names:
        if not hasattr(mod, n):
            errors.append(f"接口: {mod.__name__}.{n}"); all_ok = False
log(all_ok, "全部接口完整" if all_ok else f"缺失 {len(errors)} 个接口")

# 4. 运行自测
print("\n═══ 4. 模块自测 ═══")
tests = [
    ("anchor_selector", lambda: anchor_selector.AnchorSelector().select_anchors([{"x":i} for i in range(20)],5,anchor_selector.DataPattern.GENERIC)),
    ("smart_crusher", lambda: smart_crusher.SmartCrusher()),
    ("ccr_lite", lambda: ccr_lite.CCRStore(backend="dict")),
    ("code_compressor", lambda: code_compressor.compress_python("x=1")),
]
all_ok = True
for name, fn in tests:
    try: fn(); log(True, name)
    except Exception as e: errors.append(f"自测 {name}: {e}"); log(False, f"{name}: {e}"); all_ok = False
if all_ok: log(True, "全部自测通过")

# 5. 综合测试
print("\n═══ 5. 综合测试 ═══")
r = subprocess.run([sys.executable, os.path.join(ROOT,"test_comprehensive.py")],
                   capture_output=True, text=True, timeout=30)
if r.returncode == 0:
    for line in r.stdout.split("\n"):
        s = line.strip()
        if not s or "═" in s: continue
        print(f"  {s}" if not s.startswith("  ") else s)
    log(True, "综合测试通过")
else:
    errors.append(f"综合测试: exit={r.returncode}")
    log(False, f"exit={r.returncode}")
    print(r.stderr[:500])

# 6. 报告
print(f"\n═══ 最终 ═══")
if errors:
    print(f"❌ {len(errors)} 个问题:")
    for e in errors: print(f"  {e}")
    sys.exit(1)
else:
    print("✅ 全部通过 — 0 问题")
    sys.exit(0)
