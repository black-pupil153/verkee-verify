# VerAI Research — Auto 全量透视

本目录含 **2026-07-11** 长检索交付物，以及 **2026-07-12～13** 按可行性矩阵落地的实现进展说明。

## 文档索引

| 文件 | 内容 |
|------|------|
| [AUTO_TRANSPARENCY_LITREV.md](AUTO_TRANSPARENCY_LITREV.md) | 长文献综述（Track A–H）+ 主/辅/弃结论 |
| [BIB.md](BIB.md) | 48 条可引用文献与开源实现清单 |
| [TELEMETRY_FIELD_CENSUS.md](TELEMETRY_FIELD_CENSUS.md) | 本机 Cursor 3.10.20 遥测字段普查 |
| [FEASIBILITY_MATRIX.md](FEASIBILITY_MATRIX.md) | 路线可行性矩阵与实现顺序 |
| [EXPERIMENT_PROTOCOL.md](EXPERIMENT_PROTOCOL.md) | 手选 GT 标定与评估协议 |

## 一页结论

- **不能**仅靠遥测对纯 Auto 做数学级逐步真名（~30% `default`）。
- **可以**做到：每 turn **覆盖** + **事实/推断分轨** + **校准置信度**。
- **主路径**：Hook/遥测事实强化 → 代码+文本被动归因（扩展 blindtest）→ 融合进默认 Auto 报表。
- **辅路径**：周期探针先验、时序特征。
- **放弃**：白盒权重指纹、等官方逐步 API、默认全流量 MITM。

## 实现进展（2026-07-12～13）

主路径已落地产品代码（非仅研究）：

| Phase | 内容 | 状态 |
|-------|------|------|
| G | Hook `model_id` / tokens / duration → 导入事实层 | 已完成 |
| H | `factual_*` / `inferred_*` / `coverage`；`auto-opaque` → `pending-infer`；**默认 auto_infer** | 已完成 |
| C+B | blindtest 轻量代码/文本特征 + hook 标签优先级 | 已完成 |

**Phase 1 已落地并本机跑通**（split + 密封标签 + forced/selective eval）。**Phase 2**：duration_ms、通道消融、`eval-auto`；GT `cheap-gt-v2` Acc@forced **78.6%** / Acc@τ=0.7 **90%**；消融见 `PROJECT_STATUS`（text 主力，+latency 最高）。**产品化**：见 [`docs/ROADMAP.md`](../ROADMAP.md)（侧边栏插件 ∥ GT 加固）。Phase 3 微调后置。

本机验收摘要与最新数字以 [`docs/PROJECT_STATUS.md`](../PROJECT_STATUS.md) 为准（勿混 LOCO-CV 与盲评）。
