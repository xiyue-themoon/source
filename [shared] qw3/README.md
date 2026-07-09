# [shared] qw3

qw3 多 Agent 协作框架 — FIFO 管道通信系统。

## 文件清单

| 脚本 | 行数 | 说明 |
|:-----|:----:|:-----|
| `qw3-listener.py` | 167 | FIFO 管道监听器 — 持续读取 /tmp/qw3-in 分发任务 |
| `qw3-sender.py` | 140 | FIFO 管道发送器 — 写入 /tmp/qw3-out 返回结果 |
| `qw3-fifo-health.sh` | 40 | FIFO 管道健康检查 — 检测管道是否存在/可读写 |
| `setup-fifo.sh` | 28 | FIFO 管道初始化 — 创建 /tmp/qw3-{in,out} 命名管道 |

**归属:** Shared

**架构:** 三阶段状态机 + 阶段锁 + FIFO 管道 + 意图拆分

**注意:** 依赖 Linux 命名管道和特定目录结构，不可直接部署。
