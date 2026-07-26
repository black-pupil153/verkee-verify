# VerAI Auto 透视 — 文献库（BIB）

> 更新日期：2026-07-11  
> 条目数：48  
> 评分 **Mig**：对 Cursor Auto 黑盒逐步归因的可迁移性 1–5  
> 场景：W=白盒权重 / B=黑盒 API / A=应用层 GenAI / N=网络侧信道 / C=校准理论

每条格式：`ID | 年份 | Mig | 场景 | 标题 | 链接 | 一句话`

---

## Track A — 问题边界 / GenAI 应用指纹

| ID | 年 | Mig | 场景 | 标题 | 链接 | 摘要 |
|----|----|-----|------|------|------|------|
| A1 | 2025 | 5 | A | Invisible Traces: Hybrid Fingerprinting in GenAI Apps | https://arxiv.org/abs/2501.18712 | 静态探针+动态被动观察融合，专打多代理/动态路由应用 |
| A2 | 2025 | 4 | B/W | Implicit Identity Technologies for LLMs (survey) | https://arxiv.org/html/2605.29245 | Implicit-ID 统一抽象：指纹 vs 水印；输出-only 归因专章 |
| A3 | 2025 | 3 | W/B | SoK: LLM Copyright Auditing via Fingerprinting | https://arxiv.org/html/2508.19843 | 版权审计 SoK；白盒/黑盒指纹分类与攻击面 |
| A4 | 2025 | 5 | A | Cursor forum: Show model per Auto step | https://forum.cursor.com/t/164163 | 官方：Auto 不暴露逐步模型；需求与 VerAI 完全对齐 |
| A5 | 2025 | 5 | A | Cursor forum: Auto-model mechanism | https://forum.cursor.com/t/159697 | Auto 按任务/负载动态换模型；非单一 benchmark 模型 |
| A6 | 2024 | 4 | A | Cursor: Transparency on auto model selection | https://forum.cursor.com/t/66961 | 长期用户诉求；agent 被指示不暴露内部 alias |
| A7 | 2024 | 3 | B | Instructional fingerprinting / backdoor triggers (IP) | https://arxiv.org/abs/2401.12255 | 触发器式所有权指纹（需训练注入；对 Cursor 不可用） |

---

## Track B — 被动文本风格 / 多类归因

| ID | 年 | Mig | 场景 | 标题 | 链接 | 摘要 |
|----|----|-----|------|------|------|------|
| B1 | 2025 | 5 | B | Your LLMs are Leaving Fingerprints | https://aclanthology.org/2025.genaidetect-1.6 | POS/形态句法指纹可多类区分模型族；跨域相对稳 |
| B2 | 2025 | 4 | B | Detecting Stylistic Fingerprints of LLMs | https://arxiv.org/abs/2503.01659 | 三分类器集成；高 precision 低 FP；见/未见模型 |
| B3 | 2025 | 4 | B | DA-MTL: Multi-Task Detection and Attribution | https://arxiv.org/abs/2508.14190 | 检测+归因多任务；共享表示 |
| B4 | 2026 | 4 | B | SSLA: Stylometric-Semantic Dual-Path | https://aclanthology.org/2026.findings-acl.1855 | 风格+语义双路注意力；Macro-F1 高 |
| B5 | 2025 | 3 | B | Multilingual MGT Authorship Attribution | https://arxiv.org/abs/2508.01656 | 18 语言×多生成器；跨语系迁移难 |
| B6 | 2023 | 3 | B | Ghostbuster: Detecting Text Ghostwritten by LLMs | https://arxiv.org/abs/2305.15047 | 概率特征检测；可作特征灵感非多类 SOTA |
| B7 | 2023 | 3 | B | DetectGPT / zero-shot MGT detection | https://arxiv.org/abs/2301.11305 | 曲率检测；偏二分类 |
| B8 | 2024 | 4 | B | Who Wrote this Code?（及相关文本 AA 综述脉络） | https://arxiv.org/abs/2403.00686 | 生成文本作者识别方向入口 |
| B9 | 2024 | 3 | B | Raidar / RAID benchmarks for MGT | https://arxiv.org/abs/2405.07940 | 评测基准；用于对比稳健性 |
| B10 | 2025 | 4 | B | FDLLM / LoRA-based black-box fingerprinting | 检索关键词 FDLLM LoRA fingerprint | 用适配器做黑盒文本源识别 |
| B11 | 2024 | 3 | B | Outfox / Deepfake-MGT datasets | 多数据集 | 训练多类分类器的公开语料来源 |
| B12 | 2026 | 3 | B | GPTZero industrial detection | https://arxiv.org/abs/2602.13042 | 工业检测架构；偏人机二分类 |

---

## Track C — 代码风格计量

| ID | 年 | Mig | 场景 | 标题 | 链接 | 摘要 |
|----|----|-----|------|------|------|------|
| C1 | 2025 | 5 | B | I Know Which LLM Wrote Your Code Last Summer | https://arxiv.org/abs/2506.17323 | CodeT5-Authorship + LLM-AuthorBench；多类 >95%（C） |
| C2 | 2025 | 5 | B | LPcodedec: LLM-paraphrased code detection | https://arxiv.org/abs/2502.17749 | 10 个编码风格特征；识别哪家 LLM 改写 |
| C3 | 2026 | 5 | B | Code Fingerprints: DCAN disentangled attribution | https://arxiv.org/abs/2603.04212 | 语义/风格解耦；多语言代码归因基准 |
| C4 | 2025 | 4 | B | CoDet-M4: multi-lingual multi-generator code detect | https://arxiv.org/abs/2503.13733 | 人机代码检测；跨语言/域 |
| C5 | 2024 | 3 | B | Detecting LLM-generated code surveys / baselines | 关键词 LLM generated code detection | 二分类基线；可扩展多类 |
| C6 | 2025 | 4 | B | H-AIRosetta / large code stylometry corpora | 关键词 H-AIRosettaMP | 大规模多语言代码风格语料 |
| C7 | 2023 | 2 | B | Classic code authorship (AST n-grams) | 软件工程 AA 经典 | 非 LLM 但特征可迁移 |

---

## Track D — 主动探针

| ID | 年 | Mig | 场景 | 标题 | 链接 | 摘要 |
|----|----|-----|------|------|------|------|
| D1 | 2025 | 4 | A | LLMmap (USENIX Security 25) | https://arxiv.org/abs/2407.15847 | 3–8 探针识别 42 版本 >95%；应用层稳健 |
| D2 | 2024 | 3 | B | PROFess / prompt-based model fingerprinting | 关键词 prompt fingerprint LLM version | 主动问答差异 |
| D3 | 2024 | 2 | W | Intrinsic Fingerprint / attention std patterns | https://arxiv.org/abs/2507.03014 | 权重层统计；Cursor 不可用 |
| D4 | 2024 | 2 | W | Instructional fingerprinting watermarks | https://arxiv.org/abs/2401.12255 | 需训练注入 |
| D5 | 2023 | 3 | B | LLM version identification via quirks | 安全社区/博客聚合 | 知识截止、特殊 token 行为 |
| D6 | — | 4 | A | VerAI `fingerprint.py` 渠道探针 | 仓库内 | 已有反侦测探针；可对照 LLMmap 升级 |
| D7 | 2026 | 5 | A/B | One Token Is Enough / PAMELA（Bruckner） | https://arxiv.org/abs/2607.10252 · Zenodo [data](https://doi.org/10.5281/zenodo.21278557) / [code](https://doi.org/10.5281/zenodo.21278793) | 单 token 回答分布作行为指纹；盲测用为廉价特征通道（ROADMAP B6）；家族 LOO≈60%，验证 EER≈7% 需参考 |

---

## Track E — 时序 / 侧信道

| ID | 年 | Mig | 场景 | 标题 | 链接 | 摘要 |
|----|----|-----|------|------|------|------|
| E1 | 2025 | 4 | N | LLMs Have Rhythm (ITT + traffic) | https://arxiv.org/abs/2502.20589 | Inter-token times 指纹；跨网络 F1~0.7–0.85 |
| E2 | 2024 | 3 | N | Remote Timing Attacks on Efficient LM Inference | https://arxiv.org/abs/2410.17175 | 推测解码引入可利用时序 |
| E3 | 2025 | 2 | N | Whisper Leak (packet size/IAT → topic) | https://arxiv.org/abs/2511.03675 | 偏内容推断；特征可借鉴 |
| E4 | 2024 | 3 | N | Token-length side channels in streaming | Weiss et al. 及相关 | 包长↔token |
| E5 | 2025 | 3 | B | TTFT as weak model discriminator | 工程观察+E1 | 单标量弱；需序列 ITT |
| E6 | — | 3 | A | Cursor structured `ttft_ms` | VerAI 已采 | 仅有 TTFT，无完整 ITT |

---

## Track F — 路由 / MoE 类比

| ID | 年 | Mig | 场景 | 标题 | 链接 | 摘要 |
|----|----|-----|------|------|------|------|
| F1 | 2025 | 3 | W | RouteMark: routing fingerprints for MoE merge | https://arxiv.org/abs/2508.01784 | RSF/RPF 路由行为指纹；思想可迁到标定任务集 |
| F2 | 2024 | 2 | W | MoE expert attribution / merging IP | RouteMark 引用链 | 白盒为主 |
| F3 | 2024 | 3 | A | LLM routers / RouteLLM 等路由系统 | 关键词 RouteLLM | 理解 Auto 类路由器目标函数 |
| F4 | 2025 | 3 | A | Invisible Traces 中的 dynamic routing 挑战节 | A1 内文 | 动态换模破坏单一指纹假设 |

---

## Track H — 校准 / 选择性分类 / 融合

| ID | 年 | Mig | 场景 | 标题 | 链接 | 摘要 |
|----|----|-----|------|------|------|------|
| H1 | 2017 | 5 | C | On Calibration of Modern Neural Networks (temp scaling) | https://arxiv.org/abs/1706.04599 | 温度缩放；blindtest 已用同类思想 |
| H2 | 2022 | 4 | C | Calibrated Selective Classification | https://arxiv.org/abs/2208.12084 | 选择性校准；拒识不确定样本 |
| H3 | 2025 | 5 | C | What Does It Take to Build a Performant Selective Classifier? | https://arxiv.org/abs/2510.20242 | 单调校准不改排序；全量覆盖需慎用强制 top-1 |
| H4 | 2022 | 3 | C | SelectiveNet / abstention literature | 经典选择性分类 | 覆盖-精度权衡 |
| H5 | 2024 | 4 | C | Evidence fusion / late fusion ensembles | 多模态融合综述入口 | stylometry⊕timing⊕telemetry |
| H6 | — | 5 | A | VerAI blindtest temperature + threshold=0.7 | 仓库 | 已有校准与弃权；需升格产品语义 |

---

## 开源实现清单（Track B/C/D）

| 项目 | 轨道 | 链接/定位 | 备注 |
|------|------|-----------|------|
| LLM-AuthorBench / CodeT5-Authorship | C | https://github.com/LLMauthorbench | C 代码多类归因 |
| LPcodedec | C | https://github.com/Shinwoo-Park/detecting_llm_paraphrased_code_via_coding_style_features | 风格特征轻量 |
| LLMmap code | D | 论文配套（USENIX 25） | 主动探针查询集 |
| Multilingual-MGT-AA | B | https://github.com/MLNTeam-Unical/Multilingual-MGT-AA | 多语归因基线 |
| VerAI blindtest | B/E | `verkee_verify/blindtest/` | 本地可扩展底座 |

---

## 覆盖统计

| Track | 条目数 | 精读优先（Mig≥4） |
|-------|-------:|-------------------|
| A | 7 | A1 A2 A4 A5 A6 |
| B | 12 | B1–B4 B8 B10 |
| C | 7 | C1–C4 C6 |
| D | 6 | D1 D6 |
| E | 6 | E1 E2 |
| F | 4 | F1 F4 |
| H | 6 | H1 H2 H3 H6 |
| **合计** | **48** | — |
