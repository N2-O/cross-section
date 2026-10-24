"""本地服务：demo 管理 + 分析 + 统计 API + 静态页面。

启动：python server.py [--port 8765] [--no-browser]
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

VERSION = "6.2.4"
# 开源发布仓库（检查新版本用）
REPO_SLUG = "N2-O/cross-section"
RELEASES_URL = f"https://github.com/{REPO_SLUG}/releases"
# 版本检查走网页重定向（/releases/latest → 302 /releases/tag/<tag>），
# 不碰 api.github.com：未认证的 GitHub API 只有 60 次/小时，很容易撞 403。
RELEASES_LATEST = f"{RELEASES_URL}/latest"
UPDATE_TTL = 24 * 3600        # 检查结果缓存 24 小时，别每次开页面都打 GitHub
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import store2          # noqa: E402
import stats_api       # noqa: E402
import settings as S  # noqa: E402
import rounddata  # noqa: E402
import ability    # noqa: E402
import api_v1     # noqa: E402
import awpy_ingest  # noqa: E402
import metrics as metricsmod  # noqa: E402

if getattr(sys, "frozen", False):
    BASE = os.path.dirname(sys.executable)     # 打包后：exe 所在目录
else:
    BASE = os.path.dirname(HERE)               # 开发：项目根目录
DEMO_DIR = os.path.join(BASE, "demos")
DATA_DIR = os.path.join(BASE, "data")
HOST = "127.0.0.1"
for _i, _a in enumerate(sys.argv):
    if _a == "--demos" and _i + 1 < len(sys.argv):
        DEMO_DIR = os.path.abspath(sys.argv[_i + 1])
    if _a == "--data" and _i + 1 < len(sys.argv):
        DATA_DIR = os.path.abspath(sys.argv[_i + 1])
    if _a == "--host" and _i + 1 < len(sys.argv):
        HOST = sys.argv[_i + 1]
WEB_DIR = os.path.join(HERE, "web")
# 配置文件固定在 BASE/data/settings.json（引导位置，不随 data_dir 变化）
BOOT_CFG = os.path.join(BASE, "data", "settings.json")
S.init(BOOT_CFG)
_boot = S.load()
if "--demos" not in sys.argv and _boot.get("demos_dir"):
    DEMO_DIR = os.path.abspath(_boot["demos_dir"])
if "--data" not in sys.argv and _boot.get("data_dir"):
    DATA_DIR = os.path.abspath(_boot["data_dir"])
DB_PATH = os.path.join(DATA_DIR, "cs2.db")
for d in (DEMO_DIR, DATA_DIR, os.path.join(DATA_DIR, "overviews")):
    os.makedirs(d, exist_ok=True)

def _overview_candidates():
    """按优先级列出可能的 overviews 目录。"""
    c = [os.path.join(DATA_DIR, "overviews"),
         os.path.join(BASE, "overviews"),
         os.path.join(HERE, "overviews")]
    cs2 = (_boot or {}).get("cs2_dir")
    if cs2:
        for sub in ("game/csgo/resource/overviews",
                    "csgo/resource/overviews",
                    "Counter-Strike Global Offensive/game/csgo/resource/overviews"):
            c.append(os.path.join(cs2, *sub.split("/")))
    # 自动探测常见 Steam 库
    relatives = []
    for d in "CDEFGH":
        for base in ("SteamApp", "Steam", "SteamLibrary", "Games"):
            relatives.append(f"{d}:/{base}/steamapps/common/Counter-Strike Global Offensive")
    for r in relatives:
        c.append(os.path.join(r, "game", "csgo", "resource", "overviews"))
    return c


def _pick_overviews():
    for d in _overview_candidates():
        try:
            if os.path.isdir(d) and any(f.endswith(".txt") for f in os.listdir(d)):
                return d
        except OSError:
            continue
    return os.path.join(DATA_DIR, "overviews")


OVERVIEW_DIR = _pick_overviews()


def _count_overviews():
    try:
        return sum(1 for f in os.listdir(OVERVIEW_DIR) if f.endswith(".txt"))
    except OSError:
        return 0

REPLAY_DIR = os.path.join(DATA_DIR, "replays")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)
os.makedirs(REPLAY_DIR, exist_ok=True)
MAPS_DIR = os.path.join(WEB_DIR, "maps")
if not os.path.isdir(MAPS_DIR):
    MAPS_DIR = os.path.normpath(os.path.join(HERE, "..", "extract", "app", "_internal", "ui", "assets", "maps"))

_conn = store2.connect(DB_PATH)
_lock = threading.Lock()
_jobs = {"running": False, "total": 0, "done": 0, "current": "", "errors": []}


def _conv(o):
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def _bigint_safe(obj):
    """递归把超出 JS 安全整数范围的 int 转成字符串。

    SteamID64 约 7.6e16，而 JS 的 Number 只能精确到 2^53（9.0e15）。
    直接当 JSON number 发过去，浏览器解析出来末尾几位就被抹平了：
    76561199385933782 → 76561199385933780（实测差 2）。
    后果是点「切换玩家」传回来的 id 根本不存在，后端静默拒绝，下拉弹回原值，
    控制台还一片安静 —— 这个 bug 就是这么来的。
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return str(obj) if abs(obj) > 9007199254740991 else obj
    if isinstance(obj, dict):
        return {k: _bigint_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_bigint_safe(v) for v in obj]
    return obj


def _json(obj, status=200):
    body = json.dumps(_bigint_safe(obj), ensure_ascii=False, default=_conv).encode()
    return status, "application/json; charset=utf-8", body


def _cfg_steamid():
    """settings 里「当前看谁」：my_steamid（切人写的）优先，其次 steamid（Steam 账号）。"""
    cfg = S.load() or {}
    for key in ("my_steamid", "steamid"):
        v = str(cfg.get(key) or "").strip()
        if v:
            try:
                return int(v)
            except ValueError:
                continue
    return None


def _me(conn):
    """找出「我」的 steamid。

    顺序有讲究：不能用 matches.my_steamid 打头。
    那个字段有可能是脏的——历史上 _me() 自己写进去的错误值会一直传染下去
    （真实案例：库里 25 场全是 ...970，而 players 表 249 行里根本没这个人，
    正确的 ...967 出现 24 场，于是 demos 列表 JOIN 不上 pms，满屏横线）。

    所以先用 settings 里显式配置的 steamid，再用 players 的真实名单投票，
    最后才回头看 matches，而且要求它确实在 players 里出现过。
    """
    # 1) settings.my_steamid —— 右上角切人直接写这个。用户手点的就认，
    #    但必须能算出数据（pms 里有行），否则主页会一片空白：
    #    overview 算不出来 → renderAll 在每个区块里都写「还没有对局数据」。
    cfg = S.load() or {}
    v = str(cfg.get("my_steamid") or "").strip()
    if v:
        try:
            sid = int(v)
        except ValueError:
            sid = 0
        if sid and conn.execute(
                "SELECT 1 FROM pms WHERE steamid=? LIMIT 1", (sid,)).fetchone():
            return sid

    # 2) settings.steamid —— Steam 账号，这个是配置值，要求确实在 players 里出现过
    try:
        cfg_sid = int(str(cfg.get("steamid") or "0").strip() or 0)
    except (TypeError, ValueError):
        cfg_sid = 0
    if cfg_sid and conn.execute(
            "SELECT 1 FROM players WHERE steamid=? LIMIT 1", (cfg_sid,)).fetchone():
        return cfg_sid

    # 3) players.is_me=1 —— 同样是人手动切换留下的标记
    r = conn.execute("SELECT steamid FROM players WHERE is_me=1 LIMIT 1").fetchone()
    if r and r["steamid"]:
        return int(r["steamid"])

    # 2) players 表投票：本人场场都在，队友很少
    total = conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]
    if total:
        r = conn.execute(
            """SELECT steamid, COUNT(DISTINCT match_id) n FROM players
               GROUP BY steamid ORDER BY n DESC, steamid LIMIT 1""").fetchone()
        if r and r["n"] >= max(2, total - 1):
            sid = int(r["steamid"])
            with conn:
                conn.execute("UPDATE players SET is_me=(steamid=?)", (sid,))
                conn.execute("UPDATE matches SET my_steamid=?", (sid,))
            print(f"[自动识别] 你在 {r['n']}/{total} 场里都出现，认定为本人: {sid}")
            return sid

    # 3) 最后才看 matches，且必须能在 players 里找到，否则就是脏值
    r = conn.execute("SELECT my_steamid FROM matches WHERE my_steamid IS NOT NULL "
                     "ORDER BY id DESC LIMIT 1").fetchone()
    if r and r["my_steamid"]:
        sid = int(r["my_steamid"])
        if conn.execute("SELECT 1 FROM players WHERE steamid=? LIMIT 1",
                        (sid,)).fetchone():
            return sid
        print(f"[WARN] matches.my_steamid={sid} 不在任何一场的玩家名单里，判定为脏值，忽略")
    return None


def _detect_cs2():
    """从正在运行的 cs2.exe 反推 CS2 根目录 / replays / overviews（Windows）。

    比读注册表靠谱：多 Steam 库、多份安装时，跑着的那个就是你要的那个。
    """
    if not sys.platform.startswith("win"):
        return {"ok": False, "error": "进程探测只在 Windows 上可用"}
    try:
        import subprocess
        ps = ("Get-Process cs2 -ErrorAction SilentlyContinue | "
              "Select-Object -First 1 -ExpandProperty Path")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=12).stdout.strip()
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    if not out or not out.lower().endswith("cs2.exe"):
        return {"ok": False, "error": "没找到运行中的 cs2.exe——先把游戏开起来（大厅界面就行）"}
    d = os.path.dirname(out)
    root = d
    for _ in range(4):                       # ...\game\bin\win64\cs2.exe → CS2 根
        root = os.path.dirname(root)
    if not os.path.isdir(root):
        return {"ok": False, "error": "反推的目录不存在: %s" % root}
    replays = os.path.join(root, "game", "csgo", "replays")
    overviews = os.path.join(root, "game", "csgo", "resource", "overviews")
    steamapps = os.path.dirname(os.path.dirname(root))   # ...\steamapps
    steam_dir = os.path.dirname(steamapps)               # ...\Steam
    return {
        "ok": True,
        "exe": out,
        "cs2_dir": root,
        "replays_dir": replays if os.path.isdir(replays) else "",
        "overviews_dir": overviews if os.path.isdir(overviews) else "",
        "steam_dir": steam_dir,
    }


def api_state():
    with _lock:
        me = _me(_conn)
        demos = store2.list_demos(_conn, me)
        # 每场补两个「物理状态」，列表最前面那两盏灯就是读它们：
        #   file_exists — 原始 .dem 还在不在
        #   has_replay  — 回放缓存（replays/<match_id>.json）在不在
        # 解析成功时回放缓存是同步生成的，所以正常情况下「解析灯亮 = 能回放」；
        # has_replay 单独给出，是为了覆盖旧数据（那段代码之前解析的）和缓存失败的情况。
        for _d in demos:
            _d["file_exists"] = os.path.isfile(os.path.join(DEMO_DIR, _d.get("name") or ""))
            _mid = _d.get("match_id")
            _d["has_replay"] = bool(_mid) and os.path.isfile(
                os.path.join(REPLAY_DIR, "%s.json" % int(_mid)))
        players = stats_api.player_list(_conn)
        ov = stats_api.overview(_conn, me) if me else {"empty": True}
        if me:
            try:
                ov["detail"] = stats_api.detail(_conn, me)
                ov["econ"] = stats_api.econ_stats(_conn, me)
                ov["utility"] = stats_api.utility(_conn, me)
                ov["duel"] = stats_api.duel_stats(_conn, me)
                ability.ensure_snapshots(_conn)
                ov["ability"] = ability.trend(_conn, me)
            except Exception as e:
                import traceback
                ov["detail"] = {"error": str(e),
                                "trace": traceback.format_exc()[-900:]}
        return {"demos": demos, "me": me, "players": players,
                "overview": ov, "job": dict(_jobs),
                "settings": S.load(),
                "version": VERSION,
                # 拉取功能是否存在：取决于有没有解压 AutoPull 增量包（cs2tool/gc_pull.py）
                "gc_pull": _gc_pull_module() is not None,
                "paths": {"demos": DEMO_DIR, "data": DATA_DIR,
                          "db": os.path.join(DATA_DIR, "cs2.db"),
                          "overviews": OVERVIEW_DIR,
                          "overview_count": _count_overviews()}}


def _ver_parts(v):
    """'v6.10.2' → (6, 10, 2)。只认数字段，非数字的段忽略，解析不出返回 ()。"""
    out = []
    for seg in str(v or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        if not digits:
            continue
        try:
            out.append(int(digits))
        except ValueError:
            continue
    return tuple(out)


def _ver_newer(latest, current):
    """逐段按整数比，短的一边补 0：6.10 > 6.9（字符串比会反过来）。

    任何一边解析不出段就当作「不更新」，宁可漏报也不要误报。
    """
    a, b = _ver_parts(latest), _ver_parts(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def _err_brief(e):
    """异常压成一行短原因，给前端看，不往 stderr 丢 traceback。"""
    code = getattr(e, "code", None)
    if code:
        return "HTTP %s" % code
    msg = str(getattr(e, "reason", "") or e or "").replace("\n", " ").strip()
    return (type(e).__name__ + (": " + msg if msg else ""))[:120]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """不让 urllib 自动跟随 3xx：版本号就写在 Location 里，跟过去白多一次请求。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _release_tag_from_location(loc):
    """把 302 的 Location 拆成 (tag, 页面地址)。

    - 含 /releases/tag/<tag> → 有正式 Release，tag 取最后一段（URL 解码）
    - 其它（多半是跳到 /releases）→ 仓库在、但还没发版，tag 为空
    """
    loc = str(loc or "").strip()
    if not loc:
        return "", RELEASES_URL
    if loc.startswith("/"):                      # 相对路径补上域名
        loc = "https://github.com" + loc
    page = urlparse(loc)._replace(query="", fragment="").geturl()
    marker = "/releases/tag/"
    if marker not in page:
        return "", RELEASES_URL
    tag = unquote(page.rsplit(marker, 1)[1].strip("/"))
    return (tag, page) if tag else ("", RELEASES_URL)


_update_check_state = {"running": False}
_update_check_lock = threading.Lock()


def _update_check_network():
    """真去问一次 GitHub（301/302 的 Location 里带 tag），成功才写缓存。

    失败一律吞掉：被墙、DNS、超时、404 都不抛，也不留痕。
    """
    now = int(time.time())
    cache_path = os.path.join(DATA_DIR, "update_check.json")
    try:
        req = urllib.request.Request(RELEASES_LATEST, headers={
            "User-Agent": f"Cross-Section/{VERSION}",   # 不带 UA 会被 GitHub 403
        })
        status, loc = 0, ""
        try:
            # 不跟随跳转：3xx 在这里会抛 HTTPError，但 headers 里带着 Location
            with urllib.request.build_opener(_NoRedirect).open(req, timeout=2) as r:
                status, loc = r.status, r.headers.get("Location") or ""
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                status = e.code                 # 3xx 是正常路径
                loc = (e.headers.get("Location") if e.headers else "") or ""
            else:
                return                          # 404 / 其它：不缓存，静默
        if status not in (301, 302, 303, 307, 308):
            return
        tag, page = _release_tag_from_location(loc)
        latest = tag.lstrip("vV") or VERSION     # 还没发版 → 就当自己是最新
        res = {"ok": True, "current": VERSION, "latest": latest,
               "newer": _ver_newer(latest, VERSION),
               "url": page,
               "releases_url": RELEASES_URL, "checked_at": now}
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False)
        except OSError:
            pass
    except Exception:
        pass


def _update_check_spawn():
    """后台跑一次版本检查；已经有线程在跑就不重复起。"""
    with _update_check_lock:
        if _update_check_state["running"]:
            return
        _update_check_state["running"] = True

    def _run():
        try:
            _update_check_network()
        finally:
            with _update_check_lock:
                _update_check_state["running"] = False

    threading.Thread(target=_run, daemon=True, name="update-check").start()


def api_update_check():
    """只读缓存，**绝不在这里联网**。

    以前这一支在缓存过期时会现场去问 GitHub，被墙的机器每次打开页面都要白等
    2 秒。现在改成：启动时后台查一次写缓存；页面请求只读文件——
      有新鲜缓存  → 直接返回（cached）
      缓存过期    → 返回旧值并标 stale，同时在后台刷新
      完全没有    → 返回 pending，同时在后台查
    页面因此永远不会为了「有没有新版本」卡住，下一次刷新就能看到徽章。
    """
    now = int(time.time())
    cache_path = os.path.join(DATA_DIR, "update_check.json")
    base = {"current": VERSION, "releases_url": RELEASES_URL}
    try:
        with open(cache_path, encoding="utf-8") as f:
            c = json.load(f)
        if not isinstance(c, dict) or c.get("ok") is False:
            raise ValueError("bad cache")
        fresh = now - int(c.get("checked_at") or 0) < UPDATE_TTL
        out = dict(c)
        out.update({"ok": True, "cached": True, "current": VERSION,
                    "releases_url": RELEASES_URL})
        if not fresh:
            out["stale"] = True
            _update_check_spawn()       # 过期：后台刷新，不影响这次返回
        return out
    except (OSError, ValueError, TypeError):
        _update_check_spawn()           # 没缓存：后台去查，这次先回 pending
        return {"ok": False, "pending": True, **base}


def api_reset_all():
    """清空所有分析数据、缓存、导出和设置。demo 文件不动。"""
    if _jobs["running"]:
        return {"ok": False, "error": "有其他任务正在运行，请等它完成"}
    _jobs.update(running=True, total=5, done=0, current="准备中", errors=[])

    def worker():
        try:
            # 1) 数据库
            _jobs["current"] = "清空数据库"
            with _lock:
                # 一次清空所有按 match_id 存的子表 + 主表。
                # 清单只在 store2.MATCH_CHILD_TABLES 维护一份，不要在这里另写。
                for t in store2.MATCH_CHILD_TABLES + ("matches", "demos"):
                    try:
                        _conn.execute(f"DELETE FROM {t}")
                    except sqlite3.OperationalError:
                        pass
                _conn.commit()
                try:
                    _conn.execute("VACUUM")
                except sqlite3.OperationalError:
                    pass
            _jobs["done"] += 1

            # 2) 回放缓存
            _jobs["current"] = "删除回放缓存"
            for f in os.listdir(REPLAY_DIR):
                if f.endswith(".json"):
                    try:
                        os.remove(os.path.join(REPLAY_DIR, f))
                    except OSError:
                        pass
            _jobs["done"] += 1

            # 3) 导出报告
            _jobs["current"] = "删除导出报告"
            exp = os.path.join(DATA_DIR, "exports")
            if os.path.isdir(exp):
                for f in os.listdir(exp):
                    try:
                        os.remove(os.path.join(exp, f))
                    except OSError:
                        pass
            _jobs["done"] += 1

            # 4) 设置
            _jobs["current"] = "重置设置"
            try:
                if os.path.isfile(BOOT_CFG):
                    os.remove(BOOT_CFG)
            except OSError:
                pass
            try:
                S.init(BOOT_CFG)
            except Exception:
                pass
            _jobs["done"] += 1

            # 5) 重新登记 demo 文件
            _jobs["current"] = "重新扫描 demo 目录"
            with _lock:
                store2.scan_demos(_conn, DEMO_DIR)
            _jobs["done"] += 1
        except Exception as e:
            _jobs["errors"].append(f"{type(e).__name__}: {e}")
            traceback.print_exc()
        finally:
            _jobs.update(running=False, current="")

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "need_restart": True}


def api_scan():
    with _lock:
        # 带上 settings 里的 steamid：scan 时会用它补 matches.my_steamid
        r = store2.scan_demos(_conn, DEMO_DIR, _cfg_steamid())
    return {"ok": True, **r}


def _replays_dir():
    """CS2 的 replays 目录：设置里的 → 由 cs2_dir 推 → 从进程探测。"""
    st = S.load() or {}
    cands = []
    if st.get("replays_dir"):
        cands.append(st["replays_dir"])
    cs2 = st.get("cs2_dir") or ""
    if cs2:
        cands.append(os.path.join(cs2, "game", "csgo", "replays"))
    try:
        det = _detect_cs2()
        if det.get("replays_dir"):
            cands.append(det["replays_dir"])
    except Exception:
        pass
    return next((c for c in cands if c and os.path.isdir(c)), None)


def api_pull():
    """从 CS2 的 replays 目录把新 demo 复制过来。
    CS2 客户端里「下载 demo」后文件落在 <CS2>/game/csgo/replays/*.dem，
    用户不用手动去文件夹里翻。路径优先用设置里的 replays_dir，
    没有就按 cs2_dir 推，再没有就自动探测。
    """
    src = _replays_dir()
    if not src:
        return {"ok": False,
                "error": "找不到 CS2 的 replays 目录。请在「设置 → CS2 安装目录」里填写，"
                         "或手动把 .dem 复制到 demos/ 目录。"}

    os.makedirs(DEMO_DIR, exist_ok=True)
    have = {f for f in os.listdir(DEMO_DIR) if f.lower().endswith(".dem")}
    added, skipped, failed = [], 0, []
    try:
        files = [f for f in os.listdir(src) if f.lower().endswith(".dem")]
    except OSError as e:
        return {"ok": False, "error": f"读不了 replays 目录：{e}"}

    for f in files:
        if f in have:
            skipped += 1
            continue
        try:
            shutil.copy2(os.path.join(src, f), os.path.join(DEMO_DIR, f))
            added.append(f)
        except OSError as e:
            failed.append(f"{f}: {e}")

    with _lock:
        store2.scan_demos(_conn, DEMO_DIR)
    return {"ok": True, "src": src, "added": len(added), "skipped": skipped,
            "failed": failed[:5], "names": added[:50]}


# ---------------------------------------------------------------- HTTP 直下
# 绕开 CS2 客户端：分享码本地解出 matchId，扫 Valve 的 CDN 分片找到 .dem.bz2，
# 直接 HTTP 下载（支持 Range 续传）。比「双击 bat 让 CS2 下」稳，也能走代理。
_http_pull = {"running": False, "total": 0, "done": 0, "current": "",
              "bytes": 0, "bytes_total": 0, "error": None,
              "ok_count": 0, "fail_count": 0, "errors": []}


def _gc_pull_module():
    """AutoPull 增量包提供的模块。主程序里**没有**这个文件，所以这个功能默认不存在。

    增量包解压到程序根目录后会多出 cs2tool/gc_pull.py，这里就能 import 到。
    故意做成「存在才启用」：正式包里不含任何借 Steam 登录态的代码。
    """
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gc_pull.py")
    if not os.path.isfile(p):
        return None
    try:
        import gc_pull  # noqa: F401
        return gc_pull
    except Exception:
        return None


def api_gc_pull(payload=None):
    payload = payload or {}
    mod = _gc_pull_module()
    if mod is None:
        return {"ok": False, "need_patch": True,
                "error": "这个功能需要「AutoPull 增量包」：把包解压到程序根目录后重启即可"}
    mode = str(payload.get("mode") or "recent")
    log = lambda s: print("[autopull]", s, flush=True)
    try:
        if mode == "codes":
            codes = payload.get("codes") or []
            if isinstance(codes, str):
                codes = [c for c in re.split(r"[\s,，;；]+", codes) if c.strip()]
            r = mod.fetch_by_codes(codes, DATA_DIR, log=log)
        else:
            r = mod.fetch(DATA_DIR, log=log)
    except Exception as e:
        return {"ok": False, "error": "AutoPull 出错：%s" % e}
    if r.get("ok"):
        print("[autopull] %s：%d 场，%d 场可下载"
              % ("按分享码" if mode == "codes" else "最近比赛",
                 len(r.get("matches") or []), len(r.get("urls") or [])), flush=True)
    return r


def api_http_pull(items=None):
    if _http_pull["running"]:
        return {"ok": False, "error": "已有下载任务在进行"}
    if not items:
        # 待下载清单：优先 pull_pending，其次 pull_last
        # 新链写 urls（AutoPull 给的完整地址），老链写 codes（分享码，已废弃）
        for fn in ("pull_pending.json", "pull_last.json"):
            try:
                with open(os.path.join(DATA_DIR, fn), encoding="utf-8") as f:
                    _d = json.load(f) or {}
                    items = _d.get("urls") or _d.get("codes") or []
            except Exception:
                items = []
            if items:
                break
    if not items:
        return {"ok": False, "error": "没有待下载的清单——先点「从 Steam 拉新比赛」"}
    try:
        import demoget  # 懒加载：老包里没这个文件也不影响其它功能
    except Exception as e:
        return {"ok": False, "error": f"下载模块不可用：{e}"}
    _http_pull.update({"running": True, "total": len(items), "done": 0, "current": "",
                       "bytes": 0, "bytes_total": 0, "error": None,
                       "ok_count": 0, "fail_count": 0, "errors": []})
    threading.Thread(target=_http_pull_worker, args=(list(items),), daemon=True).start()
    return {"ok": True, "total": len(items)}


def _http_pull_worker(codes):
    import demoget
    tmp = os.path.join(DATA_DIR, "dl")
    os.makedirs(tmp, exist_ok=True)

    def _prog(done, total):
        # demoget 拿不到 Content-Length 时 total 会传 -1；别让它变成负宽度
        d = int(done or 0)
        t = int(total or 0)
        _http_pull["bytes"] = d
        _http_pull["bytes_total"] = t if t > 0 else 0

    try:
        for i, code in enumerate(codes, 1):
            _http_pull["current"] = str(code)
            _http_pull["bytes"] = _http_pull["bytes_total"] = 0
            r = demoget.download_one(str(code), DEMO_DIR, tmp, log=print, progress=_prog)
            _http_pull["current"] = r.get("body") or str(code)
            if r.get("ok"):
                _http_pull["ok_count"] = _http_pull.get("ok_count", 0) + 1
            else:
                _http_pull["fail_count"] = _http_pull.get("fail_count", 0) + 1
                _http_pull["errors"] = (_http_pull.get("errors") or []) + [r.get("error")]
            _http_pull["done"] = i
        with _lock:
            store2.scan_demos(_conn, DEMO_DIR, _cfg_steamid())
    except Exception as e:
        _http_pull["error"] = f"{type(e).__name__}: {e}"
    finally:
        _http_pull["running"] = False
        _http_pull["bytes"] = _http_pull["bytes_total"] = 0
        # 把真实结果写成「上次检查」那一行，别让它还挂着「已生成 bat」这种过时文案
        _okc = int(_http_pull.get("ok_count") or 0)
        _failc = int(_http_pull.get("fail_count") or 0)
        _msg = (f"已下载 {_okc} 场" + (f"，失败 {_failc} 场" if _failc else "")
                if _okc else (f"下载失败 {_failc} 场" if _failc else "没有可下载的场次"))
        try:
            with open(os.path.join(DATA_DIR, "pull_last.json"), "w", encoding="utf-8") as f:
                json.dump({"t": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "ok": _failc == 0 and _okc > 0,
                           "status": "ok" if _okc and not _failc else "error",
                           "added": _okc, "failed": _failc, "msg": _msg,
                           # 失败也留着清单 —— 重试时靠它，别让已经推进的起点无法补下
                           "urls": list(codes),
                           "errors": (_http_pull.get("errors") or [])[:3]},
                          f, ensure_ascii=False, indent=2)
        except OSError:
            pass


def api_playdemo(name: str):
    """生成 CS2 控制台的 playdemo 命令（绝对路径，文件不用挪位置）。"""
    nm = os.path.basename(str(name or "").strip())
    if not nm:
        return {"ok": False, "error": "缺少文件名"}
    src = os.path.join(DEMO_DIR, nm)
    if not os.path.isfile(src):
        return {"ok": False, "error": f"找不到文件：{src}"}
    return {"ok": True, "cmd": f'playdemo "{src}"', "path": src}


def api_analyze(names: list[str], force: bool = False):
    if _jobs["running"]:
        return {"ok": False, "error": "已有分析任务在进行"}
    with _lock:
        todo = []
        for nm in names:
            row = _conn.execute("SELECT analyzed, match_id FROM demos WHERE name=?", (nm,)).fetchone()
            if not force and row and row["analyzed"] and row["match_id"]:
                continue
            path = os.path.join(DEMO_DIR, nm)
            if os.path.isfile(path):
                todo.append((nm, path))
    if not todo:
        return {"ok": True, "done": 0, "msg": "没有待分析的文件"}

    _jobs.update(running=True, total=len(todo), done=0, current="", errors=[])
    me = _me(_conn)

    def worker():
        # 解析用独立连接，不占全局 _lock —— 否则整场解析（5 场约 2 分钟）会把
        # 全局连接锁死，期间所有 API 请求全部排队，页面看起来像卡住。
        # sqlite 是 WAL 模式，多连接并发读写没有问题。
        ws = store2.connect(DB_PATH)
        try:
            for nm, path in todo:
                _jobs["current"] = nm
                try:
                    mid = awpy_ingest.ingest_awpy(ws, path, me, log=lambda *a: None, force=force)
                    # 只有这两个「写全局状态」的动作需要短锁
                    with _lock:
                        row = _conn.execute("SELECT map, platform, server FROM matches WHERE id=?", (mid,)).fetchone()
                        store2.mark_analyzed(_conn, nm, mid, row["map"], row["platform"], row["server"])
                    # demo 分析完就被清理了；不在这里留一份回放数据，之后永远播不了
                    try:
                        _rp = os.path.join(REPLAY_DIR, f"{mid}.json")
                        if not os.path.exists(_rp):
                            _rd = rounddata.build(ws, mid, path, OVERVIEW_DIR)
                            with open(_rp, "w", encoding="utf-8") as _f:
                                json.dump(_rd, _f, ensure_ascii=False,
                                          separators=(",", ":"), default=_conv)
                    except Exception as _e:
                        _jobs["errors"].append(f"{nm}: 回放缓存失败 {type(_e).__name__}: {_e}")
                except Exception as e:
                    _jobs["errors"].append(f"{nm}: {type(e).__name__}: {e}")
                    with _lock:
                        store2.mark_error(_conn, nm, f"{type(e).__name__}: {e}")
                    traceback.print_exc()
                _jobs["done"] += 1
        finally:
            try:
                ws.close()
            except Exception:
                pass
            _jobs.update(running=False, current="")
    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "queued": len(todo)}


class Handler(BaseHTTPRequestHandler):
    server_version = "CS2Tool/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, ctype, body):
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            # 允许本地工具 / 浏览器插件跨源调用只读 API
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # 浏览器提前断开（用户切页面/关标签），不是错误，静默忽略
            pass

    def do_OPTIONS(self):
        # CORS 预检
        self._send(204, "text/plain", b"")

    def do_GET(self):
        u = urlparse(self.path)
        path = unquote(u.path)
        qs = parse_qs(u.query)
        try:
            # ---- 只读 API v1（供外部 AI / harness 调用）----
            if path == "/api/v1/map_pool":
                import export_csv
                return self._send(*_json({"ok": True, "maps": export_csv.map_pool(DB_PATH)}))
            if path.startswith("/api/v1"):
                with _lock:
                    r = api_v1.dispatch(_conn, path, qs)
                return self._send(*_json(r[1], r[0]))
            if path == "/api":
                return self._send(200, "text/html; charset=utf-8",
                                  api_v1.doc_page().encode())
            if path == "/api/metrics":
                return self._send(*_json({"ok": True, "version": metricsmod.VERSION,
                                          "metrics": metricsmod.all_metrics()}))
            if path == "/api/export/csv":
                import export_csv
                only_me = (qs.get("me", ["0"])[0] == "1")
                out = os.path.join(EXPORT_DIR, "cs2_export_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
                export_csv.write_csv(DB_PATH, out, only_me=only_me)
                data = open(out, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="%s"' % os.path.basename(out))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/state":
                return self._send(*_json(api_state()))
            if path == "/api/update_check":
                return self._send(*_json(api_update_check()))
            if path == "/api/detect":
                return self._send(*_json(_detect_cs2()))
            if path == "/api/scan":
                return self._send(*_json(api_scan()))
            if path == "/api/pull":
                return self._send(*_json(api_pull()))
            if path == "/api/http_pull_progress":
                return self._send(*_json(_http_pull))
            if path == "/api/pull_result":
                # 上次拉取结果（自动检查或手动跑过之后写的）
                _p = os.path.join(DATA_DIR, "pull_last.json")
                try:
                    with open(_p, encoding="utf-8") as _f:
                        return self._send(*_json(json.load(_f)))
                except Exception:
                    return self._send(*_json({"ok": None, "msg": "还没有拉取记录"}))
            if path == "/api/bg":
                # 自定义背景优先，没有就用内置那张
                bn = (S.load() or {}).get("bg_custom") or ""
                fp = os.path.join(DATA_DIR, bn) if bn else ""
                if not (fp and os.path.isfile(fp)):
                    fp = os.path.join(WEB_DIR, "bg.jpg")
                if not os.path.isfile(fp):
                    return self._send(404, "text/plain", b"no bg")
                ct = mimetypes.guess_type(fp)[0] or "image/jpeg"
                with open(fp, "rb") as f:
                    return self._send(200, ct, f.read())
            if path == "/api/overview":
                sid = int(qs.get("steamid", ["0"])[0])
                with _lock:
                    return self._send(*_json(stats_api.overview(_conn, sid)))
            if path == "/api/replay":
                # 前端链接用 ?m=，历史/文档里写过 ?match=，两个都认
                mid = int(qs.get("m", qs.get("match", ["0"]))[0] or 0)
                rp = os.path.join(REPLAY_DIR, f"{mid}.json")
                if os.path.exists(rp):
                    with open(rp, "rb") as f:
                        return self._send(200, "application/json; charset=utf-8", f.read())
                row = _conn.execute("SELECT file FROM matches WHERE id=?", (mid,)).fetchone()
                if not row:
                    return self._send(*_json({"ok": False, "error": "match 不存在"}, 404))
                demo = os.path.join(DEMO_DIR, row["file"])
                if not os.path.isfile(demo):
                    return self._send(*_json({"ok": False, "error": f"demo 文件不在: {demo}"}, 404))
                data = None
                try:
                    # 单独开一条连接：build 要跑 30 秒，若跟别的请求共用全局 _conn，
                    # sqlite 会抛 "bad parameter or other API misuse"（match 5 就这样 500 过）
                    _c2 = store2.connect(DB_PATH)
                    try:
                        data = rounddata.build(_c2, mid, demo, OVERVIEW_DIR)
                    finally:
                        _c2.close()
                except FileNotFoundError as e:
                    # 缺地图雷达参数：不打印 traceback，给可读提示
                    msg = str(e).replace("\n", " ")
                    return self._send(*_json({"ok": False, "error": msg}, 404))
                with open(rp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, separators=(",", ":"), default=_conv)
                return self._send(*_json(data))
            if path.startswith("/maps/"):
                fn = os.path.basename(path)
                fp2 = os.path.join(MAPS_DIR, fn)
                if os.path.isfile(fp2):
                    with open(fp2, "rb") as f:
                        return self._send(200, "image/png", f.read())
                return self._send(404, "text/plain", b"no map")
            if path == "/api/open_demos":
                _open_folder(DEMO_DIR)
                return self._send(*_json({"ok": True}))
            # 静态文件
            if path == "/" or path == "":
                path = "/index.html"
            fp = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
            if not fp.startswith(WEB_DIR) or not os.path.isfile(fp):
                return self._send(404, "text/plain; charset=utf-8", b"not found")
            ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
            if fp.endswith((".html", ".js", ".css")):
                ctype += "; charset=utf-8"
            with open(fp, "rb") as f:
                return self._send(200, ctype, f.read())
        except Exception as e:
            traceback.print_exc()
            return self._send(*_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500))

    def do_POST(self):
        # DEMO_DIR 会在 /api/settings 里被改（用户改 demo 目录），所以整个 do_POST
        # 都算「使用并可能重绑」它 —— 声明必须放在函数最开头，不能等到后面某个分支，
        # 否则前面任何分支读到它都会被判定「使用早于 global 声明」。
        global DEMO_DIR
        u = urlparse(self.path)
        try:
            ln = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(ln).decode() or "{}") if ln else {}
            if u.path == "/api/scan":
                return self._send(*_json(api_scan()))
            if u.path == "/api/analyze":
                names = payload.get("names")
                if not names:
                    # 按钮叫「分析未处理」，不传名字就该自己找没分析过的。
                    # 之前直接把空列表丢给 api_analyze，它遍历空列表 → 永远返回
                    # 「没有待分析的文件」，看起来像按钮坏了。
                    with _lock:
                        names = [r["name"] for r in _conn.execute(
                            "SELECT name FROM demos "
                            "WHERE analyzed=0 OR match_id IS NULL ORDER BY id")]
                return self._send(*_json(api_analyze(names)))
            if u.path == "/api/reparse":
                # 强制重新解析：不传 names = 全部；传了 = 只重解析这几场
                names = payload.get("names")
                single = bool(names)
                if not names:
                    names = [r["name"] for r in
                             _conn.execute("SELECT name FROM demos").fetchall()]
                if not names:
                    return self._send(*_json({"ok": False, "error": "demo 列表为空"}))
                # 旧回放缓存基于旧数据，必须先清。单场重解析只清那一场的缓存——
                # 不然重解一场会把其他场几 MB 的缓存一起废掉。
                if single:
                    for nm in names:
                        row = _conn.execute("SELECT match_id FROM demos WHERE name=?",
                                            (nm,)).fetchone()
                        if row and row["match_id"]:
                            try:
                                os.remove(os.path.join(REPLAY_DIR, f"{int(row['match_id'])}.json"))
                            except OSError:
                                pass
                else:
                    for f in os.listdir(REPLAY_DIR):
                        if f.endswith(".json"):
                            try:
                                os.remove(os.path.join(REPLAY_DIR, f))
                            except OSError:
                                pass
                return self._send(*_json(api_analyze(names, force=True)))
            if u.path == "/api/delete_demo":
                # mode=all（默认）：原始 .dem + 分析数据 + 回放缓存 + 列表行，一起删
                # mode=file_only  ：只删原始 .dem，数据和回放缓存都留着（省空间用）
                nm = str(payload.get("name") or "").strip()
                if not nm:
                    return self._send(*_json({"ok": False, "error": "缺少 name"}))
                mode = str(payload.get("mode") or "all").strip().lower()
                demo_path = os.path.join(DEMO_DIR, nm)
                with _lock:
                    row = _conn.execute("SELECT match_id FROM demos WHERE name=?",
                                        (nm,)).fetchone()
                    if not row:
                        return self._send(*_json({"ok": False, "error": f"列表里没有 {nm}"}))
                    mid = row["match_id"]

                # 两种模式都要删原始文件；文件本来就不在就跳过
                freed = 0
                if os.path.isfile(demo_path):
                    try:
                        freed = os.path.getsize(demo_path)
                        os.remove(demo_path)
                    except OSError as e:
                        return self._send(*_json({"ok": False, "error": f"删文件失败：{e}"}))

                if mode == "file_only":
                    # 只瘦身：demos 行留着，列表上文件灯变灭、解析灯照旧亮
                    return self._send(*_json({
                        "ok": True, "name": nm, "mode": "file_only", "freed": freed,
                        "msg": "已删除原始文件（释放 %.0f MB），分析数据保留" % (freed / 1048576.0),
                        "warn": "这场以后不能再重新解析了"}))

                with _lock:
                    if mid:
                        store2.delete_match(_conn, int(mid))
                        try:
                            os.remove(os.path.join(REPLAY_DIR, f"{int(mid)}.json"))
                        except OSError:
                            pass
                    _conn.execute("DELETE FROM demos WHERE name=?", (nm,))
                    _conn.commit()
                return self._send(*_json({"ok": True, "name": nm, "mode": "all", "freed": freed,
                                          "msg": "已删除 %s（原始文件 + 分析数据，释放 %.0f MB）"
                                                 % (nm, freed / 1048576.0)}))
            if u.path == "/api/reset_all":
                return self._send(*_json(api_reset_all()))
            if u.path == "/api/clear_cache":
                # 只清不解析：删回放缓存 + 清解析结果，demo 标记回未分析
                n_file = 0
                for f in os.listdir(REPLAY_DIR):
                    if f.endswith(".json"):
                        try:
                            os.remove(os.path.join(REPLAY_DIR, f))
                            n_file += 1
                        except OSError:
                            pass
                # demos 表保留（列表要回到「未分析」而不是消失），
                # matches 与所有子表清空。
                with _lock:
                    for t in store2.MATCH_CHILD_TABLES + ("matches",):
                        try:
                            _conn.execute("DELETE FROM " + t)
                        except Exception:
                            pass
                    _conn.execute("UPDATE demos SET analyzed=0, match_id=NULL, error=NULL")
                    _conn.commit()
                return self._send(*_json({"ok": True, "files_removed": n_file,
                                          "msg": "已清除解析缓存，列表回到未分析"}))
            if u.path == "/api/set_me":
                sid = int(payload.get("steamid") or 0)
                if not sid:
                    return self._send(*_json({"ok": False, "error": "缺少 steamid"}))
                # 切到库里没有任何数据的人会让主页整片空白（overview 算不出来），
                # 这里直接挡掉，比让人切过去看到空白页好。
                with _lock:
                    has = _conn.execute(
                        "SELECT 1 FROM pms WHERE steamid=? LIMIT 1", (sid,)).fetchone()
                if not has:
                    return self._send(*_json({
                        "ok": False,
                        "error": "这个人在 demo 里没有统计数据（可能还没解析），换个人试试"}))
                S.set(my_steamid=sid)
                with _lock:
                    _conn.execute("UPDATE matches SET my_steamid=?", (sid,))
                    _conn.execute("UPDATE players SET is_me=(steamid=?)", (sid,))
                    _conn.commit()
                    # 注：这里不再重算 pms —— 指标由 awpy 解析产出，
                    # 用旧的 compute_match 重算会把口径覆盖回错误版本。
                return self._send(*_json({"ok": True}))
            if u.path == "/api/settings":
                upd = {}
                nd = (payload.get("demos_dir") or "").strip().strip('"')
                if nd:
                    if not os.path.isdir(nd):
                        return self._send(*_json({"ok": False, "error": f"目录不存在: {nd}"}))
                    DEMO_DIR = os.path.abspath(nd)
                    upd["demos_dir"] = DEMO_DIR
                ndata = (payload.get("data_dir") or "").strip().strip('"')
                need_restart = False
                if ndata:
                    if not os.path.isdir(ndata):
                        try:
                            os.makedirs(ndata, exist_ok=True)
                        except Exception:
                            return self._send(*_json({"ok": False, "error": f"无法创建目录: {ndata}"}))
                    if os.path.abspath(ndata) != DATA_DIR:
                        upd["data_dir"] = os.path.abspath(ndata)
                        need_restart = True
                ncs2 = (payload.get("cs2_dir") or "").strip().strip('"')
                if ncs2 and ncs2 != (S.load() or {}).get("cs2_dir", ""):
                    upd["cs2_dir"] = ncs2
                    need_restart = True
                elif not ncs2 and (S.load() or {}).get("cs2_dir"):
                    upd["cs2_dir"] = ""
                    need_restart = True
                # Steam 相关只剩两项：steamid（识别「我」）、replays_dir（从 CS2 目录拷 demo）
                # 允许直接粘链接：steamid 从主页 URL 里提取 17 位数字，省得人数位数
                _notes = []
                _raw = {k: payload.get(k) for k in ("steamid", "replays_dir") if k in payload}
                for _k, _v in _raw.items():
                    _val = str(_v or "").strip().strip('"')
                    if _k == "steamid":
                        _m = re.search(r"\d{17}", _val)
                        if _m:
                            if _m.group(0) != _val:
                                _notes.append("steamid：已从输入里取出 17 位数字")
                            _val = _m.group(0)
                        elif _val:
                            _notes.append("steamid：没找到 17 位数字")
                    upd[_k] = _val
                if "auto_pull_hours" in payload:
                    try:
                        upd["auto_pull_hours"] = max(0.0, float(payload.get("auto_pull_hours") or 0))
                    except (TypeError, ValueError):
                        upd["auto_pull_hours"] = 0
                # 外观：烟雾开关 / 主题色调（"r,g,b"）
                if "fx_smoke" in payload:
                    upd["fx_smoke"] = 1 if payload.get("fx_smoke") else 0
                if "fx_tip" in payload:
                    upd["fx_tip"] = 1 if payload.get("fx_tip") else 0
                if "theme_tint" in payload:
                    _t = str(payload.get("theme_tint") or "").strip()
                    if _t and len(_t.split(",")) == 3:
                        upd["theme_tint"] = _t
                if "player_min_matches" in payload:
                    # 玩家下拉筛选阈值：0 = 全部（含路人），越大筛得越狠
                    try:
                        upd["player_min_matches"] = max(0, int(payload.get("player_min_matches") or 0))
                    except Exception:
                        upd["player_min_matches"] = 1
                if "bg_custom" in payload:
                    # 传空串 = 恢复默认背景
                    upd["bg_custom"] = str(payload.get("bg_custom") or "").strip()
                S.set(**upd)
                with _lock:
                    store2.scan_demos(_conn, DEMO_DIR, _cfg_steamid())
                return self._send(*_json({"ok": True, "need_restart": need_restart,
                                          "notes": _notes,
                                          "paths": {"demos": DEMO_DIR, "data": DATA_DIR}}))
            if u.path == "/api/playdemo":
                # 生成 playdemo 命令用的；顺带把 demo 放进 CS2 的 csgo 目录
                return self._send(*_json(api_playdemo(payload.get("name"))))
            if u.path == "/api/gc_pull":
                # 借本机 Steam 登录态取比赛列表（需要 AutoPull 增量包，主包没有这个文件）
                # mode=recent 取最近 8 场；mode=codes 按给定的分享码逐场查
                return self._send(*_json(api_gc_pull(payload)))
            if u.path == "/api/http_pull":
                # 直接走 Valve 的 demo CDN 下载（绕开 CS2 客户端）。
                # urls = 从比赛历史页复制来的链接；codes = 上次清单（只能定位比赛，拼不出地址）
                _items = payload.get("urls") or payload.get("codes")
                return self._send(*_json(api_http_pull(_items)))
            if u.path == "/api/set_excluded":
                # 标记/取消标记「这局不算数」：投降、摆烂、半路不打了。
                # 数据留在库里，只是默认不参与平均/走势/能力画像。
                mid = int(payload.get("match_id") or 0)
                on = 1 if payload.get("excluded") else 0
                note = str(payload.get("note") or "").strip()[:120]
                if not mid:
                    return self._send(*_json({"ok": False, "error": "缺 match_id"}, 400))
                with _lock:
                    cur = _conn.execute(
                        "UPDATE matches SET excluded=?, exclude_note=? WHERE id=?",
                        (on, note or None, mid))
                    _conn.commit()
                if not cur.rowcount:
                    return self._send(*_json({"ok": False, "error": "match 不存在"}, 404))
                return self._send(*_json({"ok": True, "match_id": mid, "excluded": bool(on)}))
            if u.path == "/api/upload_bg":
                import base64
                d = str(payload.get("data") or "")
                if "," not in d:
                    return self._send(*_json({"ok": False, "error": "缺少图片数据"}))
                head, b64 = d.split(",", 1)
                ext = "jpg"
                hl = head.lower()
                for e in ("png", "webp", "jpeg", "jpg"):
                    if e in hl:
                        ext = "jpg" if e == "jpeg" else e
                        break
                try:
                    raw = base64.b64decode(b64)
                except Exception:
                    return self._send(*_json({"ok": False, "error": "图片解码失败"}))
                if len(raw) > 12 * 1024 * 1024:
                    return self._send(*_json({"ok": False, "error": "图片太大（上限 12MB）"}))
                for old in os.listdir(DATA_DIR):
                    if old.startswith("bg_custom."):
                        try:
                            os.remove(os.path.join(DATA_DIR, old))
                        except OSError:
                            pass
                fp = os.path.join(DATA_DIR, "bg_custom." + ext)
                with open(fp, "wb") as f:
                    f.write(raw)
                S.set(bg_custom=os.path.basename(fp))
                return self._send(*_json({"ok": True, "file": os.path.basename(fp),
                                          "v": int(time.time())}))
            if u.path == "/api/export":
                # 一份自包含 CSV：注释头里就写着「给 AI 的指令」+ 字段口径，
                # 后面是汇总行与逐场明细。丢给任何 AI 都能直接开始分析。
                import export_csv
                me = _me(_conn)
                if not me:
                    return self._send(*_json({"ok": False, "error": "还没确定玩家身份"}))
                out = os.path.join(DATA_DIR, "exports")
                os.makedirs(out, exist_ok=True)
                fn = "cs2_export_%s.csv" % time.strftime("%Y%m%d_%H%M%S")
                export_csv.write_csv(DB_PATH, os.path.join(out, fn))
                _open_folder(out)
                return self._send(*_json({"ok": True, "dir": out, "file": fn,
                                          "size": os.path.getsize(os.path.join(out, fn))}))
            if u.path == "/api/open_data":
                _open_folder(DATA_DIR)
                return self._send(*_json({"ok": True}))
            if u.path == "/api/pick_dir":
                # 桌面端无原生对话框：返回建议路径，由前端展示
                return self._send(*_json({"ok": True, "demos": DEMO_DIR, "data": DATA_DIR}))
            return self._send(404, "text/plain", b"no route")
        except Exception as e:
            traceback.print_exc()
            return self._send(*_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500))


def _open_folder(p):
    try:
        if sys.platform.startswith("win"):
            os.startfile(p)  # noqa
        elif sys.platform == "darwin":
            os.system(f'open "{p}"')
        else:
            os.system(f'xdg-open "{p}" >/dev/null 2>&1 &')
    except Exception:
        pass


def free_port(start=8765):
    for p in range(start, start + 60):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return 8765


def _kill_port_owner(port: int) -> bool:
    """Windows: 杀掉占用指定端口的进程（旧实例）。返回是否动了手。"""
    if os.name != "nt":
        return False
    try:
        import subprocess
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=8).stdout
        pids = set()
        for line in out.splitlines():
            if f":{port}" in line and "LISTENING" in line.upper():
                parts = line.split()
                if parts and parts[-1].isdigit():
                    pids.add(parts[-1])
        for pid in pids:
            if pid in ("0", "4"):
                continue
            print(f"  停止占用 {port} 端口的旧进程 PID={pid}")
            subprocess.run(["taskkill", "/F", "/PID", pid],
                           capture_output=True, timeout=8)
        return bool(pids)
    except Exception:
        return False


def _auto_pull_loop():
    """后台定时取新比赛，把库里还没有的场次写进待下载清单。

    走 AutoPull 增量包（gc_pull）。没装那个模块就完全不做事 —— 主包不碰 Steam。
    只写清单不自动下载：正在打游戏时被弹一个下载很烦，也白占带宽。
    """
    import time as _t
    _t.sleep(90)                       # 启动后先让初始化和扫描跑完
    while True:
        try:
            st = S.load() or {}
            hours = float(st.get("auto_pull_hours") or 0)
            if hours <= 0:
                _t.sleep(1800)
                continue
            mod = _gc_pull_module()
            if mod is None:
                _t.sleep(1800)
                continue
            r = mod.fetch(DATA_DIR, log=lambda s: print("[autopull]", s, flush=True))
            if r.get("ok") and r.get("urls"):
                known = set()
                with _lock:
                    try:
                        for (nm,) in _conn.execute("SELECT name FROM demos"):
                            known.add(str(nm))
                    except Exception:
                        pass
                fresh = []
                for u in r["urls"]:
                    body = u.rsplit("/730/", 1)[-1].replace(".dem.bz2", "")
                    if not any(body in k for k in known):
                        fresh.append(u)
                if fresh:
                    try:
                        with open(os.path.join(DATA_DIR, "pull_pending.json"), "w",
                                  encoding="utf-8") as _f:
                            json.dump({"t": time.strftime("%Y-%m-%d %H:%M:%S"),
                                       "total": len(fresh), "urls": fresh},
                                      _f, ensure_ascii=False)
                    except Exception:
                        traceback.print_exc()
                    print("[autopull] 自动检查：%d 场待下载" % len(fresh), flush=True)
            _t.sleep(max(600, hours * 3600))
        except Exception:
            traceback.print_exc()
            _t.sleep(1800)


def main():
    # 解析层依赖 awpy（内部用 polars），不再需要 pandas / demoparser2 版本自检

    port = free_port()
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    show = "127.0.0.1" if HOST in ("0.0.0.0", "", "::") else HOST
    url = f"http://{show}:{port}/"

    srv = None
    for attempt in (1, 2):
        try:
            srv = ThreadingHTTPServer((HOST, port), Handler)
            break
        except OSError as e:
            if attempt == 1 and _kill_port_owner(port):
                print("  等待旧进程释放端口...")
                time.sleep(2)
                continue
            print()
            print("=" * 52)
            print(f"  启动失败：端口 {port} 已被占用")
            print(f"  {e}")
            print()
            print("  请手动处理：")
            print("   1) 找到旧的黑色命令行窗口，关掉它")
            print("   2) 或按 Ctrl+Shift+Esc 打开任务管理器，")
            print("      结束所有 python.exe，再重新运行 START.bat")
            print("=" * 52)
            print()
            try:
                input("按回车退出...")
            except EOFError:
                pass
            return 1

    # 启动时先扫一遍 demo 目录：文件是直接拷进来的（没走页面），不扫列表里就不出现
    try:
        _sc = api_scan()
        if _sc.get("added"):
            print(f"新扫到 {_sc['added']} 个 demo 文件")
    except Exception:
        traceback.print_exc()

    print(f"Cross-Section v{VERSION} 已启动: {url}")
    # 版本检查挪到启动时后台跑：页面打开时只读缓存，不再等网络
    _update_check_spawn()
    threading.Thread(target=_auto_pull_loop, daemon=True).start()
    print(f"demo 目录: {DEMO_DIR}")
    print(f"数据目录: {DATA_DIR}")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    return 0


if __name__ == "__main__":
    main()
