# Source — 生产代码仓库

> 供 Pioneer / Builder Agent 客户端查阅和部署。
> 笔记和知识管理请移步 [`xiyue-themoon/hermes-notes`](https://github.com/xiyue-themoon/hermes-notes) 📚

## 项目目录

| 目录（含归属前缀） | 归属 | 说明 | 状态 |
|:-------------------|:----:|:-----|:----:|
| `[pioneer] vision2model` | pioneer | 图像→3D 测量管线 | ✅ 交付 |
| `[pioneer] system-scripts` | pioneer | 计费/自学习/配置监控等 | ✅ 活跃 |
| `[pioneer] smart-truncate` | pioneer | Token 压缩工具 v3 | ✅ 存档 |
| `[shared] system-scripts` | shared | 偏差防护 + 健康监控 | ✅ 活跃 |
| `[shared] qw3` | shared | 多 Agent 协作 FIFO 框架 | ✅ 活跃 |
| `[shared] memory-scorer` | shared | 自学习系统评分代理 | ✅ 活跃 |
| `[shared] quality-tools` | shared | SOUL 自检 + 清单校验 | ✅ 活跃 |
| `[shared] paper-toolchain` | shared | 论文写作工具链（模板/脚本/示例） | ✅ 交付 |
| `[shared] note-tools` | shared | 笔记库维护扫描脚本 | ✅ 新 |
| `[builder] qw3-bridge` | builder | qw3 通信桥接 | ✅ 活跃 |
| `[builder] pioneer-comm` | builder | Builder→Pioneer 通信 | ✅ 活跃 |
| `[builder] win-toolkit` | builder | Windows 工具脚本 | ✅ 活跃 |
| `[builder] system-diagnostics` | builder | BSOD 诊断 + 健康检查（10 脚本） | ✅ 新 |

## 规范

- 前缀 `[pioneer]` / `[builder]` / `[shared]` 区分维护归属
- 每个项目含独立 README 和依赖声明
- 提交格式：`{type}: [归属] 描述`
- 废弃直接 `git rm -r`，git history 会记住

## 防重复规则（依据 source skill §十一）

- 新工具链组件优先入 `[shared]`，仅在 Windows 专用时入 `[builder]`
- 加新文件前先 `ls -d "\[*\] 同名项目/"` 检查是否已有规范版
- 发现 `[builder]` + `[shared]` 同名重复时 → 合并到 `[shared]`，废弃 `[builder]`
- skill 脚本入库遵循：Windows 诊断 → `[builder] system-diagnostics`，笔记维护 → `[shared] note-tools`，工具链附属 → 对应项目 `scripts/`
