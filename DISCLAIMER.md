# 免责声明与使用条款

**Cross-Section** · 版本 v6.1 · 生效日期 2026-10-23

> 本文件构成使用本软件的前提条件。请在使用前完整阅读。
> 中文版本为准，英文摘要仅供参阅。

---

## 定义

**1.1** 「本软件」指 Cross-Section 项目的全部内容，包括源代码、二进制发行包、可执行文件、文档及其后续版本。

**1.2** 「作者」指本软件著作权的持有人。

**1.3** 「用户」指下载、安装、复制、运行或以其他任何方式使用本软件的自然人或法人。

**1.4** 「游戏素材」指本软件 `cs2tool/web/icons/` 与 `cs2tool/web/maps/` 目录下的全部图像文件及其衍生数据。

**1.5** 「第三方组件」指本软件所依赖、但非由作者编写的软件库、运行时及数据。

---

## 第一条 条款的接受

**1.1** 用户下载、解压、安装、运行或以其他任何方式使用本软件，即视为已完整阅读、理解并同意本文件全部条款。

**1.2** 用户不同意本文件任何条款的，应当立即停止使用，并删除本软件的全部副本。

---

## 第二条 非官方声明与商标

**2.1** 本软件为第三方独立开发项目，与 Valve Corporation（以下称「Valve」）不存在任何关联关系，未获其授权、许可、赞助或背书。

**2.2** `Counter-Strike`、`Counter-Strike 2`、`CS2`、`Valve`、`Steam` 及相关名称、标识、图像，均为 Valve 的商标或注册商标。相关权利归 Valve 所有。

**2.3** 本软件对上述名称的使用，仅限于指称其所对应的游戏产品（即描述性合理使用），不构成对任何权利的取得、主张、转让或许可。

**2.4** 游戏素材来源于 Counter-Strike 2 客户端资源，著作权归 Valve。该等素材随本软件分发，目的仅限于使本软件能够在离线状态下完成界面显示，不构成对任何权利的许可。

**2.5** 如 Valve 或任何权利人提出异议，作者将立即移除游戏素材所涉目录。移除后本软件其余功能不受影响，相关图标与地图将显示为空白。

**2.6** 本软件未获 Valve 认证、测试或批准，不构成 Valve 对任何事项的认可。

---

## 第三条 软件性质与使用方式

**3.1** 本软件的功能范围为：读取用户本地磁盘上已存在的 Counter-Strike 2 录像文件（`.dem`），在用户本机完成离线解析与统计，并生成本地报告。

**3.2** 本软件不实施、亦不具备以下能力：

- 读取或写入游戏客户端进程内存；
- 向游戏进程注入代码、加载动态链接库或挂钩（hook）系统或图形接口；
- 修改、替换、删除游戏文件或游戏配置；
- 模拟用户输入、自动执行游戏操作、提供自动瞄准或透视等辅助功能；
- 与游戏客户端建立任何形式的运行时通信。

**3.3** 本软件不提供任何游戏内的竞争优势，不属于外挂、辅助、脚本或任何形式的作弊工具。

**3.4** 关于反作弊系统（包括但不限于 Valve Anti-Cheat 及第三方平台的同类系统）：

- 本软件与游戏客户端之间不存在运行时交互，其设计与上述系统的检测对象无交集；
- 但上述系统的检测策略、判定标准及执行方式由第三方独立决定并可能随时变更，**作者无法控制，亦无法预知**；
- 因此，**作者不对用户的任何账号状态作出任何明示或默示的保证**。用户使用本软件所产生的一切账号相关后果，由用户自行承担。

---

## 第四条 数据准确性与使用限制

**4.1** 本软件的统计结果基于第三方开源解析库（awpy 等）所输出的数据集，由作者在其基础上进行二次计算与呈现。

**4.2** 本软件不保证统计结果的准确性、完整性、及时性，亦不保证其与任何第三方平台（包括但不限于 HLTV、Leetify、Faceit、完美世界竞技平台、5E 对战平台）所公布的数值一致。各方的统计口径、样本窗口与计算方式可能存在差异。

**4.3** 本软件中部分指标（包括但不限于残局次数、跳跃击杀、每武器命中率、保枪判定）系在第三方库现有字段不足时，依据事件流重建的推算值，存在误差可能。

**4.4** 对于无公开计算标准的指标（如 Rating 3.0），本软件不予实现，以避免提供无法复核的数值。

**4.5** 本软件中的能力评估类指标系基于事件的启发式模型输出，不构成对任何个人竞技水平的客观评价，亦不代表任何官方或行业标准。不同版本之间可能因算法调整而产生数值差异。

**4.6** 统计结果仅供用户个人参考。**用户不得将本软件的输出用于下列用途**：

- 赌博、投注或任何以金钱为标的的活动；
- 赛事裁决、争议判定或成绩认定；
- 职业选手选拔、招募或能力评估；
- 账号、代练、教学等服务的宣传与定价依据。

因用户将本软件用于上述用途而产生的任何后果，与作者无关。

---

## 第五条 本地运行与数据处理

**5.1** 本软件不收集、不上传、不存储用户的任何数据至作者或第三方控制的服务器；本软件不设账号体系，不采集使用统计，不包含遥测组件。

**5.2** 本软件在启动后至多发出一项对外网络请求：访问 GitHub 公开页面以获取本软件的最新版本号，用于在界面中提示是否存在更新。该请求：

- 不携带用户的任何本地数据、设备信息或使用记录；
- 不包含 Cookie 或持久化标识；
- 结果仅用于界面提示，不构成任何形式的使用统计。

此外，本软件不发起其他对外网络请求。

**5.3** 用户的分析数据存储于本机，形式为单一 SQLite 数据库文件及关联目录。删除本软件所在目录即可清除全部数据。

**5.4** 录像文件（`.dem`）本身包含比赛内其他参与者的 SteamID 与游戏昵称。用户通过本软件导出的 CSV、报告、截图或回放数据，同样包含上述信息。

**5.5** 用户公开分享上述导出内容时，应自行评估是否涉及他人个人信息或隐私权益。由此产生的责任由分享者自行承担，与作者无关。

---

## 第六条 商业使用

**6.1** 本软件的自研代码以 MIT 许可证发布（全文见 `LICENSE`）。MIT 许可证**允许商业使用**：用户可在商业环境中使用、修改、再分发本软件代码，无需另行取得作者授权。

**6.2** MIT 许可证的授权范围**仅限于本软件的自研代码**，不覆盖以下内容：

- **游戏素材**：`cs2tool/web/icons/` 与 `cs2tool/web/maps/` 下的全部文件，著作权归 Valve，未经其授权不得用于商业分发；
- **第三方组件**：其各自许可证为准（见 `THIRD-PARTY-NOTICES.md`）；
- **商标**：不得将 `Counter-Strike`、`CS2` 等标识用于商业宣传，不得以任何方式暗示本软件或经修改的版本与 Valve 存在关联，或获得 Valve 的认可。

**6.3** 用户拟对**本软件或其修改版本进行商业分发**的，应当自行解决游戏素材与商标的授权问题。作者不就此提供任何授权、担保、协助或法律意见，亦不承担由此产生的任何责任。

**6.4** 用户拟商业分发且不希望处理上述素材问题的，可采用以下方式：删除 `cs2tool/web/icons/` 与 `cs2tool/web/maps/` 两个目录。删除后本软件其余功能正常，相关图标与地图显示为空白。

**6.5** 依据 MIT 许可证的要求，任何再分发行为均须保留本项目的版权声明与许可声明，并附上本文件及 `THIRD-PARTY-NOTICES.md`。

---

## 第七条 第三方组件

**7.1** 本软件包含或依赖若干第三方组件，各组件遵循其各自的许可证，作者不对其重新授权。

**7.2** 第三方组件的完整清单、用途及许可信息载于 `THIRD-PARTY-NOTICES.md`。该文件可能随版本更新。

**7.3** 用户再分发本软件时，应当自行核验并遵守其中列明的全部第三方许可条款；因违反第三方许可产生的责任由再分发者承担。

---

## 第八条 免责与责任限制

**8.1** 本软件按**「现状」（AS IS）**提供，不附带任何形式的明示或默示担保，包括但不限于对适销性、特定用途适用性、权利完整性、无错误、不中断的担保。

**8.2** 在适用法律允许的最大范围内，作者不对因使用或无法使用本软件而产生的任何直接、间接、附带、特殊、惩罚性或后果性损害承担责任，包括但不限于：

- 数据丢失、损坏或无法恢复；
- 游戏账号或平台账号被限制、封禁或处罚；
- 设备、存储介质或其他财产的损坏；
- 利润损失、业务中断或商业机会损失；
- 因用户分享导出数据而引发的第三方索赔或争议；
- 因用户违反第三方服务条款而产生的法律责任。

**8.3** 用户应在使用前自行备份其数据目录（`data/`）及原始录像文件。

**8.4** 本软件为个人业余项目，作者不承诺提供技术支持、缺陷修复、功能更新或持续维护，亦不承诺对任何问题作出回复。

**8.5** 本软件可能包含缺陷。用户应在充分理解上述风险的前提下自行决定是否使用。

---

## 第九条 合规义务

**9.1** 用户应自行确认，其所在国家或地区对使用、分发此类软件是否存在限制或特别规定，并自行承担合规责任。

**9.2** 用户不得将本软件用于违反游戏服务条款、侵犯他人合法权益或违反当地法律法规的目的。

**9.3** 若用户所在平台的服务条款禁止使用第三方工具解析其录像文件，用户不得在该平台使用本软件。

---

## 第十条 条款的变更与项目的终止

**10.1** 作者可随时修改本文件，修改后的版本自发布之日起生效。

**10.2** 作者可随时变更本软件的许可方式（已发布版本除外）、暂停或永久停止本项目的开发与分发，无需事先通知，亦无需说明理由。

**10.3** 本软件可能随时被删除、转为私有或停止维护。**已依据 MIT 许可证发布的版本，其授权不因后续变更而撤销。**

**10.4** 本文件的更新版本发布于本代码仓库。用户应自行查阅最新版本。

---

## 第十一条 其他

**11.1** 本文件的任何条款被认定为无效或不可执行的，不影响其余条款的效力。

**11.2** 本文件不排除、不限制用户依其所在地强制性法律规定所享有的权利。

**11.3** 中文本文件与英文摘要存在歧义的，以中文文本为准。

---

# English Summary

*Non-binding summary. The Chinese text prevails.*

**Nature.** Cross-Section is an unofficial, third-party project developed independently. It is **not affiliated with, authorized, sponsored, or endorsed by Valve Corporation**. `Counter-Strike`, `CS2`, and related marks are trademarks of Valve Corporation. Game assets included in `cs2tool/web/icons/` and `cs2tool/web/maps/` are the property of Valve and are distributed solely to enable offline display; they will be removed upon any objection from the rights holder.

**Function.** The software reads `.dem` replay files already present on the user's disk and performs offline analysis. It **does not** read game process memory, inject code, hook APIs, modify game files, simulate input, or communicate with the game client at runtime. It provides **no in-game advantage** and is **not a cheat tool**. However, **no warranty or guarantee of any kind is made regarding the user's account status** — anti-cheat policies are determined independently by third parties, are outside the author's control, and the user assumes all associated risk.

**Accuracy.** Statistics are derived from third-party open-source parsing libraries and are **not guaranteed to be accurate, complete, or consistent with any other platform's figures**. Certain metrics are heuristic reconstructions. Output is for personal reference only and **must not be used** for gambling, betting, competitive rulings, player scouting, or any decision involving money or personal rights.

**Data handling.** The software **uploads nothing**, collects **no telemetry**, and requires **no account**. It makes at most **one** outbound request: fetching the latest release version from GitHub's public pages, used solely to display an update indicator. That request carries no local data, no cookies, and no device or user identifiers. Note that replay files contain other participants' Steam IDs and nicknames; users are responsible for evaluating privacy implications before sharing any export.

**Commercial use.** The project's own code is licensed under **MIT**, which **permits commercial use**. However, MIT covers **only the author's original code** — it does **not** cover the Valve-owned game assets, third-party dependencies, or trademarks. Anyone commercially redistributing this software or a modified version **must independently resolve those rights**; no authorization or assistance is provided. Removing `cs2tool/web/icons/` and `cs2tool/web/maps/` is a practical way to avoid the asset issue.

**Liability.** The software is provided **"AS IS"**, without warranty of any kind. To the maximum extent permitted by law, the author is **not liable** for any damages arising from its use, including data loss, account penalties, device damage, loss of profit, or third-party claims. This document does not exclude rights granted by mandatory local law.

---

<div align="right"><sub>Cross-Section · v6.1 · 2026-10-23</sub></div>
