# Closed Alpha 清单（Track C）

> 目标：约 5 人 Cursor 重度用户装上侧边栏，验证「5 秒内看懂谁用得最多」。

## 给 alpha 的安装步骤（复制即可）

1. 安装本机 CLI（仓库 `pip install -e .`，保证 `ai-verify` 在 PATH）
2. 从 Release 下载 `verai-cursor-0.1.0.vsix` → Cursor **Install from VSIX…**
3. `ai-verify cursor doctor` 应为可工作状态（允许 warnings）
4. `ai-verify cursor import --since 7d`
5. 可选：`ai-verify cursor hooks install`
6. Activity Bar → **VerAI** → 选最近会话

对照：`ai-verify cursor task --latest` 与面板占比一致（读 `model_mix_v2`）。

## 问卷（两问即可）

1. 打开侧边栏后，是否 **5 秒内**看懂「哪个模型用得最多」？（是 / 否 + 一句原因）
2. 看到「部分结果为估算」或「未识别」时，是否仍信任展示？（信任 / 半信 / 不信任 + 一句）

可选反馈落盘（本机、默认不上报）：`~/.ai-verify/feedback.jsonl`。

## 我们收集什么

- doctor 是否绿、PATH / VSIX 安装卡点
- 面板与 CLI 数字是否一致
- 「不准 / 未知过高」是否连续出现 → 再触发 Track B（含 B6）

## 明确不承诺

- 推断 ≠ Cursor 官方逐步真名
- 不上传对话正文
- 不做 Composer 内嵌 Tab
