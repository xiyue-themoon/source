# win-toolkit — Windows 工具脚本

> 归属: `[builder]` | 子系统: 工具链

## 文件

| 文件 | 行数 | 功能 |
|:-----|:----:|:------|
| `gh-raw-win.sh` | 50 | 从 GitHub 原始 URL 下载文件（Win/Git Bash） |
| `git-credential-gh.sh` | 28 | Git 凭据辅助脚本 |

## 依赖

- Git Bash (MSYS2)
- curl

## 部署

```bash
cp gh-raw-win.sh git-credential-gh.sh ~/.hermes/scripts/
```
