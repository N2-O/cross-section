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
  const r = el.getBoundingClientRect();
  let x = r.left + r.width / 2 - t.offsetWidth / 2;
  x = Math.max(10, Math.min(x, innerWidth - t.offsetWidth - 10));
  let y = r.top - t.offsetHeight - 10;
  if (y < 10) y = r.bottom + 10;
  t.style.left = x + 'px'; t.style.top = y + 'px';
}
document.addEventListener('mouseover', e => {
  if (document.body.classList.contains('nott')) return;
  const el = e.target.closest('[data-m]');
  if (el) showTip(el);
});
document.addEventListener('mouseout', e => { if (e.target.closest('[data-m]')) hideTip(); });
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
  const sel = $('#player');
  if (!sel) return;
  const ps = (S.players || []).slice().sort(
    (a, b) => (b.matches || 0) - (a.matches || 0) || String(a.name).localeCompare(String(b.name)));
  if (!ps.length) { sel.innerHTML = '<option>暂无玩家</option>'; return; }
  // 按场次分组：常一起打的放最上面，只同场过一次的单列一组。
  // 215 个人平铺在一个下拉里翻不动，分组后至少先看到熟人。
  const groups = [
    { label: '常一起打（3 场以上）', f: p => (p.matches || 0) >= 3 },
    { label: '同场过 2 场', f: p => (p.matches || 0) === 2 },
    { label: '只同场过 1 场', f: p => (p.matches || 0) < 2 },
  ];
  const one = p => `<option value="${p.steamid}"${p.is_me ? ' selected' : ''}>` +
    `${esc(p.name || '（无名字）')}（${p.excluded ? `${p.matches}/${p.matches + p.excluded}` : p.matches} 场）</option>`;
  const used = new Set();
  let html = '';
  for (const g of groups) {
    const list = ps.filter(p => !used.has(p.steamid) && g.f(p));
    if (!list.length) continue;
    list.forEach(p => used.add(p.steamid));
    html += `<optgroup label="${g.label} · ${list.length} 人">` +
      list.map(one).join('') + '</optgroup>';
  }
  const rest = ps.filter(p => !used.has(p.steamid));
  if (rest.length) html += `<optgroup label="其他">${rest.map(one).join('')}</optgroup>`;
  sel.innerHTML = html;
  sel.title = `共 ${ps.length} 名玩家；括号里是参与的场次。按场次分组，常一起打的在最上面`;
}
$('#player').onchange = async e => {
  // 不能 Number() —— SteamID64 超出 JS 安全整数范围，转数字会丢尾数
  // （76561199385933782 → 76561199385933780），后端查不到这个人就静默拒绝。
  const r = await api('/api/set_me', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ steamid: String(e.target.value) })
  });
  if (r && r.ok === false) {
    hint(r.error || '切换失败', false);
    return;
  }
  load();
};

/* ================= 总入口 ================= */
function renderAll() {
  if (!S.overview || S.overview.empty) {
    $$('.sec').forEach(el => {
      if (!el.querySelector('.nil'))
        el.insertAdjacentHTML('beforeend',
          '<div class="nil">还没有对局数据。打开「设置 → 数据操作」扫描 demo 目录并分析。</div>');
    });
    return;
  }
  const v = view();
  rOverview(v);
  rAvg(v);
  rWeapons();
  rEvents();
  rClutch();
  rReason();
  rMaps();
  rEcon();
  rUtil();
  rReceived();
  rPool();
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
  $$('#sideSel span[data-side]').forEach(s =>
    s.classList.toggle('on', (s.dataset.side || '') === SIDE));
}
$('#sideSel').onclick = () => {
  SIDE = SIDE_ORDER[(SIDE_ORDER.indexOf(SIDE) + 1) % SIDE_ORDER.length];
  renderAll();
};

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
function rMaps() {
  const bm = S.overview.by_map || [];
  const mx = Math.max(1, ...bm.map(x => x.matches || 0));
  $('#mpTable').innerHTML = table([
    { t: '地图', get: r => esc(mapCn(r.map)) },
    { t: '场次', num: 1, get: r => `${r.matches} ${minibar(r.matches, mx)}` },
    { t: '胜率', num: 1, get: r => `<span class="${r.win_rate >= 50 ? 'w' : 'l'}">${r.win_rate}%</span>` },
    { t: '回合', f: 'rounds', num: 1, k: 'rounds_played' },
    { t: 'ADR', get: r => num(r.adr, 1), num: 1, k: 'adr' },
    { t: 'KAST', get: r => num(r.kast, 1), num: 1, k: 'kast' },
    { t: 'Rating', get: r => num(r.rating, 2), num: 1, k: 'rating' },
    { t: 'K/D', get: r => num(r.kd, 2), num: 1, k: 'kd' },
    { t: '每回合花费', get: r => r.spent_avg ? '$' + nth(r.spent_avg) : '—', num: 1, k: 'spent_avg' },
  ], bm);
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
    { t: '人均装备', num: 1, get: r => r.eq ? '$' + nth(r.eq) : '—' },
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
async function rPool() {
  let pool = [];
  try { pool = (await api('/api/v1/map_pool')).maps || []; } catch (e) { pool = []; }
  const byMap = {};
  (S.overview?.by_map || []).forEach(m => { byMap[m.map] = m; });
  const rows = pool.map(p => {
    const m = byMap[p.map] || {};
    let delta = '<span class="m">—</span>';
    if (p.delta != null) {
      if (p.delta === 0) delta = '<span class="m">持平</span>';
      else delta = `<span class="${p.delta > 0 ? 'w' : 'l'}">${p.delta > 0 ? '▲ +' : '▼ '}${p.delta}pt</span>`;
    }
    return {
      map: esc(mapCn(p.map)), played: p.played, rec: `${p.win}胜 ${p.loss}负`,
      wr: `<span class="${p.win_rate == null ? 'm' : (p.win_rate >= 50 ? 'w' : 'l')}">${p.win_rate == null ? '—' : p.win_rate + '%'}</span>`,
      delta, adr: num(m.adr, 1), kast: num(m.kast, 1), rating: num(m.rating, 2),
    };
  });
  $('#poolTable').innerHTML = table([
    { t: '地图', f: 'map' },
    { t: '游玩', f: 'played', num: 1 },
    { t: '战绩', f: 'rec', num: 1 },
    { t: '胜率', f: 'wr', num: 1 },
    { t: '环比', f: 'delta', num: 1 },
    { t: 'ADR', f: 'adr', num: 1, k: 'adr' },
    { t: 'KAST', f: 'kast', num: 1, k: 'kast' },
    { t: 'Rating', f: 'rating', num: 1, k: 'rating' },
  ], rows);
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
function jobUI(j) {
  const el = $('#job');
  if (!el) return;
  if (j && j.running) {
    el.classList.add('on');
    const pct = j.total ? Math.round(j.done / j.total * 100) : 0;
    const nm = (j.current || '').replace(/\.dem$/i, '').slice(0, 24);
    $('#jobtext').textContent =
      `解析中 ${j.done}/${j.total} · ${pct}%${nm ? ' · ' + nm : ''}`;
    $('#progbar').style.width = pct + '%';
  } else {
    el.classList.remove('on');
  }
}

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
const exportCsv = () => { location.href = '/api/export/csv'; };
if ($('#btnExport')) $('#btnExport').onclick = exportCsv;

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
if ($('#btnRecompute')) $('#btnRecompute').onclick = async () => {
  hint('重算评分…');
  const r = await post('/api/recompute', {});
  hint(r.ok ? `已重算 ${r.rows} 行` : (r.error || '失败'), r.ok);
  load();
};
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
