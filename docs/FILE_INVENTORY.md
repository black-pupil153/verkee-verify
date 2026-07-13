# AI Verify 文件整理索引

> 更新日期：2026-07-13

本文按用途整理 `ai-verify/` 下的项目文件，帮助后续开发时快速定位入口、核心模块、测试和本地产物。

## 目录概览

```text
ai-verify/
├── ai_verify/                 # Python 包源码
│   ├── alerts/                 # 报警与通知
│   ├── blindtest/              # Cursor Auto 底层模型盲测
│   ├── monitor/                # 验证引擎、指纹、质量题库、定时巡检
│   ├── providers/              # 上游供应商配置解析
│   ├── proxy/                  # 透明代理与被动监控
│   └── storage/                # SQLite 存储
├── docs/                       # 设计文档与规划
├── tests/                      # 单元测试
├── README.md                   # 项目说明与使用入口
├── Makefile                    # 常用开发命令
├── pyproject.toml              # 包配置、依赖、工具配置
├── requirements.txt            # 运行依赖清单
├── LICENSE                     # MIT License
├── .envrc                      # direnv 本地 venv 自动激活
└── .gitignore                  # 本地构建/缓存/虚拟环境忽略规则
```

纳入 Git 的项目文件以 `git add -n ai-verify` 预览为准。完整目录中约 24k 个文件主要来自本地虚拟环境 `venv/`，属于可重建产物，不应提交。

## 根目录文件

| 文件 | 类型 | 作用 |
| --- | --- | --- |
| `.gitignore` | 配置 | 忽略 Python 缓存、构建产物、虚拟环境、测试缓存、日志、数据库等本地文件。 |
| `.envrc` | 本地开发 | 进入目录时通过 direnv 自动激活 `venv/`，不包含密钥。 |
| `Makefile` | 开发入口 | 封装 `install`、`test`、`lint`、Cursor 导入/看板等常用命令。 |
| `README.md` | 文档 | 用户入口，包含安装、配置、主动验证、代理、看板、监控和报警用法。 |
| `pyproject.toml` | 配置 | Python 包元数据、依赖、可选依赖、`ai-verify` CLI 入口、Black/Ruff/Mypy/Pytest 配置。 |
| `requirements.txt` | 配置 | 运行依赖的传统 pip 清单。 |
| `LICENSE` | 法务 | MIT License。 |

## 源码文件

### 包入口

| 文件 | 作用 |
| --- | --- |
| `ai_verify/__init__.py` | 包版本与作者信息。 |
| `ai_verify/cli.py` | Click CLI 主入口，注册 `config`、`proxy`、`monitor`、`providers`、`run`、`check`、`score`、`history`、`alert`、`report` 等命令。 |
| `ai_verify/config.py` | `ConfigManager`，负责 `~/.ai-verify/config.yaml` 的初始化、读取、写入和嵌套配置项管理。 |
| `ai_verify/runner.py` | `ai-verify run -- <command>` 实现：读取上游、启动本地代理、注入环境变量、执行子进程并转发信号。 |
| `ai_verify/dashboard.py` | 智力打分看板：运行评测、保存 `score_snapshots`、展示最新分数和趋势火花图。 |
| `ai_verify/dashboard_cursor.py` | Cursor Auto Usage 看板：展示周期聚合、模型占比、产出占比和任务列表。 |
| `ai_verify/report.py` | 日报/周报/月报生成：聚合打分快照和代理调用统计，输出降级/异常提示。 |
| `ai_verify/cursor_logs.py` | 解析 Cursor structured logs / renderer logs，抽取请求、模型、trace、outcome 等事件。 |
| `ai_verify/cursor_hook_events.py` | 读取 Cursor hook 采集的 NDJSON 事件。 |
| `ai_verify/cursor_hooks.py` | 安装、卸载、合并和分析 Cursor hooks 配置。 |
| `ai_verify/cursor_probe.py` | 扫描 Cursor 日志和 tracking 数据，定位模型字段与任务相关证据。 |
| `ai_verify/cursor_recommend.py` | 基于使用数据和盲测结果生成 Cursor 模型选择建议。 |

### 监控与验证

| 文件 | 作用 |
| --- | --- |
| `ai_verify/monitor/__init__.py` | 监控模块导出入口。 |
| `ai_verify/monitor/engine.py` | `VerifyEngine`，整合指纹识别、质量测试、安全检查、OpenAI/Anthropic/GLM 请求发送和结果展示。 |
| `ai_verify/monitor/fingerprint.py` | `FingerprintDetector`，用反侦测探针和响应特征识别模型家族，缺少可选 ML 依赖时回退到轻量启发式。 |
| `ai_verify/monitor/quality.py` | `QualityTester`，内置数学、逻辑、代码、知识题库和模型基准分，计算质量分与偏差。 |
| `ai_verify/monitor/probes.py` | 中英混合探针题池，按 discriminative / behavioral / stylistic 分层。 |
| `ai_verify/monitor/daemon.py` | 定时巡检循环，解析 `90s`、`30m`、`6h` 等间隔，周期打分并在异常时报警。 |
| `ai_verify/monitor/cursor_usage.py` | Cursor Auto Usage 导入、证据合并、任务/周期聚合和报表渲染核心逻辑。 |
| `ai_verify/monitor/blindtest_view.py` | 将盲测推断结果与 Cursor 任务事件对齐，生成 per-turn 推断视图。 |

### Cursor 盲测

| 文件 | 作用 |
| --- | --- |
| `ai_verify/blindtest/__init__.py` | 盲测模块导出入口。 |
| `ai_verify/blindtest/features.py` | 文风 / 行为 / 时延 / 轻量代码风格特征（哈希桶，不落正文）。 |
| `ai_verify/blindtest/corpus.py` | 从 transcripts、hooks、logs、tracking DB 构建带标签语料（hook `model_id` 优先）。 |
| `ai_verify/blindtest/classifier.py` | 训练和运行底层模型风格分类器，支持 sklearn 与纯 Python 回退。 |

### 代理、存储和供应商

| 文件 | 作用 |
| --- | --- |
| `ai_verify/proxy/__init__.py` | 代理模块导出入口。 |
| `ai_verify/proxy/server.py` | `ProxyServer`，透明转发普通/SSE 流式请求，解析响应模型与 usage，记录 API 调用，检测模型替换、短响应、高延迟等异常。 |
| `ai_verify/storage/__init__.py` | 存储模块导出入口。 |
| `ai_verify/storage/database.py` | `Database`，管理 SQLite 表：`api_calls`、`quality_tests`、`anomalies`、`score_snapshots`，并提供历史、统计和打分快照读写。 |
| `ai_verify/providers/__init__.py` | 供应商模块导出入口。 |
| `ai_verify/providers/cc_switch.py` | 读取 CC Switch、Claude settings 或 ai-verify config，解析当前上游 `ProviderConfig`。 |
| `ai_verify/providers/cursor.py` | 发现 Cursor 本地路径，探测 ai-tracking、logs、composer headers、agent transcripts 等数据源。 |

### 报警与通知

| 文件 | 作用 |
| --- | --- |
| `ai_verify/alerts/__init__.py` | 报警模块导出入口。 |
| `ai_verify/alerts/webhook.py` | `AlertManager`、`WebhookAlerter` 和 `Alert`，支持飞书、钉钉、企业微信、Slack、通用 Webhook。 |
| `ai_verify/alerts/notify.py` | 系统通知与简单 Webhook 通知辅助函数。 |

## 测试文件

| 文件 | 覆盖范围 |
| --- | --- |
| `tests/__init__.py` | 测试包标记。 |
| `tests/test_engine.py` | API 类型识别、端点拼接、模型匹配、综合分惩罚、安全检查。 |
| `tests/test_fingerprint.py` | 探针题池、敏感句式规避、模型家族判断、可选 ML 依赖回退。 |
| `tests/test_quality.py` | 数字/精确/包含/代码匹配、基准选择、mock client 质量测试。 |
| `tests/test_proxy.py` | OpenAI/Anthropic SSE 解析、JSON 提取、响应头过滤、异常检测。 |
| `tests/test_cc_switch.py` | CC Switch env 提取、必要字段校验、密钥脱敏、当前供应商读取。 |
| `tests/test_misc.py` | 巡检间隔解析、看板火花图和分数颜色。 |
| `tests/test_cursor_paths.py` | Cursor 路径发现、ai-tracking schema、structured logs、doctor 检查。 |
| `tests/test_cursor_logs.py` | Cursor structured logs、renderer logs、trace line 解析。 |
| `tests/test_cursor_hooks.py` | Cursor hooks 安装、卸载、合并和 probe NDJSON 分析。 |
| `tests/test_cursor_probe.py` | Probe 日志扫描、模型字段抽取和任务过滤。 |
| `tests/test_cursor_usage.py` | Cursor 事件导入、去重、证据合并、任务聚合、hook 补采。 |
| `tests/test_cursor_report.py` | Cursor 报告、质量分关联和任务评分表渲染。 |
| `tests/test_dashboard_cursor.py` | Cursor 看板周期聚合和 Rich 视图渲染。 |
| `tests/test_blindtest_features.py` | 盲测特征提取的稳定性、文本结构、行为和延迟特征。 |
| `tests/test_blindtest_corpus.py` | transcripts 分段、日志/tracking 标签合并、语料保存加载。 |
| `tests/test_blindtest_classifier.py` | 盲测分类器训练、阈值、保存加载、纯 Python 回退。 |
| `tests/test_blindtest_view.py` | 盲测推断视图、版本过滤、任务前缀匹配和 CLI smoke。 |
| `tests/fixtures/cursor/create_ai_tracking_sample.py` | 生成 Cursor ai-tracking 测试样本库。 |
| `tests/fixtures/cursor/structured_log_sample.log` | Cursor structured log 解析测试夹具，作为 `.log` 例外纳入 Git。 |

## 文档与规划

| 文件 | 作用 |
| --- | --- |
| `docs/CURSOR_AUTO_USAGE.md` | Cursor Auto Usage 的数据源、置信度、隐私边界与验收记录（P0–P2.5 已落地）。 |
| `docs/research/` | Auto 全量透视长检索：综述、文献库、遥测普查、可行性矩阵、实验协议。 |
| `docs/FILE_INVENTORY.md` | 本文件，整理当前项目文件职责与维护边界。 |
| `docs/PROJECT_STATUS.md` | 当前阶段、验证结果、产品决策、关键边界与下一会话执行入口。 |

## 本地产物

| 路径 | 状态 | 处理建议 |
| --- | --- | --- |
| `venv/` | 本地虚拟环境，约 749M、约 24k 个文件。 | 可由 `python -m venv venv && pip install -e ".[dev]"` 重建，已被 `.gitignore` 忽略，无需提交。 |
| `.pytest_cache/` | Pytest 缓存，约 20K。 | 可删除或由下一次测试自动重建，已被 `.gitignore` 忽略，无需提交。 |
| `.ruff_cache/` | Ruff 缓存。 | 可删除或由下一次 lint 自动重建，已被 `.gitignore` 忽略，无需提交。 |

## 维护边界

- 新增 CLI 命令优先放在 `ai_verify/cli.py`，复杂业务逻辑拆到对应功能模块，CLI 只做参数解析和编排。
- 与 API 调用、模型识别、质量评分相关的逻辑优先放在 `ai_verify/monitor/`。
- 与被动流量采集相关的逻辑优先放在 `ai_verify/proxy/server.py`，持久化统一走 `ai_verify/storage/database.py`。
- 与渠道读取相关的逻辑放在 `ai_verify/providers/`，避免把特定工具的探测逻辑塞进通用验证引擎。
- 与 Cursor Auto Usage 相关的导入/聚合逻辑集中在 `ai_verify/monitor/cursor_usage.py`，路径发现集中在 `ai_verify/providers/cursor.py`。
- 与盲测相关的语料、特征、分类器集中在 `ai_verify/blindtest/`，展示层放在 `ai_verify/monitor/blindtest_view.py`。
- 测试文件与源码模块保持对应；改动核心模块时，优先补充相邻的 `tests/test_*.py`。
