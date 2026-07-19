# [builder] system-diagnostics — Windows 系统诊断工具链

> **归属:** `[builder]` | Windows 11 专用，由 Builder 维护

## 组件

| 脚本 | 来源 skill | 用途 |
|:-----|:----------|:------|
| `triage-bsod.ps1` | windows-bsod-analysis | BSOD 一阶段排查：列出 minidump + BugCheck 事件 |
| `cdb-analyze.ps1` | windows-bsod-analysis | WinDbg (cdb) dump 分析 |
| `check-system-health.ps1` | windows-bsod-analysis | BSOD 后系统健康检查 |
| `post-reboot-check.ps1` | windows-bsod-analysis | 重启后验证 |
| `scan-pagedump64.py` | windows-bsod-analysis | 扫描 page dump 文件 |
| `verify-vbs-teardown.ps1` | windows-bsod-analysis | VBS 卸载验证 |
| `bsod-collect.ps1` | windows-crash-diagnostics | 收集 BSOD 事件日志 |
| `check-intel-io-drivers.ps1` | windows-crash-diagnostics | Intel IO 驱动检查 |
| `copy-minidump.ps1` | windows-crash-diagnostics | 复制 minidump |
| `health_check.ps1` | windows-system-audit | 全系统健康检查 |

## 依赖

- PowerShell 5.1+（内置于 Windows 11）
- WinDbg (cdb) — 可选，用于深度 dump 分析
