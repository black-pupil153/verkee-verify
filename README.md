# AI Verify

> 给你的 AI API 装一个监控摄像头

CLI 工具：以**被动监控为主、反侦测主动探测为辅**，检测中转站偷换模型、质量下滑，以及官方模型降智。支持 OpenAI / Anthropic / GLM。

## 核心能力

| 能力 | 说明 |
|------|------|
| 智力打分看板 | `ai-verify score` 给当前渠道打分，可常驻刷新 |
| 透明代理 | 拦截真实流量，支持 SSE 流式，旁路落库 + 异常报警 |
| 反侦测探针 | 中英自然对话题池，随机抽样与参数扰动，降低被墙概率 |
| 多模型 | OpenAI / Anthropic / GLM（智谱）及 OpenAI 兼容中转 |
| 定时巡检 | `monitor start` 周期性打分，异常时 Webhook 通知 |
| 历史与周报 | `history` / `report` 看趋势与降级 |

## 安装

```bash
cd ai-verify
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

可选 ML 指纹（重依赖）：`pip install -e ".[ml]"`

## 快速验证效果

### 1. 单元测试（不耗 API）

```bash
pytest
```

### 2. 配置你的渠道

```bash
ai-verify config init
ai-verify config set base_url https://你的中转或官方/v1
ai-verify config set api_key sk-xxx
ai-verify config set model claude-sonnet-4.6   # 或 gpt-4o / glm-4.6
ai-verify config list
```

GLM 官方示例：

```bash
ai-verify config set base_url https://open.bigmodel.cn/api/paas/v4
ai-verify config set api_key 你的智谱key
ai-verify config set model glm-4.6
```

### 3. 主动验证（会消耗少量 token）

```bash
# 快速：指纹 + 安全 + 少量质量题
ai-verify check

# 完整：更多探针 + 质量题
ai-verify check --full --probes 8 --questions 10
```

### 4. 智力打分看板

```bash
ai-verify score              # 打一次分并展示
ai-verify score --board      # 只看历史，不发请求
ai-verify score --watch --interval 30m   # 常驻刷新
```

## 用 Claude Code + CC Switch（推荐）

`ai-verify` 会自动读 `~/.cc-switch/` 里**当前选中的供应商**，不用再手动 `config set`。

```bash
# 看看读到了什么
ai-verify providers list
ai-verify providers current

# 一条命令开 Claude Code（自动走当前 CC Switch 渠道 + 本地监控）
ai-verify run -- claude

# 直接测当前渠道
ai-verify check
ai-verify score
```

在 CC Switch 里切换供应商后，下次 `run` / `check` / `score` 会自动跟上。

代理日志：`~/.ai-verify/logs/proxy.log`  
调用记录：`ai-verify history --last 1d`

### 6. 定时巡检与报告

```bash
ai-verify monitor start --interval 6h
ai-verify report --period weekly
```

### 7. 报警（可选）

```bash
ai-verify alert set https://你的飞书或钉钉webhook
ai-verify alert test
```

## 配置文件

`~/.ai-verify/config.yaml`，数据在 `~/.ai-verify/data/ai_verify.db`。

## 开发

```bash
pip install -e ".[dev]"
pytest
black ai_verify/
ruff check ai_verify/
python -m build
```

文件职责索引见 [`docs/FILE_INVENTORY.md`](docs/FILE_INVENTORY.md)。
当前阶段状态与下一会话交接见 [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)。

## License

MIT
