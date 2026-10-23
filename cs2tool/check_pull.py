#!/usr/bin/env python3
"""自检「抓不到新比赛」卡在哪一环。

只读：不改库、不改配置、不推进 start_code。

用法：
    python cs2tool/check_pull.py                      # 用 <安装根>/data
    python cs2tool/check_pull.py --data <data 目录>    # 与 server 的 --data 一致

会依次检查：
  1. data 目录里有没有 settings.json，四项配置（api key / auth_code / steamid / start_code）齐不齐
  2. 安装根下面有没有第二个 settings.json（两份的话就是「填了一处、读另一处」）
  3. 直接调 Steam 的 GetNextMatchSharingCode，把 HTTP 状态翻成人话：
     200=有新比赛 / 202=已是最新 / 403=key 与 auth_code 或 steamid 对不上 / 401=key 无效 / 503=调用过频
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.steampowered.com/ICSGOPlayers_730/GetNextMatchSharingCode/v1/"
KEYS = (("steam_api_key", "Steam Web API Key"),
        ("steam_auth_code", "Match Sharing auth code（steamidkey）"),
        ("steamid", "SteamID64"),
        ("start_code", "起点 start_code（必须是一条已知的 match sharing code）"))


def mask(v: str) -> str:
    v = str(v or "")
    if len(v) <= 10:
        return v[:2] + "…" if v else "(空)"
    return f"{v[:6]}…{v[-4:]}（{len(v)} 字符）"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    data = os.path.abspath(a.data) if a.data else os.path.join(root, "data")

    print(f"安装根：{root}")
    print(f"data ：{data}")

    # ---- 1. settings.json：固定在 <安装根>/data（server 的 BOOT_CFG），不随 --data 变
    sp = os.path.join(root, "data", "settings.json")
    print(f"\n[1] 配置文件：{sp}")
    if data != os.path.join(root, "data"):
        print(f"    （--data 指向 {data}，那只影响数据库与拉取产物；配置永远在上面这个位置）")
    if not os.path.isfile(sp):
        print("    ✗ 不存在。设置页保存的东西没写到这里，或者 server 的 --data 指的不是这个目录。")
        return 1
    try:
        with open(sp, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"    ✗ 读不了：{type(e).__name__}: {e}")
        return 1
    missing = []
    for k, name in KEYS:
        v = str(cfg.get(k) or "").strip()
        print(f"    {'✓' if v else '✗'} {k:<16} {name:<40} {mask(v) if v else '（空）'}")
        if not v:
            missing.append(k)
    if "start_code" in cfg and not str(cfg.get("start_code")).upper().startswith("CSGO-"):
        print("    ! start_code 一般形如 CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx")
    if missing:
        print(f"\n    ✗ 缺 {', '.join(missing)} —— 先在设置页补齐，或者把 server 的 --data 指到这个目录")
        return 1

    # ---- 2. 是否有第二份 settings.json（填一处读另一处）
    others = []
    for cand in (os.path.join(root, "data", "settings.json"),
                 os.path.join(here, "settings.json")):
        c = os.path.abspath(cand)
        if c != os.path.abspath(sp) and os.path.isfile(c):
            others.append(c)
    print("\n[2] 其他位置的 settings.json：")
    if others:
        for c in others:
            print(f"    ! {c}  ← 跟你刚才检查的那份不是同一个文件，容易「填了没生效」")
    else:
        print("    没有，只有一份")

    # ---- 3. 调 Steam
    key = str(cfg.get("steam_api_key")).strip()
    auth = str(cfg.get("steam_auth_code")).strip()
    sid = str(cfg.get("steamid")).strip()
    start = str(cfg.get("start_code")).strip()
    q = urllib.parse.urlencode({"key": key, "steamid": sid,
                                "steamidkey": auth, "knowncode": start})
    url = API + "?" + q

    ctx = ssl.create_default_context()
    schemes = [("直连", urllib.request.build_opener(urllib.request.ProxyHandler({})))]
    try:
        schemes.append(("系统代理", urllib.request.build_opener()))
    except Exception:
        pass

    print("\n[3] 请求 Steam（GetNextMatchSharingCode）：")
    body = status = None
    for label, op in schemes:
        try:
            with op.open(urllib.request.Request(url, headers={"User-Agent": "cs2tool-check"}), timeout=20) as r:
                status, body = r.status, r.read()
            print(f"    {label}: HTTP {status}  {len(body)} 字节")
            break
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read()
            print(f"    {label}: HTTP {status}")
            break
        except Exception as e:
            print(f"    {label}: {type(e).__name__} —— 连不上（网络/代理）")

    if status is None:
        print("\n结论：请求没发出去。Steam 在国内直连经常不稳，先确认这台机器能打开 store.steampowered.com")
        return 1

    text = (body or b"").decode("utf-8", "replace")[:400]
    if status == 200:
        try:
            nxt = json.loads(text).get("result", {}).get("nextcode")
        except Exception:
            nxt = None
        if nxt:
            print(f"    → 有新比赛：{nxt}")
            print("\n结论：链路是通的。点「检查新比赛」应该能看到场次；看不到就是 server 读的 data 目录不对。")
        else:
            print(f"    返回体：{text}")
            print("\n结论：HTTP 200 但没有 nextcode，Steam 返回格式变了或 start_code 不是一条有效 code。")
    elif status == 202:
        print("\n结论：202 = 你的 start_code 已经是最新的一条，后面没有更新的比赛了。")
        print("     打过新比赛还没出现？CS2 要等比赛结束后官方生成分享码，通常几分钟到几小时。")
    elif status in (401, 403):
        print(f"    返回体：{text}")
        print("\n结论：认证不过。Steam 对下面三种情况都回 403，不区分：")
        print("     ① API Key 不是这个 steamid 本人申请的")
        print("        （steamcommunity.com/dev/apikey，用要拉的那个 Steam 账号登录去申请）")
        print("     ② auth_code 不对：它来自 CS2 里「观看 → 你的比赛」点某场 → 「复制分享链接」，")
        print("        链接里 ?steamidkey= 后面那一串，形如 93JQ-5N8HM-VV4B")
        print("     ③ start_code 不是你账号里的一条分享码：它必须是你某场 demo 的 CSGO-xxxxx-…，")
        print("        不能拿别人的，也不能自己编")
        print("     三项任意一项错都只是 403，看不出来是哪一项——所以只能逐项核对。")
    elif status == 503:
        print("\n结论：503 = 调用太频繁，等 10 分钟再试")
    else:
        print(f"    返回体：{text}\n\n结论：没见过的状态码，把上面的返回体贴给我。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
