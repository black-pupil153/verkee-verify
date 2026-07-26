<p align="center">
  <img src="media/app-icon-128.png" alt="Verkee Verify" width="96" />
</p>

# Verkee Verify Cursor Extension（原 VerAI）

**守真·验 Verkee Verify**：本地看清 Cursor 这次会话主要用了哪些模型。不上传对话正文。

侧边栏展示当前/最近会话的统一调用次数构成；确认/估算拆分在折叠细则里，不占默认主视图。

> Cursor 无公开「Composer 会话内嵌 Tab」API；本扩展是产品化首发形态（见 [`docs/ROADMAP.md`](../../docs/ROADMAP.md)）。

## 安装前准备

需要：

- Cursor 或 VS Code 1.85+
- Python 3.9+
- 本机安装 Verkee Verify CLI

```bash
# 在 verkee-verify 仓库根目录执行
python -m pip install --upgrade pip
pip install -e .
command -v verkee-verify
verkee-verify cursor doctor
```

Windows 可用 `where verkee-verify` 查找路径。如果终端能运行 CLI、Cursor
里仍提示找不到，请打开 Settings，搜索 `verai.aiVerifyPath`，填入
`verkee-verify` 可执行文件的绝对路径；也可以直接编辑设置：

```json
{
  "verai.aiVerifyPath": "/absolute/path/to/verkee-verify"
}
```

## 从 VSIX 安装

1. 从 [GitHub Releases](https://github.com/black-pupil153/VerAI/releases) 下载  
   `verai-cursor-0.1.0.vsix`（或本机 `npm run package` 产物）。
2. 在 Cursor 打开 Extensions。
3. 点击右上角 `⋯` → **Install from VSIX…**。
4. 选择 `.vsix`，安装完成后按提示 Reload Window。
5. 点击 Activity Bar 中的 **Verkee Verify** 图标。

也可以使用 Cursor CLI，并用实际 VSIX 路径替换示例：

```bash
cursor --install-extension ./verai-cursor-0.1.0.vsix
```

## 首次使用

扩展打开或点击 Refresh 时，会先在后台尝试导入最近 1 天数据。第一次安装
建议主动扫描最近 7 天，避免近期没有会话时面板为空：

```bash
verkee-verify cursor doctor
verkee-verify cursor import --since 7d
verkee-verify cursor task --latest --json
```

**可选但推荐**：安装 Cursor hooks，提高 Auto 会话的事实覆盖（仍非云端逐步真名）：

```bash
verkee-verify cursor hooks install
```

安装后新开或继续会话，再点侧边栏 Refresh。卸载用 `verkee-verify cursor hooks uninstall`。

随后打开 Verkee Verify 侧边栏。正常情况下 5 秒内应看懂「哪个模型用得最多」。
若没有数据，面板会显示正常空状态；若 CLI、PATH 或 JSON 契约异常，面板会
给出对应修复提示。

## 验收：面板与 CLI 一致

1. 在侧边栏选择最近会话并记录各模型调用占比。
2. 在终端运行：

   ```bash
   verkee-verify cursor task --latest --json
   ```

3. 优先对照 `model_mix_v2`（`total_calls`、各模型 `call_count` / `pct`）。
   旧字段 `factual_*` / `inferred_*` / `coverage` 仍会返回，供诊断与兼容。

显示取整可能不同，但底层比例与计数必须一致。估算不得伪装成已确认，也不能
被描述成 Cursor 官方逐步模型真名。

## 故障排查

| 状态 | 处理方式 |
|------|----------|
| CLI not found | 设置 `verai.aiVerifyPath` 为绝对路径 |
| doctor needs fix | 在终端运行 `verkee-verify cursor doctor` 并按 suggestion 修复核心数据源 |
| doctor green · N warnings | 可选源（如 proxy supplement）缺失；占比仍可加载 |
| invalid JSON | 更新本地 Verkee Verify CLI，使版本与插件匹配 |
| import warning | 面板会继续展示缓存；在终端运行 import 查看详情 |
| No recent sessions | 执行 `verkee-verify cursor import --since 7d` 扩大时间范围 |
| 大量「未识别」 | 试 `verkee-verify cursor hooks install` 后新开会话；Refresh 再看 |

## 开发与打包

```bash
cd extensions/verai-cursor
npm install
npm test
# A3 验收：侧边栏字段 ≡ CLI --json（需本机 verkee-verify + Cursor 数据）
npm run accept
npm run package
```

`npm run package` 会先编译，再执行 `vsce package --no-dependencies`，产出
`verai-cursor-0.1.0.vsix`。`npm run accept` 用 bridge 拉 latest，再对同一
`task_id` 跑 `verkee-verify cursor task <id> --json`，核对 `model_mix_v2` 与
legacy 分轨字段；预算 10 秒（可设 `VERAI_AI_VERIFY_PATH`）。

## 命令

| 命令 | 作用 |
|------|------|
| Verkee Verify: Show Session Usage | 打开/刷新侧边栏 |
| Verkee Verify: Refresh | 重新拉 doctor + tasks + latest |
| Verkee Verify: Open Latest Session | 加载最近任务占比 |

## 隐私

- 只读本机 `~/.verkee/verify` 与 Cursor 遥测元数据
- 面板不展示 prompt/response 正文
- 估算来源仅在折叠细则中展示，不得当作官方逐步真名
