# VerAI alpha brand assets

> **VerAI（读 ver-eye）**：本地看清 Cursor 这次会话主要用了哪些模型。不上传对话正文。

- 中文 tagline：看清这次会话，用了哪些模型。
- English tagline: See which models this session used.
- 图形：眼形表示“看清”，内部 V 同时像验真勾。
- 主色：冷青 `#62C8BC`；中性底 `#111820`；浅色 `#E7EFEE`。
- App icon 使用深色满版底；不要自行加渐变、发光、阴影或文字。
- Activity Bar 只用 `currentColor`；不得加入第二种颜色或小于 1px 的线。
- 深色界面用浅色轮廓；浅色界面使用 `logo/verai-mark.svg` 的默认配色。
- 社交图底部保留了可叠加二维码或链接的空区。
- 禁用风格：紫渐变、赛博霓虹、机器人脸、复杂仪表盘。
- SVG 是源文件；PNG 只从同名 SVG 导出，不在位图上二次修改。

目录：`logo/` 为主标与字标，`app/` 为应用图标，`ide/` 为单色侧栏图标，`social/` 为传播图。

## 仓库里放什么

本目录是**已定稿的产品脸**（体积小），会进 git，供 README / 扩展引用：

- `social/github-og-1280x640.png` → 仓库 README 头图
- `logo/*.svg` → README lockup
- `ide/activity-bar.svg` → 拷到 `extensions/verai-cursor/media/icon.svg`
- `app/icon-128.png` → 扩展 `package.json` `icon`

ChatGPT 多轮废稿、PSD、未压缩超大原图：**不要**丢进本目录。
