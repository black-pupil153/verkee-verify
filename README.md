# VerAI

> AI 渠道验真 / AI 消费验真器  
> 读作 **ver-eye** · CLI 与包名仍为 `ai-verify`（兼容不改）

你付费买到的模型，到底是不是它、值不值——应当有可追溯的证据。  
VerAI 以**被动监控为主、主动探测为辅**，检测中转站偷换模型、质量下滑、官方模型降智，并可选透视 Cursor Auto 实际路由了哪些模型。

仓库：<https://github.com/black-pupil153/VerAI>

## 核心能力

| 能力 | 说明 |
|------|------|
| 渠道验真 | `check` / `score`：指纹、质量题、反侦测探针，给当前渠道打分 |
| 透明代理 | 拦截真实流量（含 SSE），旁路落库 + 异常报警 |
| 多模型渠道 | OpenAI / Anthropic / GLM（智谱）及 OpenAI 兼容中转 |
| CC Switch | 自动读当前供应商；`ai-verify run -- claude` 一键包装 |
| 定时巡检与周报 | `monitor` / `history` / `report` |
| Cursor Auto Usage | 只读本机 Cursor 遥测；任务级事实/推断分轨与 coverage（推断≠云端真值） |

## 安装

```bash
cd ai-verify
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

可选 ML 指纹（重依赖）：`pip install -e ".[ml]"`

## 快速开始：渠道验真

### 1. 单元测试（不耗 API）

```bash
pytest -q tests -k "not ml_optional"
```

### 2. 配置渠道

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

### 3. 主动验证与打分

```bash
ai-verify check
ai-verify check --full --probes 8 --questions 10
ai-verify score
ai-verify score --board
ai-verify score --watch --interval 30m
```

## Claude Code + CC Switch

```bash
ai-verify providers list
ai-verify providers current
ai-verify run -- claude
ai-verify check
ai-verify score
```

代理日志：`~/.ai-verify/logs/proxy.log`  
调用记录：`ai-verify history --last 1d`

```bash
ai-verify monitor start --interval 6h
ai-verify report --period weekly
ai-verify alert set https://你的飞书或钉钉webhook
ai-verify alert test
```

## Cursor Auto Usage

只读本机元数据（不读 prompt/response 正文）。Cursor 未公开承诺每个 Auto 任务的底层模型；输出保留 **confidence**、**factual / inferred** 分轨与 `pending-infer`，不把推断写成事实，也不宣称云端逐步真名 100% 可知。

```bash
ai-verify cursor doctor
ai-verify cursor import --since 30d
ai-verify cursor tasks --limit 5
ai-verify cursor task --latest
ai-verify cursor board
ai-verify cursor report --period weekly
```

可选：`ai-verify cursor hooks install` 补采 hook 事件中的 model 字段。

机器可读（插件桥接）：

```bash
ai-verify cursor doctor --json
ai-verify cursor tasks --json --limit 15
ai-verify cursor task --latest --json
```

侧边栏扩展（开发中）：[`extensions/verai-cursor/`](extensions/verai-cursor/README.md)  
产品路线图：[`docs/ROADMAP.md`](docs/ROADMAP.md)  
设计与验收细节见 [`docs/CURSOR_AUTO_USAGE.md`](docs/CURSOR_AUTO_USAGE.md)。

## 配置与数据

`~/.ai-verify/config.yaml`，数据在 `~/.ai-verify/data/ai_verify.db`。

## 开发

```bash
pip install -e ".[dev]"
pytest -q tests -k "not ml_optional"
black ai_verify/
ruff check ai_verify/
python -m build
```

文件职责索引：[`docs/FILE_INVENTORY.md`](docs/FILE_INVENTORY.md)  
阶段交接：[`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)  
产品路线图：[`docs/ROADMAP.md`](docs/ROADMAP.md)

## License

MIT
