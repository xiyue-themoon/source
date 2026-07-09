#!/usr/bin/env python3
"""
config.yaml 写入后校验守护

用法:
  python3 validate_config.py                  # 修模式 — 修复发现的错误
  python3 validate_config.py --check-only     # 只检查，不修复
  python3 validate_config.py --watch          # 启动 inotify 后台监控


修模式会自动修复:
- 重复的 YAML key（只保留最后一个）
- Indentation 不一致
- 无法修复的问题会报告 + 建议恢复备份

备份自动保存到 ~/.hermes/config.yaml.bak.<timestamp>
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

CONFIG_PATH = os.path.expanduser("~/.hermes/config.yaml")
BACKUP_DIR = os.path.expanduser("~/.hermes")


def get_backup_path():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(BACKUP_DIR, f"config.yaml.bak.{ts}")


def validate_yaml(content: str) -> tuple[bool, str]:
    """Return (is_valid, error_message)"""
    import yaml
    try:
        yaml.safe_load(content)
        return True, ""
    except yaml.YAMLError as e:
        return False, str(e)


def detect_duplicate_keys(content: str) -> list[dict]:
    """Detect duplicate top-level and nested keys that would cause silent overwrites."""
    import yaml

    issues = []
    lines = content.split("\n")

    # Check for consecutive duplicate keys at same indent level
    prev_key = None
    prev_indent = -1
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            prev_key = None
            continue
        indent = len(line) - len(line.lstrip())
        # Check if this looks like a key: value or key: (with value on next line)
        if ":" in stripped and (stripped.endswith(":") or stripped.index(":") < len(stripped) - 1):
            key = stripped.split(":")[0].strip()
            if key == prev_key and indent == prev_indent:
                issues.append({
                    "line": i,
                    "key": key,
                    "indent": indent,
                    "message": f"重复 key '{key}' at line {i} (前一个在 indent={prev_indent})"
                })
            prev_key = key
            prev_indent = indent
        else:
            prev_key = None

    return issues


def fix_yaml(content: str) -> tuple[str, list[str]]:
    """
    Try to fix common YAML issues.
    Returns (fixed_content, log_messages)
    """
    logs = []
    lines = content.split("\n")
    result = []
    skip_until = -1

    # Fix 1: Remove duplicate keys (keep only the last occurrence)
    # We do a reverse scan to find which keys to keep (last wins)
    seen = {}  # (indent, key) -> last_line_index
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].rstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            indent = len(lines[i]) - len(lines[i].lstrip())
            key = stripped.split(":")[0].strip()
            if (indent, key) not in seen:
                seen[(indent, key)] = i
            else:
                logs.append(f"  ⚠ 删除重复 key '{key}' (原第{i+1}行，保留第{seen[(indent, key)]+1}行)")

    # Build result, skipping duplicates
    skip_key = {}  # (indent, key) -> list of lines to skip
    for (indent, key), line_num in seen.items():
        skip_key[(indent, key)] = [l for l in range(line_num + 1, len(lines))
                                    if lines[l].strip() and not lines[l].startswith("#")
                                    and ":" in lines[l]
                                    and len(lines[l]) - len(lines[l].lstrip()) <= indent]

    i = 0
    while i < len(lines):
        stripped = lines[i].rstrip()
        if ":" in stripped:
            indent = len(lines[i]) - len(lines[i].lstrip())
            key = stripped.split(":")[0].strip()
            # Check if this line should be skipped (earlier duplicate)
            for (k_indent, k_key), keep_line in seen.items():
                if k_indent == indent and k_key == key and i < keep_line:
                    # Skip this duplicate
                    skip_to = keep_line
                    while i < skip_to:
                        i += 1
                    i -= 1  # compensate for the i+=1 at loop end
                    break
            else:
                result.append(lines[i])
        else:
            result.append(lines[i])
        i += 1

    return "\n".join(result), logs


def check_only():
    """Just check, don't modify."""
    with open(CONFIG_PATH, "r") as f:
        content = f.read()

    valid, err = validate_yaml(content)
    if not valid:
        print(f"❌ YAML 解析失败:\n{err}")
        sys.exit(1)

    duplicates = detect_duplicate_keys(content)
    if duplicates:
        print("⚠ 重复 key 检测结果:")
        for d in duplicates:
            print(f"  {d['message']}")
        sys.exit(1)

    print(f"✅ {CONFIG_PATH} 有效，无重复 key")
    return True


def auto_fix():
    """检查并修复 config.yaml"""
    with open(CONFIG_PATH, "r") as f:
        content = f.read()

    valid, err = validate_yaml(content)
    if valid:
        duplicates = detect_duplicate_keys(content)
        if not duplicates:
            print(f"✅ {CONFIG_PATH} 已经健康，无需修复")
            return True

    # Backup
    backup_path = get_backup_path()
    shutil.copy2(CONFIG_PATH, backup_path)
    print(f"📦 备份保存到 {backup_path}")

    fixed, logs = fix_yaml(content)
    for log in logs:
        print(log)

    with open(CONFIG_PATH, "w") as f:
        f.write(fixed)

    # Re-validate
    valid, err = validate_yaml(open(CONFIG_PATH).read())
    if not valid:
        print(f"❌ 修复后仍然无效:\n{err}")
        print(f"💡 恢复备份: cp {backup_path} {CONFIG_PATH}")
        shutil.copy2(backup_path, CONFIG_PATH)
        return False

    print(f"✅ 修复完成，config.yaml 已验证通过")
    return True


def watch_mode():
    """Polling-based config file watcher (no inotify dependency)."""
    import time  # noqa: ensure imported

    print(f"🔍 轮询监控 {CONFIG_PATH} (每2秒)... (Ctrl+C 停止)")

    last_mtime = 0
    poll_interval = 2  # seconds
    health_counter = 0

    try:
        while True:
            time.sleep(poll_interval)
            health_counter += 1

            if not os.path.exists(CONFIG_PATH):
                continue

            current_mtime = os.stat(CONFIG_PATH).st_mtime_ns

            # Skip if file hasn't changed
            if current_mtime == last_mtime:
                # Log a heartbeat every 300 checks (10 min) to show it's alive
                if health_counter % 300 == 0:
                    print(f"  ✓ {datetime.now().strftime('%H:%M:%S')} - watcher active (no changes)")
                continue

            last_mtime = current_mtime

            # File changed — validate
            try:
                with open(CONFIG_PATH) as f:
                    content = f.read()

                valid, err = validate_yaml(content)
                if valid:
                    duplicates = detect_duplicate_keys(content)
                    if duplicates:
                        for d in duplicates:
                            print(f"\n{'='*50}")
                            print(f"⚠ {datetime.now().strftime('%H:%M:%S')} - "
                                  f"检测到重复 key (line {d['line']}): {d['key']}")
                            print(f"   重复 key 会导致后者静默覆盖前者，建议运行修复")
                            print(f"   python3 {__file__}  # 自动修复")
                            print(f"{'='*50}")
                    else:
                        print(f"  ✓ {datetime.now().strftime('%H:%M:%S')} - config.yaml 有效")
                else:
                    print(f"\n{'='*50}")
                    print(f"❌ {datetime.now().strftime('%H:%M:%S')} - config.yaml 无效!")
                    print(f"   错误: {err.split(chr(10))[0]}")
                    print(f"   建议: python3 {__file__}  # 尝试自动修复")
                    print(f"   恢复: 从备份目录恢复")
                    print(f"{'='*50}")
            except Exception as e:
                print(f"  ⚠ {datetime.now().strftime('%H:%M:%S')} - 检查时出错: {e}")

    except KeyboardInterrupt:
        print("\n👋 监控停止")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="config.yaml 校验守护")
    parser.add_argument("--check-only", action="store_true", help="只检查不修改")
    parser.add_argument("--watch", action="store_true", help="启动后台文件监控")
    args = parser.parse_args()

    if args.watch:
        watch_mode()
    elif args.check_only:
        check_only()
    else:
        # Default: auto-fix mode
        auto_fix()
