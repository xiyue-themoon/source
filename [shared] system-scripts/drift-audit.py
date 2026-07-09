#!/usr/bin/env python3
"""
drift-audit.py — 设计意图 vs 实际配置对照工具

三级分层：
  🔴 Must Match   — 偏差即告警，非预期值直接报 CRITICAL
  🟡 Track Trend  — 偏差不告警，报告趋势变化
  🟢 Free Drift   — 不追踪，仅罗列已知自由漂移项

用法：
  python3 ~/.hermes/scripts/drift-audit.py
  python3 ~/.hermes/scripts/drift-audit.py --json          # JSON 输出（供 cron 消费）
  python3 ~/.hermes/scripts/drift-audit.py --quiet         # 仅输出偏差项
  python3 ~/.hermes/scripts/drift-audit.py --init          # 用当前 config 生成初始 schema
"""

import os
import sys
import json
import yaml
import subprocess
from datetime import date

# ── 路径 ──────────────────────────────────────────────────
CONFIG_PATH = os.path.expanduser("~/.hermes/config.yaml")
INTENT_PATH = os.path.expanduser("~/.hermes/design-intent.yaml")

# ── YAML 路径解析器 ──────────────────────────────────────

def resolve_path(data, path_str):
    """按点号路径从嵌套 dict 中取值。
    支持: 'model.provider', 'fallback_providers.0.provider'
    返回 (value, found_bool)
    """
    parts = path_str.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                return None, False
        elif isinstance(current, list):
            try:
                idx = int(part)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None, False
            except ValueError:
                return None, False
        else:
            return None, False
    return current, True


def get_nested(data, path_str):
    val, found = resolve_path(data, path_str)
    return val


def flatten_dict(d, parent_key="", sep="."):
    """将嵌套 dict 展平为 { 'a.b.c': value }"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    items.extend(flatten_dict(item, f"{new_key}{sep}{i}", sep=sep).items())
                else:
                    items.append((f"{new_key}{sep}{i}", item))
        else:
            items.append((new_key, v))
    return dict(items)


# ── Shell 验证器 ──────────────────────────────────────────

SHELL_CHECKS = {
    "which_trash-put": 'command -v trash-put >/dev/null 2>&1 && echo "present" || echo "absent"',
    "rm_alias_set": 'bash -c "source ~/.bashrc 2>/dev/null; alias rm 2>/dev/null | grep -q trash && echo present || echo absent"',
    "gateway_active": 'systemctl --user is-active hermes-gateway.service >/dev/null 2>&1 && echo "active" || echo "inactive"',
    "config_watcher_alive": 'kill -0 $(cat ~/.hermes/run/validate_watcher.pid 2>/dev/null) 2>/dev/null && echo "running" || echo "dead"',
}


def run_shell_check(check_name):
    cmd = SHELL_CHECKS.get(check_name)
    if not cmd:
        return "unknown"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return "error"


# ── 主逻辑 ────────────────────────────────────────────────

def load_yaml(path):
    if not os.path.exists(path):
        print(f"❌ 文件不存在: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r") as f:
        return yaml.safe_load(f)


def generate_initial_schema(config_path, intent_path):
    """--init 模式：用当前 config.yaml 的全部 flatten 键生成初始意图"""
    config = load_yaml(config_path)
    flat = flatten_dict(config)
    print(f"# design-intent.yaml 草稿 — 自动生成于 {date.today()}")
    print("# 请手动将条目分类到 🔴/🟡/🟢 层级")
    print(f"version: 1")
    print(f"last_updated: '{date.today()}'")
    print("")
    print("🔴_must_match:")
    print("  # TODO: 将安全关键项移到这里")
    print("")
    print("🟡_track_trend:")
    for key in sorted(flat.keys()):
        val = flat[key]
        if isinstance(val, str) and val:
            print(f"  - path: \"{key}\"")
            print(f"    expected: \"{val}\"")
            print(f"    acceptable: [\"{val}\"]")
            print(f"    reason: \"TODO: 填写理由\"")
            print("")
    print("🟢_free_drift:")
    print("  # TODO: 标记不需要追踪的项")


def audit(config_data, intent_data):
    results = {
        "🔴": {"total": 0, "match": 0, "mismatch": 0, "items": []},
        "🟡": {"total": 0, "match": 0, "mismatch": 0, "items": [], "trends": []},
        "🟢": {"total": 0, "items": []},
    }

    for tier_key, tier_label in [("🔴_must_match", "🔴"), ("🟡_track_trend", "🟡"), ("🟢_free_drift", "🟢")]:
        tier_data = intent_data.get(tier_key, [])
        for entry in tier_data:
            if tier_label == "🟢":
                results[tier_label]["total"] += 1
                results[tier_label]["items"].append(entry)
                continue

            path = entry.get("path", "")
            expected = entry.get("expected", "")
            acceptable = entry.get("acceptable", [expected]) if entry.get("acceptable") else [expected]
            reason = entry.get("reason", "")

            # 获取实际值
            if path.startswith("!shell:"):
                check_name = path.replace("!shell:", "")
                actual = run_shell_check(check_name)
            else:
                actual = get_nested(config_data, path)
                actual = str(actual) if actual is not None else None

            # 判断是否匹配
            actual_str = str(actual) if actual is not None else "❓ not_found"
            is_match = actual_str in acceptable

            item = {
                "path": path,
                "expected": expected,
                "acceptable": acceptable,
                "actual": actual_str,
                "match": is_match,
                "reason": reason,
            }
            results[tier_label]["total"] += 1
            results[tier_label]["items"].append(item)

            if is_match:
                results[tier_label]["match"] += 1
            else:
                results[tier_label]["mismatch"] += 1
                if tier_label == "🟡":
                    # 记录趋势变化
                    results[tier_label]["trends"].append({
                        "path": path,
                        "expected": expected,
                        "actual": actual_str,
                        "acceptable": acceptable,
                    })

    return results


def format_report(results, intent_data=None):
    if intent_data is None:
        intent_data = {}
    lines = []
    lines.append(f"📊 设计偏差月报 — {date.today()}")
    lines.append("")

    # 摘要
    r = results["🔴"]
    y = results["🟡"]
    lines.append(f"━━━ 摘要 ━━━")
    lines.append(f"  🔴 安全层: {r['match']}/{r['total']} 匹配")
    lines.append(f"  🟡 核心路由: {y['match']}/{y['total']} 匹配 | {len(y['trends'])} 项趋势偏移")
    lines.append(f"  🟢 自由漂移: {results['🟢']['total']} 项已知")
    lines.append("")

    # 🔴 偏差详情
    mismatches = [i for i in r["items"] if not i["match"]]
    if mismatches:
        lines.append(f"━━━ 🔴 关键偏差 (需立即处理) ━━━")
        for item in mismatches:
            lines.append(f"  ⚠ {item['path']}")
            lines.append(f"    期望: {item['expected']}")
            lines.append(f"    当前: {item['actual']}")
            lines.append(f"    理由: {item['reason']}")
            lines.append("")
    else:
        lines.append("━━━ 🔴 关键偏差 — 无 ━━━")
        lines.append("")

    # 🟡 趋势
    if y["trends"]:
        lines.append(f"━━━ 🟡 趋势偏移 ━━━")
        for t in y["trends"]:
            lines.append(f"  ↻ {t['path']}")
            lines.append(f"    期望: {t['expected']} | 当前: {t['actual']}")
            lines.append(f"    可接受: {', '.join(t['acceptable'])}")
            lines.append("")
    else:
        lines.append("━━━ 🟡 趋势偏移 — 无 ━━━")
        lines.append("")

    # 🟢 自由漂移
    if results["🟢"]["items"]:
        lines.append(f"━━━ 🟢 自由漂移 (不追踪) ━━━")
        for item in results["🟢"]["items"]:
            desc = item.get("description", item.get("path", "?"))
            note = item.get("note", "")
            lines.append(f"  · {desc}")
            if note:
                lines.append(f"    📝 {note}")
        lines.append("")

    # 完整匹配清单（仅 🔴 🟡）
    lines.append("━━━ ✅ 匹配项 ━━━")
    for tier_label in ["🔴", "🟡"]:
        for item in results[tier_label]["items"]:
            if item["match"]:
                path = item["path"]
                val = item["actual"]
                lines.append(f"  ✅ {tier_label} {path} = {val}")
    lines.append("")

    # 变更日志
    cl = intent_data.get("change_log", [])
    if cl:
        lines.append("━━━ 变更历史 ━━━")
        for entry in cl:
            lines.append(f"  [{entry.get('date','')}] {entry.get('description','')}")
            for dev in entry.get("known_deviations", []):
                lines.append(f"    ↳ {dev}")
        lines.append("")

    return "\n".join(lines)


def format_json(results):
    """JSON 输出 — 供 cron 或外部工具消费"""
    return json.dumps(results, ensure_ascii=False, indent=2)


def main():
    # 解析参数
    args = set(sys.argv[1:])
    if "--init" in args:
        generate_initial_schema(CONFIG_PATH, INTENT_PATH)
        return

    # 加载数据
    config = load_yaml(CONFIG_PATH)
    intent = load_yaml(INTENT_PATH)

    quiet = "--quiet" in args
    json_mode = "--json" in args

    # 运行审计
    results = audit(config, intent)

    # 输出
    if json_mode:
        print(format_json(results))
    elif quiet:
        # 仅输出偏差项
        for item in results["🔴"]["items"]:
            if not item["match"]:
                print(f"🔴 {item['path']}: 期望={item['expected']}, 当前={item['actual']}")
        for item in results["🟡"]["items"]:
            if not item["match"]:
                print(f"🟡 {item['path']}: 期望={item['expected']}, 当前={item['actual']}")
    else:
        print(format_report(results, intent))

    # exit code
    if results["🔴"]["mismatch"] > 0:
        sys.exit(2)  # 有关键偏差
    elif results["🟡"]["mismatch"] > 0:
        sys.exit(1)  # 有趋势偏移
    else:
        sys.exit(0)  # 完全匹配


if __name__ == "__main__":
    main()
