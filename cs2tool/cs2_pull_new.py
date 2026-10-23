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
SETTINGS = os.path.join(ROOT, "data", "settings.json")
BAT = os.path.join(ROOT, "cs2_new_download.bat")
RESULT = os.path.join(ROOT, "data", "pull_last.json")
PROGRESS = os.path.join(ROOT, "data", "pull_progress.json")
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

    # 网络：默认走系统代理；第一次失败就永久切直连（连不上就当没有）
    state = {"op": urllib.request.build_opener(), "mode": "系统代理"}
    DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def next_code(known):
        q = urllib.parse.urlencode({"key": key, "steamid": sid,
                                    "steamidkey": auth, "knowncode": known})
        for attempt in (0, 1):
            try:
                with state["op"].open(API + "?" + q, timeout=20) as r:
                    return json.loads(r.read()).get("result", {}).get("nextcode")
            except urllib.error.HTTPError as e:
                if e.code == 202:
                    return "n/a"          # 没有更新的比赛了
                if e.code in (403, 503):
                    return "err:认证码无效或调用过频"
                return f"err:HTTP {e.code}"
            except Exception as e:
                if attempt == 0 and state["mode"] == "系统代理":
                    log(f"[WARN] {state['mode']}不通（{type(e).__name__}），改直连重试")
                    state["op"] = DIRECT
                    state["mode"] = "直连"
                    continue
                return f"err:{type(e).__name__}"
        return "err:未知"

    progress(state="running", done=0, total=0, current=start,
             mode="dry" if DRY else "pull", msg="正在查询新比赛…")

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
        progress(state="done", done=len(new), total=len(new), mode="dry",
                 msg=f"共 {len(new)} 场" + (f"（{err}）" if err else ""))
        write_json(os.path.join(ROOT, "data", "pull_preview.json"),
                   {"t": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "count": len(new), "codes": new, "start_code": start,
                    "error": err})
        return 0

    if not new:
        progress(state="done", done=0, total=0, mode="pull", msg="没有新比赛")
        write_json(RESULT, {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": True,
                            "added": 0, "codes": [], "bat": "",
                            "start_code": start, "msg": "没有新比赛"})
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
                        "added": len(new), "codes": new,
                        "bat": os.path.basename(BAT), "start_code": code,
                        "msg": f"新增 {len(new)} 场，已生成 {os.path.basename(BAT)}"})
    progress(state="done", done=len(new), total=len(new), mode="pull",
             msg=f"新增 {len(new)} 场，清单已生成")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                       # 兜底：别让前端一直转圈
        progress(state="error", error=f"{type(e).__name__}: {e}")
        raise
