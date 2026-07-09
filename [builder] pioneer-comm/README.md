# pioneer-comm — Builder→Pioneer 通信工具

> 归属: `[builder]` | 子系统: Pioneer 通信

## 文件

| 文件 | 行数 | 功能 |
|:-----|:----:|:------|
| `call_pioneer.py` | 46 | SSH 调用 Pioneer CLI，传递消息 |

## 依赖

- Python 3.11+
- SSH 密钥配置
- TencentCloud 主机可达 (43.139.75.69:22)

## 部署

```bash
cp call_pioneer.py ~/.hermes/scripts/
```
