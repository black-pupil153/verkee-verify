# VerAI 项目阶段交接

> 更新日期：2026-07-21  
> 适用对象：继续本项目的下一会话 / 下一位开发者

## 一句话状态

VerAI 渠道验真 + Cursor Auto Usage MVP + Auto 全量透视 + Phase 1/2 盲评 + Cheap GT `cheap-gt-v3`（Acc@forced **53.1%** n=32）已完成。产品化 **A3 dogfood + A3.1/A3.2 理解性重构**（`model_mix_v2` 统一构成 + 一层子代理 + 侧边栏简化）已通。**A4 软发布已完成**（[Release v0.1.0-sidebar](https://github.com/black-pupil153/VerAI/releases/tag/v0.1.0-sidebar)）。当前主线是 **closed alpha（Track C）**。Track B（GT/特征）反馈触发；**B6 单 token 分布特征（PAMELA）已立项**，不抢主线。

## 仓库与运行状态

- GitHub：<https://github.com/black-pupil153/VerAI>
- 本地仓库根目录：`/Users/gelion/code/alibaba/ai-verify`
- 分支：本地 `a3-sidebar-dogfood`（自 `leo24yuyu/app-12-…`；含 APP-12 + B3 + A3 dogfood）
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
| **Cheap GT + hook_task 对齐（2026-07-13）** | Task 子代理用 `hook.task`↔transcript 指纹对齐；语料曾 **53** 样本；split `cheap-gt`：**Acc@forced 87.5%**（n=16）、**Acc@τ=0.7 90%**（coverage 62.5%） |
| **GT 10-scenario 扩量（2026-07-13）** | composer/gpt-sol/gpt-terra 各补满 **10** 会话（fable 不扩、存量进闭集；grok 已 ≥10）；语料 **78** 样本；split `cheap-gt-v2` 复测：见下节 |
| **APP-12 长会话扩量（2026-07-15）** | 每便宜类 +5 真实 ≥5-turn 会话；语料 **163** 样本；split `cheap-gt-v3`：**n_test=32**；见下节 |
| **B3 近亲门控 MVP（2026-07-15）** | 推理侧 near-pair margin 弃权 + eval 近亲指标；见下节 |

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

### Cheap GT 盲评（2026-07-13，split=`cheap-gt` seed=42）

语料扩到 53 标签样本；`hook_task` 对齐 Task 子代理（composer/gpt/grok）。划分：train 16 / val 5 / test 4 会话；密封 16 条。gpt 两类会话过少未进 test。

| 评估 | 指标 | 值 |
|------|------|----|
| Val Acc（非盲评） | | 85.7% |
| **Acc@forced** | | **87.5%**（n=16） |
| macro-F1 / ECE / Brier | | 0.808 / 0.177 / 0.260 |
| **Acc@τ=0.7** | | **90.0%**（coverage 62.5%） |
| τ@0.8 | Acc / cov | 100% / 50% |

Runs：`~/.ai-verify/blindtest/runs/20260713-201802/`（train）、`…-1`（forced）、`…-2`（selective）。

说明：早先误跑了一批 fable Task（额度已花）；后续 GT 以 composer / gpt / grok 为主。

### Cheap GT v2 盲评（2026-07-13，split=`cheap-gt-v2` seed=42；复测）

按「GT 10-scenario expansion」补齐后 `import --since 7d --full` → `build-corpus --since 30d` → split/train/eval。复测相对首次多 1 条 grok 训练样本。

| 模型 | 会话数 | 样本数 | 备注 |
|------|--------|--------|------|
| composer-2.5-fast | 10 | 10 | 达标 |
| gpt-5.6-sol-medium | 10 | 10 | 达标 |
| gpt-5.6-terra-medium | 10 | 10 | 达标 |
| grok-4.5 | 11 | 39 | 已 ≥10，未再扩 |
| claude-fable-5 | 6 | 9 | **不扩**；存量进闭集 |

划分：train 28 / val 9 / test 9 会话；密封 14 条。标签来源：hook_task 37 / hook 27 / structured_log 11 / uniform 3。

| 评估 | 指标 | 值 |
|------|------|----|
| Val Acc（非盲评） | | 72.2%（T=1.00；n_train=46 / n_val=18） |
| **Acc@forced** | | **78.6%**（n=14 / 9 会话；首次同 split 曾 85.7%） |
| macro-F1 / ECE / Brier | | 0.638 / 0.146 / 0.260 |
| **Acc@τ=0.7** | | **90.0%**（coverage **71.4%**；abstain 4） |
| τ@0.5–0.6 | Acc / cov | 90.9% / 78.6% |
| τ@0.8 | Acc / cov | 100% / 57.1% |
| τ@0.9 | Acc / cov | 100% / 28.6% |

混淆（forced）：composer 2/2、terra 2/2；grok 6/7（1→fable）；sol 1/2（1→terra）；fable 0/1（→composer）。

Runs（复测）：`~/.ai-verify/blindtest/runs/20260713-203239/`（train）、`…/20260713-203240/`（forced）、`…/20260713-203240-1/`（selective+sweep）。

**勿与 LOCO-CV 91.7% 或旧 Acc@forced 66.7%（default split n=3）混报。**

### Cheap GT v3 长会话扩量（2026-07-15，split=`cheap-gt-v3` seed=42）

采集：固定模型 Task 子代理（非 Auto）× 三便宜类 × 五场景（解释/编辑草稿/重构提案/Plan/工具密集），每会话 resume 至 **5 turns**。并行同 prompt 曾导致 `hook_task` 指纹碰撞、全部误标为 terra；已用 `~/.ai-verify/blindtest/conversation_model_overrides.json`（`launch_override`）按启动模型纠偏，并让冲突指纹不再静默覆盖。

| 模型 | 会话 | 长会话(≥5) | 样本 | test 会话 / 样本 |
|------|-----:|----------:|-----:|-----------------:|
| composer-2.5-fast | 15 | 5 | 35 | 3 / 11 |
| gpt-5.6-sol-medium | 15 | 5 | 35 | 3 / 3 |
| gpt-5.6-terra-medium | 15 | 5 | 35 | 3 / 3 |
| grok-4.5 | 15 | 5 | 52 | 3 / 14 |
| claude-fable-5 | 5 | 0 | 6 | 1 / 1（不扩） |

划分：train 39 / val 13 / test 13 会话；密封 **32** 条。标签来源：launch_override 75 / hook_task 37 / hook 37 / structured_log 11 / uniform 3。`inventory --split cheap-gt-v3`：**ready**（n_test=32≥30；每便宜类长会话≥5、test 会话≥3）。未覆盖 `cheap-gt-v2`。

| 评估 | 指标 | 值 |
|------|------|----|
| Val Acc（非盲评） | | 44.4%（T=3.05；n_train=86 / n_val=45） |
| **Acc@forced** | | **53.1%**（n=32 / 13 会话） |
| macro-F1 / ECE / Brier | | 0.380 / 0.079 / 0.627 |
| **Acc@τ=0.7** | | **100%**（coverage **6.2%**；几乎全弃权） |

混淆（forced）：grok 11/14；composer 3/11（多→sol）；sol/terra 近亲仍混；fable 0/1。读法：扩量后 forced 从 v2 的 78.6%（n=14）降到 53.1%（n=32）——长会话 + 近亲类更难，属预期平台期，优先 B3 近亲混淆而非宣称涨点。

Runs：`~/.ai-verify/blindtest/runs/20260715-113407/`（train）、`…-1`（forced）、`…-2`（selective）。

### B3 近亲门控 MVP（2026-07-15，split=`cheap-gt-v3`）

实现（推理侧，不改标签空间 / 不重训）：

- `NEAR_RELATIVE_PAIRS`：sol↔terra、composer↔sol、composer↔terra、fable↔composer
- `near_margin=0.12`：top2 落在任一对且 `p1-p2 < margin` → `inferred_model=None`（`abstain_reason=near_margin`）
- eval / CLI 报告 `near_pair_swap`（forced 诊断）与 `near_abstain`（selective）
- 产品路径：`predict_turn` → Auto 推断轨自动更保守

复评（runs `…/20260715-145746/` forced、`…-1` τ=0.5、`…-2` τ=0.7+sweep）：

| 评估 | 指标 | 值 |
|------|------|----|
| **Acc@forced** | | **53.1%**（不变；门控不改 forced） |
| near_pair_swap（forced） | | **61.1%**（11/18；composer→sol/terra + sol↔terra） |
| **Acc@τ=0.7** | | **100%**（cov **6.2%**；near_abstain **25%**=8/32） |
| Acc@τ=0.5 | | 70%（cov 31.2%；near_abstain 25%） |

低 τ 对照（说明门控价值；默认产品 τ=0.7 时多与阈值重叠）：τ=0.3 有门控 Acc **60.9%** / cov 71.9% vs 无门控 Acc 53.3% / cov 93.8%——挡住约 4 条本会自信发出的近亲错报。

读法：B3 MVP 优先**诚实弃权**而非涨 forced；sol↔terra 现有特征仍几乎不可分。后续靠侧边栏反馈再决定是否补特征 / 修 duration。

### cheap-gt-v2 通道消融 + Auto 弱验证（2026-07-13）

`ablate --split cheap-gt-v2`（Acc@forced，n=14；runs `…/20260713-205144/`）：

| preset | Acc@forced | Val Acc |
|--------|------------|---------|
| text | **85.7%** | 61.1% |
| code | 28.6% | 22.2% |
| text+code | **85.7%** | 61.1% |
| text+code+behavior | 78.6% | 66.7% |
| +latency | **92.9%** | 66.7% |

读法：在本闭集上 **text 已是主力**；纯 code 很弱；behavior 略扰动；**latency 再抬一截**（小样本，勿外推成 SLA）。全通道日常评测仍以此前 forced **78.6%** 为准（与 ablate 中间一行同量级）。

`eval-auto --limit 20 --no-infer`（runs `…/20260713-205144-1/`）：coverage **75%**；opaque_residual **25%**；agree_with_fact **66.7%**（n=3 事实子集）。**非盲评 GT**。

基线测试：
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

### A3 侧边栏 dogfood（2026-07-16）

| 项 | 结果 |
|----|------|
| 面板 | 会话选择器（最近 N / 选中态）+ 事实/推断**堆叠条+表** + coverage / pending-infer；推断 disclaimer |
| 刷新 | ready/Refresh 静默 `cursor import --since 1d`；失败仅 notice，仍展示缓存 |
| doctor | green / green·warnings / needs fix；CLI not found → Open Settings → `verai.aiVerifyPath` |
| 打包 | `cd extensions/verai-cursor && npm run package` → `verai-cursor-0.1.0.vsix` |
| 对账 | `npm run accept`：bridge `task` ≡ `ai-verify cursor task <id> --json`（coverage / factual_* / inferred_*；<10s） |
| 分轨 | 推断不写 `resolved_model`；面板不展示 prompt/response 正文 |

分支：`a3-sidebar-dogfood`。装 VSIX 后 Activity Bar → VerAI 即可 dogfood。

### A3.1 / A3.2 理解性重构（2026-07-21）

| 项 | 结果 |
|----|------|
| `model_mix_v2` | `aggregate_task` 统一调用次数构成；确认/估算/未识别仅进细则 |
| 会话范围 | 根任务 + 一层子代理；`list_tasks.request_count` ≡ 详情 `total_calls` |
| CLI | 默认「本会话模型构成」；`--verbose` 才看分轨/状态/证据 |
| 侧边栏 | 单一构成条 + 条件提示 + 折叠「这是怎么判断的？」；默认无事实/推断轨文案 |
| 回归 | `pytest` cursor_usage/json/app16；`accept` 含 `model_mix_v2` 对账 |
| 工具 | `tools/dogfood_app16.py` 本机日检；`tests/test_app16_dogfood.py` 合成 Auto 夹具 |

## 下一阶段建议

**唯一主线：A4 软发布（GitHub Release + VSIX）→ Track C closed alpha（5–15 人）。**  
B 轨（GT）已到 B3 MVP；B4 / Phase 3 / duration / 探针仅用户点名再做。  
**B6（单 token 输出分布 → 盲测特征通道）**：已写入 [`docs/ROADMAP.md`](ROADMAP.md) Track B；依据 arXiv:2607.10252 / PAMELA。用途是给 `P(model | features)` 加一维超便宜主动特征，**不是**改成「有官方参考才验真」。未开工；反馈触发或点名再做。

已完成（勿重做）：Cursor P0/P1、长检索、G/H/C+B、Phase 1/2、GT 10-scenario、cheap-gt-v2/v3、B1–B3、CLI `--json`、扩展骨架、**A3 dogfood、A3.1/A3.2**。

### A4 软发布进度（2026-07-21）

| 项 | 状态 |
|----|------|
| 根 README 一页 Install from VSIX | ✅ |
| 扩展 README + hooks install 提示 | ✅ |
| `docs/ALPHA_CHECKLIST.md` | ✅ |
| 本机重打 `verai-cursor-0.1.0.vsix`（A3.1/A3.2 UI） | ✅（gitignore，Release 附件） |
| dogfood `tools/dogfood_app16.py` | ✅ 本机通过 |
| GitHub Release 挂 VSIX | ✅ [v0.1.0-sidebar](https://github.com/black-pupil153/VerAI/releases/tag/v0.1.0-sidebar) |

**A4 软发布已落地。** 下一主线：Track C closed alpha（约 5 人）。

1. 按 [`ALPHA_CHECKLIST.md`](ALPHA_CHECKLIST.md) 发安装步骤 + 两问问卷
2. 自用 dogfood 日记；PATH / 空数据卡点记回本文件
3. 连续「不准 / 未知过高」再开 Track B（含 B6）

## 安全边界

- Cursor Auto 的底层路由并非官方逐任务承诺；输出必须保留 `confidence`、事实/推断分轨；**不得**把推断静默写入 `resolved_model`，也不得宣称云端逐步真名 100% 可知。
- Cursor 第一方云请求通常不走本地代理；proxy 仅是 BYOK / 兼容 API 场景的补充证据。
- Cursor 数据处理应只保留任务标识、模型、计数、状态等元数据；不要把 prompt 或 response 正文写入项目数据库或测试夹具。
- 不要提交 `venv/`、真实日志、数据库、Token、API key 或 Cursor 用户数据。
- 盲测 sealed labels / corpus / runs 仅存 `~/.ai-verify/blindtest/`，不入 git。

## 下一会话开场提示

```text
执行 Track C closed alpha（A4 已发布）。先读 docs/ALPHA_CHECKLIST.md、docs/ROADMAP.md、docs/PROJECT_STATUS.md。

不要重做：A3/A3.1/A3.2、A4 Release、B6/盲测/微调（除非 alpha 反馈触发或点名）。
Release：https://github.com/black-pupil153/VerAI/releases/tag/v0.1.0-sidebar

本会话只做：
1) 招募 ~5 人按 ALPHA_CHECKLIST 安装；收集两问（看懂占比 / 信任推断）
2) 记录安装卡点（PATH/VSIX/空数据）写回 PROJECT_STATUS
3) 连续不准/未知过高再开 Track B（含 B6）

保持 factual vs inferred 分轨与隐私边界；产品默认读 model_mix_v2。
```
