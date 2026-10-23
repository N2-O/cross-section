# 第三方依赖与许可声明

Cross-Section 本体（`cs2tool/` 下的全部代码）为自研代码。
下列第三方软件以**依赖库**形式被调用（`import`），没有复制、修改或分发其源码。

---

## 运行时依赖

### awpy 3.1.1
- 用途：CS2 `.dem` 文件解析（回合、击杀、伤害、射击、道具、致盲、经济等数据集）
- 主页：https://github.com/pnxenopoulos/awpy
- 文档：https://awpy.readthedocs.io/
- 许可：**MIT License**
- 版权：Copyright (c) Peter Xenopoulos

```
MIT License

Copyright (c) Peter Xenopoulos

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### demoparser2 0.42.0
- 用途：投掷者归属（引爆事件的 `user_steamid`）+ 护甲/拆弹钳的花费反推
- 主页：https://github.com/LaihoE/demoparser
- 许可：**待核实**。已安装的 wheel 内未携带 LICENSE 文件，PyPI 元数据也没有 license 字段，
  需到上游仓库确认后补充。**以该项目的实际许可证为准。**
- 说明：本项目只调用它的 `parse_event` / `parse_ticks` 读取 demo，不分发其源码

### polars 2.x
- 用途：awpy 的数据表结构依赖
- 主页：https://github.com/pola-rs/polars
- 许可：**MIT License**
- 版权：Copyright (c) Ritchie Vink

### typer
- 用途：awpy 的 CLI 依赖
- 许可：**MIT License**

### Python 标准库
- 用途：HTTP 服务、SQLite、JSON、多线程等
- 许可：**PSF License**（Python Software Foundation）

---

## 数据与资产

### CS2 游戏资产
`cs2tool/web/icons/*.svg`（武器、道具、界面图标）与 `cs2tool/web/maps/*.png`（地图雷达底图）
来自 **Counter-Strike 2** 客户端资源。

- 版权：**© Valve Corporation**
- 用途：仅用于本地显示，随工具一同分发以便离线运行
- 声明：本项目与 Valve Corporation 无关联，未获其授权或背书。
  Counter-Strike、CS2 及相关标识是 Valve Corporation 的商标。
- 若 Valve 提出异议，删除这两个目录即可，工具其余功能不受影响（图标与地图会显示为空白）

### 地图雷达标定参数
`data/overviews/*.txt` 来自 CS2 客户端 `game/csgo/resource/overviews/`，
用于把游戏内坐标换算成雷达图上的像素位置。版权同上。

---

## 版本检查的网络请求

程序启动后会请求 `https://github.com/N2-O/cross-section/releases/latest` 做一次
重定向探测，只为读出最新版本号，最多每 24 小时一次；请求不带任何本地数据、
不带 cookie、不带设备或用户标识，也不构成遥测，失败时静默跳过。

For version checking the app requests
`https://github.com/N2-O/cross-section/releases/latest` at most once every 24 hours
and only reads the redirect target; it carries no local data, no cookies and no
device or user identifiers, and is not telemetry. Failures are silently ignored.

---

## 数据口径参考

以下公开资料被用于确定统计指标的定义（**仅参考公式，未复制代码**）：

| 指标 | 参考来源 |
|---|---|
| Rating 2.0 | HLTV 公开公式（社区整理，非官方文档） |
| Impact | 同上 |
| KAST / ADR / KPR / DPR | HLTV 与社区通用定义 |
| 购买类型分档 | CS2 经济系统公开规则 |

> Rating 3.0 没有公开公式，本项目**未实现**，避免给出无法复核的数字。

---

## 本人编写的部分

`cs2tool/` 下全部 Python 与前端代码（server / awpy_ingest / stats_api / metrics /
clutch / rounddata / ability / export_csv / api_v1 / 以及 web/ 下的 HTML/CSS/JS）
均为本项目自研，基于 awpy 提供的数据集做二次统计与呈现。

其中若干实现细节是在 awpy 现有字段不足时**自行重建**的，例如：

- 残局（1v1~1v5）：awpy 的 `clutch_1vN` 字段未填充，改为按击杀事件流重建存活人数
- 跳跃击杀：awpy 无该字段，用击杀 tick 上的 `is_jumping` 快照判定
- 每武器命中率：用开火与伤害事件做同 tick 配对
- 保枪判定：在回合判定前 1 秒采样存活状态与装备库存

这些都属于**在库之上做计算**，不涉及对 awpy 源码的修改。

---

## 引用建议

awpy 作者在 README 中提出（非许可条款，属礼貌请求）：

> If you use the parser for any public analysis, we kindly ask you to link to
> the Awpy repository, so that others may know how you parsed, analyzed or
> visualized your data.

如果要把基于本工具产出的数据公开发表，建议注明：

> 数据解析使用 awpy (https://github.com/pnxenopoulos/awpy)
