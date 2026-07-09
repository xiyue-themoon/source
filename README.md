# Source — 生产代码仓库

> 供 Pioneer / Builder Agent 客户端查阅和部署。
> 笔记和知识管理请移步 [`xiyue-themoon/hermes-notes`](https://github.com/xiyue-themoon/hermes-notes) 📚

## 项目目录

| 目录 | 说明 | 状态 |
|:-----|:-----|:----:|
| `[pioneer] vision2model` | 图像→3D 测量管线 | ✅ 交付 |
| `[pioneer] system-scripts` | Hermes 子系统脚本（计费/自学习/配置监控等） | ✅ 存档 |
| `[pioneer] smart-truncate` | Token 压缩工具 | ✅ 存档 |
| `[shared] system-scripts` | Shared 子系统脚本（偏差防护） | ✅ 存档 |
| `[shared] qw3` | 多 Agent 协作 FIFO 框架 | ✅ 存档 |

## 规范

- 每个项目一个独立子目录，含独立的 README 和依赖声明
- 已完成的项目归档不删，保留完整 git 历史
- Agent 直接 `git clone` 或 `git pull` 即可部署
