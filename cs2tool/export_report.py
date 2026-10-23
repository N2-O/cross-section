"""导出 AI 可直接分析的报告：Markdown（人看/AI 读）+ JSON（结构化）。

口径说明也写进报告，避免接手分析的人/AI 误读字段含义。
"""
from __future__ import annotations

import datetime
import json
import os

import stats_api

WEAK = "手枪 / 冲锋枪 / 霰弹枪"

_WNAME = {
    "ak47": "AK-47", "m4a1": "M4A4", "m4a1_silencer": "M4A1-S", "awp": "AWP",
    "deagle": "Desert Eagle", "usp_silencer": "USP-S", "glock": "Glock-18",
    "hkp2000": "P2000", "p250": "P250", "fiveseven": "Five-SeveN", "tec9": "Tec-9",
    "cz75a": "CZ75-Auto", "elite": "Dual Berettas", "revolver": "R8 Revolver",
    "mac10": "MAC-10", "mp9": "MP9", "mp7": "MP7", "mp5sd": "MP5-SD",
    "ump45": "UMP-45", "p90": "P90", "bizon": "PP-Bizon", "galilar": "Galil AR",
    "famas": "FAMAS", "aug": "AUG", "sg556": "SG 553", "ssg08": "SSG 08",
    "scar20": "SCAR-20", "g3sg1": "G3SG1", "nova": "Nova", "xm1014": "XM1014",
    "mag7": "MAG-7", "sawedoff": "Sawed-Off", "negev": "Negev", "m249": "M249",
    "taser": "电击枪", "knife": "刀", "knife_t": "刀",
    "hegrenade": "HE 手雷", "inferno": "燃烧弹", "molotov": "燃烧瓶",
    "incgrenade": "燃烧弹", "flashbang": "闪光弹", "smokegrenade": "烟雾弹",
    "decoy": "诱饵弹", "world": "世界", "worldent": "世界",
}


def wname(w) -> str:
    k = str(w or "").replace("weapon_", "")
    return _WNAME.get(k, w or "—")


def _md_table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join(["---"] * len(head)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def render_md(ov: dict) -> str:
    t = ov.get("total") or {}
    d = ov.get("detail") or {}
    e = ov.get("econ") or {}
    du = ov.get("duel") or {}
    pl = ov.get("player") or {}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    L: list[str] = []
    L.append(f"# CS2 对局分析报告 · {pl.get('name') or '未知玩家'}")
    L.append("")
    L.append(f"- 生成时间：{now}")
    L.append(f"- 样本：**{t.get('matches', 0)} 场 / {t.get('rounds', 0)} 回合**"
             f"（{t.get('wins', 0)} 胜 / {t.get('matches', 0) - t.get('wins', 0)} 负）")
    L.append(f"- steamid：{pl.get('steamid')}")
    L.append("")
    L.append("> 本报告由 Cross-Section 从 .dem 原始解析生成。所有比率均为**回合加权**，"
             "不是场次简单平均。经济数据来自 `economy` 表（按阵营分行，数值是**全队 5 人合计**）。")
    L.append("")

    # ===== 一、综合 =====
    L.append("## 一、综合数据")
    L.append("")
    L.append(_md_table(["指标", "数值", "说明"], [
        ["Rating", t.get("rating"), "HLTV 式综合评分，回合加权"],
        ["ADR", t.get("adr"), "每回合平均伤害"],
        ["KAST", f"{t.get('kast')}%", "有击杀/助攻/存活/被换的回合占比"],
        ["K/D", t.get("kd"), f"{t.get('kills')} 杀 / {t.get('deaths')} 死"],
        ["KPR / DPR / APR", f"{t.get('kpr')} / {t.get('dpr')} / {t.get('apr')}", "每回合击杀/死亡/助攻"],
        ["Impact", t.get("impact"), "首杀+多杀加权影响力"],
        ["爆头率", f"{t.get('hs_pct')}%", f"{t.get('hs')} 次爆头击杀"],
        ["首杀 / 首死", f"{t.get('fk')} / {t.get('fd')}", "开局第一个击杀 / 第一个死亡"],
        ["胜率", f"{t.get('win_rate')}%", ""],
        ["总伤害", t.get("dmg"), ""],
    ]))
    L.append("")

    # ===== 二、分阵营 =====
    side = t.get("side") or {}
    L.append("## 二、分阵营（T 进攻 / CT 防守）")
    L.append("")
    rows = []
    for k, label in (("T", "T 进攻"), ("CT", "CT 防守")):
        s = side.get(k) or {}
        rows.append([label, s.get("rounds"), s.get("kills"), s.get("deaths"),
                     s.get("adr"), s.get("kpr"), s.get("dpr"),
                     round((s.get("kpr") or 0) / max(s.get("dpr") or 0.01, 0.01), 2)])
    L.append(_md_table(["阵营", "回合", "击杀", "死亡", "ADR", "KPR", "DPR", "K/D"], rows))
    L.append("")
    L.append("> 攻守两端表现差异通常反映：T 侧依赖突破/道具，CT 侧依赖卡点/残局。")
    L.append("")

    # ===== 三、经济局 =====
    L.append("## 三、经济局胜率")
    L.append("")
    buy = e.get("buy") or []
    if buy:
        L.append(_md_table(
            ["购买类型", "回合", "胜", "胜率", "队均花费", "人均", "存活装备"],
            [[b.get("type"), b.get("n"), b.get("w"), f"{b.get('wr')}%",
              f"{(b.get('spent') or 0):,}", f"{(b.get('spent') or 0) // 5:,}",
              f"{(b.get('eq') or 0):,}"] for b in buy]))
    else:
        L.append("（无数据）")
    L.append("")
    L.append("**购买类型判定口径**：")
    L.append("- `手枪局`：每半场第 1 回合（R1 / R13）")
    L.append("- `ECO`：人均装备 < 1200 且人均花费 < 800（只起手枪 / 买点道具）")
    L.append("- `强起`：人均装备 < 3000 或人均花费 < 2000（便宜枪 + 半甲）")
    L.append("- `全买`：其余（步枪 + 全甲）")
    L.append("")
    fr = e.get("fk_rounds") or {}
    dr = e.get("fd_rounds") or {}
    pi = e.get("pistol") or {}
    L.append(_md_table(["关键局面", "回合", "胜", "胜率"], [
        ["我方先拿首杀", fr.get("n"), fr.get("w"), f"{fr.get('wr')}%"],
        ["敌方先拿首杀", dr.get("n"), dr.get("w"), f"{dr.get('wr')}%"],
        ["手枪局", pi.get("n"), pi.get("w"), f"{pi.get('wr')}%"],
    ]))
    L.append("")
    L.append(f"- 队伍总花费：**{(e.get('spent_total') or 0):,}**"
             f"（场均 {(e.get('spent_avg') or 0):,}，人均 {int((e.get('spent_avg') or 0) // 5):,}）")
    L.append(f"- 赛后存活装备：**{(e.get('saved_total') or 0):,}**")
    L.append(f"- 装备保留率：**{e.get('inv_rate')}%**（存活装备 / 总花费）")
    L.append("")

    # ===== 四、武器对枪 =====
    L.append("## 四、武器与对枪")
    L.append("")
    # 射击质量：急停率用开火瞬间速度判定（≤34 units/s 算停住），不用 inaccuracy
    if t.get("fire_count"):
        L.append("### 射击质量")
        L.append("")
        L.append(_md_table(["指标", "数值", "说明"], [
            ["开火次数", t.get("fire_count"), f"每回合 {t.get('per_fire')} 次"],
            ["开火命中率", f"{t.get('fire_accuracy')}%",
             f"{t.get('hit_count')} 次开火产生了伤害（按开火去重，非命中弹丸数）"],
            ["阈值内低速开火率", f"{t.get('stop_rate')}%",
             f"{t.get('stop_shots')}/{t.get('gun_fire_count')} 次枪械开火时速度 ≤34 units/s"],
            ["超阈值速度开火率", f"{t.get('imprecise_rate')}%",
             f"{t.get('imprecise_shots')} 次枪械开火时还在滑步/跑动（>34 units/s）"],
        ]))
        L.append("")
        L.append("> **急停判据**：看开火瞬间的移动速度。34 units/s 是 CS2 步枪还能精确射击的"
                 "速度上限，超过就在散布失控区。速度是引擎真实物理量，跨场可直接比较。")
        L.append("> ")
        L.append("> **不用 inaccuracy 的原因**：awpy 的 `shots.inaccuracy` 读的是武器实体的 "
                 "`m_fAccuracyPenalty`（连发累积的精度惩罚），官方源码注释明确写着 "
                 "「CS2 does not network the fully-computed inaccuracy」——真正的散布由引擎"
                 "实时计算，不写进 demo。实测印证：速度 0-5 与 120+ 的开火，该值中位数几乎相同。")
        L.append("")

    wp = d.get("weapons") or []
    if wp:
        L.append("### 击杀武器分布")
        L.append("")
        L.append(_md_table(["武器", "击杀", "爆头率", "命中率", "未急停率"], [
            [wname(w.get("w")), w.get("n"),
             f"{round((w.get('hs') or 0) / max(w.get('n') or 1, 1) * 100)}%",
             f"{w.get('acc')}%" if w.get("acc") is not None else "—",
             f"{w.get('imp_rate')}%" if w.get("imp_rate") is not None else "—"] for w in wp[:12]]))
        L.append("")

    db = du.get("died_by") or []
    if db:
        L.append("### 死亡原因（死于什么武器）")
        L.append("")
        tot = du.get("died_total") or 1
        L.append(_md_table(["武器类型", "次数", "占比"], [
            [x.get("t"), x.get("n"), f"{round(x.get('n', 0) / tot * 100)}%"] for x in db]))
        L.append("")

    L.append("### 精确对枪胜率（双方手持武器已知）")
    L.append("")
    adv = du.get("duel_adv") or {}
    dis = du.get("duel_disadv") or {}
    ev = du.get("duel_even") or {}
    L.append(_md_table(["对枪类型", "次数", "胜", "负", "胜率"], [
        ["我拿主战枪 vs 对方劣势枪", adv.get("n"), adv.get("w"), adv.get("l"), f"{adv.get('wr')}%"],
        ["我拿劣势枪 vs 对方主战枪", dis.get("n"), dis.get("w"), dis.get("l"), f"{dis.get('wr')}%"],
        ["同档对枪", ev.get("n"), ev.get("w"), ev.get("l"), f"{ev.get('wr')}%"],
    ]))
    L.append("")
    L.append(f"- 主战枪 = 步枪 + 狙击；劣势枪 = {WEAK}")
    L.append(f"- 被劣势武器击杀（粗口径，含自己也是劣势枪）：**{du.get('weak_death_pct')}%**")
    L.append(f"- 被劣势武器击杀（精确，自己拿主战枪时）：**{du.get('weak_death_exact')}%**")
    L.append("")

    eadv = du.get("advantage") or {}
    edis = du.get("disadvantage") or {}
    eev = du.get("even") or {}
    L.append("### 经济不对称下的表现")
    L.append("")
    L.append(_md_table(["局面", "回合", "击杀", "死亡", "K/D"], [
        ["我方装备优势", eadv.get("rounds"), eadv.get("k"), eadv.get("d"), eadv.get("kd")],
        ["我方装备劣势", edis.get("rounds"), edis.get("k"), edis.get("d"), edis.get("kd")],
        ["势均力敌", eev.get("rounds"), eev.get("k"), eev.get("d"), eev.get("kd")],
    ]))
    L.append("")

    # ===== 五、多杀 =====
    multi = d.get("multi") or {}
    if multi:
        L.append("## 五、多杀分布")
        L.append("")
        L.append(_md_table(["每回合击杀数", "出现回合数"], [
            [f"{k}K", v] for k, v in sorted(multi.items(), key=lambda kv: int(kv[0]))]))
        L.append("")

    # ===== 六、分地图 =====
    maps = ov.get("by_map") or []
    if maps:
        L.append("## 六、分地图")
        L.append("")
        L.append(_md_table(
            ["地图", "场次", "胜率", "回合", "ADR", "KAST", "Rating", "K/D", "首杀"],
            [[m.get("map"), m.get("matches"), f"{m.get('win_rate')}%", m.get("rounds"),
              m.get("adr"), m.get("kast"), m.get("rating"), m.get("kd"), m.get("fk")]
             for m in maps]))
        L.append("")

    # ===== 七、每场明细 =====
    tl = ov.get("timeline") or []
    if tl:
        L.append("## 七、每场明细（时间顺序）")
        L.append("")
        L.append(_md_table(
            ["日期", "地图", "比分", "结果", "K", "D", "A", "K/D", "ADR", "KAST", "Rating"],
            [[(x.get("played_at") or "")[:10], x.get("map"), x.get("score"),
              "胜" if x.get("win") else "负", x.get("kills"), x.get("deaths"),
              x.get("assists"), x.get("kd"), x.get("adr"), x.get("kast"), x.get("rating")]
             for x in tl]))
        L.append("")

    # ===== 附录：字段说明 =====
    L.append("---")
    L.append("")
    L.append("## 附录：字段口径")
    L.append("")
    L.append("- `ADR` 每回合平均伤害；`KAST` 有贡献回合占比；`Rating` 综合评分（回合加权）")
    L.append("- `KPR/DPR/APR` = 每回合击杀/死亡/助攻")
    L.append("- `Impact` = 首杀与多杀加权的场面影响力")
    L.append("- 经济数值均为**全队 5 人合计**，`人均` 列为除以 5")
    L.append("- `存活装备` = 回合结束时仍存活队员的装备价值（能带到下回合的部分）")
    L.append("- 对枪数据依赖 `victim_weapon`（死亡瞬间手持武器），已覆盖全部击杀事件")
    L.append("- `急停率` = 开火瞬间速度 ≤34 units/s 的次数 ÷ 总开火次数；"
             "`超阈值速度开火率` 是它的补数。这是急停的代理指标：速度达标不等于动作正确、更不等于打中")
    L.append("- `开火命中率` 以「开火次数」为分母：一次开火即使命中多颗弹丸也只算一次命中；"
             "霰弹枪天然偏高，与步枪不可直接横比")
    L.append("- `盲狙击杀` 取自 `player_death` 的 noscope 字段，由引擎在击杀结算时判定")
    L.append("- 样本量提示：少于 5 场时，多数比率波动很大，不宜下强结论")
    return "\n".join(L)


def build(conn, steamid: int, out_dir: str) -> dict:
    ov = stats_api.overview(conn, steamid)
    if ov.get("empty"):
        raise RuntimeError("还没有可导出的比赛数据")
    ov["detail"] = stats_api.detail(conn, steamid)
    ov["econ"] = stats_api.econ_stats(conn, steamid)
    ov["duel"] = stats_api.duel_stats(conn, steamid)

    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nm = (ov.get("player") or {}).get("name") or "player"
    safe = "".join(c for c in nm if c.isalnum() or c in "-_") or "player"

    jp = os.path.join(out_dir, f"cs2_report_{safe}_{ts}.json")
    mp = os.path.join(out_dir, f"cs2_report_{safe}_{ts}.md")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(ov, f, ensure_ascii=False, indent=2, default=str)
    md = render_md(ov)
    with open(mp, "w", encoding="utf-8") as f:
        f.write(md)
    return {"ok": True, "json": jp, "md": mp, "dir": out_dir,
            "files": [os.path.basename(jp), os.path.basename(mp)]}
