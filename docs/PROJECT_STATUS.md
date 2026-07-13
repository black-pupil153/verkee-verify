# VerAI 项目阶段交接

> 更新日期：2026-07-13  
> 适用对象：继续本项目的下一会话 / 下一位开发者

## 一句话状态

VerAI 渠道验真 + Cursor Auto Usage MVP + Auto 全量透视 + Phase 1 盲评基建（已 commit）+ 本机隐藏 test 跑通均已完成。**Phase 2 落地中**：duration_ms 特征、通道消融（`ablate`）、Auto 弱验证（`eval-auto`）；GT 扩量 = **批量开「手选模型」会话**（picker 固定，标签自动对齐），不是逐 turn 手标。瓶颈仍是数据（test n=3）；91.7%=LOCO-CV≠盲评；Acc@forced=66.7%。微调后置。

## 仓库与运行状态

- GitHub：<https://github.com/black-pupil153/VerAI>
- 本地仓库根目录：`/Users/gelion/code/alibaba/ai-verify`
- 分支：`main`，已跟踪 `origin/main`
- 本地语料/模型在 `~/.ai-verify/blindtest/`（不入 git）；split registry / sealed labels / runs 亦在此目录。
- `venv/`、`.pytest_cache/`、`.ruff_cache/`、本地数据库和日志均已忽略，测试夹具 `tests/fixtures/**/*.log` 与脱敏 `*.ndjson` 是特意纳入 Git 的例外。

## 产品判断

- 对用户的主承诺不是“做一次 AI 盲测”，而是“我付费买到的模型到底是不是它、值不值”。盲测、指纹和趋势比较是实现证据的手段。
- **最根本能力是模型盲测**：隐藏真名时估计 `P(model | turn_features)`；看板是展示层，不是能力本身。
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
- hook ID 清洗：`ai_verify.cursor_hook_events.normalize_cursor_id`
- 看板、报告、hooks、盲测视图和模型建议均已有实现与对应测试。

`docs/CURSOR_AUTO_USAGE.md` 已更新为「已实现并完成本机验收」；仍可作为数据源、置信度和隐私边界的设计依据。

### 盲测 Phase 1（盲评基建）

```bash
ai-verify blindtest build-corpus --since 30d
ai-verify blindtest split --name default --seed 42 --ratios 0.6,0.2,0.2
ai-verify blindtest train --split default
ai-verify blindtest eval --split default --forced
ai-verify blindtest eval --split default --tau 0.7 --sweep
```

- `ai_verify/blindtest/splits.py` — 按 conversation_id 的 train/val/test registry + 密封标签
- `ai_verify/blindtest/eval.py` — Acc@forced / Acc@τ / τ sweep / macro-F1 / ECE / Brier；Auto 弱验证；通道消融；runs 落盘
- `classifier.train(..., split=)` — T 只在 val 拟合；test 标签不可见
- 双模式：selective（阈值弃权）vs forced top-1
- Phase 2：`duration_ms` 时序特征；`train/eval --channels/--ablate`；`blindtest ablate`；`blindtest eval-auto`
- 推断仍不得写入 `resolved_model`；报告不落 prompt/response 正文
- **GT 扩量**：关 Auto、固定 picker=M 批量开会话 → `import` + `build-corpus` 自动打标（见实验协议 §3）
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
| 手选 train + coverage（2026-07-13） | `build-corpus --since 30d`：24 标签样本（grok-4.5×19 / claude-fable-5×5；标签 hook 10 / structured_log 11 / uniform 3）；无 split 时 `train` CV **91.7%**（**LOCO-CV 诊断，非盲评**）；Auto 任务 `166af1e3` infer 后 **coverage 100%**（fact 0% / inferred 100%，`resolved_model` 仍为 default/unknown）；mixed `469c3074` coverage 75%、分轨可见、阈值下仍有 pending-infer |
| H 默认融合 + 标题回退（2026-07-13） | `aggregate_task(auto_infer=True)` 对 auto/mixed 自动写 `blindtest_inferences`；`conversation_summaries.title/tldr` 作无 composerHeader 时的标题回退 |
| **隐藏 test 盲评（2026-07-13）** | 见下节；**勿与 LOCO-CV 91.7% 混报** |

### 隐藏 test 盲评（2026-07-13，split=`default` seed=42）

语料：24 标签样本 / 6 会话。划分：train 4 / val 1 / test 1 会话；密封标签 3 条。注：`claude-fable-5` 仅 1 会话 → 全进 train（test 无该类）。

| 评估 | 指标 | 值 | 说明 |
|------|------|----|------|
| LOCO-CV（旧） | Acc | **91.7%** | **非盲评**；leave-one-conversation-out 诊断 |
| train --split | Val Acc | 44.4% | 非盲评；T=7.45 仅在 val 拟合；n_train=12 / n_val=9 |
| **盲评 forced** | Acc@forced | **66.7%** | 隐藏 test；coverage 100%；n=3 / 1 会话（全为 grok-4.5） |
| 盲评 forced | macro-F1 | 0.400 | 类不平衡；claude-fable-5 真值行全 0 |
| 盲评 forced | ECE / Brier | 0.532 / 0.576 | 校准偏乐观 |
| **盲评 selective** | Acc@τ=0.7 | N/A | coverage **0%**（3/3 abstain） |
| τ sweep | Acc / cov @0.5 | 66.7% / 100% | 与 forced 同量级 |
| τ sweep | Acc / cov @0.6 | 0.0% / 33.3% | 唯一未弃权样本判错 |
| τ sweep | cov @≥0.7 | 0% | 当前阈值下无有效 Acc@τ |

Runs（仅本机，不入 git）：

- TrainReport：`~/.ai-verify/blindtest/runs/20260713-192614/`
- EvalReport forced：`~/.ai-verify/blindtest/runs/20260713-192621/`
- EvalReport selective+sweep：`~/.ai-verify/blindtest/runs/20260713-192621-1/`

结论：管道已通；数字不可外推——test n=3、单会话、闭集缺一类。扩量（批量手选模型会话）优先于换模型。

### Phase 2 本机结果（2026-07-13）

消融 `ablate --split default`（Acc@forced，n=3；runs `…/20260713-201038/`）：

| preset | Acc@forced | Val Acc |
|--------|------------|---------|
| text | 33.3% | 55.6% |
| code | 33.3% | 11.1% |
| text+code | 66.7% | 33.3% |
| text+code+behavior | 66.7% | 33.3% |
| +latency | 66.7% | 33.3% |

Auto 弱验证 `eval-auto --limit 20 --no-infer`（runs `…/20260713-201046/`）：coverage **75%**；opaque_residual **25%**；agree_with_fact **66.7%**（n=3 事实子集）。**非盲评 GT**。

基线测试：

```bash
venv/bin/python -m pytest -q tests -k "not ml_optional"
```

完整测试集会触发可选的 ML / Hugging Face 路径；除非本次工作涉及 ML 指纹依赖，否则以上基线命令应作为回归检查。`tests/test_cursor_usage.py` 已隔离本机 Cursor hook 事件路径，保留这项隔离。

## 下一阶段建议

优先按以下顺序推进：

1. ~~本机真实 Cursor 数据 E2E~~（已完成）
2. ~~按真实结果修解析/合并 + 脱敏夹具~~（已完成：hook ID / 子任务列表）
3. ~~同步 `CURSOR_AUTO_USAGE.md` 与 README 品牌收口~~（已完成）
4. ~~Auto 全量透视长检索~~（已完成：见 [`docs/research/`](research/README.md)）
5. ~~实现 Auto 全量透视主路径~~（已完成：见 [`docs/research/`](research/README.md)）
6. ~~提交本轮工作区改动~~（含 `docs/research/` 与 Auto 透视代码）
7. ~~手选会话 `blindtest build-corpus` → `train` → `infer` + 本机 Auto coverage 验收~~（已完成；语料/模型仅存本机）
8. ~~H 融合默认开启 + 无 composerHeader 标题 summary 回退~~
9. ~~Phase 1 盲评基建 + 本机隐藏 test 跑通~~（已 commit：`6c25caa`）
10. **Phase 2（进行中）**：duration/消融/`eval-auto` 代码；**GT 扩量需你批量开手选模型会话**（每类 ≥2 会话进 test）后再 `import`→`build-corpus`→`split`→`eval`
11. **Phase 3**（隐藏 test 平台期后且用户要求）：sentence-transformers / 微调
12. **可选**：周期探针先验（D/F）、ITT（E）、proxy merge — 仅用户点名时做

## 关键边界

- Cursor Auto 的底层路由并非官方逐任务承诺；输出必须保留 `confidence`、事实/推断分轨；**不得**把推断静默写入 `resolved_model`，也不得宣称云端逐步真名 100% 可知。
- Cursor 第一方云请求通常不走本地代理；proxy 仅是 BYOK / 兼容 API 场景的补充证据。
- Cursor 数据处理应只保留任务标识、模型、计数、状态等元数据；不要把 prompt 或 response 正文写入项目数据库或测试夹具。
- 不要提交 `venv/`、真实日志、数据库、Token、API key 或 Cursor 用户数据。
- 盲测 sealed labels / corpus / runs 仅存 `~/.ai-verify/blindtest/`，不入 git。

## 下一会话开场提示

```text
先读 docs/PROJECT_STATUS.md、docs/research/README.md、docs/research/EXPERIMENT_PROTOCOL.md。
不要重做：Cursor P0/P1、长检索、G/H/C+B、手选 train/coverage、H 默认融合、标题 summary 回退、Phase 1、本机隐藏 test、duration/消融/eval-auto 基建、D/F/ITT（除非用户点名）。
产品判断：最根本能力是模型盲测；瓶颈是数据。91.7%=LOCO-CV≠盲评；Acc@forced=66.7%。
「手选 GT」= Cursor picker 固定模型（可批量开会话）；标签用 import+build-corpus 自动对齐；禁止 Auto 自标。
下一优先：用户批量开手选模型会话（每类≥2）后 rebuild corpus→split→eval；或 commit/push Phase 2。
回归：venv/bin/python -m pytest -q tests -k "not ml_optional"。
保持 factual vs inferred 分轨与隐私边界。
```
