#!/usr/bin/env python3
"""从 settings.json 的 start_code 往后拉新比赛，生成 steam:// 批量下载用的 bat。

放在 cs2tool/ 里，靠「上两级 = 安装根」定位 data/settings.json，
源码目录（cs2-demo/cs2tool/）和打包版（CS2Tool/cs2tool/）都成立。

用法
----
  cs2_pull_new.py                 正式拉取：查到就生成 bat，并把 start_code 推进
  cs2_pull_new.py --dry-run       只查有多少场、都是哪些码，不写 bat、不推进起点
  cs2_pull_new.py --dry-run --limit 30

进度写在 data/pull_progress.json，前端轮询它画进度条。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SELF = os.path.abspath(__file__)
ROOT = os.path.dirname(os.path.dirname(SELF))          # cs2tool/ 的上一级 = 安装根
# 注意两条路径不是一回事：
#   · settings.json 固定在 <安装根>/data/settings.json —— server.py 里叫 BOOT_CFG，
#     是引导位置，**不随 --data 变化**（--data 只换数据库/产物所在目录）。
#   · pull_last / pull_progress / pull_preview 是运行产物，跟着 --data 走，
#     这样 server 的 DATA_DIR 指向别处时，前端仍能读到进度和结果。
# 之前把两者混成一个，settings 跟着 --data 跑 → 「设置页明明填了，拉取说配置缺」。
DATA = os.path.join(ROOT, "data")
if "--data" in sys.argv:
    try:
        DATA = os.path.abspath(sys.argv[sys.argv.index("--data") + 1])
    except IndexError:
        pass
SETTINGS = os.path.join(ROOT, "data", "settings.json")
BAT = os.path.join(ROOT, "cs2_new_download.bat")
RESULT = os.path.join(DATA, "pull_last.json")
PROGRESS = os.path.join(DATA, "pull_progress.json")
API = "https://api.steampowered.com/ICSGOPlayers_730/GetNextMatchSharingCode/v1/"

DRY = "--dry-run" in sys.argv
LIMIT = 100
if "--limit" in sys.argv:
    try:
        LIMIT = max(1, int(sys.argv[sys.argv.index("--limit") + 1]))
    except (IndexError, ValueError):
        LIMIT = 100


def log(msg):
    print(msg, flush=True)


def write_json(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)          # 原子替换，前端不会读到半截文件
    except OSError:
        pass


def progress(**kw):
    write_json(PROGRESS, {"t": time.strftime("%Y-%m-%d %H:%M:%S"), **kw})


def main() -> int:
    if not os.path.isfile(SETTINGS):
        log(f"[ERROR] 找不到设置文件: {SETTINGS}")
        progress(state="error", error=f"找不到设置文件 {SETTINGS}")
        return 1

    with open(SETTINGS, encoding="utf-8") as f:
        cfg = json.load(f)

    key = str(cfg.get("steam_api_key") or "").strip()
    auth = str(cfg.get("steam_auth_code") or "").strip()
    sid = str(cfg.get("steamid") or "").strip()
    start = str(cfg.get("start_code") or "").strip()

    missing = [n for n, v in (("steam_api_key", key), ("steam_auth_code", auth),
                              ("steamid", sid), ("start_code", start)) if not v]
    if missing:
        log(f"[ERROR] 设置缺: {', '.join(missing)}")
        progress(state="error", error="设置缺 " + ", ".join(missing))
        return 1

    # 网络：直连优先（Steam API 在国内通常直连比代理稳），不通再退回系统代理/Clash。
    # 旧版是「先系统代理」——这台机器上代理一慢就整个查询超时，表现成「抓不到新比赛」。
    DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        PROXY = urllib.request.build_opener()
    except Exception:
        PROXY = DIRECT
    state = {"mode": "直连"}

    def next_code(known):
        q = urllib.parse.urlencode({"key": key, "steamid": sid,
                                    "steamidkey": auth, "knowncode": known})
        last = ""
        for label, op in ORDER:      # 顺序由 probe 的结果决定，见下方 ORDER
            for _ in range(2):          # 单次抽风不放弃整轮
                try:
                    with op.open(API + "?" + q, timeout=15) as r:
                        state["mode"] = label
                        return json.loads(r.read()).get("result", {}).get("nextcode")
                except urllib.error.HTTPError as e:
                    if e.code == 202:
                        return "n/a"          # 没有更新的比赛了
                    if e.code in (401, 403):
                        # Steam 对这三类情况都回 403，不区分：
                        #   api key 不属于这个 steamid / auth_code 不对 / start_code 不是本人的分享码
                        return ("err:认证不过（403）。三种可能：① api key 不是这个 steamid "
                                "本人申请的；② auth_code（steamidkey）填错；③ 起点 start_code "
                                "不是你账号里的一条分享码")
                    if e.code == 503:
                        return "err:调用过频，等 10 分钟再试"
                    last = f"HTTP {e.code}"
                    break
                except Exception as e:
                    last = type(e).__name__
                    time.sleep(1.2)
        return f"err:{last or '未知'}"

    # ---- 连通性探测：先确认能不能连上 Steam，不通就明确报「网络不通」。
    # 不能和「没有新比赛」混成一个结果——查询超时和真没新局是完全不同的两件事，
    # 之前一律显示「没有新比赛」，会让人以为账号/配置没问题。
    PROBE = "https://api.steampowered.com/ISteamWebAPIUtil/GetServerInfo/v1/"

    def probe():
        last = "未知"
        for label, op in (("直连", DIRECT), ("系统代理", PROXY)):
            try:
                with op.open(PROBE, timeout=8) as r:
                    if 200 <= r.status < 300:
                        return label, None
                    last = f"HTTP {r.status}"
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
            except Exception as e:
                last = f"{label}:{type(e).__name__}"
        return None, last

    net, neterr = probe()
    if not net:
        msg = f"网络不通：连不上 api.steampowered.com（直连和系统代理都试过，最后错误 {neterr}）"
        log(f"[ERROR] {msg}")
        progress(state="error", phase="network", error=msg)
        write_json(os.path.join(DATA, "pull_preview.json"),
                   {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "offline",
                    "count": 0, "codes": [], "start_code": start, "error": msg})
        return 2

    progress(state="running", done=0, total=0, current=start,
             mode="dry" if DRY else "pull", msg="正在查询新比赛…")

    # 探测到哪个模式通，就优先用它——不然每场都要先撞一次不通的（实测能拖到 70 秒+）
    ORDER = [("直连", DIRECT), ("系统代理", PROXY)]
    if net == "系统代理":
        ORDER.reverse()

    code = start
    new = []
    err = None
    for i in range(LIMIT):
        nxt = next_code(code)
        if nxt is None or nxt == "n/a":
            break
        if isinstance(nxt, str) and nxt.startswith("err:"):
            err = nxt[4:]
            break
        new.append(nxt)
        code = nxt
        progress(state="running", done=len(new), total=0, current=nxt,
                 mode="dry" if DRY else "pull")
        time.sleep(0.3)

    log(f"起点: {start}")
    log(f"新增 {len(new)} 场" + (f"（查询出错: {err}）" if err else ""))
    for i, c in enumerate(new, 1):
        log(f"  {i}. {c}")

    if DRY:
        # 只报告，不写 bat、不动 start_code
        status = "error" if err else ("ok" if new else "empty")
        if status == "error":
            progress(state="error", error=f"查询失败：{err}")
        else:
            progress(state="done", done=len(new), total=len(new), mode="dry",
                     msg=(f"共 {len(new)} 场" if new else "没有新比赛（已是最新的）"))
        write_json(os.path.join(DATA, "pull_preview.json"),
                   {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "status": status,
                    "count": len(new), "codes": new, "start_code": start,
                    "error": err, "net": net})
        return 1 if status == "error" else 0

    if not new:
        if err:
            # 查询本身失败了 —— 这跟「确实没有新比赛」必须区分开
            msg = f"拉取失败：{err}"
            log(f"[ERROR] {msg}")
            progress(state="error", phase="query", error=msg)
            write_json(RESULT, {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": False,
                                "status": "error", "added": 0, "codes": [], "bat": "",
                                "start_code": start, "error": err, "msg": msg})
            return 1
        progress(state="done", done=0, total=0, mode="pull", msg="没有新比赛（已是最新的）")
        write_json(RESULT, {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": True,
                            "status": "empty", "added": 0, "codes": [], "bat": "",
                            "start_code": start, "msg": "没有新比赛（已是最新的）"})
        return 0

    lines = [
        "@echo off",
        "chcp 65001 >nul",
        f"echo 新增 {len(new)} 场，逐个唤起 CS2 下载（间隔 45 秒）",
        'set "GAME=steam://rungame/730/76561202255233023/+csgo_download_match%20"',
        "",
    ]
    for i, c in enumerate(new, 1):
        lines.append(f"echo [{i}/{len(new)}] {c}")
        lines.append(f'start "" "%GAME%{c}"')
        if i < len(new):
            lines.append("timeout /t 45 /nobreak >nul")
    lines += ["", "echo 全部触发完毕，等 CS2 下完。", "pause", ""]
    with open(BAT, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines))
    log(f"bat 已写: {BAT}")

    cfg["start_code"] = code
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    log(f"start_code 已推进到: {code}")

    write_json(RESULT, {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": True,
                        "status": "ok", "added": len(new), "codes": new,
                        "bat": os.path.basename(BAT), "start_code": code,
                        "warning": err or None,
                        "msg": f"新增 {len(new)} 场，已生成 {os.path.basename(BAT)}"
                               + (f"（查到第 {len(new)+1} 场时出错：{err}）" if err else "")})
    progress(state="done", done=len(new), total=len(new), mode="pull",
             msg=f"新增 {len(new)} 场，清单已生成"
                 + (f"；中途出错：{err}" if err else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                       # 兜底：别让前端一直转圈
        progress(state="error", error=f"{type(e).__name__}: {e}")
        raise
