# qw3-bridge — Builder 侧 qw3 通信桥接

> 归属: `[builder]` | 子系统: qw3 消息总线

## 文件

| 文件 | 行数 | 功能 |
|:-----|:----:|:------|
| `qw3v3.py` | 604 | qw3 协议实现：FIFO 读写、心跳、重连 |
| `qw.py` | 133 | CLI 封装：单条消息发送/接收 |

## 依赖

- Python 3.11+
- 无第三方包（仅 stdlib）

## 部署

```bash
cp qw3v3.py ~/.hermes/scripts/
cp qw.py ~/.hermes/scripts/
```
