# VerAI 纯 Auto 全量透视 — 文献综述（LITREV）

> 版本：v1.0 · 2026-07-11  
> 范围：Track A–H；配套 [`BIB.md`](BIB.md)、[`TELEMETRY_FIELD_CENSUS.md`](TELEMETRY_FIELD_CENSUS.md)、[`FEASIBILITY_MATRIX.md`](FEASIBILITY_MATRIX.md)、[`EXPERIMENT_PROTOCOL.md`](EXPERIMENT_PROTOCOL.md)  
> 本阶段只做检索与结论，**不改产品代码**

---

## 0. 执行摘要

Cursor Auto **故意不暴露**逐步底层模型；本机 `ai_code_hashes.model` 约 **30%** 为 `default`。仅靠现有遥测无法「数学证明」每个 Auto turn 的真实模型。

学术与工程上可行的「全量透视」定义为：

1. **Coverage 100%**：每个 Auto turn 都有标签（事实或推断）
2. **分轨展示**：`factual_share` vs `inferred_share`，禁止把推断写入事实 `resolved_model`
3. **可校准置信度**：高置信进主报表；低置信标注但仍覆盖（或双视图）

**主路线（推荐）**：强化 Hook/遥测事实合并（G）→ 以**代码风格 + 文本风格**增强 blindtest（C/B）→ 融合与校准进默认 Auto 看板（H）。  
**辅路线**：周期主动探针标定（D，注意路由污染）；TTFT/ITT 侧信道（E，需新采集）。  
**放弃/降级**：白盒权重指纹、训练注入水印、依赖官方逐步 API。

与 VerAI 最近的论文是 **Invisible Traces (A1)**：专论 GenAI 应用内动态路由下的混合指纹。

---

## 1. Track A — 威胁模型与问题边界

### 1.1 Cursor Auto 作为对手

官方与论坛（A4–A6）一致：

- Auto 按任务类型、上下文、可用性/负载**逐步换模**
- UI/transcript **不保证**逐步 `model_id`
- Agent 系统提示可要求**不透露**内部模型别名

因此 VerAI 面对的是：**应用层黑盒路由器 + 可选本地遥测泄漏**，不是开源权重审计。

### 1.2 Invisible Traces（A1）精读要点

- **问题**：多代理、频繁换模、无内部访问时，单一静态指纹失效
- **方法**：Static（主动探针，如 LLMmap 类）+ Dynamic（被动风格观察）加权融合
- **对 VerAI**：几乎同构——Cursor = 多代理 + Auto 动态路由；应采用「混合管线」而非单一分类器
- **差距**：论文评测多为可控 GenAI app；Cursor 还有工具调用、代码块、子代理，需代码轨（Track C）

### 1.3 SoK / Implicit-ID（A2–A3）

- 区分 **fingerprint（被动推断）** vs **watermark（主动嵌入）**
- 输出-only 指纹 = VerAI 主战场
- 白盒参数指纹（注意力标准差等）对 Cursor **不可用** → 文献中大量 IP 审计工作仅作背景

### 1.4 威胁模型图（文字）

```text
[用户] → Cursor Client → (云端 Auto Router) → {Model_i}
                ↓本地
        logs / tracking / hooks / transcripts
                ↓
             VerAI Observer（无服务端权限）
```

观察者可：读本地元数据、可选装 hook、对历史 turn 做被动特征、主动发探针会话。  
观察者不可：读路由策略、强制云端返回 model、在不改用户工作流下拦截全部云流量明文。

---

## 2. Track B — 被动文本归因

### 2.1 核心主张

多篇工作（B1–B4）表明：不同 LLM 族在 **POS、形态句法、词频、结构标记** 上有稳定差异，足以做**多类**归属（不只是人机二分类）。

### 2.2 对 Cursor 的可迁移性

| 因素 | 影响 |
|------|------|
| 短 turn / 工具调用密集 | 文本信号弱；需行为特征（blindtest 已有 tool batches） |
| 中英混合 + Markdown | 需多语/结构特征（B5 警示跨语系难） |
| 系统提示统一「Auto 人设」 | 可能压缩风格差；Invisible Traces 亦讨论应用层包装 |
| 无标签 Auto 样本 | 不能自标；必须用手选模型会话做 GT（见实验协议） |

### 2.3 与 blindtest 差距

现有 [`features.py`](../../verkeep_verify/blindtest/features.py)：char n-gram 哈希桶、列表/标题/代码围栏、tool 名哈希、TTFT。  
**缺失（论文级）**：显式 POS/依存统计、句子长度分布高阶矩、开场套话类型学、语义编码器嵌入（SSLA 双路）。  
**已有优势**：隐私友好（不落原文）、温度校准、阈值弃权（H6）。

---

## 3. Track C — 代码风格归因（Cursor 主战场）

Agent 产出以**代码编辑**为主；文本 AA 不足时，代码轨是提高 Auto 可解析率的关键。

### 3.1 代表工作

- **C1 CodeT5-Authorship**：C 语言多类 >95%；证明「哪家模型写的代码」可分
- **C2 LPcodedec**：命名一致性、结构、可读性等 **10 个轻量特征**——更适合嵌入 CLI
- **C3 DCAN**：语义/风格解耦，多语言（Py/Java/C/Go）——贴近 Cursor 多语言仓库

### 3.2 工程含义

- 从 transcript 代码块或 diff 提取特征（**特征入语料，代码正文不入库**）
- 最小可归因长度：文献多用完整函数/文件；Cursor 小 patch 可能需聚合多 turn 或降低置信
- `ai_code_hashes` 提供产出量但不提供 Auto 真名 → 代码指纹补的是 **model 名**，不是 hash 计数

### 3.3 开源可复用

优先评估 LPcodedec 特征集（轻）与 CodeT5-Authorship（重，可选 `[ml]` extra）。

---

## 4. Track D — 主动探针（LLMmap）

### 4.1 LLMmap（D1）

- 3–8 条精心设计 query → 闭集 42 版本 >95%
- 对系统提示、采样、RAG/CoT 有稳健性声明
- 提供开集对比学习签名

### 4.2 Cursor Auto 上的**路由污染风险**（核心否决点）

主动探针会改变「任务类型/复杂度」信号，**可能触发与真实用户 turn 不同的路由决策**。  
因此：

- **禁止**把探针结果直接当作「下一个用户 turn 的模型」
- **允许**用途：(1) 手选模型下建指纹库；(2) 周期性估计 Auto **池分布先验**；(3) 与 Invisible Traces 的 static 支路对齐
- VerAI 现有 [`fingerprint.py`](../../verkeep_verify/monitor/fingerprint.py) 面向**渠道 API**，不是 Cursor 内 Auto；复用题库思想，但会话上下文不同

### 4.3 结论

Track D = **辅路线 / 标定工具**，不是逐步归因主引擎。

---

## 5. Track E — 时序侧信道

### 5.1 Rhythm（E1）

- Inter-Token Time 序列可区分模型；加密流量下仍有信号
- 跨日/跨网 F1 下降 → 需域适应与重标定

### 5.2 与 Cursor 采集差距

| 信号 | 现状 | 缺口 |
|------|------|------|
| TTFT | structured log `ttft_ms`；blindtest 已用 | 单点弱判别 |
| ITT 序列 | **无** | 需 hook 时间戳流或本地 MITM/代理 |
| 包级 IAT | **无** | 工程重、隐私与稳定性差 |

### 5.3 结论

短期：用好 TTFT + 生成时长（若 hook `duration_ms`）。  
中期：若 hook/流式事件能提供逐 token 或分块时间，再上 ITT 分类器。  
不优先做全流量侧信道（成本与合规差）。

---

## 6. Track F — 路由行为类比

RouteMark（F1）在 MoE **专家激活**上建指纹——Cursor 无专家门控可见性。  
可迁移思想：

- 构造**固定标定任务集**（简单补全 / 重构 / 多文件 / 计划模式）
- 在 Auto 下重复运行，估计「任务类型 → 模型分布」先验
- 作为融合层的 **hierarchical prior**，而非逐步真值

---

## 7. Track G — 遥测（详见普查文档）

要点复述：

- `default` ≈ 30% 代码哈希 → 遥测不全
- Hook 常含真实 `model_id` **与 tokens** → 实现阶段应提升 hook 优先级并填 P4 字段
- 无官方逐步 Auto API

---

## 8. Track H — 融合、校准与「全量」语义

### 8.1 温度缩放（H1）与 blindtest

已有 leave-one-conversation-out 温度拟合；应保留。

### 8.2 选择性分类警告（H3）

**单调校准不改变排序**。若产品要求 Coverage=100% 且强制 top-1，会在低置信区**乱猜**。  
推荐产品形态：

```text
每个 Auto turn:
  if factual_model: label = factual; tier = fact
  elif max(p) >= τ_high: label = argmax; tier = inferred_high
  elif max(p) >= τ_low:  label = argmax; tier = inferred_low   # 仍覆盖
  else: label = argmax or "uncertain"; tier = inferred_weak
报表:
  factual_share / inferred_high_share / inferred_all_share
```

「消灭 auto-opaque」= 不再把「无事实」显示为不透明桶终态，而是 **inferred_*** 桶。

### 8.3 融合结构（对齐 Invisible Traces）

```text
P(model | turn) ∝ P_fact(model)          # one-hot if telemetry hit
                 · P_code(model | code_feats)
                 · P_text(model | text_feats)
                 · P_time(model | ttft,...)
                 · Prior_task(model | mode, complexity)
```

实现可用对数意见池或 stacking 元分类器（需标定集）。

---

## 9. 与 VerAI 模块挂钩总表

| 模块 | 现状 | 文献驱动的下一步（实现阶段） |
|------|------|------------------------------|
| `cursor_usage` auto-opaque | 终态桶 | 改为「待推断」触发 blindtest；保留 factual 优先 |
| `blindtest/features` | 轻量哈希特征 | +代码风格特征（C2）；可选 POS（B1） |
| `blindtest/corpus` | 需非 default 标签 | 手选 GT 协议；禁止 Auto 自标 |
| `blindtest/classifier` | LR+温度+阈值 | 双阈值报表；代码/文本双塔 |
| `fingerprint.py` | 渠道探针 | 不直接用于 Auto 逐步；可作池先验 |
| hooks | 已装可采 model/tokens | **事实层 P0 增强**（普查新发现） |
| `--inferred` 视图 | 可选 | 升格为 Auto 默认双轨看板 |

---

## 10. 一页结论（主 / 辅 / 弃）

| 级别 | 路线 | 理由 |
|------|------|------|
| **主** | G 强化 hook/遥测事实 + C/B 被动代码/文本归因 + H 分轨融合 | 覆盖每 turn；对齐 Invisible Traces；契合现有 blindtest |
| **辅** | D 周期探针先验；E 增强时序（duration/ITT） | 提升校准与域适应；探针不逐步套用 |
| **弃** | 白盒权重指纹、训练水印、等官方逐步 API、全流量 MITM 侧信道（默认） | 不可用或性价比/合规差 |

**诚实边界**：无法承诺与云端路由器日志 100% 一致；可承诺 **100% turn 覆盖 + 校准推断 + 事实/推断分轨**。
