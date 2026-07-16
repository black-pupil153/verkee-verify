# VerAI Cursor Extension

侧边栏 Webview：查看**当前/最近会话**的模型占比（事实轨 vs 推断轨）。本地调用 `ai-verify … --json`，不上传对话正文。

> Cursor 无公开「Composer 会话内嵌 Tab」API；本扩展是产品化首发形态（见 [`docs/ROADMAP.md`](../../docs/ROADMAP.md)）。

## 安装前准备

需要：

- Cursor 或 VS Code 1.85+
- Python 3.9+
- 本机安装 VerAI CLI

```bash
# 在 VerAI 仓库的 ai-verify 目录执行
python -m pip install --upgrade pip
pip install -e .
command -v ai-verify
ai-verify cursor doctor
```

Windows 可用 `where ai-verify` 查找路径。如果终端能运行 CLI、Cursor
里仍提示找不到，请打开 Settings，搜索 `VerAI: AI Verify Path`，填入
`ai-verify` 可执行文件的绝对路径；也可以直接编辑设置：

```json
{
  "verai.aiVerifyPath": "/absolute/path/to/ai-verify"
}
```

## 从 VSIX 安装

1. 下载 `verai-cursor-0.1.0.vsix`。
2. 在 Cursor 打开 Extensions。
3. 点击右上角 `⋯` → **Install from VSIX…**。
4. 选择 `.vsix`，安装完成后按提示 Reload Window。
5. 点击 Activity Bar 中的 **VerAI** 图标。

也可以使用 Cursor CLI，并用实际 VSIX 路径替换示例：

```bash
cursor --install-extension ./verai-cursor-0.1.0.vsix
```

## 首次使用

扩展打开或点击 Refresh 时，会先在后台尝试导入最近 1 天数据。第一次安装
建议主动扫描最近 7 天，避免近期没有会话时面板为空：

```bash
ai-verify cursor doctor
ai-verify cursor import --since 7d
ai-verify cursor task --latest --json
```

随后打开 VerAI 侧边栏。正常情况下 10 秒内应看到最近会话、事实/推断占比
和 coverage。若没有数据，面板会显示正常空状态；若 CLI、PATH 或 JSON 契约
异常，面板会给出对应修复提示。

## 验收：面板与 CLI 一致

1. 在侧边栏选择最近会话并记录 task id、coverage 和各模型占比。
2. 在终端运行：

   ```bash
   ai-verify cursor task --latest --json
   ```

3. 对照以下字段：

   - `factual_request_shares`
   - `inferred_request_shares`
   - `factual_output_shares` / `output_shares`
   - `coverage`
   - `pending_infer_count`

显示取整可能不同，但底层比例与计数必须一致。推断轨不应写入事实轨，也不能
被描述成 Cursor 官方逐步模型真名。

## 故障排查

| 状态 | 处理方式 |
|------|----------|
| CLI not found | 设置 `verai.aiVerifyPath` 为绝对路径 |
| doctor needs fix | 在终端运行 `ai-verify cursor doctor` 并按 suggestion 修复核心数据源 |
| doctor green · N warnings | 可选源（如 proxy supplement）缺失；占比仍可加载 |
| invalid JSON | 更新本地 VerAI CLI，使版本与插件匹配 |
| import warning | 面板会继续展示缓存；在终端运行 import 查看详情 |
| No recent sessions | 执行 `ai-verify cursor import --since 7d` 扩大时间范围 |

## 开发与打包

```bash
cd extensions/verai-cursor
npm install
npm test
# A3 验收：侧边栏字段 ≡ CLI --json（需本机 ai-verify + Cursor 数据）
npm run accept
npm run package
```

`npm run package` 会先编译，再执行 `vsce package --no-dependencies`，产出
`verai-cursor-0.1.0.vsix`。`npm run accept` 用 bridge 拉 latest，再对同一
`task_id` 跑 `ai-verify cursor task <id> --json`，核对 coverage / factual_* /
inferred_*；预算 10 秒。

## 命令

| 命令 | 作用 |
|------|------|
| VerAI: Show Session Usage | 打开/刷新侧边栏 |
| VerAI: Refresh | 重新拉 doctor + tasks + latest |
| VerAI: Open Latest Session | 加载最近任务占比 |

## 隐私

- 只读本机 `~/.ai-verify` 与 Cursor 遥测元数据
- 面板不展示 prompt/response 正文
- 推断轨带 disclaimer，不得当作官方逐步真名
