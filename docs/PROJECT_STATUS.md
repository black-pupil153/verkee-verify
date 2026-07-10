# VerAI 项目阶段交接

> 更新日期：2026-07-10  
> 适用对象：继续本项目的下一会话 / 下一位开发者

## 一句话状态

VerAI 是一个面向 AI 使用者的渠道验真工具：用户付费购买的模型是否被偷换、降智或异常计费，应当有可追溯的证据。当前 Python CLI 已具备渠道验证、被动代理监控，以及 Cursor Auto 路由使用分析；下一阶段的重点是用本机真实 Cursor 数据完成端到端验证和产品收口，而不是重新实现 Cursor MVP。

## 仓库与运行状态

- GitHub：<https://github.com/black-pupil153/VerAI>
- 本地仓库根目录：`/Users/gelion/code/alibaba/ai-verify`
- 分支：`main`，已跟踪 `origin/main`
- 当前提交：`bb34afe Initial import of VerAI`
- 推送已经完成；本机通过 GitHub CLI 以 `black-pupil153` 登录。
- `venv/`、`.pytest_cache/`、`.ruff_cache/`、本地数据库和日志均已忽略，测试夹具 `tests/fixtures/**/*.log` 是唯一特意纳入 Git 的日志例外。

## 产品判断

- 对用户的主承诺不是“做一次 AI 盲测”，而是“我付费买到的模型到底是不是它、值不值”。盲测、指纹和趋势比较是实现证据的手段。
- `AI Verify` / `ai-verify` 仍是现有包名与 CLI 名；对外仓库名为 `VerAI`，读作 `ver-eye`。不要在没有兼容迁移方案的前提下批量改包名或命令名。
- Cursor Auto 是第二条叙事：回答“Cursor 在这个任务里实际路由了哪些模型、各占多少”，用来补充渠道验真的价值，而不替代它。

## 已实现能力

### 渠道验真与监控

- OpenAI、Anthropic、GLM 及 OpenAI 兼容渠道配置。
- 被动透明代理、SSE 转发、调用记录、异常和报警。
- 主动 `check`、质量题、探针、指纹、`score` 看板、定时巡检和报告。
- CC Switch 当前供应商读取与 `ai-verify run -- <command>` 包装。

### Cursor Auto Usage

以下命令和对应模块已经存在，不能按旧规划重复创建：

```bash
ai-verify cursor doctor
ai-verify cursor import --since 30d
ai-verify cursor tasks --limit 5
ai-verify cursor task --latest
ai-verify cursor board --watch
ai-verify cursor report --period weekly
ai-verify cursor hooks install
ai-verify cursor probe
ai-verify cursor recommend
```

- 路径发现与 Cursor schema 诊断：`ai_verify/providers/cursor.py`
- structured / renderer log 解析：`ai_verify/cursor_logs.py`
- 导入、去重、证据合并、任务与周期聚合：`ai_verify/monitor/cursor_usage.py`
- 看板、报告、hooks、盲测视图和模型建议均已有实现与对应测试。

`docs/CURSOR_AUTO_USAGE.md` 中 P0/P1/P2 的待办勾选和“待实施”标题已经落后于代码现状；它仍可作为数据源、置信度和隐私边界的设计依据，但不应被当作未开始的开发清单。

## 已验证结果

基线测试命令：

```bash
venv/bin/python -m pytest -q tests -k "not ml_optional"
```

最近结果：`108 passed, 1 deselected`。

完整测试集会触发可选的 ML / Hugging Face 路径，开发机上曾在该路径等待很久；除非本次工作涉及 ML 指纹依赖，否则以上基线命令应作为回归检查。`tests/test_cursor_usage.py` 已隔离本机 Cursor hook 事件路径，保留这项隔离，避免真实本机事件污染去重测试。

## 下一阶段建议

优先按以下顺序推进：

1. 在本机真实 Cursor 数据上运行 `doctor -> import -> tasks -> task --latest`，记录 Cursor 版本、发现的数据源、unknown 占比和任何解析失败样本。
2. 根据真实结果修正路径发现、日志解析或证据合并规则，并增加脱敏夹具与回归测试。
3. 更新 `docs/CURSOR_AUTO_USAGE.md` 的阶段状态与验收结果，避免文档继续宣称功能“待实施”。
4. 收口对外文案：将 README 的主价值改为“AI 渠道验真 / AI 消费验真器”，并明确 `VerAI` 与 `ai-verify` 的品牌和兼容关系。
5. 仅在真实数据证明有必要时，再扩展 hooks、质量关联或 token / 费用估算。

## 关键边界

- Cursor Auto 的底层路由并非官方逐任务承诺；输出必须保留 `confidence` 和 `unknown`，不得宣称 100% 可知。
- Cursor 第一方云请求通常不走本地代理；proxy 仅是 BYOK / 兼容 API 场景的补充证据。
- Cursor 数据处理应只保留任务标识、模型、计数、状态等元数据；不要把 prompt 或 response 正文写入项目数据库或测试夹具。
- 不要提交 `venv/`、真实日志、数据库、Token、API key 或 Cursor 用户数据。

## 下一会话开场提示

```text
先阅读 docs/PROJECT_STATUS.md、README.md 和 docs/CURSOR_AUTO_USAGE.md。
不要重做 Cursor P0/P1：代码和测试已经存在。
先在本机运行 ai-verify cursor doctor、cursor import --since 30d、cursor tasks --limit 5、cursor task --latest，
根据真实输出补齐问题、测试与文档；保持 confidence/unknown 和隐私边界。
回归使用：venv/bin/python -m pytest -q tests -k "not ml_optional"。
```
