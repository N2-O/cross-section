#!/usr/bin/env python3
"""自检拉取配置：能自动判断的都判断掉，别让人逐项试。

只读：不改库、不改配置、不推进 start_code。

用法：
    python cs2tool/check_pull.py                      # 用 <安装根>/data
    python cs2tool/check_pull.py --data <data 目录>    # 与 server 的 --data 一致

检查顺序（前面能过，后面的才需要人核对）：
  1. settings.json 在不在、四项齐不齐
  2. 三项格式对不对（steamid 17 位 / auth_code 4-5-4 / start_code CSGO-5x5）
  3. key 本身有没有效 + steamid 指向哪个账号（GetPlayerSummaries，能排除两项）
  4. 才轮到 GetNextMatchSharingCode：200 有新比赛 / 202 已是最新 /
     403 只剩「auth_code 与账号不符」或「start_code 不属于该账号」
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.steampowered.com/ICSGOPlayers_730/GetNextMatchSharingCode/v1/"
SUMMARIES = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
KEYS = (("steam_api_key", "Steam Web API Key"),
        ("steam_auth_code", "Match Sharing auth code（steamidkey）"),
        ("steamid", "SteamID64"),
        ("start_code", "起点 start_code（必须是你自己一条分享码）"))


def mask(v: str) -> str:
    v = str(v or "")
    if len(v) <= 10:
        return v[:2] + "…" if v else "(空)"
    return f"{v[:6]}…{v[-4:]}（{len(v)} 字符）"


def check_formats(cfg: dict) -> list[str]:
    """格式不对的话 Steam 只会回 403，这里先把手抄错挡掉。"""
    bad = []
    sid = str(cfg.get("steamid") or "").strip()
    if not re.fullmatch(r"\d{17}", sid):
        bad.append(f"steamid 应该是 17 位纯数字，现在是「{sid}」（{len(sid)} 字符）")
    elif not sid.startswith("7656119"):
        bad.append(f"steamid 以 7656119 开头才对，现在是「{sid}」")

    auth = str(cfg.get("steam_auth_code") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{4}-[A-Za-z0-9]{5}-[A-Za-z0-9]{4}", auth):
        bad.append(f"auth_code 形如 93JQ-5N8HM-VV4B（4-5-4，带连字符），现在是「{auth}」")

    start = str(cfg.get("start_code") or "").strip()
    if not re.fullmatch(r"CSGO(-[A-Za-z0-9]{5}){5}", start):
        bad.append(f"start_code 形如 CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx（5 段各 5 位），现在是「{start}」")

    key = str(cfg.get("steam_api_key") or "").strip()
    if not re.fullmatch(r"[0-9A-Fa-f]{32}", key):
        bad.append(f"api key 应该是 32 位十六进制，现在是 {len(key)} 字符（{mask(key)}）")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    data = os.path.abspath(a.data) if a.data else os.path.join(root, "data")
    sp = os.path.join(root, "data", "settings.json")

    print(f"安装根：{root}")
    print(f"data ：{data}")
    print(f"\n[1] 配置文件：{sp}")
    if not os.path.isfile(sp):
        print("    ✗ 不存在 —— 设置页保存的东西没写到这里，或 server 的安装根不是这个目录")
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
    if missing:
        print(f"\n    ✗ 缺 {', '.join(missing)}")
        return 1

    print("\n[2] 格式检查：")
    bad = check_formats(cfg)
    if bad:
        for b in bad:
            print(f"    ✗ {b}")
        print("\n结论：照着上面的格式改，改完再跑一次。格式错的时候 Steam 一律回 403，"
              "跟认证失败长得一样。")
        return 1
    print("    三项格式都对")

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    proxy = urllib.request.build_opener()

    def get(url, timeout=15):
        """直连优先，不通再走系统代理。"""
        last = None
        for op in (opener, proxy):
            try:
                with op.open(urllib.request.Request(url, headers={"User-Agent": "cs2tool-check"}),
                             timeout=timeout) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.read()
            except Exception as e:
                last = e
        raise last

    key = str(cfg["steam_api_key"]).strip()
    sid = str(cfg["steamid"]).strip()
    auth = str(cfg["steam_auth_code"]).strip()
    start = str(cfg["start_code"]).strip()

    # ---- 3. 用 key 查账号：能确认 key 有效 + steamid 指向谁（任何有效 key 都能查公开资料）
    print("\n[3] 验 key 是否有效 + steamid 指向哪个账号：")
    st, body = get(SUMMARIES + "?" + urllib.parse.urlencode(
        {"key": key, "steamids": sid}))
    if st == 403:
        print("    ✗ 403：这把 api key 无效或已被撤销")
        print("\n结论：去 steamcommunity.com/dev/apikey 重新拿一把（用要拉比赛的那个账号登录）。")
        return 1
    if st != 200:
        print(f"    ✗ HTTP {st}：{body[:200].decode('utf-8', 'replace')}")
        return 1
    try:
        players = json.loads(body).get("response", {}).get("players") or []
    except Exception:
        players = []
    if not players:
        print("    ✗ key 有效，但查不到这个 steamid —— 这个号不存在（填错了）")
        return 1

    p = players[0]
    print(f"    ✓ key 有效")
    print(f"    → steamid {sid} 的账号名是「{p.get('personaname')}」")
    print(f"      （如果不是你的号，说明 steamid 填错了；这一项错了 Steam 也是回 403）")

    # ---- 4. 才到真正要 code 的接口
    print("\n[4] 拉取接口（GetNextMatchSharingCode）：")
    st, body = get(API + "?" + urllib.parse.urlencode(
        {"key": key, "steamid": sid, "steamidkey": auth, "knowncode": start}))
    text = (body or b"").decode("utf-8", "replace")[:400]
    print(f"    HTTP {st}  {text[:200]}")
    if st == 200:
        try:
            nxt = json.loads(text).get("result", {}).get("nextcode")
        except Exception:
            nxt = None
        if nxt:
            print(f"\n结论：通了。下一场分享码 {nxt}")
        else:
            print("\n结论：200 但没 nextcode，返回格式变了。")
    elif st == 202:
        print("\n结论：202 = start_code 已经是最新一条，后面没有更新的比赛了。")
        print("     刚打完的局要等官方生成分享码（几分钟到几小时）。")
    elif st in (401, 403):
        print("\n结论：key 有效、steamid 是「%s」、三项格式都对，所以只剩两种："
              % p.get("personaname"))
        print("     ① auth_code 不是这个账号的（它来自 CS2「观看 → 你的比赛」分享链接里的 "
              "?steamidkey=，不是 Steam Guard 验证码）")
        print("     ② start_code 不是你账号里的一条分享码（拿别人的、自己编的都会 403）")
        print("     最省事的做法：从 CS2 里随便复制一场你的比赛分享链接，")
        print("     里面那条 CSGO-… 就是合法的 start_code，auth_code 从同一个页面拿，别分开抄。")
    elif st == 503:
        print("\n结论：503 = 调用太频繁，等 10 分钟再试。")
    else:
        print(f"\n结论：没见过的状态码 {st}，把返回体贴给我。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
