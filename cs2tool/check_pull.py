#!/usr/bin/env python3
"""拉取配置自检：能自动判断的都判断掉，别让人逐项试。

既是 CLI，也是 server 的 `/api/check_pull` 背后的实现（同一份逻辑，两条入口）：

    python cs2tool/check_pull.py        # 命令行
    界面 demos 页「🔍 检查拉取配置」      # 走 run_check()

检查顺序（前面能过，后面的才需要人核对）：
  1. settings.json 在不在、四项齐不齐
  2. 三项格式对不对（steamid 17 位 / auth_code 4-5-4 / start_code CSGO-5x5）
  3. key 本身有没有效 + steamid 指向哪个账号（GetPlayerSummaries，能排除两项）
  4. 才轮到 GetNextMatchSharingCode：
     200 有新比赛 / 202 已是最新 / 403 只剩「auth_code 与账号不符」或「start_code 不属于该账号」
"""
from __future__ import annotations

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


_RE_SID = re.compile(r"7656119\d{10}")
_RE_CODE = re.compile(r"CSGO(?:-[A-Za-z0-9]{5}){5}")
_RE_AUTH = re.compile(r"[A-Za-z0-9]{4}-[A-Za-z0-9]{5}-[A-Za-z0-9]{4}")
_RE_KEY = re.compile(r"\b[0-9A-Fa-f]{32}\b")
_RE_VANITY = re.compile(r"steamcommunity\.com/id/([^/?#\s]+)", re.I)


def normalize_fields(raw: dict) -> tuple[dict, list[str]]:
    """把粘进来的链接 / 整段文字提取成要的值。

    用户不该为了一个 steamid 去数位数：粘
    https://steamcommunity.com/profiles/76561198…/ 也应该能用。
    """
    out, notes = {}, []
    for k, v in (raw or {}).items():
        s = str(v or "").strip().strip('"').strip()
        if s:
            if k == "steamid":
                m = _RE_SID.search(s)
                if m:
                    if m.group(0) != s:
                        notes.append(f"steamid：已从输入里提取 {m.group(0)}")
                    s = m.group(0)
            elif k == "start_code":
                m = _RE_CODE.search(s)
                if m:
                    if m.group(0) != s:
                        notes.append("start_code：已从输入里提取 CSGO-… 分享码")
                    s = m.group(0)
            elif k == "steam_auth_code":
                m = _RE_AUTH.search(s)
                if m and m.group(0) != s:
                    notes.append("auth_code：已从输入里提取认证码")
                    s = m.group(0)
            elif k == "steam_api_key":
                m = _RE_KEY.search(s)
                if m and m.group(0) != s:
                    notes.append("api key：已从输入里提取 32 位 key")
                    s = m.group(0)
        out[k] = s
    return out, notes


def _bad_formats(cfg: dict) -> list[str]:
    """格式不对时 Steam 只会回 403，这里先把手抄错挡掉。"""
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


_OK_OP = None          # 记住哪条通道通（直连/代理），第二次请求就别再撞一遍


def _get(url: str, timeout: int = 10):
    """直连优先，不通再走系统代理；成功过的通道下次排前面。"""
    global _OK_OP
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    proxy = urllib.request.build_opener()
    cands = ([_OK_OP] if _OK_OP else []) + [direct, proxy]
    last = None
    for op in cands:
        try:
            with op.open(urllib.request.Request(url, headers={"User-Agent": "cs2tool-check"}),
                         timeout=timeout) as r:
                _OK_OP = op
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            _OK_OP = op
            return e.code, e.read()
        except Exception as e:
            last = e
    raise last if last else RuntimeError("请求失败")


def run_check(data_dir: str | None = None) -> dict:
    """返回 {ok, verdict, steps:[{name, ok, detail}], player}，供界面直接渲染。"""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    sp = os.path.join(root, "data", "settings.json")
    steps: list[dict] = []

    def add(name, ok, detail=""):
        steps.append({"name": name, "ok": bool(ok), "detail": detail})
        return ok

    def done(ok, verdict, player=None):
        return {"ok": bool(ok), "verdict": verdict, "steps": steps,
                "player": player, "settings": sp}

    # ---- 1. 文件与四项是否齐
    if not add("配置文件", os.path.isfile(sp), sp):
        return done(False, "找不到 settings.json —— 先在设置页填一次，或确认工具的安装根没变")
    try:
        with open(sp, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        add("读取配置", False, f"{type(e).__name__}: {e}")
        return done(False, "settings.json 读不了，内容可能坏了")
    missing = [k for k, _ in KEYS if not str(cfg.get(k) or "").strip()]
    add("四项配置", not missing,
        "都填了" if not missing else "缺 " + "、".join(missing))
    if missing:
        return done(False, "还缺 " + "、".join(missing) + "，先去设置页补齐")

    # 粘进来的链接/整段文字，先就地提取（他粘 steamcommunity 主页链接是常态）
    cfg, _notes = normalize_fields(cfg)
    if _notes:
        add("自动识别", True, "；".join(_notes))

    # /id/自定义名 这种得联网换成 17 位（有 key 才做，失败就留给格式检查报错）
    if not _RE_SID.search(str(cfg.get("steamid") or "")):
        mv = _RE_VANITY.search(str(cfg.get("steamid") or ""))
        if mv and re.fullmatch(r"[0-9A-Fa-f]{32}", str(cfg.get("steam_api_key") or "")):
            try:
                st, body = _get("https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?"
                                + urllib.parse.urlencode({"key": str(cfg["steam_api_key"]),
                                                          "vanityurl": mv.group(1)}))
                j = json.loads(body).get("response", {}) if st == 200 else {}
                if j.get("success") == 1 and j.get("steamid"):
                    cfg["steamid"] = str(j["steamid"])
                    add("自动识别", True, f"自定义链接 /id/{mv.group(1)} → {cfg['steamid']}")
            except Exception:
                pass

    # ---- 2. 格式
    bad = _bad_formats(cfg)
    add("格式检查", not bad, "三项格式都对" if not bad else "；".join(bad))
    if bad:
        return done(False, "格式就不对，Steam 会一律回 403（跟认证失败长得一样），照着提示改")

    key = str(cfg["steam_api_key"]).strip()
    sid = str(cfg["steamid"]).strip()
    auth = str(cfg["steam_auth_code"]).strip()
    start = str(cfg["start_code"]).strip()

    # ---- 3. key 有效性 + steamid 指向谁（能排除两项）
    try:
        st, body = _get(SUMMARIES + "?" + urllib.parse.urlencode({"key": key, "steamids": sid}))
    except Exception as e:
        add("连通性", False, f"{type(e).__name__}: 直连和代理都连不上 api.steampowered.com")
        return done(False, "网络不通：连不上 Steam API（先确认这台机器能打开 store.steampowered.com）")
    if st == 403:
        add("API Key", False, "403：这把 key 无效或已被撤销")
        return done(False, "去 steamcommunity.com/dev/apikey 重新拿一把（用要拉比赛的那个账号登录）")
    if st != 200:
        add("API Key", False, f"HTTP {st}")
        return done(False, f"验证 key 时返回 HTTP {st}，把这句话贴给作者")
    players = []
    try:
        players = json.loads(body).get("response", {}).get("players") or []
    except Exception:
        pass
    if not players:
        add("SteamID", False, "key 有效，但查不到这个 steamid——这个号不存在")
        return done(False, "steamid 填错了（17 位那个号不存在）")
    pname = players[0].get("personaname") or "(无名)"
    add("API Key", True, "有效")
    add("SteamID", True, f"{sid} → 账号「{pname}」")
    if data_dir:
        add("数据目录", True, data_dir)

    # ---- 4. 真正要 code 的接口
    try:
        st, body = _get(API + "?" + urllib.parse.urlencode(
            {"key": key, "steamid": sid, "steamidkey": auth, "knowncode": start}))
    except Exception as e:
        add("拉取接口", False, f"{type(e).__name__}")
        return done(False, "连不上拉取接口，稍后重试", pname)
    text = (body or b"").decode("utf-8", "replace")[:400]

    if st == 200:
        try:
            nxt = json.loads(text).get("result", {}).get("nextcode")
        except Exception:
            nxt = None
        if nxt:
            add("拉取接口", True, "有新比赛：" + nxt)
            return done(True, f"配置没问题，下一场分享码 {nxt}", pname)
        add("拉取接口", False, "200 但没有 nextcode")
        return done(False, "接口返回格式变了，把返回体贴给作者", pname)

    if st == 202:
        add("拉取接口", True, "202 = start_code 已是最新一条")
        return done(True, "配置没问题，只是还没有更新的比赛（刚打完要等官方生成分享码）", pname)

    if st in (401, 403):
        add("拉取接口", False, f"HTTP {st}")
        add("auth_code", None, f"{mask(auth)}")
        add("start_code", None, mask(start))
        return done(False,
                    f"key 有效、steamid 是「{pname}」、格式都对，所以只剩两种可能："
                    "① auth_code 不是这个账号的（来自 CS2「观看 → 你的比赛」分享链接里的 "
                    "?steamidkey=，不是 Steam Guard 验证码）；"
                    "② start_code 不是你账号里的一条分享码（拿别人的、自己编的都会 403）。"
                    "最省事：从 CS2 复制一场你自己的比赛分享链接，里面的 CSGO-… 就是合法 start_code",
                    pname)

    if st == 503:
        add("拉取接口", False, "503 = 调用过频")
        return done(False, "调用太频繁，等 10 分钟再试", pname)

    add("拉取接口", False, f"HTTP {st}")
    return done(False, f"没见过的状态码 {st}，把「{text[:120]}」贴给作者", pname)


def main() -> int:
    # CLI：加 --data 只为跟 server 的说法对齐（配置固定在 <安装根>/data）
    data = None
    for i, a in enumerate(sys.argv):
        if a == "--data" and i + 1 < len(sys.argv):
            data = os.path.abspath(sys.argv[i + 1])
    r = run_check(data)
    print(f"安装根：{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}")
    print(f"配置文件：{r['settings']}\n")
    for i, s in enumerate(r["steps"], 1):
        mark = "✓" if s["ok"] is True else ("✗" if s["ok"] is False else "·")
        print(f"  {mark} {s['name']:<10} {s['detail']}")
    print("\n结论：" + r["verdict"])
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
