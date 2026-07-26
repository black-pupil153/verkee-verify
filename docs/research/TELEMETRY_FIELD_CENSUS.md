# Cursor 本地遥测字段普查（Track G）

> 日期：2026-07-11  
> Cursor 版本：3.10.20  
> 方法：只读 SQLite / hook NDJSON / composerHeaders；**不读取、不导出 prompt/response 正文**  
> 目的：判断是否存在可消灭 `auto-opaque` 的**事实源**；若无，则指纹路线为必需

## 1. 观察者能力（威胁模型摘要）

| 能力 | 本机是否具备 | 说明 |
|------|:------------:|------|
| 读 `~/.cursor/ai-tracking/*.db` | ✓ | 代码产出哈希与 model 列 |
| 读 Application Support logs | ✓ | structured / renderer / requestTraces（VerAI 已解析） |
| 读 `composer.composerHeaders` | ✓ | 标题/模式；**无 per-turn model** |
| 读 agent-transcripts | ✓ | 结构与正文；隐私上默认不入库正文 |
| Cursor Hooks stdin | ✓（若已 install） | **含 model / model_id / tokens** |
| 服务端 usage dashboard API | ✗ | 无官方逐步 Auto 路由 API |
| 模型权重 / 路由内部状态 | ✗ | 黑盒 |

**对手模型**：Cursor Auto = 黑盒动态路由器；可对观察者隐藏真实 model（写 `default`），并可指示 agent 不暴露内部 alias。

## 2. `ai-code-tracking.db`

### 2.1 表与 model 相关列

| 表 | model 列 | 本机行数/备注 | 可作事实源？ |
|----|----------|---------------|:------------:|
| `ai_code_hashes` | `model` TEXT | 4295 行 | **部分** |
| `conversation_summaries` | `model`, `mode` | **0 行**（本机空） | 理论可用 |
| `tracked_file_content` | `model` | 有；含 `content`（**禁止入库正文**） | 仅 model 元数据 |
| `ai_deleted_files` | `model` | 有 | 弱 |
| `scored_commits` | 无 model | AI% 统计 | 否 |

### 2.2 `ai_code_hashes.model` 分布（本机）

| model | count | 占比 |
|-------|------:|-----:|
| claude-fable-5 | 1554 | 36.2% |
| **default** | **1276** | **29.7%** |
| grok-4.5 | 1191 | 27.7% |
| gpt-5.5 | 234 | 5.4% |
| null/empty | 40 | 0.9% |

**结论**：约 **30%** 代码产出在 Auto 路径上被记为 `default` → VerAI 正确映射为 `auto-opaque`。  
**不存在**第二列「真实 resolved model」可直接替代。全量透视**不能**仅靠 tracking DB。

## 3. Composer headers（`state.vscdb`）

- 82 composers；键含 `unifiedMode`、`subtitle`、`numSubComposers`、`subagentInfo` 等
- **无** `model` / `catalogModelId` / `resolvedModel` 字段
- 仅 ~40% 有 subtitle；与 agent-transcript `conversationId` 常不对齐 → 标题缺失属预期

## 4. Hooks（`~/.verkee/verify/cursor-hook-probe.ndjson`）

本机 16 条事件字段普查（高频）：

| 字段 | 出现 | 对 Auto 透视的价值 |
|------|-----:|-------------------|
| `model` | 16/16 | 高；可为 `default` 或真实 slug |
| `model_id` | 12/16 | **高**；常比 `model` 更规范 |
| `input_tokens` / `output_tokens` | 12/16 | **高**（P4 token 的事实来源！） |
| `cache_read_tokens` / `cache_write_tokens` | 12/16 | 中 |
| `subagent_model` | 2/16 | 高（子代理） |
| `generation_id` / `conversation_id` | 16/16 | 对齐主键 |
| `text` / `summary` / `task` | 部分 | **勿入库正文** |

本机 `model`/`model_id` 取值样例（计数）：

- `grok-4.5` / `grok-4.5-fast-xhigh`（非 Auto 或已解析）
- `default`（Auto 不透明）
- `composer-2.5-fast`（含 subagent）

**结论**：Hook 是目前**最强的逐步事实补充源**；但 Auto 仍会给出 `default`。  
Token 字段已存在 → 实现阶段应优先从 hook 填 `input_tokens`/`output_tokens`，而非估算。

## 5. Structured / renderer logs（VerAI 已解析契约）

依据 [`cursor_logs.py`](../../verkee_verify/cursor_logs.py) 与设计文档（本机 parser 已覆盖）：

| 事件/来源 | 模型相关字段 | Auto 时典型值 | 置信度 |
|-----------|--------------|---------------|--------|
| `Starting stream request` / Composer state | `modelName` | 常为 `default` | med |
| `agent.turn.outcome` | `model_intent` | `default` → route=auto | med |
| renderer `[buildRequestedModel]` | `catalogModelId`, `composerModelName` | 可能补充 catalog | med-high |
| requestTraces | requestId ↔ composerId | 无 model | 结构 |

**未发现**稳定的「Auto → 真实底层模型名」官方字段。社区与论坛确认产品侧故意不暴露逐步模型。

## 6. 事实源优先级（更新）

```text
1. hook.model_id / hook.model（≠ default）     → factual high
2. ai_code_hashes.model（≠ default）           → factual high（按 requestId）
3. renderer catalogModelId（≠ default）        → factual medium-high
4. structured modelName / model_intent=default → 仅能标 auto，不能消歧
5. 指纹 / 侧信道推断                           → inferred（不得写入 resolved 事实列）
```

## 7. Track G 裁决

| 问题 | 裁决 |
|------|------|
| 仅靠遥测能否全量透视 Auto？ | **否**（~30%+ default） |
| 遥测是否仍值得穷尽？ | **是**：hook tokens、非 default 合并、子代理 model |
| 指纹是否必需？ | **是**，作为 inferred 层消灭 `auto-opaque` 终态 |
| 下一步工程 | 强化 hook 事实合并 + 被动/代码归因 + 融合分轨展示 |
