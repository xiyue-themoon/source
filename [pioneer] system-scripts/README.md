# [pioneer] system-scripts

Pioneer 侧 Hermes 子系统脚本合集。每个脚本对应一个子系统，作为代码参考存档。

## 文件清单

| 脚本 | 行数 | 对应子系统 | 说明 |
|:-----|:----:|:-----------|:-----|
| `billing.py` | 567 | 计费系统 | API token 计费追踪 — 日志解析+缓存+交叉验证 |
| `memory-scorer.py` | 349 | 自学习系统 | 记忆评分 — §格式解析+自动评分+淘汰 |
| `validate_config.py` | 268 | 配置监控 | config.yaml 合法性与完整性校验 |
| `auto-heal.sh` | 80 | 自愈子系统 | 自动修复 — 进程/网关/连接异常检测 |
| `snapshot.sh` | 54 | 快照备份 | 系统快照 — 配置/状态/关键文件备份 |
| `notes-sync.sh` | 23 | 笔记同步 | 笔记库 Git 自动同步 |
| `health-check.sh` | 65 | 安全与部署 | 系统健康检查 — 资源/网络/服务 |
| `safe-exec.sh` | 67 | 安全与部署 | 安全执行包装器 — 幂等+回滚+审计 |
| `gh-raw.sh` | 67 | 安全与部署 | GitHub raw 内容代理 — 绕过网络限制 |

**归属:** Pioneer

**注意:** 这些脚本强依赖 Hermes 环境（路径/config/state），不可直接部署，仅作参考存档。
