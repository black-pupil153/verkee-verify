# 实验协议 — Auto 推断标定与评估

> 2026-07-11  
> 目的：用手选模型会话构造 **ground truth**，训练/评估推断器；**禁止**用 Auto 会话自标当 GT  
> 隐私：特征与标签可存 `~/.ai-verify/blindtest/`；**不提交**真实正文到 git

---

## 1. 目标与非目标

**目标**

- 估计 `P(model | turn_features)` 在 Cursor 真实分布上的准确率与校准
- 验证「Coverage 100% + 分轨展示」的产品语义
- 对比：仅文本 / 仅代码 / 文本+代码 / +时序

**非目标**

- 证明与 Cursor 服务端路由日志一致
- 在 Auto 样本上用推断结果当训练标签（避免循环证实）

---

## 2. 模型池（标签空间）

以本机近期真实出现的 slug 为闭集起点（可配置）：

```text
claude-fable-5 | grok-4.5 | gpt-5.5 | composer-2.5-fast | …
```

规则：

- 训练标签使用 **规范化 model_id**（与 hook/`ai_code_hashes` 对齐）
- 稀有模型 < N 样本则并入 `other` 或排除出闭集评估

---

## 3. Ground Truth 采集（手选）

### 3.1 会话设计

对每个目标模型 M，创建 **手动选中 M**（关闭 Auto）的 Agent 会话，覆盖任务类型：

| 类型 | 示例 | 最少 turns |
|------|------|----------:|
| 解释/问答 | 解释一段代码 | 5 |
| 单文件编辑 | 改函数 | 5 |
| 多文件重构 | 跨 2+ 文件 | 5 |
| 计划模式 | Plan 产出 | 3 |
| 工具密集 | 多次 shell/读文件 | 5 |

记录：`conversation_id`、选定模型 M、开始/结束时间。

### 3.2 标签对齐（已有 corpus 逻辑）

沿用 [`blindtest/corpus.py`](../../ai_verify/blindtest/corpus.py) 优先级：

1. structured log `modelName != default` 按时间对齐
2. `ai_code_hashes.model != default` join `requestId`
3. 会话级统一标签（整会话单一模型时）

**新增（实现阶段）**：hook `model_id` 按 `generation_id` join，优先于 2。

### 3.3 数据划分

- 按 **conversation_id** 划分 train/val/test（防 turn 泄漏）
- 建议 60/20/20；leave-one-conversation-out 作校准（与现分类器一致）

---

## 4. Auto 评估集（无 GT 模型名）

另采纯 Auto 会话（真实使用即可）：

- 只评估：**coverage**、推断分布、与 factual 子集一致性
- 对 Auto 中 hook/`tracking` 偶然非 default 的 turn：可作 **弱验证**（semi-supervised check），不进训练集

指标：

```text
coverage = (# turns with fact or inferred label) / (# auto turns)
agree_with_fact = Acc(inferred, factual) on turns where factual ≠ default
opaque_residual = (# turns still shown as auto-opaque) / total  → 目标 0
```

---

## 5. 特征协议

| 通道 | 特征 | 存储 |
|------|------|------|
| 文本 | 现有 blindtest + 可选 POS/结构扩展 | 浮点向量 |
| 代码 | LPcodedec 风格特征或 AST n-gram 哈希桶 | 浮点向量 |
| 时序 | ttft_ms, duration_ms, 输出长度 | 标量 |
| 行为 | tool 名哈希、batch 数 | 已有 |

**禁止**：原始 user/assistant 文本、完整代码文件写入 git 或共享语料包。

---

## 6. 模型与校准

基线：现有 `BlindModelClassifier`（LogReg + 温度 + 阈值）。

对比实验：

1. text-only  
2. code-only  
3. text+code 拼接  
4. +timing  
5. （可选）小编码器微调（`[ml]` extra）

校准：

- 验证集学温度 T
- 报告 ECE、Brier、reliability diagram
- 选择性曲线：accuracy vs coverage（扫 τ）

注意（H3）：若强制 100% coverage，须同时报告 **forced top-1 Acc** 与 **Acc@τ_high**。

---

## 7. 产品验收门槛（建议）

| 门槛 | 建议初值 | 说明 |
|------|----------|------|
| Auto coverage | 100% | 无 auto-opaque 终态 |
| Acc@τ=0.7 手选 test | ≥ 基线+10pt 或 ≥0.75 | 以实验定 |
| Acc@forced 手选 test | 记录不设硬闸 | 防刷指标 |
| factual 优先 | 冲突时 100% 用 factual | 回归测试 |
| 隐私扫描 | CI 拒录正文夹具 | 已有策略延续 |

---

## 8. 操作检查清单

```text
[ ] 每模型手选会话按类型跑完
[ ] ai-verify cursor import --since …
[ ] ai-verify blindtest build-corpus（或等价）
[ ] 确认标签来源统计：hook / tracking / log 占比
[ ] train → 记录 TrainReport
[ ] test 表：Acc / F1 / ECE / 混淆矩阵
[ ] Auto 集：coverage、opaque_residual、agree_with_fact
[ ] 更新 FEASIBILITY 中的「实测」列（实现阶段）
```

---

## 9. 伦理与额度

- 手选标定消耗用户订阅额度；控制每模型 turns
- 主动探针（Track D）单独会话，避免污染日常 Auto 统计
- 不对外发布可还原用户代码的特征逆推材料
