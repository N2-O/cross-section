# Cross-Section v6.2.0

**2026-10-24** · 拉取功能拆成可选增量包，主包不再碰 Steam。

## 主包变化

- 自动拉取官匹 demo 移到独立的 **AutoPull 增量包**，正式包里不含任何借 Steam 登录态的代码，也不带第三方 exe 和 Valve 的 dll
- 没装增量包时，拉取按钮和设置页的拉取配置都不出现，不会露出点不通的入口
- 设置页删掉 Steam Web API Key、游戏认证码、分享码起点三项——新方案零配置
- 相应清掉旧分享码链的全部代码（`cs2_pull_new.py`、`check_pull.py` 及对应接口）

## 新增（装增量包后）

- **AutoPull 区域**：一次取最近 8 场，或按分享码补任意早的场次
- 下载地址改由 Game Coordinator 直接给出（replay 分片号 + 文件名两段完整值），不再靠分享码拼凑
- 分享码解码确认：`matchId` 在 `b[0:8]`、`outcomeId` 在 `b[8:16]`、`token` 只有 16 位（这是必须问 GC 的原因）

## 修正

- Demo 页进度条：总场次进度跟随当前场已下字节连续推进，不再整场停在 0%；拿不到总大小时不显示负宽度
- 下载中断也保留待下载清单，重试不用重新拉
- Demo 页右上角显示后端版本号，覆盖代码后忘记重启能一眼看出来

## 装法

- **全新**：下载 `Cross-Section-v6.2.0-Portable.zip`（74.5 MB，自带 Python 与全部依赖）或 `Cross-Section-v6.2.0-src.zip`（源码，需要 Python 3.10+）
- **覆盖升级**：保留你自己的 `data/` 与 `demos/`。旧版残留的 `cs2tool/check_pull.py`、`cs2tool/cs2_pull_new.py` 已无用处，可手动删掉
- **增量包**：解压 `Cross-Section-AutoPull-v6.2.0.zip` 到程序根目录即可启用，删 `cs2tool/gc_pull.py` 即撤销

## 关于这次的便携包

这一版便携包是在 Linux 服务器上**交叉组装**的：Python 3.12.10 embeddable（华为云镜像）+ awpy/polars 等 10 个 `win_amd64` wheel（清华镜像）解压进 `python/Lib/site-packages`，并写好了 `python312._pth`。

结构自检都过了（`python.exe`、`awpy/_awpy.cp312-win_amd64.pyd`、`_polars_runtime_32/_polars_runtime.pyd` 均在位），但**没有在 Windows 真机上跑过**。如果 `START.bat` 报「Bundled Python cannot import awpy」或别的启动错误，用源码版先顶上，同时把报错贴到 Issue，我按反馈重打。
