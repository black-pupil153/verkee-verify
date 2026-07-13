# VerAI 项目阶段交接

> 更新日期：2026-07-13  
> 适用对象：继续本项目的下一会话 / 下一位开发者

## 一句话状态

VerAI 渠道验真 + Cursor Auto Usage MVP + Auto 全量透视长检索 + **主路径实现（G/H/C+B）均已完成**。下一里程碑：手选会话 `blindtest build-corpus` → `train` → 本机验证 Auto `coverage`；可选 D/F 探针先验 / ITT / 标题补全。

## 仓库与运行状态

- GitHub：<https://github.com/black-pupil153/VerAI>
- 本地仓库根目录：`/Users/gelion/code/alibaba/ai-verify`
- 分支：`main`，已跟踪 `origin/main`
- Auto 透视主路径（G/H/C+B）与 `docs/research/` 已纳入本轮 commit；**尚未 push**。新会话继续手选语料训练与 coverage 验收即可。
- `venv/`、`.pytest_cache/`、`.ruff_cache/`、本地数据库和日志均已忽略，测试夹具 `tests/fixtures/**/*.log` 与脱敏 `*.ndjson` 是特意纳入 Git 的例外。

## 产品判断

- 对用户的主承诺不是“做一次 AI 盲测”，而是“我付费买到的模型到底是不是它、值不值”。盲测、指纹和趋势比较是实现证据的手段。
- `AI Verify` / `ai-verify` 仍是现有包名与 CLI 名；对外仓库名为 `VerAI`，读作 `ver-eye`。不要在没有兼容迁移方案的前提下批量改包名或命令名。
- Cursor Auto 是可选叙事：回答“Cursor 在这个任务里实际路由了哪些模型、各占多少”，用来补充渠道验真的价值，而不替代它。

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
- hook ID 清洗：`ai_verify/cursor_hook_events.normalize_cursor_id`
- 看板、报告、hooks、盲测视图和模型建议均已有实现与对应测试。

`docs/CURSOR_AUTO_USAGE.md` 已更新为「已实现并完成本机验收」；仍可作为数据源、置信度和隐私边界的设计依据。

## 本机验收摘要（2026-07-11）

| 项 | 结果 |
|----|------|
| Cursor 版本 | 3.10.20 |
| doctor | ai-tracking ✓、structured logs ✓、composerHeaders ✓、transcripts ✓；有 hook tokens 时显示 `tokens (hook)` |
| import | `--since 30d --full` 可导入；hook `model_id` / tokens / duration 进入事实层 |
| 验收任务 `906dea0f` | 产出占比 claude-fable-5 **64.2%** / grok-4.5 **35.8%** |
| 修复 | hook `subagent_id` 引号+换行清洗；子任务不再出现在顶层 `tasks` 列表 |
| 标题缺口 | agent-transcript 任务常无 composerHeader 对齐 →「(无标题)」；不读 prompt 补标题 |
| Auto 透视（2026-07-12） | 无事实 → `pending-infer`（非终态）；报表双轨 `factual_*` / `inferred_*` + `coverage`；推断不写入 `resolved_model` |

基线测试：

```bash
venv/bin/python -m pytest -q tests -k "not ml_optional"
```

最近结果：`114 passed, 1 deselected`（2026-07-13 复验）。

完整测试集会触发可选的 ML / Hugging Face 路径；除非本次工作涉及 ML 指纹依赖，否则以上基线命令应作为回归检查。`tests/test_cursor_usage.py` 已隔离本机 Cursor hook 事件路径，保留这项隔离。

## 下一阶段建议

优先按以下顺序推进：

1. ~~本机真实 Cursor 数据 E2E~~（已完成）
2. ~~按真实结果修解析/合并 + 脱敏夹具~~（已完成：hook ID / 子任务列表）
3. ~~同步 `CURSOR_AUTO_USAGE.md` 与 README 品牌收口~~（已完成）
4. ~~Auto 全量透视长检索~~（已完成：见 [`docs/research/`](research/README.md)）
5. ~~实现 Auto 全量透视主路径~~（已完成：hook 事实/tokens、分轨报表、blindtest 代码/文本特征）
6. ~~提交本轮工作区改动~~（含 `docs/research/` 与 Auto 透视代码）
7. **手选会话 `blindtest build-corpus` → `train` → `infer` + 本机 Auto coverage 验收**
8. 可选：周期探针先验（D/F）、ITT（E）、无 composerHeader 标题来源、proxy merge

## 关键边界

- Cursor Auto 的底层路由并非官方逐任务承诺；输出必须保留 `confidence`、事实/推断分轨；**不得**把推断静默写入 `resolved_model`，也不得宣称云端逐步真名 100% 可知。
- Cursor 第一方云请求通常不走本地代理；proxy 仅是 BYOK / 兼容 API 场景的补充证据。
- Cursor 数据处理应只保留任务标识、模型、计数、状态等元数据；不要把 prompt 或 response 正文写入项目数据库或测试夹具。
- 不要提交 `venv/`、真实日志、数据库、Token、API key 或 Cursor 用户数据。

## 下一会话开场提示

```text
先阅读 docs/PROJECT_STATUS.md 与 docs/research/README.md。
不要重做 Cursor P0/P1、长检索或 G/H/C+B。
下一优先：手选会话 blindtest build-corpus → train → 本机验证 Auto coverage。
保持 factual vs inferred 分轨与隐私边界。
回归：venv/bin/python -m pytest -q tests -k "not ml_optional"。
```
