# quality-tools — SOUL 自检 + 清单校验

> 归属: `[shared]` | 子系统: 系统完整性

## 文件

| 文件 | 行数 | 功能 |
|:-----|:----:|:------|
| `soul-selfcheck.sh` | 107 | SOUL.md 行为规则自检（18 项检查） |
| `manifest-check.sh` | 94 | 项目清单一致性校验 |

## 依赖

- Git Bash (MSYS2)
- 无第三方依赖

## 部署

```bash
cp soul-selfcheck.sh manifest-check.sh ~/.hermes/scripts/
```
