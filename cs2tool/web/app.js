/* Cross-Section v5 —— 单页渲染层
 * 楼层：概览 / 平均 / 武器 / 回合事件 / 多杀残局 / 地图数据 / 经济 / 道具 / 逐场 / 图池 / Demo
 */
let S = { demos: [], overview: {}, me: null, players: [], settings: {} };
let METRICS = {};
let SIDE = '';            // '' | 'CT' | 'T'
let TREND_KEY = 'rating';
let WCLASS = 'rifle';     // 武器类别

window.addEventListener('error', ev => {
  const b = document.createElement('div');
  b.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:99999;max-width:60vw;'
    + 'background:#3a1414;border:1px solid #7a2b2b;color:#ffd6d6;padding:10px 14px;'
    + 'border-radius:8px;font:12px/1.6 ui-monospace,monospace;white-space:pre-wrap';
  b.textContent = 'JS: ' + (ev.message || '') + '\n' + (ev.filename || '').split('/').pop()
    + ':' + (ev.lineno || '');
  document.body.appendChild(b);
});
window.addEventListener('unhandledrejection', ev => {
  const b = document.createElement('div');
  b.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:99999;max-width:60vw;'
    + 'background:#3a2c14;border:1px solid #7a5a2b;color:#ffe9c7;padding:10px 14px;'
    + 'border-radius:8px;font:12px/1.6 ui-monospace,monospace;white-space:pre-wrap';
  b.textContent = 'Promise: ' + (ev.reason && ev.reason.message || ev.reason || '');
  document.body.appendChild(b);
});

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const num = (v, d = 0) => (v == null || v === '' ? '—' : Number(v).toFixed(d));
const nth = v => (v == null ? '—' : Number(v).toLocaleString('en-US'));
const pct = v => (v == null || v === '' ? '—' : Number(v).toFixed(1) + '%');

const MAP_CN = {
  de_dust2: '炙热沙城2', de_mirage: '荒漠迷城', de_inferno: '炼狱小镇',
  de_ancient: '远古遗迹', de_anubis: '阿努比斯', de_nuke: '核子危机',
  de_vertigo: '殒命大厦', de_overpass: '死亡游乐园', de_train: '列车停放站',
  de_office: '办公室', de_italy: '意大利小镇', de_cache: '死城之谜',
  de_cbble: '古堡激战', de_tuscan: '托斯卡纳',
};
const mapCn = m => MAP_CN[m] || String(m || '').replace(/^de_/, '');

/* 武器 → 类别 + 中文名 */
const WCLASS_MAP = {};
[
  ['rifle', ['ak47', 'm4a1', 'm4a1_silencer', 'galilar', 'famas', 'aug', 'sg556',
             'ssg08', 'awp', 'g3sg1', 'scar20', 'm249', 'negev']],
  ['smg', ['mp9', 'mp7', 'mac10', 'ump45', 'p90', 'bizon', 'mp5sd']],
  ['pistol', ['glock', 'usp_silencer', 'hkp2000', 'p250', 'deagle', 'fiveseven',
              'tec9', 'cz75a', 'revolver', 'elite']],
  ['heavy', ['nova', 'xm1014', 'mag7', 'sawedoff']],
  ['other', ['knife', 'knife_t', 'taser', 'world', 'worldent', 'c4']],
].forEach(([c, arr]) => arr.forEach(w => { WCLASS_MAP[w] = c; }));
const wclass = w => WCLASS_MAP[String(w || '').replace(/^weapon_/, '')] || 'other';

const WNAME_CN = {
  ak47: 'AK-47', m4a1: 'M4A4', m4a1_silencer: 'M4A1-S', galilar: '加利尔',
  famas: '法玛斯', aug: 'AUG', sg556: 'SG553', ssg08: 'SSG08', awp: 'AWP',
  g3sg1: 'G3SG1', scar20: 'SCAR-20', m249: 'M249', negev: '内格夫',
  mp9: 'MP9', mp7: 'MP7', mac10: 'MAC-10', ump45: 'UMP-45', p90: 'P90',
  bizon: 'PP-野牛', mp5sd: 'MP5-SD', glock: '格洛克', usp_silencer: 'USP-S',
  hkp2000: 'P2000', p250: 'P250', deagle: '沙漠之鹰', fiveseven: 'FIVE-SEVEN',
  tec9: 'TEC-9', cz75a: 'CZ75-Auto', revolver: 'R8 左轮', elite: '双持贝瑞塔',
  nova: '新星', xm1014: 'XM1014', mag7: 'MAG-7', sawedoff: '截短霰弹枪',
  knife: '刀', knife_t: '刀', taser: '电击枪', c4: 'C4',
};
const wcn = w => {
  const k = String(w || '').replace(/^weapon_/, '');
  return WNAME_CN[k] || k;
};

async function api(path, opt) {
  const r = await fetch(path, opt);
  return await r.json();
}

/* ================= 悬浮说明 ================= */
async function loadMetrics() {
  if (Object.keys(METRICS).length) return;
  try { METRICS = (await api('/api/metrics')).metrics || {}; } catch (e) { METRICS = {}; }
}
function hideTip() { const t = $('#mtip'); if (t) t.classList.remove('on'); }
/* 把气泡放到锚点元素上方（放不下就下方），水平方向夹在视口内 */
function placeTip(t, el) {
  const r = el.getBoundingClientRect();
  let x = r.left + r.width / 2 - t.offsetWidth / 2;
  x = Math.max(10, Math.min(x, innerWidth - t.offsetWidth - 10));
  let y = r.top - t.offsetHeight - 10;
  if (y < 10) y = r.bottom + 10;
  t.style.left = x + 'px'; t.style.top = y + 'px';
}
/* 能力画像的 ? 圈圈：文案是纯文本（可能含空行），走同一个气泡 */
function showAbTip(el) {
  const txt = el.dataset.abtip;
  if (!txt) return;
  const t = $('#mtip'); if (!t) return;
  t.innerHTML = `<div class="d">${esc(txt)}</div>`;
  t.classList.add('on');
  placeTip(t, el);
}
function showTip(el) {
  const m = METRICS[el.dataset.m];
  if (!m) return;
  const t = $('#mtip'); if (!t) return;
  const rows = [];
  if (m.numerator) rows.push(`<div class="r"><b>分子</b><span>${esc(m.numerator)}</span></div>`);
  if (m.denominator) rows.push(`<div class="r"><b>分母</b><span>${esc(m.denominator)}</span></div>`);
  if (m.unit) rows.push(`<div class="r"><b>单位</b><span>${esc(m.unit)}</span></div>`);
  t.innerHTML = `<div class="t">${esc(m.name)}<span class="ttag">${esc(m.cat || '')}</span></div>`
    + (m.definition ? `<div class="d">${esc(m.definition)}</div>` : '')
    + (m.formula ? `<div class="f">${esc(m.formula)}</div>` : '')
    + rows.join('')
    + (m.note ? `<div class="n">${esc(m.note)}</div>` : '')
    + (m.source ? `<div class="s">来源：${esc(m.source)}</div>` : '');
  t.classList.add('on');
  placeTip(t, el);
}
document.addEventListener('mouseover', e => {
  if (document.body.classList.contains('nott')) return;
  const ab = e.target.closest('[data-abtip]');
  if (ab) { showAbTip(ab); return; }          // 能力画像的 ? 圈圈
  const el = e.target.closest('[data-m]');
  if (el) showTip(el);
});
document.addEventListener('mouseout', e => {
  if (e.target.closest('[data-m]') || e.target.closest('[data-abtip]')) hideTip();
});
window.addEventListener('scroll', hideTip, { passive: true });

const M = (k, label) => `<span data-m="${k}">${esc(label || (METRICS[k] || {}).name || k)}</span>`;

/* ================= 组件 ================= */
function kpi(v, label, sub = '', mk = '') {
  const l = mk ? M(mk, label) : esc(label);
  return `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div>`
    + (sub ? `<div class="s">${sub}</div>` : '') + `</div>`;
}
function cell(v, label, sub = '', mk = '') {
  const l = mk ? M(mk, label) : esc(label);
  return `<div class="ri"><div class="k">${l}</div><div class="v">${v}</div>`
    + (sub ? `<div class="s">${sub}</div>` : '') + `</div>`;
}
function bars(items, opt = {}) {
  if (!items || !items.length) return '<div class="nil">—</div>';
  const mx = Math.max(1, ...items.map(x => Math.abs(x.val || 0)));
  const sum = items.reduce((a, b) => a + Math.abs(b.val || 0), 0) || 1;
  /* opt.money：金额格式（$39,850），不再显示裸数字 39850 */
  const fmt = v => opt.money ? '$' + nth(Math.round(Math.abs(v))) : String(Math.round(v));
  return items.map(x => {
    const w = Math.round(Math.abs(x.val || 0) / mx * 100);
    // opt.pct：在数值后补「占总量比例」，让横向条有可比较的百分比
    const pctTxt = opt.pct
      ? `<span class="pct">${(Math.abs(x.val || 0) / sum * 100).toFixed(1)}%</span>` : '';
    return `<div class="bar${opt.neg ? ' neg' : ''}">
      <span class="lab" title="${esc(x.lab)}">${esc(x.lab)}</span>
      <span class="mbtr"><i class="mb${x.val < 0 ? ' neg' : ''}" style="width:${w}%"></i></span>
      <span class="val">${fmt(x.val)}${opt.suffix || ''}${pctTxt}</span></div>`;
  }).join('');
}
function table(cols, rows, opt = {}) {
  if (!rows || !rows.length) return '<div class="nil">—</div>';
  const th = cols.map(c => `<th class="${c.num ? 'num' : ''}">${c.k ? M(c.k, c.t) : esc(c.t)}</th>`).join('');
  const tr = rows.map((r, i) => `<tr${opt.click ? ` class="clickable" data-i="${i}"` : ''}>`
    + cols.map(c => {
      const v = c.get ? c.get(r) : r[c.f];
      return `<td class="${c.num ? 'num' : ''}">${v == null || v === '' ? '—' : v}</td>`;
    }).join('') + '</tr>').join('');
  return `<table class="tb"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
}
const minibar = (v, max, cls = '') => {
  const w = max > 0 ? Math.round(Math.abs(v) / max * 100) : 0;
  return `<span class="mbtr"><i class="mb ${cls}" style="width:${w}%"></i></span>`;
};

/* ================= 视角（全部 / CT / T） ================= */
function view() {
  const ov = S.overview || {};
  const t = ov.total || {};
  if (!SIDE) return { t, isSide: false };
  const s = (t.side || {})[SIDE] || {};
  return {
    isSide: true, side: SIDE,
    t: {
      ...t,
      rounds: s.rounds || 0, kills: s.kills || 0, deaths: s.deaths || 0,
      adr: s.adr, kpr: s.kpr, dpr: s.dpr,
      kd: s.deaths ? +(s.kills / s.deaths).toFixed(2) : null,
      assists: null, hs: null, hs_pct: null, fk: null, fd: null,
      fire_count: null, hit_count: null, fire_accuracy: null,
      imprecise_shots: null, imprecise_rate: null, stop_shots: null, stop_rate: null,
      survive_rounds: null, survive_pct: null,
      trade_kills: null, traded_deaths: null, trade_rate: null, traded_death_rate: null,
      spent: null, spent_avg: null, equip_value: null, equip_round_start: null,
      flashes_thrown: null, enemies_flashed: null, flash_eff: null, flash_duration: null,
    },
  };
}

/* ================= 加载 ================= */
async function load() {
  S = await api('/api/state');
  await loadMetrics();
  applyLook();
  $('#ver').textContent = S.version ? 'v' + S.version : '';
  if ($('#footVer')) $('#footVer').textContent = S.version ? 'v' + S.version : '';
  if ($('#whoAmI')) $('#whoAmI').textContent = S.overview?.player?.name || '';
  renderPlayers();
  renderAll();
  jobUI(S.job);
  if (S.job && S.job.running) pollJob();
  checkUpdate();          // 版本检查放最后，不阻塞首屏，失败了也没人看见
}

/* ================= 版本检查（GitHub Release） =================
 * 只做两件事：版本号变可点（跳发布页）+ 有新版本时挂个 NEW 徽章。
 * 断网、后端 404、GitHub 挂了都要完全静默 —— 面板不能因为这个弹红条。
 */
let VER_CHECKED = false;

async function checkUpdate() {
  if (VER_CHECKED) return;      // 只查一次；load() 被重复调用也不会插两个徽章
  VER_CHECKED = true;
  const el = $('#ver');
  if (!el) return;

  let r = null;
  try {
    const res = await fetch('/api/update_check', { cache: 'no-store' });
    if (!res.ok) return;
    r = await res.json();
  } catch (e) {
    return;                     // 断网 / 服务没起：静默
  }
  if (!r || typeof r !== 'object') return;

  // 版本号可点 → 发布页（拿不到 releases_url 就不绑，免得出个死链接）
  if (r.releases_url) {
    el.classList.add('ver-link');
    el.style.color = '';        // index.html 里写死 inline color，清掉才能吃到 hover 变色
    el.title = '查看发布页';
    el.setAttribute('role', 'link');
    el.onclick = () => window.open(r.releases_url, '_blank', 'noopener');
  }

  if (r.ok !== true || r.newer !== true || !r.latest) return;
  if (document.querySelector('.ver-new')) return;

  const b = document.createElement('span');
  b.className = 'ver-new';
  b.textContent = 'NEW';
  b.title = '有新版本 v' + r.latest;
  b.setAttribute('role', 'link');
  b.onclick = ev => {
    ev.stopPropagation();
    window.open(r.url || r.releases_url, '_blank', 'noopener');
  };
  el.insertAdjacentElement('afterend', b);
}

function renderPlayers() {
  PlayerSelect.render($('#player'), S.players);
}
PlayerSelect.bind($('#player'),
  (p, b) => api(p, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(b)
  }),
  async () => { await load(); });

/* ================= 总入口 ================= */
function renderAll() {
  if (!S.overview || S.overview.empty) {
    hideAbility();
    $$('.sec').forEach(el => {
      if (el.hidden) return;             // 能力画像这类按需出现的区块不塞占位
      if (!el.querySelector('.nil'))
        el.insertAdjacentHTML('beforeend',
          '<div class="nil">还没有对局数据。打开「设置 → 数据操作」扫描 demo 目录并分析。</div>');
    });
    return;
  }
  const v = view();
  rOverview(v);
  renderAbility();
  rAvg(v);
  rWeapons();
  rEvents();
  rClutch();
  rReason();
  rMaps();
  rEcon();
  rUtil();
  rReceived();
  updateSideSel();
}

/* ================= 概览 ================= */
const RATING_PARTS = [
  ['rating', 'Rating'], ['adr', 'ADR'], ['kast', 'KAST'],
  ['kpr', 'KPR'], ['dpr', 'DPR'], ['impact', 'Impact'],
];
const TREND_FMT = { rating: 2, adr: 1, kast: 1, kpr: 2, dpr: 2, impact: 2 };
const TREND_LABEL = { rating: 'Rating', adr: 'ADR', kast: 'KAST',
                      kpr: 'KPR', dpr: 'DPR', impact: 'Impact' };

function rOverview(v) {
  const t = v.t, ov = S.overview;
  $('#ovSub').textContent = ov.player?.name || '';
  /* 胜率分母不含平局：12:12 打满常规时间，既不算赢也不算输 */
  const _dr = t.played ? Math.round((t.draws || 0) / t.played * 100) : 0;
  const _dsub = (t.draws || 0) > 0 ? ` · ${t.draws} 平 (${_dr}%)` : '';
  const _lsub = t.losses != null ? t.losses : ((t.played ?? 0) - (t.wins ?? 0) - (t.draws || 0));
  $('#ovHero').innerHTML = [
    kpi(nth(t.rounds), '总回合', `${t.matches || ov.timeline?.length || 0} 场对局`, 'rounds_played'),
    kpi(nth(t.dmg), '总伤害', `${num(t.adr, 1)} ADR`, 'damage_total'),
    kpi(t.win_rate == null ? '—' : t.win_rate + '%', '总胜率',
        `${t.wins ?? 0} 胜 ${_lsub} 负${_dsub}`, 'win_rate'),
  ].join('');

  $('#ratingRow').innerHTML = RATING_PARTS.map(([k, lab]) => {
    const on = k === TREND_KEY ? ' on' : '';
    return `<div class="ri${on}" data-k="${k}">
      <div class="k" data-m="${k}">${lab}</div>
      <div class="v">${num(t[k], TREND_FMT[k] ?? 2)}</div></div>`;
  }).join('');
  $$('#ratingRow .ri').forEach(el => {
    el.onclick = () => { TREND_KEY = el.dataset.k; rOverview(view()); };
  });

  rTrend();
}

/* ================= 能力画像（七维） =================
 * 数据来自 /api/v1/ability；后端没装 ability2、没数据、接口报错时整块安静隐藏。
 * 分数条颜色按 step（-2 差 … 2 好），说明一律走 ? 悬浮，卡片里不写小字。
 */
let AB_SEQ = 0;
const abStepCls = s => (s >= 2 ? 's2' : s === 1 ? 's1' : s <= -2 ? 'sm2' : s === -1 ? 'sm1' : 's0');
const abStepFromZ = z => {
  const v = Number(z);
  if (!isFinite(v)) return 0;
  return v >= 1 ? 2 : v >= .35 ? 1 : v <= -1 ? -2 : v <= -.35 ? -1 : 0;
};
/* ? 圈圈：文案放 data-abtip，悬浮时交给全局 #mtip 渲染（fixed 定位、向上弹、自动避边界） */
const abQ = txt => txt
  ? `<span class="abq" data-abtip="${esc(txt)}">?</span>` : '';

/* 维度说明：中文是我们自己的口径解释，英文是 HLTV 官方 tooltip 原文（逐字引用）。
   渲染时两段拼在一个悬浮框里，中间空一行。 */
const AB_DIM_DESC = {
  firepower: {
    zh: '赢下对枪的能力——官方刻意奖励"高产出"，即使这么打的代价很高（死得多也不扣分）。'
      + '这里用每胜局击杀、无伤击杀、多杀频率、回合贡献和伤害每回合来衡量输出密度。',
    en: "A player's ability to win their duels, designed to reward high-output players "
      + 'even if the cost of that output is high.'
  },
  opening: {
    zh: '你有多主动去找首杀和早期对枪。看首杀尝试率、队内首杀顺位、首个交火发生得多早，'
      + '以及每回合开火次数——这项高说明你常年是第一个碰敌人的那个人。',
    en: 'How often a player goes looking for openers or early-round duels.'
  },
  entrying: {
    zh: '你多常死在队友能换到的地方。分高说明你主动承担第一个风险、让别人不必去冒；'
      + '这个维度不分进攻防守——防守方前压被留下、守点被破后能不能被补掉，同样算在里面。',
    en: 'How often a player dies somewhere their team can trade. High scorers take the '
      + 'first risk so somebody else does not have to.'
  },
  trading: {
    zh: '你多常因为队友吸引火力而受益——他挨打时你补枪、他被换掉时你换回来。'
      + '看换人机会、换人成功率、诱饵击杀和助攻击杀。',
    en: 'How often a player is the one to benefit from a teammate taking fire, via a trade '
      + 'or a frag while they are being damaged.'
  },
  closing: {
    zh: '你多常活到残局情形（安包后、1vN）。看每回合存活时长、安放后是否还活着、'
      + '是不是最后一个倒下，以及残局胜率。',
    en: 'How often a player is alive for late-round situations like post-plants or clutches.'
  },
  sniping: {
    zh: '你多常把狙击枪当主武器使。看有狙的回合占比、狙击击杀占你总击杀的比例，AWP 单列一档。',
    en: 'How often a player deploys sniper rifles as their primary weapon.'
  },
  utility: {
    zh: '你多常当队伍的投掷手。数量轨看每回合投掷量（3 颗算满档、按 2/3 次幂换算），'
      + '质量轨看这些道具是否真干扰到人；总分取两者几何平均——只囤不用拿不到高分。',
    en: "How often a player is their team's grenadier, ready to throw smokes, flashes, "
      + 'or damage-dealing utility.'
  }
};
/* 维度悬浮文案：中文口径 + HLTV 英文原文（空一行分隔） */
const abDimTip = (key, fallback) => {
  const d = AB_DIM_DESC[key];
  if (!d) return fallback || '';
  return d.zh + '\n\nHLTV: ' + d.en;
};
/* 七维图标：自绘 SVG（通用符号，无第三方素材），stroke=currentColor 跟随主题。
   尺寸统一 24 网格，细线 1.6 —— 跟项目其它图标同一套手感。 */
const AB_ICON = {
  firepower: '<circle cx="12" cy="12" r="2.4"/><path d="M12 3.6v3M12 17.4v3M3.6 12h3M17.4 12h3M6.1 6.1l2.1 2.1M15.8 15.8l2.1 2.1M17.9 6.1l-2.1 2.1M8.2 15.8l-2.1 2.1"/>',
  entrying: '<path d="M14.5 4H20v16h-5.5"/><path d="M3.5 12h8.5M9 8.6l3.4 3.4L9 15.4"/>',
  trading: '<path d="M3.5 8.5h11M12 5.2 15.3 8.5 12 11.8"/><path d="M20.5 15.5h-11M11.5 12.2 8.2 15.5l3.3 3.3"/>',
  opening: '<path d="M13.6 2.5 5.2 13.2h4.9L9.1 21.5l8.4-10.7h-4.9l1-8.3z"/>',
  closing: '<circle cx="12" cy="12" r="7.6"/><circle cx="12" cy="12" r="3.6"/><circle cx="12" cy="12" r=".9"/>',
  sniping: '<circle cx="12" cy="12" r="6.8"/><path d="M12 2.4v4.6M12 17v4.6M2.4 12h4.6M17 12h4.6"/><circle cx="12" cy="12" r="1.1"/>',
  utility: '<path d="M9.2 6.4h5.6l1 4.2V19H8.2V10.6l1-4.2z"/><path d="M10.9 6.4V4.2h2.2v2.2"/><path d="M13.4 5.2h3.4"/><path d="M8.2 12.6h7.6"/>'
};
const abIcon = key => {
  const body = AB_ICON[key];
  return body
    ? `<svg class="abi-i" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"
         aria-hidden="true">${body}</svg>` : '';
};
/* 七维英文名（母项也做中英对照，跟子项一套） */
const AB_DIM_EN = {
  firepower: 'Firepower', entrying: 'Entrying', trading: 'Trading',
  opening: 'Opening', closing: 'Closing', sniping: 'Sniping', utility: 'Utility'
};
/* 细项英文名：与 Leetify 官方术语逐条对齐（中文为主，英文做对照） */
const AB_EN = {
  kpr_win: 'Kills per Round Win', nd_kill_pr: 'Perfect Kills per Round',
  kill_round_pct: 'Rounds with a Kill', net_kill_24: 'Kills per 24 Rounds',
  win_contrib: 'Round Win Shares', prevent_trade_pr: 'Trade Denials per Round',
  multi_round_pct: 'Rounds with a Multi-Kill', net_dmg_pr: 'Damage per Round',
  tradeable_death_pr: 'Tradeable Deaths per Round', death_traded_pct: 'Deaths Traded %',
  bait_assist_pr: 'Bait Assists per Round', fd_traded_pct: 'Opening Deaths Traded %',
  trade_opp_pr: 'Trade Opportunities per Round', trade_success_pct: 'Trade Kills %',
  bait_kill_pct: 'Bait Kills %', assist_kill_pct: 'Assisted Kills %',
  fe_pct: 'Opening Attempts', fk_order: 'First Duel Rank in Team',
  fk_time_s: 'First Duel Time', fires_pr: 'Weapon Attacks per Round',
  survive_s: 'Time Alive per Round', postplant_alive_pct: 'Alive for Post-Plant %',
  last_alive_pct: 'Last Alive %', clutch_24: 'Clutches per 24 Rounds',
  sniper_round_pct: 'Rounds with a Sniper', sniper_kill_pct: 'Sniper Kills %',
  awp_round_pct: 'Rounds with an AWP', awp_kill_pct: 'AWP Kills %',
  smoke_pr: 'Smokes Thrown per Round', flash_pr: 'Flashbangs Thrown per Round',
  fire_pr: 'Molotovs Thrown per Round', he_pr: 'HE Grenades Thrown per Round'
};
/* 细项英文说明：HLTV 不公开细项定义，这些是我们的英文自述，标 EN 而非 HLTV */
const AB_EN_DESC = {
  kpr_win: 'Kills you average in each round you win.',
  nd_kill_pr: 'Kills made without taking any damage, per round.',
  kill_round_pct: 'Share of rounds where you got at least one kill.',
  net_kill_24: 'Kills per 24 rounds — a full-match volume of frags.',
  win_contrib: 'Your share of team kills + assists in the rounds you won.',
  prevent_trade_pr: 'How often your kills go unanswered by an immediate trade.',
  multi_round_pct: 'Rounds where you personally got 2 or more kills.',
  net_dmg_pr: 'Damage dealt per round (overkill and post-death shots excluded).',
  tradeable_death_pr: 'Deaths per round that happened where a teammate could trade you.',
  death_traded_pct: 'Share of your deaths that a teammate traded back.',
  bait_assist_pr: 'Assists per round where you drew fire and a teammate finished.',
  fd_traded_pct: 'Share of your opening deaths that got traded.',
  trade_opp_pr: 'Chances per round to trade a teammate\'s death.',
  trade_success_pct: 'Share of trade chances you actually converted.',
  bait_kill_pct: 'Share of your kills made right after a teammate took fire.',
  assist_kill_pct: 'Share of your kills that came with an assist (you damaged first).',
  fe_pct: 'Share of rounds where you took part in the first duel.',
  fk_order: 'Average position within your team in the opening duel.',
  fk_time_s: 'Seconds into the round when the first kill (you involved) happens.',
  fires_pr: 'Weapon attacks — shots fired — per round.',
  survive_s: 'Seconds alive per round.',
  postplant_alive_pct: 'Share of planted rounds where you were still alive when the bomb went down.',
  last_alive_pct: 'Share of rounds where you were the last one standing on your team.',
  clutch_24: '1vN clutches won per 24 rounds.',
  sniper_round_pct: 'Share of rounds where you used a sniper rifle.',
  sniper_kill_pct: 'Share of your kills made with a sniper rifle.',
  awp_round_pct: 'Share of rounds where you held an AWP.',
  awp_kill_pct: 'Share of your kills made with the AWP.',
  smoke_pr: 'Smokes thrown per round.',
  flash_pr: 'Flashbangs thrown per round.',
  fire_pr: 'Molotovs / incendiaries thrown per round.',
  he_pr: 'HE grenades thrown per round.'
};
/* 细项悬浮文案：中文说明 + 空行 + 英文自述 */
const abItemTip = it => {
  const zh = it.desc || '';
  const en = AB_EN_DESC[it.key];
  return en ? (zh + '\n\nEN: ' + en) : zh;
};
const abVal = (v, unit) => {
  if (v == null || v === '' || !isFinite(Number(v))) return '—';
  const n = Number(v);
  return esc((Number.isInteger(n) ? String(n) : String(+(+n.toFixed(2)))) + (unit || ''));
};

function hideAbility() {
  const sec = $('#s-ability');
  if (sec) sec.hidden = true;
}

async function renderAbility() {
  const sec = $('#s-ability'), box = $('#abDims');
  if (!sec || !box) return;
  const seq = ++AB_SEQ;                  // 切人/刷新时只认最后一次请求，防止旧响应回填
  let d;
  try {
    d = await api('/api/v1/ability' + (SIDE ? '?side=' + SIDE : ''));
  } catch (e) {
    return hideAbility();                // 接口不存在或网络失败：不弹错、不留空框
  }
  if (seq !== AB_SEQ) return;
  if (!d || d.error || !Array.isArray(d.dimensions) || !d.dimensions.length) {
    return hideAbility();
  }
  const sm = d.sample || {};
  $('#abSample').textContent = (sm.person_rounds || sm.players)
    ? `${nth(sm.person_rounds || 0)} 个人回合 · 对照 ${nth(sm.players || 0)} 名玩家`
    : '';
  box.innerHTML = d.dimensions.map(dim => {
    const score = Math.max(0, Math.min(100, Number(dim.score) || 0));
    const cls = abStepCls(dim.step != null ? dim.step : abStepFromZ(dim.z));
    const items = (dim.items || []).map(it => {
      const p = Number(it.pct);
      const w = Number.isFinite(p) ? Math.max(0, Math.min(100, p)) : 0;
      return `<div class="abi">
        <div class="abit"><span class="k">${esc(it.name || '')}${
          AB_EN[it.key] ? `<i class="ka">${AB_EN[it.key]}</i>` : ''}</span>${abQ(abItemTip(it))}
          <span class="v">${abVal(it.value, it.unit)}</span></div>
        <div class="abis"><i style="width:${w.toFixed(1)}%"></i></div></div>`;
    }).join('');
    return `<div class="abc">
      <div class="abh"><div class="abn">${abIcon(dim.key)}${esc(dim.name || '')}<i class="ka abd">${AB_DIM_EN[dim.key] || ''}</i>${abQ(abDimTip(dim.key, dim.desc))}</div>
        <div class="abs"><b>${Math.round(score)}</b><span>/ 100</span><i class="abcaret"></i></div></div>
      <div class="abbar"><i class="${cls}" style="width:${score.toFixed(1)}%"></i></div>
      <div class="abil">${items}</div></div>`;
  }).join('');
  // 卡片默认折叠，点头部（维度名 / 分数那一行）逐个展开；事件只绑一次
  if (!box._abBound) {
    box._abBound = true;
    box.addEventListener('click', ev => {
      const head = ev.target.closest('.abh');
      if (!head) return;
      const card = head.closest('.abc');
      if (card) card.classList.toggle('open');
    });
  }
  sec.hidden = false;
}

/* ================= 走势折线 ================= */
function rTrend() {
  const all = S.overview.timeline || [];
  const box = $('#trChart');
  if (!all.length) { box.innerHTML = '<div class="nil">—</div>'; return; }

  const CAP = 20;
  const tl = all.length > CAP ? all.slice(-CAP) : all;
  const key = TREND_KEY;
  const fd = TREND_FMT[key] ?? 2;
  const label = TREND_LABEL[key] || key;
  const vals = tl.map(x => Number(x[key] ?? 0));
  const mx = Math.max(...vals), mn = Math.min(...vals);

  /* 基准线：Rating 固定 1.00（这个体系的平均水准），其余指标用整段历史的加权平均。
     基准线要参与 y 轴范围计算，否则落在可视区外就看不见了。 */
  const tot = S.overview.total || {};
  const isRating = key === 'rating';
  const baseRaw = isRating ? 1 : Number(tot[key]);
  const hasBase = Number.isFinite(baseRaw) && baseRaw > 0;
  const base = hasBase ? baseRaw : null;
  const lo = hasBase ? Math.min(mn, base) : mn;
  const hi = hasBase ? Math.max(mx, base) : mx;
  const span = Math.max(hi - lo, 0.0001);

  const W = 1120, H = 210, PL = 68, PR = 20, PT = 30, PB = 38;
  const iw = W - PL - PR, ih = H - PT - PB;
  const X = i => PL + (tl.length === 1 ? iw / 2 : iw * i / (tl.length - 1));
  const Y = v2 => PT + ih - ((v2 - lo) / span) * ih;

  const grids = [hi, (hi + lo) / 2, lo].map(g =>
    `<line x1="${PL}" y1="${Y(g).toFixed(1)}" x2="${W - PR}" y2="${Y(g).toFixed(1)}"
       stroke="rgba(255,255,255,.07)" stroke-width="1"/>
     <text x="${PL - 12}" y="${(Y(g) + 4).toFixed(1)}" text-anchor="end"
       fill="#84848a" font-size="12" font-family="ui-monospace,monospace">${g.toFixed(fd)}</text>`).join('');

  /* 基准线：细虚线 + 常显标签。标签贴右端，太靠顶时改画在线下方，避免出画布 */
  let baseLayer = '';
  if (hasBase) {
    const by = Y(base);
    const ly = by < PT + 14 ? by + 15 : by - 7;
    baseLayer = `
      <line x1="${PL}" y1="${by.toFixed(1)}" x2="${W - PR}" y2="${by.toFixed(1)}"
        stroke="rgba(255,255,255,.3)" stroke-width="1" stroke-dasharray="4 4"/>
      <text x="${W - PR}" y="${ly.toFixed(1)}" text-anchor="end"
        fill="#9a9aa0" font-size="12">${isRating ? '基准 1.00' : '平均 ' + base.toFixed(fd)}</text>`;
  }

  const path = vals.map((v2, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v2).toFixed(1)}`).join(' ');
  const area = `M${X(0).toFixed(1)},${(PT + ih).toFixed(1)} `
    + vals.map((v2, i) => `L${X(i).toFixed(1)},${Y(v2).toFixed(1)}`).join(' ')
    + ` L${X(vals.length - 1).toFixed(1)},${(PT + ih).toFixed(1)} Z`;

  const dots = tl.map((x, i) => {
    const v2 = vals[i];
    const c = x.draw === 1 ? '#8a8a8d' : (x.win === 1 ? '#7bd44b' : '#ff6b6b');
    const lab = v2.toFixed(fd);
    return `<g>
      <circle cx="${X(i).toFixed(1)}" cy="${Y(v2).toFixed(1)}" r="3.8" fill="${c}"/>
      <text x="${X(i).toFixed(1)}" y="${(Y(v2) - 10).toFixed(1)}" text-anchor="middle"
        fill="#d4d4d9" font-size="13" font-family="ui-monospace,monospace">${lab}</text>
      <text x="${X(i).toFixed(1)}" y="${H - 21}" text-anchor="middle"
        fill="#9a9aa0" font-size="12">${esc(mapCn(x.map))}</text>
      <text x="${X(i).toFixed(1)}" y="${H - 7}" text-anchor="middle"
        fill="#5f5f66" font-size="12">${esc(x.score || '')}</text>
      <title>${esc(mapCn(x.map))} ${esc(x.score || '')} · ${label} ${lab}${hasBase ? `（${isRating ? '基准 1.00' : '平均 ' + base.toFixed(fd)}）` : ''}</title>
    </g>`;
  }).join('');

  const baseSub = hasBase ? ` · ${isRating ? '基准 1.00' : '平均 ' + base.toFixed(fd)}` : '';
  box.innerHTML = `<div id="trTitle">${label}<span class="n">共 ${all.length} 场${all.length > CAP ? ` · 只画最近 ${CAP} 场` : ''}${baseSub}</span></div>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">
      ${grids}
      ${baseLayer}
      <path d="${area}" fill="rgba(200,200,210,.07)"/>
      <path d="${path}" fill="none" stroke="#c2c2c6" stroke-width="1.6"
        stroke-linejoin="round" stroke-linecap="round"/>
      ${dots}
    </svg>`;
}

/* ================= 平均（一行） ================= */
function rAvg(v) {
  const t = v.t;
  const rd = t.rounds || 1;
  const has = x => x != null;
  const cells = [
    cell(num(t.kills / rd, 2), '击杀 / 回合', `${nth(t.kills)} 累计`, 'kpr'),
    cell(num(t.deaths / rd, 2), '死亡 / 回合', `${nth(t.deaths)} 累计`, 'dpr'),
    cell(num(t.kd, 2), 'K/D', '', 'kd'),
    has(t.assists) ? cell(num(t.assists / rd, 2), '助攻 / 回合', `${nth(t.assists)} 累计`, 'ar') : '',
    has(t.fk) ? cell(Math.round(t.fk / rd * 100) + '%', '首杀率', `${nth(t.fk)} 次`, 'opening_rate') : '',
    has(t.survive_pct) ? cell(pct(t.survive_pct), '存活率', `${t.survive_rounds}/${t.rounds}`, 'survive_pct') : '',
    has(t.trade_rate) ? cell(pct(t.trade_rate), '补枪占比',
        `${t.trade_kills}/${t.kills}`, 'trade_rate') : '',
    has(t.traded_death_rate) ? cell(pct(t.traded_death_rate), '拉枪占比',
        `${t.traded_deaths}/${t.deaths}`, 'traded_death_rate') : '',
  ].filter(Boolean);
  $('#pgRow').innerHTML = cells.join('');
}

/* 阵营切换：单击循环 */
const SIDE_ORDER = ['', 'CT', 'T'];
function updateSideSel() {
  // 两处分边控件（平均 / 能力画像）共用同一个 SIDE，必须一起点亮
  ['#sideSel', '#abSide'].forEach(sel =>
    $$(sel + ' span[data-side]').forEach(s =>
      s.classList.toggle('on', (s.dataset.side || '') === SIDE)));
}
$('#sideSel').onclick = () => {
  SIDE = SIDE_ORDER[(SIDE_ORDER.indexOf(SIDE) + 1) % SIDE_ORDER.length];
  updateSideSel();
  renderAll();
};

/* 能力画像标题右侧的分边切换：跟「平均」那套共用全局 SIDE，
   点哪个都会同步另一处高亮，全页一起重渲染。 */
const AB_SIDE_EL = $('#abSide');
if (AB_SIDE_EL) {
  AB_SIDE_EL.onclick = () => {
    SIDE = SIDE_ORDER[(SIDE_ORDER.indexOf(SIDE) + 1) % SIDE_ORDER.length];
    updateSideSel();
    renderAll();
  };
}
/* ================= 武器：‹ 名字 › 切换 + 大卡 ================= */
let WIDX = 0;
function wlist() {
  // detail.weapons 覆盖「所有开火过的武器」（含没击杀的道具/刀），
  // 页面上只轮播有击杀的，否则会切到一堆 0；CSV 仍导出全部。
  const all = (S.overview.detail || {}).weapons || [];
  return [...all].filter(x => (x.n || 0) > 0).sort((a, b) => (b.n || 0) - (a.n || 0));
}
function rWeapons() {
  const t = S.overview.total;
  const list = wlist();
  if (!list.length) {
    $('#wName').textContent = '—';
    $('#wBig').innerHTML = '<div class="nil">还没有武器击杀记录</div>';
    $('#wShoot').innerHTML = '';
    $('#wSpecial').innerHTML = '';
    return;
  }
  WIDX = Math.max(0, Math.min(WIDX, list.length - 1));
  const x = list[WIDX];
  const name = String(x.w || '').replace(/^weapon_/, '');
  const rd = t.rounds || 1;

  $('#wName').textContent = wcn(name);
  $('#wCount').textContent = `${WIDX + 1} / ${list.length}`;

  const perRound = (x.n / rd).toFixed(2);
  const isSniper = ['awp', 'ssg08', 'scar20', 'g3sg1'].includes(name);
  const stats = [
    ['命中率', x.acc == null ? '—' : x.acc + '%', `${x.hits || 0}/${x.fires || 0}`, 'fire_accuracy'],
    ['局均击杀', perRound, '每回合', ''],
    ['爆头率', x.n ? Math.round((x.hs || 0) / x.n * 100) + '%' : '—', `${x.hs || 0} 次`, 'hs_pct'],
    ['超阈值速度开火率', x.imp_rate == null ? '—' : x.imp_rate + '%',
      `${x.imprecise || 0} 次`, 'imprecise_rate'],
    ['穿墙击杀', x.pen || 0, '穿透', 'penetrated_kills'],
    ['穿烟击杀', x.smoke || 0, '混烟', 'thrusmoke_kills'],
    ['跳跃击杀', x.jump || 0, '空中', ''],
  ];
  if (isSniper) {
    stats.push(['盲狙击杀', x.noscope || 0, '不开镜', 'noscope_kills']);
  }

  $('#wBig').innerHTML = `
    <div class="art" style="background-image:url('/icons/${name}.svg')"></div>
    <div class="main">
      <div class="nm">${esc(wcn(name))} · 击杀</div>
      <div class="kills">${x.n}</div>
      <div class="sub">${x.fires || 0} 次开火 · ${x.hits || 0} 次命中</div>
    </div>
    <div class="stats" style="grid-template-columns:repeat(${stats.length},1fr)">
      ${stats.map(([k, v, sub, mk]) => `<div class="s">
        <div class="k"${mk ? ` data-m="${mk}"` : ''}>${k}</div>
        <div class="v">${v}</div><div class="x">${sub}</div></div>`).join('')}
    </div>`;

  $('#wShoot').innerHTML = [
    t.hs_pct == null ? '' : kpi(t.hs_pct + '%', '爆头率', `${nth(t.hs)} 次`, 'hs_pct'),
    t.fire_accuracy == null ? '' : kpi(pct(t.fire_accuracy), '开火命中率',
        `${nth(t.hit_count)}/${nth(t.fire_count)}`, 'fire_accuracy'),
    t.stop_rate == null ? '' : kpi(pct(t.stop_rate), '阈值内低速开火率',
        `${nth(t.stop_shots)}/${nth(t.gun_fire_count)} 次枪械开火`, 'stop_rate'),
    t.imprecise_rate == null ? '' : kpi(pct(t.imprecise_rate), '超阈值速度开火率',
        `${nth(t.imprecise_shots)} 次`, 'imprecise_rate'),
    t.per_fire == null ? '' : kpi(num(t.per_fire, 1), '开火 / 回合', '', 'per_fire'),
  ].join('');

  $('#wSpecial').innerHTML = [
    kpi(t.penetrated_kills ?? 0, '穿墙击杀', `${num(t.penetrated_pct, 1)}% 占比`, 'penetrated_kills'),
    kpi(t.thrusmoke_kills ?? 0, '穿烟击杀', `${num(t.thrusmoke_pct, 1)}% 占比`, 'thrusmoke_kills'),
    kpi(t.noscope_kills ?? 0, '盲狙击杀', 'AWP / SSG08 / G3SG1 / SCAR-20', 'noscope_kills'),
  ].join('');
}
function wStep(d) {
  const list = wlist();
  if (!list.length) return;
  WIDX = (WIDX + d + list.length) % list.length;
  rWeapons();
}
const _wPrev = $('#wPrev'), _wNext = $('#wNext');
if (_wPrev) _wPrev.onclick = () => wStep(-1);
if (_wNext) _wNext.onclick = () => wStep(1);

/* ================= 回合事件 ================= */
function rEvents() {
  const t = S.overview.total, e = S.overview.econ || {};
  const rate = (a, b) => (b ? Math.round(a / b * 100) + '%' : '—');

  $('#evOpen').innerHTML = [
    kpi(t.fk, '首杀', '', 'opening_kills'),
    kpi(rate(t.fk, t.rounds), '首杀率', `${t.rounds} 回合`, 'opening_rate'),
  ].join('');
  $('#evTrade').innerHTML = [
    kpi(t.trade_kills ?? 0, '补枪成功', `${num(t.trade_rate, 1)}%`, 'trade_rate'),
    kpi(t.kills ?? 0, '击杀总数', '分母', 'kills'),
  ].join('');
  $('#evPulled').innerHTML = [
    kpi(t.traded_deaths ?? 0, '拉枪成功', `${num(t.traded_death_rate, 1)}%`, 'traded_death_rate'),
    kpi(t.deaths ?? 0, '死亡总数', '分母', 'deaths'),
  ].join('');
}

/* ================= 多杀与残局 ================= */
function rClutch() {
  const cl = S.overview.clutch || {};
  const mk = cl.multi || {}, c = cl.clutch || {}, adv = cl.advantage || {};

  /* 多杀：回合率放大，2K~5K 一行 */
  const totalMulti = (mk.mk2 || 0) + (mk.mk3 || 0) + (mk.mk4 || 0) + (mk.mk5 || 0);
  $('#mkLead').innerHTML = `
    <div style="display:flex;align-items:baseline;gap:12px">
      <div style="font-size: 46px;font-weight:650;line-height:1;letter-spacing:-.02em;
        font-variant-numeric:tabular-nums">${pct(mk.rate)}</div>
      <div style="font-size: 13px;color:var(--dim)">
        <span data-m="multi_rate">多杀回合率</span> · ${totalMulti} 个多杀回合 / ${S.overview.total.rounds} 回合
      </div>
    </div>`;
  $('#mkRow').innerHTML = [
    kpi(mk.mk2 ?? 0, '2K', '双杀', 'mk2'),
    kpi(mk.mk3 ?? 0, '3K', '三杀', 'mk3'),
    kpi(mk.mk4 ?? 0, '4K', '四杀', 'mk4'),
    kpi(mk.mk5 ?? 0, '5K+', '五杀及以上', 'mk5'),
  ].join('');

  /* 残局：机会/胜/负/成功率/存活率/击杀/伤害 一行 */
  const clKills = c.kills ?? 0, clDmg = c.damage ?? 0;
  $('#clRow').innerHTML = [
    kpi(c.played ?? 0, '残局机会', '', 'clutch_played'),
    kpi(c.won ?? 0, '获胜', '', 'clutch_won'),
    kpi(c.lost ?? 0, '失败', '', ''),
    kpi(pct(c.pct), '成功率', `${c.won ?? 0}/${c.played ?? 0}`, 'clutch_pct'),
    kpi(pct(c.alive_pct), '残局存活率', `${c.alive ?? 0}/${c.played ?? 0}`, 'clutch_survive'),
    kpi(clKills, '残局击杀', '窗口内', 'clutch_kills'),
    kpi(nth(clDmg), '残局伤害', '窗口内', 'clutch_dmg'),
  ].join('');

  /* 1vX 明细表：局数 + 胜率 + 击杀 + 保枪 */
  const sizes = Object.entries(c.by_size || {}).sort((a, b) => a[0].localeCompare(b[0]));
  $('#clSizes').innerHTML = sizes.length ? table([
    { t: '局面', f: 'k' },
    { t: '局数', f: 'played', num: 1 },
    { t: '胜', f: 'won', num: 1 },
    { t: '负', f: 'lost', num: 1 },
    { t: '胜率', num: 1, get: r => {
        const p = r.played ? Math.round(r.won / r.played * 100) : 0;
        return `<span class="${p >= 50 ? 'w' : 'l'}">${p}%</span>`;
      } },
    { t: '击杀', f: 'kills', num: 1 },
    { t: '保枪', f: 'saves', num: 1 },
    { t: '保枪率', num: 1, get: r => {
        const p = r.played ? Math.round((r.saves || 0) / r.played * 100) : 0;
        return p + '%';
      } },
  ], sizes.map(([k, v]) => ({ k, ...v }))) : '<div class="nil">没有残局记录</div>';

  /* 保枪：次数 / 总额 / 平均 / 保枪率 */
  $('#clSave').innerHTML = [
    kpi(c.save_rounds ?? 0, '保枪次数', '残局失败但活下来', 'save_count'),
    kpi(pct(c.save_pct), '保枪率', `${c.save_rounds ?? 0}/${c.played ?? 0}`, 'save_rate'),
    kpi(c.save_value ? '$' + nth(c.save_value) : '—', '保留装备总额', '', 'save_value'),
    kpi(c.save_avg ? '$' + nth(c.save_avg) : '—', '平均每次保枪', '', 'save_avg'),
  ].join('');

  /* 人数优势：全部用比率 */
  const totalRounds = S.overview.total.rounds || 1;
  const advRate = adv.first_adv ? Math.round(adv.first_adv / totalRounds * 100) : null;
  const cbRate = adv.first_adv ? Math.round((adv.comeback ?? 0) / adv.first_adv * 100) : null;
  $('#advRow').innerHTML = [
    kpi(pct(advRate), '先形成人优势', `${adv.first_adv ?? 0}/${totalRounds} 回合`, 'adv_first'),
    kpi(pct(adv.first_adv_pct), '优势转胜率', `${adv.first_adv_win ?? 0}/${adv.first_adv ?? 0}`, 'adv_win'),
    kpi(pct(cbRate), '劣势翻盘率', `${adv.comeback ?? 0}/${adv.first_adv ?? 0}`, 'adv_comeback'),
  ].join('');
}

/* ================= 回合结束原因：环形图 ================= */
/* 图标用 CS 官方 UI 里的单色 SVG（不是 emoji） */
const REASON_META = {
  target_bombed: { cn: '炸弹爆炸', side: 'T', icon: 'bomb.svg' },
  bomb_defused: { cn: '拆包成功', side: 'CT', icon: 'defuser.svg' },
  terrorists_win: { cn: '全歼 CT', side: 'T', icon: 'icon-death.svg' },
  ct_win: { cn: '全歼 T', side: 'CT', icon: 'icon-death.svg' },
  target_saved: { cn: '时间耗尽', side: 'CT', icon: 'clock.svg' },
  ct_eliminated: { cn: 'CT 被全歼', side: 'T', icon: 'icon-death.svg' },
  t_eliminated: { cn: 'T 被全歼', side: 'CT', icon: 'icon-death.svg' },
  round_draw: { cn: '平局', side: '', icon: 'clock.svg' },
};
const SIDE_COLOR = { CT: '#5b9bd5', T: '#d9924a', '': '#7a7a80' };
const SIDE_COLOR_DIM = { CT: 'rgba(91,155,213,.55)', T: 'rgba(217,146,74,.55)', '': 'rgba(122,122,128,.5)' };

function polar(cx, cy, rad, a) {
  return [cx + rad * Math.cos(a), cy + rad * Math.sin(a)];
}

function arcPath(cx, cy, R, r, a0, a1) {
  const big = (a1 - a0) > Math.PI ? 1 : 0;
  const [x0, y0] = polar(cx, cy, R, a0), [x1, y1] = polar(cx, cy, R, a1);
  const [x2, y2] = polar(cx, cy, r, a1), [x3, y3] = polar(cx, cy, r, a0);
  return `M${x0.toFixed(2)},${y0.toFixed(2)} A${R},${R} 0 ${big} 1 ${x1.toFixed(2)},${y1.toFixed(2)} `
    + `L${x2.toFixed(2)},${y2.toFixed(2)} A${r},${r} 0 ${big} 0 ${x3.toFixed(2)},${y3.toFixed(2)} Z`;
}

function rReason() {
  const raw = (S.overview.econ || {}).reasons || [];
  const rows = raw.map(x => {
    const k = String(x.r || '');
    const meta = REASON_META[k] || { cn: k.replace(/_/g, ' '), side: '', icon: 'clock.svg' };
    return { key: k, cn: meta.cn, side: meta.side, icon: meta.icon, n: x.n ?? 0 };
  }).filter(x => x.n > 0).sort((a, b) => b.n - a.n);

  const total = rows.reduce((a, b) => a + b.n, 0) || 1;
  const ct = rows.filter(r => r.side === 'CT').reduce((a, b) => a + b.n, 0);
  const t = rows.filter(r => r.side === 'T').reduce((a, b) => a + b.n, 0);

  if (!rows.length) {
    $('#rsDonut').innerHTML = '<div class="nil">—</div>';
    $('#evReason').innerHTML = '';
    return;
  }

  /* 环形：大一点 + 段间留缝 + 整圈慢转 + 投影 */
  const R = 104, r = 66, C = 118;
  const GAP = 0.045;                       // 每段两端各留 0.045 弧度
  let acc = 0;
  const segs = rows.map(x => {
    const a0 = (acc / total) * Math.PI * 2 - Math.PI / 2;
    acc += x.n;
    const a1 = (acc / total) * Math.PI * 2 - Math.PI / 2;
    const half = Math.min(GAP, (a1 - a0) / 3);
    return { ...x, a0: a0 + half, a1: a1 - half, d: arcPath(C, C, R, r, a0 + half, a1 - half) };
  });

  /* 图标贴在外圈（环带中线），尺寸跟着段大小走 */
  const icons = segs.filter(s => (s.a1 - s.a0) > 0.14).map(s => {
    const mid = (s.a0 + s.a1) / 2, rr = (R + r) / 2;
    const [ix, iy] = polar(C, C, rr, mid);
    const sz = Math.min(26, Math.max(15, (s.a1 - s.a0) * 13));
    return `<image href="/icons/${s.icon}" x="${(ix - sz / 2).toFixed(1)}"
      y="${(iy - sz / 2).toFixed(1)}" width="${sz}" height="${sz}"
      style="filter:brightness(0) invert(1);opacity:.92">
      </image>`;
  }).join('');

  $('#rsDonut').innerHTML = `
    <div class="ring">
      <svg width="${C * 2}" height="${C * 2}" viewBox="0 0 ${C * 2} ${C * 2}" class="donut-svg">
        <defs>
          <filter id="dsh" x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow dx="0" dy="3" stdDeviation="7" flood-color="#000" flood-opacity=".55"/>
          </filter>
        </defs>
        <g class="spin" style="transform-origin:${C}px ${C}px">
          ${segs.map(s => `<path d="${s.d}" fill="${SIDE_COLOR[s.side]}" filter="url(#dsh)">
            <title>${esc(s.cn)} · ${s.n} 回合 · ${(s.n / total * 100).toFixed(1)}%</title></path>`).join('')}
          ${icons}
        </g>
        <circle cx="${C}" cy="${C}" r="${r - 3}" fill="rgba(0,0,0,.28)"/>
        <text x="${C}" y="${C - 5}" text-anchor="middle" fill="#eee"
          font-size="34" font-weight="650" font-family="inherit">${total}</text>
        <text x="${C}" y="${C + 17}" text-anchor="middle" fill="#8a8a90"
          font-size="13" font-family="inherit">回合</text>
      </svg>
    </div>
    <div class="legend">
      <div class="li" style="margin-bottom:3px">
        <span class="dot" style="background:${SIDE_COLOR.CT}"></span>
        <span>CT 获胜</span><b style="font-variant-numeric:tabular-nums">${ct}</b>
        <span class="n">${(ct / total * 100).toFixed(1)}%</span>
      </div>
      <div class="li" style="margin-bottom:10px">
        <span class="dot" style="background:${SIDE_COLOR.T}"></span>
        <span>T 获胜</span><b style="font-variant-numeric:tabular-nums">${t}</b>
        <span class="n">${(t / total * 100).toFixed(1)}%</span>
      </div>
      ${rows.map(x => `<div class="li">
        <span class="dot" style="background:${SIDE_COLOR[x.side]}"></span>
        <span>${esc(x.cn)}</span>
        <span class="n">${x.n}</span>
        <span class="n">${(x.n / total * 100).toFixed(1)}%</span>
      </div>`).join('')}
    </div>`;

  /* 明细表：去掉末尾那条没有表头的迷你条（看过两次「意义不明的条」了） */
  $('#evReason').innerHTML = table([
    { t: '结束原因', get: x => `<img src="/icons/${x.icon}" class="ric"
        style="filter:brightness(0) invert(1);opacity:.8" alt=""> ${esc(x.cn)}` },
    { t: '归属', num: 1, get: x => x.side
        ? `<span style="color:${SIDE_COLOR[x.side]}">${x.side}</span>` : '—' },
    { t: '回合', f: 'n', num: 1 },
    { t: '占比', num: 1, get: x => (x.n / total * 100).toFixed(1) + '%' },
  ], rows);
}

if ($('#rqBtn')) $('#rqBtn').onclick = () => {
  const n = $('#rqNote');
  if (n) n.style.display = n.style.display === 'none' ? 'block' : 'none';
};
if ($('#mxBtn')) $('#mxBtn').onclick = () => {
  const n = $('#mxNote');
  if (n) n.style.display = n.style.display === 'none' ? 'block' : 'none';
};

/* ================= 地图数据 ================= */
/* ================= 地图（图池 + 逐图数据合并成一张表） ================= */
async function rMaps() {
  let pool = [];
  try { pool = (await api('/api/v1/map_pool')).maps || []; } catch (e) { pool = []; }
  const byMap = {};
  (S.overview?.by_map || []).forEach(m => { byMap[m.map] = m; });
  // 两张表的数据来源不同（图池来自 map_pool，逐图指标来自 overview.by_map），取并集
  const names = [...new Set([...pool.map(p => p.map), ...Object.keys(byMap)])]
    .sort((a, b) => {
      const pa = (pool.find(x => x.map === a) || {}).played ?? (byMap[a]?.matches || 0);
      const pb = (pool.find(x => x.map === b) || {}).played ?? (byMap[b]?.matches || 0);
      return pb - pa || a.localeCompare(b);
    });
  const rows = names.map(name => {
    const p = pool.find(x => x.map === name) || {};
    const m = byMap[name] || {};
    const played = p.played ?? m.matches ?? 0;
    const rec = (p.win != null && p.loss != null) ? `${p.win}胜 ${p.loss}负` : '—';
    /* 环比 = 近段胜率 − 前段胜率（百分点）。这张图的对局按时间排序后从中间等分，
       后一半减前一半；不足 4 场不给结论。悬停能看到具体是哪两段在比。 */
    let delta = '<span class="m" title="这张图的已判定对局不足 4 场，切不出前后两段，所以不给环比">—</span>';
    if (p.delta != null) {
      const seg = `前段 ${p.prev_n ?? '?'} 场 ${p.prev_wr ?? '?'}% → 近段 ${p.recent_n ?? '?'} 场 ${p.recent_wr ?? '?'}%`;
      if (p.delta === 0) delta = `<span class="m" title="${seg}（胜率持平）">持平</span>`;
      else delta = `<span class="${p.delta > 0 ? 'w' : 'l'}" title="${seg}　→　${p.delta > 0 ? '上升' : '下降'} ${Math.abs(p.delta)} 个百分点">` +
                   `${p.delta > 0 ? '▲ +' : '▼ '}${p.delta}pt</span>`;
    }
    const wr = p.win_rate ?? m.win_rate;
    return {
      map: esc(mapCn(name)),
      played: played,
      rec: `<span class="m">${rec}</span>`,
      wr: wr == null ? '<span class="m">—</span>'
                     : `<span class="${wr >= 50 ? 'w' : 'l'}">${wr}%</span>`,
      delta: delta,
      rounds: m.rounds ?? '—',
      adr: num(m.adr, 1), kast: num(m.kast, 1), rating: num(m.rating, 2),
      kd: num(m.kd, 2),
      spent: m.spent_avg ? '$' + nth(m.spent_avg) : '—',
    };
  });
  const el = $('#mpTable');
  if (!el) return;
  el.innerHTML = table([
    { t: '地图', f: 'map' },
    { t: '场次', f: 'played', num: 1 },
    { t: '战绩', f: 'rec', num: 1 },
    { t: '胜率', f: 'wr', num: 1 },
    { t: '环比', f: 'delta', num: 1,
      title: '近期进退。把这张图的对局按时间排序后从中间等分：近段胜率 − 前段胜率 = 环比（单位 pt，百分点）。'
           + '例如前段 33.3% → 近段 66.7% 记作 +33.4pt。总数少于 4 场不给结论。'
           + '注意它只看胜负，不含 ADR/Rating 这类个人表现，也不一定等于「近期」——切的是时间序前后两半。' },
    { t: '回合', f: 'rounds', num: 1, k: 'rounds_played' },
    { t: 'ADR', f: 'adr', num: 1, k: 'adr' },
    { t: 'KAST', f: 'kast', num: 1, k: 'kast' },
    { t: 'Rating', f: 'rating', num: 1, k: 'rating' },
    { t: 'K/D', f: 'kd', num: 1, k: 'kd' },
    { t: '每回合花费', f: 'spent', num: 1, k: 'spent_avg' },
  ], rows);
}

/* ================= 经济 ================= */
/* 花费构成：低饱和但可区分的六色（ART-SPEC 限制高饱和色数量，
   这里靠明度+色相差异区分，不用荧光色） */
const MIX_COLOR = {
  rifle: '#6f9fd8', sniper: '#c47ab0', smg: '#5f7fa8', shotgun: '#4a5a70',
  armor: '#8f8f96', util: '#d8a83c', pistol: '#a87a9c', kit: '#4a9a8a', misc: '#3f3f45',
};
const MIX_NAME = {
  rifle: '步枪', sniper: '狙击枪', smg: '冲锋枪', shotgun: '霰弹/机枪',
  armor: '甲', util: '道具', pistol: '手枪', kit: '钳子', misc: '其他',
};
function mixRow(side, arr) {
  if (!arr || !arr.length) return '';
  const tot = arr.reduce((a, b) => a + (b.cost || 0), 0) || 1;
  const bar = arr.map(x =>
    `<i style="flex:${(x.cost / tot).toFixed(4)} 1 0;background:${MIX_COLOR[x.cat] || '#555'}"></i>`
  ).join('');
  const leg = arr.map(x =>
    `<span><em style="background:${MIX_COLOR[x.cat] || '#555'}"></em>${MIX_NAME[x.cat] || x.cat}
     <u>${x.pct}%</u></span>`).join('');
  return `<div class="mixRow">
    <div class="mixHead">
      <div class="side">${side}<b>$${nth(Math.round(tot))}</b></div>
      <div class="mixLeg">${leg}</div>
    </div>
    <div class="mixBar" title="${side} 共 $${nth(Math.round(tot))}">${bar}</div>
  </div>`;
}

function rEcon() {
  const t = S.overview.total, e = S.overview.econ || {};
  const se = e.save_economy || {};
  $('#ecHero').innerHTML = [
    kpi('$' + nth(t.spent), '总支出', '', 'spent'),
    kpi('$' + nth(t.spent_avg), '每回合平均支出', '', 'spent_avg'),
    kpi('$' + nth(t.equip_value), '每回合装备价值', '', 'equip_value'),
    kpi('$' + nth(t.equip_round_start), '回合初继承装备', '', 'equip_round_start'),
    kpi(se.rounds == null ? '—' : se.rounds, '保经济次数',
        se.lost_rounds ? `败局 ${se.lost_rounds} 回合` : '', 'save_economy'),
    kpi(se.pct == null ? '—' : se.pct + '%', '保经济率',
        se.rounds == null ? '' : `${se.rounds}/${se.lost_rounds}`, 'save_econ_pct'),
    kpi(se.value ? '$' + nth(se.value) : '—', '保留装备总额', '', 'save_econ_value'),
    kpi(se.avg ? '$' + nth(se.avg) : '—', '平均每次保留', '', 'save_econ_avg'),
  ].join('');

  /* 花费构成：CT / T 各一条 100% 堆叠条，图例在右侧 */
  const mix = e.spend_mix || {};
  const mixHtml = [mixRow('CT', mix.CT), mixRow('T', mix.T)].filter(Boolean).join('');
  if ($('#ecMix')) {
    $('#ecMix').innerHTML = mixHtml || '<div class="nil">暂无花费构成数据（需重解析）</div>';
  }

  const buy = e.buy || [];
  const LABEL = { full: '全买', half: '半买', force: '强起', eco: 'ECO', pistol: '手枪局' };
  $('#ecBuy').innerHTML = buy.length ? table([
    { t: '类型', get: r => esc(LABEL[r.type] || r.type || '—') },
    { t: '回合', num: 1, get: r => r.n ?? '—' },
    { t: '胜', num: 1, get: r => r.w ?? '—' },
    { t: '胜率', num: 1, get: r => {
        const wr = r.wr;
        return wr == null ? '—' : `<span class="${wr >= 50 ? 'w' : 'l'}">${wr}%</span>`;
      } },
    { t: '本人装备', num: 1, get: r => r.eq ? '$' + nth(r.eq) : '—' },
  ], buy) : '<div class="nil">暂无购买类型数据</div>';

  /* 逐场花费：只显示最近 20 场，避免场次多了拉成一长条；
     同一张地图会重复出现，标签带上日期区分 */
  const RECENT = 20;
  const tlAll = S.overview.timeline || [];
  const tl = tlAll.slice(-RECENT);
  const spendItems = tl.map(x => {
    const d = (x.played_at || '').slice(5, 10);
    return { lab: mapCn(x.map) + (d ? ' ' + d : ''), val: x.spent ?? 0 };
  });
  $('#ecSpend').innerHTML = spendItems.length
    ? bars(spendItems, { pct: true, money: true })
    : '<div class="nil">—</div>';
}

/* ================= 道具：五个独立面板 ================= */
const UTIL_ICON = {
  he: 'hegrenade', fire: 'molotov', smoke: 'smokegrenade',
  flash: 'flashbang', decoy: 'decoy',
};
const UTIL_ORDER = ['he', 'fire', 'smoke', 'flash', 'decoy'];

function rUtil() {
  const u = S.overview.utility || {};
  const cards = UTIL_ORDER.map(k => {
    const d = u[k] || {};
    const rows = [];

    /* 每张卡片第一项都必须是核心指标（统一 21px），否则会出现「有的卡片
       有个大数字、有的没有」的参差感。规则：第一行一定带 'big'。 */
    if (k === 'he' || k === 'fire') {
      /* 火雷：局均伤害是主指标（累计只反映打了多少场） */
      rows.push(['局均伤害', (d.dmg_per_round ?? 0).toFixed(2), 'big', 'util_dmg_per_round']);
      rows.push(['每颗平均伤害', d.dmg_per_use == null ? '—' : d.dmg_per_use, '', 'util_dmg_per_use']);
      rows.push(['有效投掷', nth(d.used ?? 0), '', 'util_used']);
      rows.push(['命中次数', nth(d.hits ?? 0), '', 'util_hits']);
    } else if (k === 'flash') {
      /* 闪光：每人次平均致盲才是「单个人瞎多久」，不会被多杀放大 */
      rows.push(['每人次平均致盲', d.per_hit == null ? '—' : d.per_hit + ' 秒', 'big', 'flash_per_hit']);
      rows.push(['每颗闪到几人', d.hits_per_throw == null ? '—' : d.hits_per_throw + ' 人', '', 'flash_hits_per_throw']);
      rows.push(['生效闪光', nth(d.effective ?? 0), '', 'flash_effective']);
      rows.push(['闪光效率', d.eff_pct == null ? '—' : d.eff_pct + '%', '', 'flash_eff']);
      rows.push(['致盲总时长', (d.duration ?? 0).toFixed(1) + ' 秒', '', 'flash_duration']);
    } else {
      /* 烟雾 / 诱饵：没有伤害和致盲可看，投出数就是核心 */
      rows.push(['投出', nth(d.throw ?? 0), 'big', 'grenade_throw']);
    }

    rows.push(['购买', nth(d.buy ?? 0), '', 'grenade_buy']);
    rows.push(['捡起', nth(d.pickup ?? 0), '', 'grenade_pickup']);
    /* 投出：来自引爆事件的投掷者（demoparser2），买 + 捡的上限内
       买了死在手里的不算，所以这个数比「购买 + 捡起」小是正常的 */
    if (k === 'he' || k === 'fire' || k === 'flash') {
      rows.push(['投出', nth(d.throw ?? 0), '', 'grenade_throw']);
    }

    return `<div class="ucard">
      <div class="art" style="background-image:url('/icons/${UTIL_ICON[k]}.svg')"></div>
      <div class="un">${esc(d.name || k)}</div>
      ${rows.map(([lab, val, cls, mk]) =>
        `<div class="ur${cls ? ' ' + cls : ''}"><span class="k">${mk ? M(mk, lab) : esc(lab)}</span>
         <span class="v">${val}</span></div>`).join('')}
    </div>`;
  }).join('');

  $('#utGrid').innerHTML = cards || '<div class="nil">没有道具数据</div>';
}

/* ================= 受闪与受道具伤害 ================= */
let RECV_SIDE = 'all';
function rReceived() {
  const r = (S.overview && S.overview.received) || {};
  const f = (r.flash || {})[RECV_SIDE] || {};
  const u = (r.util_taken || {})[RECV_SIDE] || {};
  const box = $('#recvKpis');
  if (!box) return;
  if (r.error) { box.innerHTML = `<div class="nil">${esc(r.error)}</div>`; return; }
  // 第一行：闪光弹。被敌方闪/队友闪挪到「被闪次数」的副位，
  // 主数值位让给「平均每次被闪白多久」——比累计时长更能说明挨打的强度。
  const avgSec = f.avg_duration == null ? '—' : `${f.avg_duration} 秒/次`;
  const cumSec = f.duration == null ? '—' : `${f.duration.toFixed(1)} 秒`;
  box.innerHTML = [
    kpi(f.count ?? 0, '被闪次数',
        `被敌方闪 ${f.by_enemy ?? 0} · 队友闪 ${f.by_teammate ?? 0}`),
    kpi(avgSec, '被致盲时长', `累计 ${cumSec}`),
    kpi(f.per_round ?? '—', '每回合平均被闪'),
    kpi(f.death_pct == null ? '—' : `${f.death_pct}%`, '被闪白死亡率',
        `阵亡 ${f.deaths ?? 0} 次`),
  ].join('');
  // 第二行：道具伤害
  const box2 = $('#recvKpis2');
  if (box2) {
    box2.innerHTML = [
      kpi(u.total ?? 0, '吃到道具伤害', `每回合平均 ${u.per_round ?? '—'}`),
      kpi(u.he ?? 0, '吃手雷'),
      kpi(u.fire ?? 0, '吃燃烧'),
    ].join('');
  }
  bindRecvSide();     // onclick 直接赋值，重复调用不会叠加
}
function bindRecvSide() {
  const el = $('#recvSide');
  if (!el) return;
  el.querySelectorAll('[data-s]').forEach(sp => {
    sp.onclick = () => {
      RECV_SIDE = sp.dataset.s;
      el.querySelectorAll('[data-s]').forEach(x => x.classList.toggle('on', x === sp));
      rReceived();
    };
  });
}

/* ================= 图池 ================= */
$$('#anchors a').forEach(a => {
  a.onclick = () => {
    const el = document.getElementById(a.dataset.s);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
});
const io = new IntersectionObserver(es => {
  es.forEach(e => {
    if (e.isIntersecting)
      $$('#anchors a').forEach(a => a.classList.toggle('on', a.dataset.s === e.target.id));
  });
}, { rootMargin: '-110px 0px -70% 0px' });
$$('.sec').forEach(s => io.observe(s));

/* ================= 外观 ================= */
function hexToTint(h) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(h || '').trim());
  if (!m) return '6,6,7';
  const v = parseInt(m[1], 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255].join(',');
}
function tintToHex(t) {
  const p = String(t || '6,6,7').split(',').map(n => Math.max(0, Math.min(255, parseInt(n, 10) || 0)));
  return '#' + p.map(n => n.toString(16).padStart(2, '0')).join('');
}
function applyLook() {
  const st = S.settings || {};
  const tint = st.theme_tint || '6,6,7';
  const rgb = String(tint).split(',').map(n => Math.max(0, Math.min(255, parseInt(n, 10) || 0)));
  document.documentElement.style.setProperty('--tint', tint);
  const lum = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
  document.documentElement.dataset.theme = lum < 0.46 ? 'dark' : 'light';
  const smokeOn = st.fx_smoke === undefined ? true : Number(st.fx_smoke) !== 0;
  const cv = $('#smoke');
  if (cv) cv.style.display = smokeOn ? '' : 'none';
  if (!smokeOn && typeof window.__stopSmoke === 'function') window.__stopSmoke();
  const tipOn = st.fx_tip === undefined ? true : Number(st.fx_tip) !== 0;
  document.body.classList.toggle('nott', !tipOn);
  if (!tipOn) hideTip();
}

/* ================= 操作 ================= */
async function post(url, body) {
  return await api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}) });
}
function hint(msg, ok) {
  const h = $('#opHint'); if (!h) return;
  h.className = 'hint' + (ok ? ' ok' : '');
  h.textContent = msg;
}

/* 顶栏进度条：解析/重解析都走这里，文字 + 百分比 */
/* 顶栏那条进度换成全局进度带（jobs-bar.js + /api/jobs）。
   这个函数保留成空实现，只为不动各处调用点。 */
function jobUI() {}

async function pollJob() {
  const t = setInterval(async () => {
    try {
      const s = await api('/api/state');
      S.job = s.job;
      jobUI(s.job);
      if (s.job && s.job.running) {
        hint(`分析中 ${s.job.done}/${s.job.total}：${s.job.current || ''}`);
      } else {
        clearInterval(t);
        hint('分析完成', true);
        load();
      }
    } catch (e) { clearInterval(t); }
  }, 1200);
}
/* 导出：一份自包含 CSV（注释头带「给 AI 的指令」与字段口径 + 汇总行 + 逐场明细），
   生成到数据目录的 exports/ 并打开文件夹。 */
const exportAll = async () => {
  hint('正在生成…');
  let r = null;
  try {
    r = await post('/api/export', {});
  } catch (e) {
    hint('导出失败：' + String(e), false);
    return;
  }
  if (r && r.ok) {
    const kb = r.size ? (r.size / 1024).toFixed(0) + ' KB' : '';
    hint('已生成 ' + (r.file || 'CSV') + (kb ? '（' + kb + '）' : ''), true);
  } else {
    hint((r && r.error) || '导出失败', false);
  }
};
if ($('#btnExport')) $('#btnExport').onclick = exportAll;

/* 数据操作（在设置弹层里） */
if ($('#btnScan')) $('#btnScan').onclick = async () => {
  hint('扫描中…');
  const r = await post('/api/scan');
  hint(r.ok ? `扫描完成，新增 ${r.added ?? 0}` : (r.error || '失败'), r.ok);
  load();
};
if ($('#btnAnalyze')) $('#btnAnalyze').onclick = async () => {
  hint('开始分析…');
  const r = await post('/api/analyze', {});
  if (r.ok) pollJob(); else hint(r.error || '失败');
};
/* 导出 AI 可读报告：Markdown（人看/AI 读）+ JSON（结构化），里面连字段口径都写了，
   可以直接丢给 AI 分析。后端生成到数据目录的 exports/ 并自动打开文件夹。 */
if ($('#btnReparse')) $('#btnReparse').onclick = async () => {
  if (!confirm('重新解析全部 demo？\n\n会清空现有分析结果并重新解析，每场约 8 秒。')) return;
  hint('重新解析中…');
  const r = await post('/api/reparse', {});
  if (r.ok) pollJob(); else hint(r.error || '失败');
};

/* ================= 设置 ================= */
function openSettings() {
  const st = S.settings || {}, p = S.paths || {};
  if ($('#setDemos')) $('#setDemos').value = st.demos_dir || p.demos || '';
  if ($('#setData')) $('#setData').value = st.data_dir || p.data || '';
  if ($('#setCs2')) $('#setCs2').value = st.cs2_dir || '';
  // AutoPull 增量包：装了才显示「已启用」，没装就显示怎么装。零配置。
  const gcOn = S.gc_pull === true;
  if ($('#steamOn')) $('#steamOn').hidden = !gcOn;
  if ($('#steamOff')) $('#steamOff').hidden = gcOn;
  if ($('#setSid')) $('#setSid').value = st.steamid || '';
  if ($('#setAutoPull')) $('#setAutoPull').value = st.auto_pull_hours ?? 0;
  if ($('#setSmoke')) $('#setSmoke').checked = st.fx_smoke === undefined ? true : Number(st.fx_smoke) !== 0;
  if ($('#setTip')) $('#setTip').checked = st.fx_tip === undefined ? true : Number(st.fx_tip) !== 0;
  if ($('#setTint')) $('#setTint').value = tintToHex(st.theme_tint || '6,6,7');
  if ($('#setMinM')) {
    const v = st.player_min_matches === undefined ? 1 : Number(st.player_min_matches);
    $('#setMinM').value = v;
    if ($('#setMinMV')) $('#setMinMV').textContent = v;
  }
  if ($('#ovDir')) $('#ovDir').textContent = p.overviews || '—';
  if ($('#ovCount')) $('#ovCount').textContent = p.overview_count || 0;
  const h = $('#setHint'); if (h) { h.className = 'hint'; h.textContent = ''; }
  $('#settings').classList.add('on');
}
if ($('#btnSettings')) $('#btnSettings').onclick = openSettings;
if ($('#setClose')) $('#setClose').onclick = () => $('#settings').classList.remove('on');
if ($('#settings')) $('#settings').addEventListener('click', e => {
  if (e.target.id === 'settings') $('#settings').classList.remove('on');
});
if ($('#setMinM')) $('#setMinM').oninput = e => {
  if ($('#setMinMV')) $('#setMinMV').textContent = e.target.value;
};
if ($('#setSave')) $('#setSave').onclick = async () => {
  const h = $('#setHint');
  const payload = {
    demos_dir: $('#setDemos').value,
    data_dir: $('#setData').value,
    cs2_dir: $('#setCs2').value,
    // 拉取改用 AutoPull 增量包后不再需要 api key / 认证码 / 分享码，
    // 这里也不再提交这三项，老配置原样留在 settings.json 里不动
    steamid: $('#setSid') ? $('#setSid').value : '',
    fx_smoke: $('#setSmoke').checked ? 1 : 0,
    fx_tip: $('#setTip').checked ? 1 : 0,
    theme_tint: hexToTint($('#setTint').value),
    player_min_matches: $('#setMinM') ? Number($('#setMinM').value) : 1,
  };
  // 这个输入框只在装了 AutoPull 时才存在；没有就别提交，免得把老值抹成 0
  if ($('#setAutoPull')) payload.auto_pull_hours = Number($('#setAutoPull').value || 0);
  const r = await post('/api/settings', payload);
  if (!r.ok) { h.className = 'hint'; h.textContent = r.error || '保存失败'; return; }
  h.className = 'hint ok';
  const bits = [];
  if (r.need_restart) bits.push('目录变更需重启程序生效');
  (r.notes || []).forEach(n => bits.push(n));
  h.textContent = bits.length ? '已保存 · ' + bits.join('；') : '已保存';
  load();
};

/* ================= 启动 ================= */
load();
