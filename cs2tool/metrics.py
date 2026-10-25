"""指标字典 —— 所有正式指标的唯一定义来源。

设计原则
--------
1. 每个指标都写清：是什么、怎么算、以什么为分母、从哪来、有什么坑
2. 前端 hover 说明、API 文档、导出报告全部从这里取，不允许各处自己解释
3. 分母字段名显式写出来，便于「样本不足显示 —」和「分子分母可回溯」

字段说明
--------
name        显示名（短，放卡片上）
cat         分类（对应页面）
definition  人话定义
formula     计算式
numerator   分子字段（对应数据库/聚合结果的 key）
denominator 分母字段
unit        单位
source      数据来源与口径说明
note        注意事项 / 已知误差
min_sample  建议最小样本量（不足时前端显示 —）
"""
from __future__ import annotations

VERSION = "1.1"

METRICS: dict[str, dict] = {

    # ============================================================ 基础产出
    "kills": dict(name="击杀", cat="产出", unit="个",
                  definition="对敌方的有效击杀总数",
                  formula="击杀事件求和",
                  numerator="kills", denominator=None,
                  source="awpy.kills 中 attacker 为本人且 victim 为敌方的行",
                  note="不含自杀、队友击杀", min_sample=1),

    "deaths": dict(name="死亡", cat="产出", unit="次",
                   definition="确认的个人死亡总数（含自杀与被队友击杀）",
                   formula="死亡事件求和",
                   numerator="deaths", denominator=None,
                   source="awpy.kills 中 victim 为本人的行，含 world/self/teammate 致死",
                   note="awpy 的 deaths 比只算敌方击杀的口径多 1-2 次/场", min_sample=1),

    "assists": dict(name="助攻", cat="产出", unit="次",
                    definition="按助攻规则归属到本人的助攻总数",
                    formula="助攻事件去重计数",
                    numerator="assists", denominator=None,
                    source="awpy.stats.assists（含闪光助攻 flash_assists 单独一列）",
                    note=None, min_sample=1),

    "kd": dict(name="K/D", cat="产出", unit="比值",
               definition="总击杀与总死亡的比值",
               formula="总击杀 ÷ 总死亡",
               numerator="kills", denominator="deaths",
               source="聚合值，不是各场 K/D 的平均",
               note="单图 K/D 的平均 ≠ 总体 K/D，两者不可混用", min_sample=1),

    "kpr": dict(name="KPR", cat="产出", unit="击杀/回合",
                definition="每个个人计入回合的击杀数",
                formula="总击杀 ÷ 个人计入回合数",
                numerator="kills", denominator="rounds",
                source="awpy.stats.kills ÷ rounds_played", note=None, min_sample=1),

    "dpr": dict(name="DPR", cat="产出", unit="死亡/回合",
                definition="每个个人计入回合的死亡次数",
                formula="总死亡 ÷ 个人计入回合数",
                numerator="deaths", denominator="rounds",
                source="awpy.stats.deaths ÷ rounds_played", note=None, min_sample=1),

    "ar": dict(name="A/R", cat="产出", unit="助攻/回合",
               definition="每个个人计入回合的助攻数",
               formula="总助攻 ÷ 个人计入回合数",
               numerator="assists", denominator="rounds",
               source="awpy.stats.assists ÷ rounds_played", note=None, min_sample=1),

    # ============================================================ 伤害
    "damage_total": dict(name="总伤害", cat="伤害", unit="点",
                         definition="对敌方造成的实际生命值损失",
                         formula="有效伤害事件求和",
                         numerator="damage_total", denominator=None,
                         source="awpy.stats 的伤害口径：按命中时的剩余血量截断",
                         note="爆头打满血只计 100 而非 120；overkill 不计入", min_sample=1),

    "rounds_played": dict(name="总回合", cat="样本", unit="回合",
                 definition="统计范围内计入的全部回合数（含对手赢的回合）",
                 formula="各场回合数求和",
                 numerator="rounds", denominator="1",
                 source="rounds 表按 match 计数", min_sample=1),

    "win_rate": dict(name="总胜率", cat="胜负", unit="%",
                 definition="赢下的场次占已分胜负场次的比例，平局不计入分母",
                 formula="胜场 ÷ (胜场 + 负场)",
                 numerator="wins", denominator="wins + losses",
                 source="按整场比分判定：我方回合数 > 对方则胜，相等为平局", min_sample=1),

    "spent": dict(name="总支出", cat="经济", unit="$",
                 definition="统计范围内买装备花掉的现金总额（武器 + 道具 + 甲 + 钳子，已扣退款）",
                 formula="各回合（回合开始现金 − 冻结结束现金）求和",
                 numerator="spent_total", denominator=None,
                 source="round_end.spend 求和（钱包法：回合开始现金 − 冻结结束现金）；"
                        "含护甲与拆弹钳，买了又退的已扣除",
                 note="是累计值，场次越多越大；比较不同时期请用每回合平均支出", min_sample=1),

    "spent_avg": dict(name="每回合平均支出", cat="经济", unit="$/回合",
                 definition="单个回合平均花掉多少现金（含武器、道具、甲、钳子，已扣退款）",
                 formula="总支出 ÷ 总回合",
                 numerator="spent_total", denominator="rounds",
                 source="钱包法花费（回合开始现金 − 冻结结束现金）求和 ÷ 回合数", min_sample=1),

    "adr": dict(name="ADR", cat="伤害", unit="伤害/回合",
                definition="每个个人计入回合平均造成的敌方伤害",
                formula="总有效伤害 ÷ 个人计入回合数",
                numerator="damage_total", denominator="rounds",
                source="awpy.stats.adr（伤害已按剩余血量截断）",
                note="只统计对敌方的实际生命值损失，穿墙/道具伤害计入但受同样截断",
                min_sample=1),

    "weapon_adr": dict(name="武器 ADR", cat="伤害", unit="伤害/回合",
                       definition="每回合由枪械与近战造成的伤害",
                       formula="武器伤害 ÷ 个人计入回合数",
                       numerator="weapon_damage", denominator="rounds",
                       source="damages 按 weapon 分组后排除投掷物",
                       note="与总 ADR 的差额即道具伤害", min_sample=1),

    "hs_kills": dict(name="爆头击杀", cat="伤害", unit="个",
                     definition="以爆头结束的击杀数",
                     formula="headshot=true 的击杀求和",
                     numerator="headshot_kills", denominator=None,
                     source="awpy.stats.headshot_kills", note=None, min_sample=1),

    "hs_pct": dict(name="爆头率", cat="伤害", unit="%",
                   definition="爆头击杀占全部击杀的比例",
                   formula="爆头击杀 ÷ 总击杀",
                   numerator="headshot_kills", denominator="kills",
                   source="awpy.stats.headshot_pct", note=None, min_sample=1),

    # ============================================================ 参与与生存
    "kast": dict(name="KAST", cat="参与", unit="%",
                 definition="满足击杀/助攻/存活/被换人任一条件的回合占比",
                 formula="KAST 回合数 ÷ 个人计入回合数",
                 numerator="kast_rounds", denominator="rounds",
                 source="awpy.stats.kast（四条件：kill / assist / survive / traded）",
                 note="awpy 口径比部分第三方严，同场对比可能低 5-10 个百分点",
                 min_sample=1),

    "survive_pct": dict(name="存活率", cat="参与", unit="%",
                        definition="回合判定时点仍存活的回合占比",
                        formula="存活回合数 ÷ 个人计入回合数",
                        numerator="survive_rounds", denominator="rounds",
                        source="按回合末 is_alive 状态统计，非「未死亡」",
                        note="保枪存活与战死前存活都算存活", min_sample=1),

    # ============================================================ 首杀
    "opening_kills": dict(name="首杀", cat="首杀", unit="次",
                          definition="取得该回合第一个有效敌方击杀的次数",
                          formula="每个可识别首杀回合最多计 1 次",
                          numerator="opening_kills", denominator=None,
                          source="awpy.stats.opening_kills（按回合首个敌方击杀归属）",
                          note="若更早的死亡事件无法解析，该回合首杀标记为未知",
                          min_sample=1),

    "opening_deaths": dict(name="首死", cat="首杀", unit="次",
                           definition="成为该回合首个被杀者的次数",
                           formula="每个可识别首杀回合最多计 1 次",
                           numerator="opening_deaths", denominator=None,
                           source="awpy.stats.opening_deaths", note=None, min_sample=1),

    "opening_rate": dict(name="首杀率", cat="首杀", unit="%",
                         definition="个人计入回合中取得首杀的比例",
                         formula="首杀回合数 ÷ 个人计入回合数",
                         numerator="opening_kills", denominator="rounds",
                         source="awpy.stats.opening_kills ÷ rounds_played", note=None,
                         min_sample=1),

    "opening_death_rate": dict(name="首死率", cat="首杀", unit="%",
                               definition="个人计入回合中成为首死者的比例",
                               formula="首死回合数 ÷ 个人计入回合数",
                               numerator="opening_deaths", denominator="rounds",
                               source="awpy.stats.opening_deaths ÷ rounds_played", note=None,
                               min_sample=1),

    "opening_win_pct": dict(name="首杀后胜率", cat="首杀", unit="%",
                            definition="本人取得首杀后本方赢下该回合的比例",
                            formula="首杀后获胜回合数 ÷ 首杀回合数",
                            numerator="opening_win_rounds", denominator="opening_kills",
                            source="opening_kills 与 rounds.winner 关联",
                            note="样本通常很小，建议 >=10 次首杀才参考", min_sample=10),

    "opening_loss_recover": dict(name="首死后挽回率", cat="首杀", unit="%",
                                 definition="本人首死后本方仍赢下该回合的比例",
                                 formula="首死后获胜回合数 ÷ 首死回合数",
                                 numerator="opening_loss_win_rounds", denominator="opening_deaths",
                                 source="opening_deaths 与 rounds.winner 关联", note=None,
                                 min_sample=10),

    # ============================================================ 换人
    "is_trade": dict(name="换人击杀", cat="换人", unit="次",
                     definition="击杀一个刚杀死自己队友的敌人（5.25 秒窗口）",
                     formula="is_trade=true 的击杀求和",
                     numerator="trade_kills", denominator=None,
                     source="awpy.kills.is_trade（官方 5.25 秒换人窗口）",
                     note="只证明事件满足时间规则，不代表有意识配合", min_sample=1),

    "traded_deaths": dict(name="被换人 deaths", cat="换人", unit="次",
                          definition="本人死亡后在窗口内被队友报仇的次数",
                          formula="victim_traded=true 且 victim 为本人的击杀数",
                          numerator="traded_deaths", denominator=None,
                          source="awpy.stats.traded_deaths", note=None, min_sample=1),

    "trade_rate": dict(name="补枪占比", cat="换人", unit="%",
                       definition="自己的击杀里，属于「替刚死的队友报仇」的比例",
                       formula="换人击杀数 ÷ 总击杀数",
                       numerator="trade_kills", denominator="kills",
                       source="trade_kills ÷ kills",
                       note="分母是击杀数不是尝试次数，所以这是占比而不是成功率", min_sample=1),

    "traded_death_rate": dict(name="拉枪占比", cat="换人", unit="%",
                              definition="自己的死亡里，随后被队友立刻换掉凶手的比例",
                              formula="被换人死亡数 ÷ 总死亡数",
                              numerator="traded_deaths", denominator="deaths",
                              source="traded_deaths ÷ deaths",
                              note="分母是死亡数不是尝试次数，所以这是占比而不是成功率；自杀与环境死亡不进分子", min_sample=1),

    # ============================================================ 多杀
    "mk2": dict(name="2K", cat="多杀", unit="回合",
                definition="单回合恰好 2 次有效击杀的回合数",
                formula="按玩家×回合统计击杀数 = 2",
                numerator="multikill_2k", denominator=None,
                source="awpy.stats.multikill_2k", note=None, min_sample=1),
    "mk3": dict(name="3K", cat="多杀", unit="回合",
                definition="单回合恰好 3 次有效击杀的回合数",
                formula="按玩家×回合统计击杀数 = 3",
                numerator="multikill_3k", denominator=None,
                source="awpy.stats.multikill_3k", note=None, min_sample=1),
    "mk4": dict(name="4K", cat="多杀", unit="回合",
                definition="单回合恰好 4 次有效击杀的回合数",
                formula="按玩家×回合统计击杀数 = 4",
                numerator="multikill_4k", denominator=None,
                source="awpy.stats.multikill_4k", note=None, min_sample=1),
    "mk5": dict(name="5K+", cat="多杀", unit="回合",
                definition="单回合至少 5 次有效击杀的回合数",
                formula="按玩家×回合统计击杀数 >= 5",
                numerator="multikill_5k", denominator=None,
                source="awpy.stats.multikill_5k", note=None, min_sample=1),

    "multi_rate": dict(name="多杀率", cat="多杀", unit="%",
                       definition="至少完成 2 杀的个人回合占比",
                       formula="2K 及以上回合数 ÷ 个人计入回合数",
                       numerator="multikill_2p", denominator="rounds",
                       source="2K+3K+4K+5K 之和 ÷ rounds_played", note=None, min_sample=1),

    # ============================================================ 残局
    "clutch_played": dict(name="残局机会", cat="残局", unit="次",
                          definition="本人成为本方唯一存活者、对方仍有存活者的次数",
                          formula="残局触发事件计数",
                          numerator="clutch_played", denominator=None,
                          source="事件流重建（clutch.py）：按该回合 roster 逐个击杀扣减人数，"
                                 "某侧刚减到 1 人且对方仍有人时触发",
                          note="1v0 不算残局；总量与 1vN 明细同源，恒等于各档机会数之和",
                          min_sample=1),

    "clutch_won": dict(name="残局获胜", cat="残局", unit="次",
                       definition="残局开始后本方最终赢下回合的次数",
                       formula="已结算残局中的获胜次数",
                       numerator="clutches_won", denominator=None,
                       source="awpy.stats.clutches_won", note=None, min_sample=1),

    "clutch_pct": dict(name="残局成功率", cat="残局", unit="%",
                       definition="已结算残局中获胜的比例",
                       formula="残局获胜数 ÷ 残局机会数",
                       numerator="clutches_won", denominator="clutches_played",
                       source="awpy.stats.clutches_won ÷ clutches_played",
                       note="建议直接显示「获胜数/机会数」，如 2/7", min_sample=5),

    "clutch_1v1": dict(name="1v1", cat="残局", unit="次",
                       definition="1v1 残局【赢下】的次数（不是机会数）", formula="对手数恰为 1 且赢下回合的次数",
                       numerator="clutch_1v1", denominator=None,
                       source="awpy.stats.clutch_1v1（官方口径为 clutches *won*，非 played）",
                       note="想看各档机会数请用 clutch 段的 by_size；"
                            "这里只统计赢下的次数，所以全 0 表示一次没赢，不是没打过", min_sample=1),
    "clutch_1v2": dict(name="1v2", cat="残局", unit="次",
                       definition="1v2 残局【赢下】的次数（不是机会数）", formula="对手数恰为 2 且赢下回合的次数",
                       numerator="clutch_1v2", denominator=None,
                       source="awpy.stats.clutch_1v2（官方口径为 clutches *won*，非 played）",
                       note="想看各档机会数请用 clutch 段的 by_size；"
                            "这里只统计赢下的次数，所以全 0 表示一次没赢，不是没打过", min_sample=1),
    "clutch_1v3": dict(name="1v3", cat="残局", unit="次",
                       definition="1v3 残局【赢下】的次数（不是机会数）", formula="对手数恰为 3 且赢下回合的次数",
                       numerator="clutch_1v3", denominator=None,
                       source="awpy.stats.clutch_1v3（官方口径为 clutches *won*，非 played）",
                       note="想看各档机会数请用 clutch 段的 by_size；"
                            "这里只统计赢下的次数，所以全 0 表示一次没赢，不是没打过", min_sample=1),
    "clutch_1v4": dict(name="1v4", cat="残局", unit="次",
                       definition="1v4 残局【赢下】的次数（不是机会数）", formula="对手数恰为 4 且赢下回合的次数",
                       numerator="clutch_1v4", denominator=None,
                       source="awpy.stats.clutch_1v4（官方口径为 clutches *won*，非 played）",
                       note="想看各档机会数请用 clutch 段的 by_size；"
                            "这里只统计赢下的次数，所以全 0 表示一次没赢，不是没打过", min_sample=1),
    "clutch_1v5": dict(name="1v5", cat="残局", unit="次",
                       definition="1v5 残局【赢下】的次数（不是机会数）", formula="对手数恰为 5 且赢下回合的次数",
                       numerator="clutch_1v5", denominator=None,
                       source="awpy.stats.clutch_1v5（官方口径为 clutches *won*，非 played）",
                       note="想看各档机会数请用 clutch 段的 by_size；"
                            "这里只统计赢下的次数，所以全 0 表示一次没赢，不是没打过", min_sample=1),

    "clutch_survive": dict(name="残局存活率", cat="残局", unit="%",
                       definition="进了残局还活到回合结束的比例（含保枪）",
                       formula="残局存活次数 ÷ 残局机会数",
                       numerator="clutch_survive", denominator="clutch_played",
                       source="回合结束前一刻的快照判定存活",
                       note="存活不等于赢。保枪是被动结果，别和残局成功率混着看", min_sample=1),

    "clutch_kills": dict(name="残局击杀", cat="残局", unit="次",
                       definition="残局场面下打出的击杀总数",
                       formula="残局回合内击杀求和",
                       numerator="clutch_kills", denominator=None,
                       source="kills 表按残局回合过滤", note=None, min_sample=1),

    "clutch_dmg": dict(name="残局伤害", cat="残局", unit="伤害",
                       definition="残局场面下造成的总伤害",
                       formula="残局回合内伤害求和",
                       numerator="clutch_dmg", denominator=None,
                       source="damage 表按残局回合过滤", note=None, min_sample=1),

    "save_count": dict(name="保枪次数", cat="残局", unit="次",
                       definition="残局里选择不硬拼、带着装备活到回合结束的次数",
                       formula="残局结束且存活且仍持枪的回合数",
                       numerator="save_count", denominator=None,
                       source="回合判定前一刻（end_tick-64）的快照", note=None, min_sample=1),

    "save_rate": dict(name="保枪率", cat="残局", unit="%",
                       definition="残局机会里有多少次最终选择保枪",
                       formula="保枪次数 ÷ 残局机会数",
                       numerator="save_count", denominator="clutch_played",
                       source="同上", note="100% 意味着一次都没尝试翻盘", min_sample=1),

    "save_value": dict(name="保留装备总额", cat="残局", unit="$",
                       definition="保枪保住的所有装备价值合计",
                       formula="每次保枪时的装备价值求和",
                       numerator="save_value", denominator=None,
                       source="快照里的 equipment_value", note=None, min_sample=1),

    "save_avg": dict(name="平均每次保枪", cat="残局", unit="$/次",
                       definition="每次保枪平均保住多少钱的装备",
                       formula="保留装备总额 ÷ 保枪次数",
                       numerator="save_value", denominator="save_count",
                       source="同上", note="单次约 3,000-5,000 属于正常满装", min_sample=1),

    # ============================================================ 人数优势
    "adv_first": dict(name="先形成人优势", cat="人数优势", unit="%",
                       definition="回合中我方先比对方多人的回合占比",
                       formula="先形成人优势的回合数 ÷ 总回合数",
                       numerator="first_adv", denominator="rounds_played",
                       source="kills 表按回合内人数变化判定", note=None, min_sample=1),

    "adv_win": dict(name="优势转胜率", cat="人数优势", unit="%",
                       definition="拿到人数优势之后真的赢下回合的比例",
                       formula="优势回合获胜数 ÷ 优势回合数",
                       numerator="first_adv_win", denominator="first_adv",
                       source="同上", note="领先却被翻盘，说明残局处理或站位有问题", min_sample=1),

    "adv_comeback": dict(name="劣势翻盘率", cat="人数优势", unit="%",
                       definition="先掉人之后仍然赢下回合的比例",
                       formula="劣势回合获胜数 ÷ 劣势回合数",
                       numerator="comeback_win", denominator="comeback_rounds",
                       source="同上", note=None, min_sample=1),

    # ============================================================ 射击
    "fire_count": dict(name="开火次数", cat="射击", unit="次",
                       definition="weapon_fire 事件总数",
                       formula="开火事件计数",
                       numerator="fire_count", denominator=None,
                       source="awpy.shots 行数（不含刀与投掷）",
                       note="连发武器每次扣扳机记 1 次，不等于子弹数", min_sample=1),

    "per_fire": dict(name="开火/回合", cat="射击", unit="次/回合",
                       definition="平均每个回合扣几次扳机",
                       formula="开火事件总数 ÷ 个人计入回合数",
                       numerator="fire_count", denominator="rounds",
                       source="awpy.shots 行数 ÷ 回合数",
                       note="连发武器每次扣扳机记 1 次，不等于子弹数", min_sample=1),

    "hit_count": dict(name="命中次数", cat="射击", unit="次",
                      definition="有命中记录的射击批次数",
                      formula="与开火事件配对的命中事件数",
                      numerator="hit_count", denominator=None,
                      source="weapon_fire 与 player_hurt 按同 tick 配对",
                      note="一次开火可能产生多条 hurt（霰弹/穿透），这里按开火去重",
                      min_sample=1),

    "fire_accuracy": dict(name="开火命中率", cat="射击", unit="%",
                          definition="开火批次中产生命中的比例",
                          formula="有命中的开火次数 ÷ 总开火次数",
                          numerator="hit_count", denominator="fire_count",
                          source="同 tick 配对 weapon_fire 与 player_hurt",
                          note="霰弹枪一次开火可命中多人，按「有/无命中」计；"
                               "狙与手枪的口径差异较大，跨武器不可直接比较",
                          min_sample=20),

    "penetrated_kills": dict(name="穿墙击杀", cat="射击", unit="次",
                             definition="子弹穿透几何体后完成的击杀",
                             formula="penetrated=true 的击杀数",
                             numerator="penetrated_kills", denominator=None,
                             source="awpy.kills.penetrated", note=None, min_sample=1),

    "thrusmoke_kills": dict(name="穿烟击杀", cat="射击", unit="次",
                            definition="穿过烟雾完成的击杀",
                            formula="thrusmoke=true 的击杀数",
                            numerator="thrusmoke_kills", denominator=None,
                            source="awpy.kills.thrusmoke", note=None, min_sample=1),

    "noscope_kills": dict(name="盲狙击杀", cat="射击", unit="次",
                          definition="狙击枪未开镜状态下完成的击杀数",
                          formula="noscope=true 的击杀数",
                          numerator="noscope_kills", denominator=None,
                          source="awpy.kills.noscope ← player_death 事件的 noscope 字段，"
                                 "由引擎在击杀结算时判定，不依赖开火瞬间的开镜状态",
                          note="不要改用 shots.scoped 反推：CS2 的 AWP 开火后会立即自动退镜，"
                               "按开火那一 tick 读到的永远是未开镜（实测 41 次 AWP 开火全为 False）",
                          min_sample=1),

    "jumping_kills": dict(name="跳跃击杀", cat="射击", unit="次",
                          definition="击杀瞬间处于腾空状态的击杀（跳狙/跳射）",
                          formula="击杀 tick 上 attacker is_jumping=true 的击杀数",
                          numerator="jumping", denominator=None,
                          source="awpy.snapshots.is_jumping，按 (steamid, tick) 对齐击杀",
                          note="awpy 的 kills 表没有跳跃字段，用同 tick 快照判定；"
                               "起跳当帧可能落在相邻 tick，会有少量漏计",
                          min_sample=1),

    "stop_rate": dict(name="阈值内低速开火率", cat="射击", unit="%",
                      definition="开火瞬间移动速度已降到 ≤34 units/s 的射击占比。"
                                 "这是「急停是否到位」的代理指标——速度达标不等于急停动作正确，"
                                 "也不代表这一枪打中了",
                      formula="枪械开火中速度 ≤ 34 units/s 的次数 ÷ 枪械开火数",
                      numerator="stop_shots", denominator="gun_fire_count",
                      source="weapon_fire 的 tick 对齐 snapshots 取 m_vecVelocity 合成速度",
                      note="分母只算枪械开火——weapon_fire 也包含投掷与挥刀，移动投掷是常态，"
                           "混进来只会变成噪声（实测道具/刀 105 次里 86% 被判超阈值）。"
                           "34 units/s 是 CS2 步枪能精确射击的速度上限",
                      min_sample=50),
    "imprecise_rate": dict(name="超阈值速度开火率", cat="射击", unit="%",
                           definition="开火瞬间移动速度 >34 units/s 的射击占比"
                                      "（阈值内低速开火率的补数）",
                           formula="枪械开火中速度 > 34 units/s 的次数 ÷ 枪械开火数",
                           numerator="imprecise_shots", denominator="gun_fire_count",
                           source="weapon_fire 的 tick 对齐 snapshots 取 m_vecVelocity 合成速度",
                           note="用速度判定，不再用 awpy 的 shots.inaccuracy —— 那个字段是"
                                "武器实体的 m_fAccuracyPenalty（连发累积的精度惩罚），"
                                "官方注释写明 CS2 不把完整 inaccuracy 写进网络流，实测也与移动速度无关",
                           min_sample=50),

    # ============================================================ 经济
    "spend": dict(name="个人支出", cat="经济", unit="$",
                  definition="本回合买装备花掉的现金（含护甲与拆弹钳，已扣退款）",
                  formula="回合开始现金 − 冻结结束现金",
                  numerator="spend", denominator=None,
                  source="round_end.spend（钱包法：回合开始现金 − 冻结结束现金）",
                  note="含护甲与拆弹钳；买了又退的已扣除，不算钱；"
                       "purchases 表只用于解释花费构成，不再相加当花费", min_sample=1),

    "equip_value": dict(name="装备价值", cat="经济", unit="$",
                        definition="冻结时间结束时个人当前装备的购置价估值",
                        formula="按库存逐项购置价求和",
                        numerator="equip_value", denominator=None,
                        source="awpy.snapshots.equipment_value（冻结结束时采样）",
                        note=None, min_sample=1),

    "equip_round_start": dict(name="继承装备", cat="经济", unit="$",
                              definition="回合开始时从上一回合带入的装备价值",
                              formula="回合开始时的库存估值",
                              numerator="equip_round_start", denominator=None,
                              source="awpy.snapshots.equipment_value_round_start",
                              note="与购买支出的差额才是本回合新增投入", min_sample=1),

    "team_equip": dict(name="团队装备", cat="经济", unit="$",
                       definition="本队冻结结束时全队装备价值合计",
                       formula="5 人装备价值求和",
                       numerator="team_equip", denominator=None,
                       source="按 side 分组的 equipment_value 求和",
                       note="这是团队口径，不能当成个人消费", min_sample=1),

    "buy_type": dict(name="个人购买档", cat="经济", unit="档",
                     definition="按个人买完后的装备价值（equip_fz）划分的购买类型",
                     formula="≥4500 全买 / 3000-4500 半买 / 1500-3000 强起 / <1500 ECO；"
                             "第 1、13 回合强制手枪局",
                     numerator="equip_fz", denominator=None,
                     source="round_end.equip_fz（个人冻结结束时的装备价值）",
                     note="这不是 CS2 内置的唯一分类标准，属于产品规则", min_sample=1),

    "eco_win_pct": dict(name="ECO 胜率", cat="经济", unit="%",
                        definition="团队处于 ECO 档时赢下回合的比例",
                        formula="ECO 档获胜回合 ÷ ECO 档回合",
                        numerator="eco_wins", denominator="eco_rounds",
                        source="按 buy_type 分组后与 rounds.winner 关联",
                        note="同时显示分母，如 3/11", min_sample=5),

    "full_win_pct": dict(name="全买胜率", cat="经济", unit="%",
                         definition="团队全买时赢下回合的比例",
                         formula="全买获胜回合 ÷ 全买回合",
                         numerator="full_wins", denominator="full_rounds",
                         source="按 buy_type 分组后与 rounds.winner 关联",
                         note=None, min_sample=5),

    "equip_share": dict(name="装备占比", cat="经济", unit="%",
                        definition="个人装备价值占本队总装备价值的比例",
                        formula="个人装备价值 ÷ 团队装备价值",
                        numerator="equip_value", denominator="team_equip",
                        source="同回合个人与团队 equipment_value 相除",
                        note="正常队伍中人均约 20%", min_sample=1),

    # ---- 保经济（与残局保枪是两个指标，别混）----
    "save_economy": dict(name="保经济次数", cat="经济", unit="次",
                         definition="败局里存活到回合结束且仍留有装备的回合数。「保枪」只是口头说法，"
                                    "本质是保经济——手枪局保半甲、保道具同样计入，所以不查具体武器。",
                         formula="该回合我方输 且 玩家存活 且 装备价值 > 0 的回合数",
                         numerator="save_economy", denominator="lost_rounds",
                         source="round_end（回合判定前 1 秒快照）+ rounds.a_win",
                         note="与「残局保枪」（clutch 分节）不同：那个只在 1vN 局面下统计",
                         min_sample=1),
    "save_econ_pct": dict(name="保经济率", cat="经济", unit="%",
                          definition="败局中被保住经济的回合占比",
                          formula="保经济次数 ÷ 败局回合数 × 100",
                          numerator="save_economy", denominator="lost_rounds",
                          source="同保经济次数", note=None, min_sample=3),
    "save_econ_value": dict(name="保留装备总额", cat="经济", unit="美元",
                            definition="保经济回合里存活下来的装备价值合计",
                            formula="Σ 保经济回合的 end 装备价值",
                            numerator=None, denominator=None,
                            source="round_end.equip（5 人合计口径）", note=None, min_sample=1),
    "save_econ_avg": dict(name="平均每次保留", cat="经济", unit="美元",
                          definition="每次保经济平均保下多少价值的装备",
                          formula="保留装备总额 ÷ 保经济次数",
                          numerator="save_econ_value", denominator="save_economy",
                          source="同上", note=None, min_sample=3),

    # ---- 受闪 / 挨道具伤害（方向与「投出」相反）----
    "flashed_count": dict(name="被闪次数", cat="道具", unit="次",
                          definition="本人被闪光弹致盲的次数（作为受害者计数，不分敌我）",
                          formula="blinds 表中 victim=本人且 duration>0.05 的行数",
                          numerator="flashed_count", denominator=None,
                          source="awpy.blinds（victim_steamid 为本人）",
                          note="by_enemy / by_teammate 再按投掷方阵营拆开——"
                               "被队友闪和吃对手的闪是两回事", min_sample=1),
    "flashed_duration": dict(name="被闪时长", cat="道具", unit="秒",
                             definition="本人被致盲的累计秒数",
                             formula="Σ blinds.duration（victim=本人）",
                             numerator="flashed_duration", denominator=None,
                             source="awpy.blinds.duration", note=None, min_sample=1),
    "flash_deaths": dict(name="闪白期间阵亡", cat="道具", unit="次",
                         definition="在致盲持续窗口内死亡的次数",
                         formula="死亡 tick 落在 [blind_tick, blind_tick + duration×64] 的次数",
                         numerator="flash_deaths", denominator="flashed_count",
                         source="blinds 与 kills 按 tick 对齐",
                         note="只证明「死时还瞎着」，不证明是因闪而死", min_sample=5),
    "util_taken": dict(name="吃到道具伤害", cat="道具", unit="点",
                       definition="本人作为受害者承受的手雷与燃烧类伤害",
                       formula="damage 表中 victim=本人且 weapon∈(hegrenade, inferno, molotov, incgrenade) 的伤害和",
                       numerator="util_taken", denominator=None,
                       source="awpy.damages（按剩余血量截断）",
                       note="与 utility_damage 方向相反：那个是我造成的，这个是我吃到的", min_sample=1),

    # ============================================================ 道具
    "grenade_thrown": dict(name="投掷次数", cat="道具", unit="次",
                          definition="已确认的独立投掷物事件数",
                          formula="按投掷物实体去重",
                          numerator="grenade_thrown", denominator=None,
                          source="awpy.grenades 按 entity_id+entity_serial 去重",
                          note=None, min_sample=1),

    "util_damage": dict(name="道具伤害", cat="道具", unit="点",
                        definition="HE 与燃烧弹造成的敌方实际伤害",
                        formula="投掷物关联的伤害事件求和",
                        numerator="util_damage", denominator=None,
                        source="awpy.stats.utility_damage",
                        note="没有伤害不代表投掷无效，可能只起到了区域限制作用",
                        min_sample=1),

    "flashes_thrown": dict(name="闪光投掷", cat="道具", unit="次",
                           definition="已确认的闪光弹投掷数",
                           formula="type=flashbang 的去重投掷物数",
                           numerator="flashes_thrown", denominator=None,
                           source="awpy.stats.flashes_thrown", note=None, min_sample=1),

    "enemies_flashed": dict(name="致盲敌人", cat="道具", unit="人次",
                            definition="被本人闪光致盲的敌方人次",
                            formula="attacker=本人且 victim 为敌方的 blinds 计数",
                            numerator="enemies_flashed", denominator=None,
                            source="awpy.stats.enemies_flashed（来自 blinds 数据集）",
                            note="同一敌人被同一颗闪多次命中会重复计数", min_sample=1),

    "flash_eff": dict(name="闪光效率", cat="道具", unit="%",
                      definition="投出的闪光弹里，至少致盲到 1 名敌人的比例",
                      formula="生效闪光数 ÷ 投出闪光数",
                      numerator="flash_effective", denominator="flashes_thrown",
                      source="blinds 事件按 tick 去重，只计敌方致盲",
                      note="不能用「致盲人次 ÷ 投出数」——一颗闪光可以同时致盲多人，会算出 90% 以上的虚高值",
                      min_sample=1),

    "util_dmg_per_round": dict(name="局均伤害", cat="道具", unit="伤害/回合",
                      definition="火雷平均每回合造成的伤害（只算火和雷，烟闪诱饵不计）",
                      formula="火雷总伤害 ÷ 总回合",
                      numerator="utility_damage", denominator="rounds_played",
                      source="damage 表按 weapon=hegrenade/molotov/incendiary 过滤",
                      note="用局均而不是累计——累计只反映打了多少场", min_sample=1),
    "util_dmg_per_use": dict(name="每颗平均伤害", cat="道具", unit="伤害/颗",
                      definition="一颗火雷平均打出多少伤害",
                      formula="火雷总伤害 ÷ 有效投掷数",
                      numerator="utility_damage", denominator="utility_used",
                      source="有效投掷 = 该 tick 真的造成了伤害的投掷",
                      note="哑弹（没伤到人）不进入分母", min_sample=1),
    "util_used": dict(name="有效投掷", cat="道具", unit="次",
                      definition="真的造成了伤害的投掷次数（哑弹不算）",
                      formula="damage 事件按 tick 去重计数",
                      numerator="utility_used", denominator=None,
                      source="damage 表按 tick 去重", note=None, min_sample=1),
    "util_hits": dict(name="命中次数", cat="道具", unit="次",
                      definition="火雷造成的伤害事件条数（一个人被烧 3 次算 3 次）",
                      formula="damage 事件计数",
                      numerator="hit_count", denominator=None,
                      source="damage 表按 weapon 过滤",
                      note="和「有效投掷」不是一个量纲，别相除", min_sample=1),

    "grenade_buy": dict(name="购买", cat="道具", unit="颗",
                      definition="自己花钱买的道具数量（不含捡到的）",
                      formula="购买事件计数",
                      numerator=None, denominator=None,
                      source="purchases 表 action=purchase", note=None, min_sample=1),
    "grenade_pickup": dict(name="捡起", cat="道具", unit="颗",
                      definition="从地上捡到的道具数量（队友死了掉的、别人丢的）",
                      formula="捡起事件计数",
                      numerator=None, denominator=None,
                      source="purchases 表 action=pickup",
                      note="烟雾常年靠捡：买 5 颗捡 10 颗是正常现象", min_sample=1),
    "grenade_throw": dict(name="投出", cat="道具", unit="颗",
                      definition="真正扔出去并触发引爆的道具数量，按投掷者归属到人",
                      formula="引爆事件计数（smoke/flash/he/inferno/decoy detonate）",
                      numerator=None, denominator=None,
                      source="demoparser2 的 *_detonate 事件的 user_steamid",
                      note="买了死在手里的不算，所以可能小于「购买 + 捡起」；捡别人的投出去会算进你的数，也可能大于购买数", min_sample=1),

    "flash_per_hit": dict(name="每人次平均致盲", cat="道具", unit="秒",
                      definition="每致盲一个人，平均让他瞎多久",
                      formula="致盲总秒数 ÷ 致盲人次",
                      numerator="flash_duration", denominator="enemies_flashed",
                      source="blinds 事件",
                      note="不用「每颗平均」——一颗闪闪到 5 个人会把数字拉得很长，看不出单个人实际瞎多久", min_sample=1),
    "flash_hits_per_throw": dict(name="每颗闪到几人", cat="道具", unit="人/颗",
                      definition="一颗闪光平均能影响几个敌人",
                      formula="致盲人次 ÷ 投出闪光数",
                      numerator="enemies_flashed", denominator="flashes_thrown",
                      source="blinds 事件按 tick 去重", note=None, min_sample=1),
    "flash_effective": dict(name="生效闪光", cat="道具", unit="颗",
                      definition="至少致盲到 1 名敌人的闪光弹数量",
                      formula="按 tick 去重计数",
                      numerator="flash_effective", denominator=None,
                      source="blinds 事件，只计敌方致盲", note=None, min_sample=1),

    "flash_duration": dict(name="致盲时长", cat="道具", unit="秒",
                           definition="本人闪光造成的敌方累计致盲秒数",
                           formula="敌方致盲事件的 duration 求和",
                           numerator="flash_duration", denominator=None,
                           source="awpy.blinds.duration（attacker=本人，victim 为敌方）",
                           note=None, min_sample=1),

    "flash_assists": dict(name="闪光助攻", cat="道具", unit="次",
                          definition="因本人致盲而产生的助攻",
                          formula="击杀事件中 assister 为本人且 assist_flash=true",
                          numerator="flash_assists", denominator=None,
                          source="awpy.stats.flash_assists / kills.assist_flash",
                          note=None, min_sample=1),

    "team_flash": dict(name="队友致盲", cat="道具", unit="人次",
                       definition="本人闪光致盲队友的人次",
                       formula="attacker=本人且 victim 为队友的 blinds 计数",
                       numerator="team_flash", denominator=None,
                       source="blinds 按阵营过滤",
                       note="单独展示，不与敌方效果抵消", min_sample=1),

    "smoke_count": dict(name="烟雾", cat="道具", unit="颗",
                        definition="已确认的烟雾部署数",
                        formula="smokegrenade_detonate 计数",
                        numerator="smoke_count", denominator=None,
                        source="awpy.smokes 行数", note=None, min_sample=1),

    "smoke_duration": dict(name="烟雾时长", cat="道具", unit="秒",
                           definition="单枚烟雾从生效到结束的平均时长",
                           formula="sum(end_tick - start_tick) ÷ 60 ÷ 烟雾数",
                           numerator="smoke_seconds", denominator="smoke_count",
                           source="awpy.smokes 的 start_tick / end_tick",
                           note=None, min_sample=3),

    "fire_count_util": dict(name="燃烧弹", cat="道具", unit="颗",
                            definition="已确认的燃烧类投掷数",
                            formula="inferno_startburn 计数",
                            numerator="fire_count_util", denominator=None,
                            source="awpy.fires 行数", note=None, min_sample=1),

    "decoy_count": dict(name="诱饵弹", cat="道具", unit="颗",
                        definition="已确认的诱饵弹投掷数",
                        formula="type=decoy 的去重投掷物数",
                        numerator="decoy_count", denominator=None,
                        source="awpy.grenades 按 type 过滤", note=None, min_sample=1),

    # ============================================================ 目标
    "plants": dict(name="安包", cat="目标", unit="次",
                   definition="由本人完成的成功安包次数",
                   formula="bomb.finish_plant 且 steamid=本人",
                   numerator="plants", denominator=None,
                   source="awpy.bomb 的 finish_plant 事件", note=None, min_sample=1),

    "defuses": dict(name="拆包", cat="目标", unit="次",
                    definition="由本人完成的成功拆弹次数",
                    formula="bomb.defuse 且 steamid=本人",
                    numerator="defuses", denominator=None,
                    source="awpy.bomb 的 defuse 事件", note=None, min_sample=1),

    "plant_rate": dict(name="安包参与率", cat="目标", unit="%",
                       definition="个人计入的 T 回合中成功安包的比例",
                       formula="本人安包回合数 ÷ 个人计入 T 回合数",
                       numerator="plant_rounds", denominator="t_rounds",
                       source="安包事件与阵营归属关联",
                       note="分母只算 T 回合，换边后不计", min_sample=10),

    "post_plant_win": dict(name="安包后胜率", cat="目标", unit="%",
                           definition="本队成功安包的回合中获胜的比例",
                           formula="安包后获胜回合数 ÷ 本队安包回合数",
                           numerator="post_plant_wins", denominator="team_plants",
                           source="bomb.finish_plant 与 rounds.winner 关联",
                           note="不区分是谁安的包", min_sample=5),

    # ============================================================ 评分
    "rating": dict(name="Rating 2.0", cat="评分", unit="分",
                   definition="HLTV Rating 2.0，综合 KAST/KPR/DPR/Impact/ADR 的加权分",
                   formula="0.0073×KAST + 0.3591×KPR − 0.5329×DPR "
                           "+ 0.2372×Impact + 0.0032×ADR + 0.1587",
                   numerator=None, denominator=None,
                   source="HLTV 公开的 Rating 2.0 公式（definition_version=2.0）",
                   note="业界通行分，1.00 为平均水准；3.0 版官方未公开公式，本工具不采用",
                   min_sample=1),

    "impact": dict(name="Impact", cat="评分", unit="分",
                   definition="回合影响力，衡量多杀与首杀等高影响行为的密度",
                   formula="2.13×KPR + 0.42×APR − 0.41",
                   numerator=None, denominator=None,
                   source="HLTV Rating 2.0 配套的 Impact 公式",
                   note="不含 ADR 与 KAST，只反映「关键时刻的产出密度」", min_sample=1),
}


def get(mid: str) -> dict | None:
    return METRICS.get(mid)


def all_metrics() -> dict:
    return METRICS


def by_cat() -> dict:
    out: dict[str, list] = {}
    for k, v in METRICS.items():
        out.setdefault(v["cat"], []).append({"id": k, **v})
    return out
