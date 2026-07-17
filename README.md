# Source — 生产代码仓库

> 供 Pioneer / Builder Agent 客户端查阅和部署。
> 笔记和知识管理请移步 [`xiyue-themoon/hermes-notes`](https://github.com/xiyue-themoon/hermes-notes) 📚

## 项目目录

| 目录 | 归属 | 说明 | 状态 |
|:-----|:----:|:-----|:----:|
| `vision2model` | pioneer | 图像→3D 测量管线 | ✅ 交付 |
| `system-scripts` | pioneer | 计费/自学习/配置监控等 | ✅ 活跃 |
| `smart-truncate` | pioneer | Token 压缩工具 | ✅ 存档 |
| `system-scripts` | shared | 偏差防护脚本 | ✅ 活跃 |
| `qw3` | shared | 多 Agent 协作 FIFO 框架 | ✅ 活跃 |
| `qw3-bridge` | builder | qw3 通信桥接 (604+133行) | ✅ 活跃 |
| `memory-scorer` | shared | 自学习系统评分代理 (351行) | ✅ 活跃 |
| `pioneer-comm` | builder | Builder→Pioneer 通信 (46行) | ✅ 活跃 |
| `quality-tools` | shared | SOUL 自检 + 清单校验 (201行) | ✅ 活跃 |
| `win-toolkit` | builder | Windows 工具脚本 (78行) | ✅ 活跃 |
| `paper-toolchain` | shared | 论文写作工具链 (pandoc/xelatex/biber + CI) | ✅ 交付 |
| `paper-toolchain` | builder | 论文实例 (Mendel→Mamba, make verify ✅) | ✅ 交付 |

## 规范

- 前缀 `[pioneer]` / `[builder]` / `[shared]` 区分维护归属
- 每个项目含独立 README 和依赖声明
- 提交格式：`{type}: [归属] 描述`
- 废弃直接 `git rm -r`，git history 会记住
