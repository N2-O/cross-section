# 免责声明 · Disclaimer

> 本文件是使用本软件（Cross-Section）的前提条件。下载、解压、运行或以任何方式使用，即视为你已阅读、理解并接受以下全部条款。不接受请删除本软件。

**中文为準 · The Chinese text prevails.**

---

## 1. 非官方 · 与 Valve 无关联

Cross-Section 是一个**第三方、非官方、独立开发**的工具。

- 本项目与 **Valve Corporation**（下称 Valve）**没有任何关联**，未获其授权、许可、赞助或背书。
- `Counter-Strike`、`CS2`、`Counter-Strike 2`、`Valve`、`Steam` 及相关标识、名称、图像，均为 Valve 的商标或注册商标。本项目对这些名称的使用**仅用于指称其对应的游戏产品**（合理使用），不主张任何权利。
- 图标（`cs2tool/web/icons/`）与地图雷达底图（`cs2tool/web/maps/`）来自 Counter-Strike 2 客户端资源，版权归 Valve。它们随包分发**仅为让工具能离线显示**，不构成对任何权利的主张、转让或许可。
- **如 Valve 或任何权利人提出异议**，作者将立即移除上述目录，工具其余功能不受影响（图标与地图将显示为空白）。权利人对本项目无任何明示或默示的认可。

---

## 2. 不接触游戏 · 不是作弊工具

Cross-Section **不是**外挂、辅助、脚本或任何形式的作弊工具，它不提供任何游戏内的不公平优势。

技术事实：

| 它做的事 | 它不做的事 |
|---|---|
| 读取磁盘上已存在的 `.dem` 录像文件 | 不读取游戏进程内存 |
| 用开源解析库离线计算统计 | 不注入 DLL、不 hook API |
| 在你自己电脑上生成网页报告 | 不修改任何游戏文件或配置 |
| 全部数据处理在本机完成 | 不模拟输入、不代打、不自动瞄准 |

**关于反作弊（VAC / 平台反作弊）**：
由于本软件与游戏客户端之间**不存在任何交互**，设计上不构成被检测的行为。
但请明确——**本软件无法、也不会对任何账号状态做出任何形式的保证**。反作弊系统的策略、判定与执行不由本项目控制，可能随时变化。**使用本软件的风险由你自己承担。**

---

## 3. 数据不保证准确

- 所有统计基于第三方开源解析库（[awpy](https://github.com/pnxenopoulos/awpy)）输出的数据集，本项目在其之上做二次计算与呈现。
- 指标口径尽量对齐公开可查的定义（如 HLTV 公开的 Rating 2.0 公式），但**不保证**与任何第三方平台（HLTV、Leetify、Faceit/5E/完美等平台自带统计）的数值一致——各家口径、样本窗口、伤害封顶方式都可能不同。
- 部分指标（残局、跳跃击杀、每武器命中率、保枪判定）是在库的现有字段不足时**自行重建**的推算值，存在误差可能。
- 无公开公式的指标（如 Rating 3.0）**本项未实现**，以避免给出无法复核的数字。
- **数据仅供自我参考。** 不得用于赌博、投注、赛事裁决、职业选拔、账号交易、或任何涉及金钱及人身权益的决策。因以上述用途使用本软件产生的任何后果，作者不承担责任。

---

## 4. 本地运行 · 你的数据不出门

- 本软件**不上传、无遥测、无账号体系**。程序会发起**唯一一个**对外请求：读取 GitHub 公开 API 上的最新版本号，仅用于在界面上提示是否有更新。该请求不携带任何本地数据、不含 cookie、不含设备或用户标识，也不构成任何形式的使用统计。除此之外，程序不发起任何外部网络请求；唯一的其它网络行为是**你自己**在浏览器里访问 `http://127.0.0.1:8790`。
- 全部统计存储在你本机的单个 SQLite 文件（`data/cs2.db`）中，删除程序目录即清除。
- **但请注意**：`.dem` 录像文件本身包含**其他玩家**的 SteamID 与昵称。你导出的 CSV、截图、回放数据同样包含这些信息。**在公开分享前，请自行评估是否涉及他人隐私**；由此产生的责任由分享者自行承担，与作者无关。
- 作者无法访问、也不会索取你的任何对局数据。

---

## 5. 责任限制

- 本软件按 **「现状」（AS IS）** 提供，不附带任何明示或默示的担保，包括但不限于适销性、特定用途适用性、无侵权、无错误、不中断。
- 在适用法律允许的最大范围内，作者**不对**因使用或无法使用本软件而产生的任何直接、间接、附带、特殊、惩罚性或后果性损害承担责任，包括但不限于：数据丢失、账号被处罚、设备损坏、利润损失、名誉损害、第三方索赔。
- **使用前请自行备份 `data/` 目录。**
- 本软件为个人业余项目，**不承诺**提供任何形式的技术支持、缺陷修复、更新或维护。

---

## 6. 第三方组件与许可

- 本项目自身代码以 **MIT License** 发布，全文见 [LICENSE](LICENSE)。
- 第三方依赖（Python 运行时、awpy、polars、demoparser2、typer 等）**遵循其各自许可证**，本项目不重新授权它们。完整清单见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。
- MIT 许可**不授予**任何商标使用权。你不得使用本项目名称、作者名义或任何标识为你的衍生作品背书或作推广。
- 分发本软件或其修改版本时，你须保留 `LICENSE` 与 `THIRD-PARTY-NOTICES.md`，并自行确保符合其中列出的全部第三方许可条款。

---

## 7. 使用合规

- 你应自行确认：在你所在的国家或地区，使用、分发本类软件是否合法合规。
- 你不得将本软件用于任何违反游戏服务条款、侵犯他人隐私、或违反当地法律法规的目的。
- 若你所在平台的服务条款禁止第三方解析录像，请勿使用本软件。

---

## 8. 变更与终止

- 作者可**随时**修改、暂停、限制或永久停止本项目的开发与分发，无需事先通知，也无需说明理由。
- 本项目可能随时被删除、转为私有或变更许可（已发布的 MIT 版本不追溯）。
- 本免责声明可能随版本更新，最新版本以仓库内本文件为准。

---

## 9. 无担保的口径声明

本项目中的"能力画像"（Ability）等衍生评分，是**基于事件的启发式重构**，不是任何官方或行业标准评分体系，不同版本之间可能因算法调整而产生数值漂移。请勿将其当作对个人能力的客观评级。

---

## English Summary (non-binding)

Cross-Section is an **unofficial, third-party** local tool for analyzing Counter-Strike 2 demo files. It is **not affiliated with, authorized by, or endorsed by Valve Corporation**. Counter-Strike, CS2 and related marks are trademarks of Valve Corporation. Game assets (icons, radar images) are included solely for offline display and remain the property of Valve; they will be removed upon any objection from the rights holder.

This software **does not interact with the game client**: it only reads `.dem` files already on your disk, performs offline computation, and produces a local report. It does **not** read game memory, inject code, hook APIs, modify game files, or provide any in-game advantage. It is **not a cheat**. However, **no guarantee of any kind is made regarding your account status** — anti-cheat policies are outside the author's control, and you use this software at your own risk.

All statistics are derived from third-party open-source parsing libraries and **are not guaranteed to be accurate**, complete, or consistent with any other platform's numbers. They are for personal reference only and must not be used for gambling, betting, competitive rulings, or any decision involving money or personal rights.

The software **uploads nothing**, collects **no telemetry**, and requires **no account**. It makes exactly **one** outbound request: fetching the latest release version from GitHub's public API, used solely to show an update indicator in the UI. That request carries no local data, no cookies, and no device or user identifiers. It is not analytics. Your data stays on your machine. Note that demo files contain other players' Steam IDs and nicknames — you are responsible for evaluating privacy implications before sharing any export.

The software is provided **"AS IS"**, without warranty of any kind. To the maximum extent permitted by law, the author is **not liable** for any damages arising from its use, including data loss, account penalties, or third-party claims.

Project code is licensed under the **MIT License**; third-party components remain under their own licenses. The MIT license grants **no trademark rights**.

---

<div align="right"><sub>Cross-Section · v6.1 · 2026</sub></div>
