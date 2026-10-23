# Changelog

## v6.1 — 2026-10-23
- 产品更名：CS2 Tool → Cross-Section
- 新增品牌标识组件：常态只显示 `CS`（即 Cross-Section 去掉小写），悬浮时 `ross-` 从中间长出、`ection` 从尾部跟出，拼成完整名称；定期播放一次电视短路效果并显示 `Counter-Strike`
- 首次以 MIT 协议开源
- 新增 `DISCLAIMER.md`：非官方与商标声明、不接触游戏进程的说明、账号状态不作保证、数据准确性免责、他人隐私提示、责任限制
- 新增 `docs/index.html`：单文件项目落地页（可直接作为 GitHub Pages 首页），桌面与 375px 手机视口实测无横向溢出
- 新增 `docs/banner.svg`：README 头图
- 新增 `RELEASE_NOTES_v6.1.md`：发布说明
- README 补全：免责警告块、隐私说明、数据存放结构、常见问题、许可与声明
- 版本号 6.0 → 6.1（`server.py` / `about.html` / 导出 CSV 文件头）
- 修复 `about.html` 侧栏 `.brand` 后代选择器会连带命中品牌组件内部片段的问题（改为 `.brand-ver` 精确限定）

### 发布物
- `Cross-Section-v6.1-Portable.zip` — 128 MB，含 Python 3.12 运行时与全部依赖
- `Cross-Section-v6.1-Source.zip` — 4.7 MB，纯源码

## 更早的版本

v6.0 及之前的版本未在公开仓库中记录 changelog（当时是私人项目）。
