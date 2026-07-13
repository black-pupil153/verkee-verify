# VerAI Cursor Extension

侧边栏 Webview：查看**当前/最近会话**的模型占比（事实轨 vs 推断轨）。本地调用 `ai-verify … --json`，不上传对话正文。

> Cursor 无公开「Composer 会话内嵌 Tab」API；本扩展是产品化首发形态（见 [`docs/ROADMAP.md`](../../docs/ROADMAP.md)）。

## 前置

```bash
# 仓库根目录
pip install -e .
which ai-verify   # 或在设置里填 verai.aiVerifyPath
ai-verify cursor doctor
ai-verify cursor import --since 7d
```

## 开发 / 打包

```bash
cd extensions/verai-cursor
npm install
npm run compile
npx vsce package --no-dependencies
```

在 Cursor：Extensions → `⋯` → Install from VSIX → 选生成的 `.vsix`。

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
