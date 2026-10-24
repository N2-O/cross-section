/* Demo 与逐场记录页 —— 数据管理、demo 列表、逐场明细集中在这里 */
let S = { demos: [], overview: {}, players: [] };
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const num = (v, d = 0) => (v == null || v === '' ? '—' : Number(v).toFixed(d));
const nth = v => (v == null ? '—' : Number(v).toLocaleString('en-US'));

const MAP_CN = {
  de_dust2: '炙热沙城2', de_mirage: '荒漠迷城', de_inferno: '炼狱小镇',
  de_ancient: '远古遗迹', de_anubis: '阿努比斯', de_nuke: '核子危机',
  de_vertigo: '殒命大厦', de_overpass: '死亡游乐园', de_train: '列车停放站',
  de_office: '办公室', de_italy: '意大利小镇', de_cache: '死城之谜',
  de_cbble: '古堡激战', de_tuscan: '托斯卡纳',
};
const mapCn = m => MAP_CN[m] || String(m || '').replace(/^de_/, '');

async function api(path, opt) {
  const r = await fetch(path, opt);
  try { return await r.json(); }
  catch (e) {
    // 后端是老版本时接口不存在，404 返回的是 HTML，.json() 会炸。
    return { ok: false, http: r.status, error: `HTTP ${r.status} —— 后端可能还是旧版本，重启一下程序` };
  }
}
async function post(url, body) {
  return await api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}) });
}
function hint(msg, ok) {
  const h = $('#opHint'); if (!h) return;
  h.className = 'hint' + (ok ? ' ok' : '');
  h.textContent = msg;
}
function table(cols, rows) {
  if (!rows || !rows.length) return '<div class="nil">—</div>';
  const th = cols.map(c => `<th class="${c.num ? 'num' : ''}"${c.title ? ` title="${esc(c.title)}"` : ''}>${esc(c.t)}</th>`).join('');
  const tr = rows.map(r => '<tr>' + cols.map(c => {
    const v = c.get ? c.get(r) : r[c.f];
    return `<td class="${c.num ? 'num' : ''}">${v == null || v === '' ? '—' : v}</td>`;
  }).join('') + '</tr>').join('');
  return `<table class="tb"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
}
const minibar = (v, max) => {
  const w = max > 0 ? Math.round(Math.abs(v) / max * 100) : 0;
  return `<span class="mbtr"><i class="mb" style="width:${w}%"></i></span>`;
};

let _scanned = false;
async function load() {
  // 首次进页面先静默扫一遍 demo 目录——scan 只在程序启动时自动跑过，
  // 运行中新丢进目录的文件不会自己出现，得手动点「扫描目录」。
  if (!_scanned) {
    _scanned = true;
    try { await post('/api/scan', {}); } catch (e) { /* 扫描失败不影响列表 */ }
    // 同时确认后端是不是新版（覆盖代码后忘了重启，是这里最常见的坑）
    const probe = await api('/api/http_pull_progress');
    if (!probe || !('running' in probe)) {
      const box = $('#pullDiag');
      if (box) {
        box.hidden = false;
        box.innerHTML = '<div class="vd bad">后端还是旧版本（没有下载接口）' +
          '——把程序关掉重新启动一次，光刷新页面不生效。</div>';
      }
    }
  }
  S = await api('/api/state');
  const dv = $('#dver');
  if (dv) dv.textContent = S.version ? 'v' + S.version : 'v?（后端未重启）';
  // AutoPull 区域（按钮 + 分享码框）只在装了增量包时出现
  const apOn = S.gc_pull === true;
  if ($('#apRecent')) $('#apRecent').hidden = !apOn;
  if ($('#apPanel')) $('#apPanel').hidden = !apOn;
  renderPlayers();
  // 两个路径都显示：出问题时用户能直接找到 db 文件，不用猜
  const _dp = S.paths?.demos || '', _db = S.paths?.db || '';
  $('#demoPath').innerHTML =
    `demo 目录：${_dp}${_db ? `<br>数 据 库：${_db}` : ''}`;
  renderGames();
  jobUI(S.job);
  if (S.job && S.job.running) pollJob();
  rPullLast();
}

/** 上次拉取结果：自动检查跑过之后，这里能看到时间和新增场次 */
async function rPullLast() {
  const el = $('#pullLast');
  if (!el) return;
  let r = null;
  try { r = await api('/api/pull_result'); } catch (e) { return; }
  if (!r || r.ok === null || r.ok === undefined) { el.textContent = ''; return; }
  const t = r.t || r.time || '';
  if (r.status === 'offline') {
    el.textContent = `上次检查 ${t}：网络不通 —— ${r.error || '连不上 Steam API'}`;
    el.style.color = 'var(--bad)';
  } else if (r.status === 'error' || r.ok === false) {
    el.textContent = `上次检查 ${t}：${r.msg || '失败'}${r.error ? ' —— ' + r.error : ''}`;
    el.style.color = 'var(--bad)';
  } else if (r.status === 'empty' || !(r.added)) {
    el.textContent = `上次检查 ${t}：没有新比赛（已是最新的）`;
    el.style.color = '';
  } else {
    // 旧记录（升级前写的）只有 added/bat，没有 failed —— 一律按「新增 N 场」说，
    // 不再把 msg 里过时的「已生成 cs2_new_download.bat」显示出来
    const failed = Number(r.failed || 0);
    el.textContent = ('failed' in r)
      ? `上次检查 ${t}：已下载 ${r.added} 场` + (failed ? `，失败 ${failed} 场` : '')
      : `上次检查 ${t}：新增 ${r.added} 场`;
    el.style.color = 'var(--ok)';
  }
}

function renderPlayers() {
  PlayerSelect.render($('#player'), S.players);
}
PlayerSelect.bind($('#player'), (p, b) => post(p, b), async () => { await load(); });

/* 一张表管全部：demo 文件信息 + 该场统计 + 回放入口。
   关联键是 match_id（未分析的 demo 没有 match_id，统计列留 —） */
function renderGames() {
  const ds = S.demos || [];
  const tl = (S.overview || {}).timeline || [];
  const byMid = {};
  for (const t of tl) byMid[t.match_id] = t;

  /* 已分析在前，按时间倒序；未分析的后 */
  const rows = ds.map(d => ({ ...d, st: byMid[d.match_id] || null }))
    .sort((a, b) => (b.played_at || b.mtime || '').localeCompare(a.played_at || a.mtime || ''));

  const n_file = rows.filter(r => r.file_exists).length;
  const n_an = rows.filter(r => r.analyzed).length;
  $('#gameSub').textContent = `${rows.length} 场 · 已解析 ${n_an}`
    + (n_file < rows.length ? ` · 原始文件在 ${n_file}（其余已瘦身）` : '');
  if (!rows.length) {
    $('#gameTable').innerHTML = '<div class="nil">目录里还没有 .dem 文件</div>';
    return;
  }

  /* demos[] 没有 st 子对象，统计字段直接挂在 r 上（me_kills / me_adr / ...）。 */
  const hasRes = r => (r.rounds || 0) > 0;
  /* 比分与胜负：完全走客观口径（team_a_wins，从回合号 + winner 算，与「我」无关），
     再用 my_side（上半场阵营）判断我在哪一队：
        my_side='T'  → 我在 A 队（上半打 T 的那队）
        my_side='CT' → 我在 B 队
     这样即使 a_win 全 0（我在这场击杀记录里没出现、或没设 ID），也不会显示成 0:xx。 */
  const scoreParts = r => {
    const a = r.team_a_wins ?? 0, total = r.rounds || 0;
    return { a: a, b: total - a, total: total };
  };
  const resOf = r => {
    if (!hasRes(r)) return '—';
    const p = scoreParts(r);
    if (!r.my_side) {
      return `<span class="m" title="这场 demo 里没有你的记录（不是你打的，或你中途才进场）。本场 ${p.a}:${p.b}">无你</span>`;
    }
    const mine = r.my_side === 'T' ? p.a : p.b;
    const theirs = r.my_side === 'T' ? p.b : p.a;
    if (mine > theirs) return '<span class="w">胜</span>';
    if (mine === theirs) return '<span class="d">平</span>';
    return '<span class="l">负</span>';
  };
  const scoreOf = r => {
    if (!hasRes(r)) return '—';
    const p = scoreParts(r);
    const ot = p.total > 24 ? '<span class="ot">加时</span>' : '';
    if (!r.my_side) {
      /* 完全不知道我在哪边：给客观比分。A 队 = 上半打 T 的那队，
         不能拿「T 阵营胜 : CT 阵营胜」求和——换边后那是两支不同的队。 */
      return `<span class="m" title="这场 demo 里没有你的记录。比分按队伍算：先打 T 的队 ${p.a} : 先打 CT 的队 ${p.b}">${p.a}:${p.b}</span>${ot}`;
    }
    const mine = r.my_side === 'T' ? p.a : p.b;
    const theirs = r.my_side === 'T' ? p.b : p.a;
    return `${mine}:${theirs}${ot}`;
  };

  $('#gameTable').innerHTML = table([
    /* 最前面两盏灯：文件（原始 .dem 在不在）· 解析（有没有分析结果） */
    { t: '状态', num: 1, get: r => {
        const cur = (S.job && S.job.running) ? String(S.job.current || '') : '';
        const parsing = cur && cur === r.name && !r.analyzed && !r.error;
        const fileDot = r.file_exists
          ? '<i class="dot on" title="原始 .dem 文件在"></i>'
          : '<i class="dot off" title="原始 .dem 已删除（数据还在，但以后不能重新解析）"></i>';
        let parseDot;
        if (r.error) parseDot = `<i class="dot bad" title="解析失败：${esc(r.error)}"></i>`;
        else if (r.analyzed) parseDot = '<i class="dot on" title="已解析"></i>';
        else if (parsing) parseDot = '<i class="dot wait" title="正在解析…"></i>';
        else parseDot = '<i class="dot off" title="还没解析"></i>';
        return `<span class="lamps" title="左=原始文件　右=解析结果">${fileDot}${parseDot}</span>`;
    } },
    { t: '地图', get: r => `<div class="gmap" title="${esc(r.name)}">
        <div class="mn">${esc(r.map ? mapCn(r.map) : '—')}</div>
        <div class="fs">${r.size ? (r.size / 1048576).toFixed(0) + ' MB' : ''}</div>
      </div>` },
    { t: '开始时间', title: 'demo 文件名里的 Steam 比赛 id 右移 31 位 = 比赛「结束」时刻，减去这场比赛的实际时长就是「开始」时刻（和 Steam 比赛历史页对齐，实测差不到 1 分钟）',
      get: r => `<span class="m">${esc((r.played_at || r.mtime || '').slice(5, 16))}</span>` },
    { t: '比分', num: 1, get: scoreOf },
    { t: '计入', title: '投降、摆烂、半路不打了的局在这里取消勾选——数据留在库里，但默认不参与平均、走势和能力画像。投降局在解析时已自动取消勾选',
      get: r => (r.match_id
        ? `<label class="sw" title="${esc(r.exclude_note
              ? '已排除：' + r.exclude_note + '（勾上就恢复计入）'
              : '取消勾选 = 这局不算数')}"><input type="checkbox" data-ex="${r.match_id}"${r.excluded ? '' : ' checked'}></label>`
        : '<span class="m">—</span>') },
    { t: '结果', num: 1, get: resOf },
    { t: 'K', num: 1, get: r => r.me_kills ?? '—' },
    { t: 'D', num: 1, get: r => r.me_deaths ?? '—' },
    { t: 'A', num: 1, get: r => r.me_assists ?? '—' },
    { t: 'ADR', num: 1, get: r => r.me_adr != null ? num(r.me_adr, 1) : '—' },
    { t: 'KAST', num: 1, get: r => r.me_kast != null ? num(r.me_kast, 1) : '—' },
    { t: 'Rating', num: 1, get: r => r.me_rating != null ? num(r.me_rating, 2) : '—' },
    { t: 'Impact', num: 1, get: r => r.me_impact != null ? num(r.me_impact, 2) : '—' },
    { t: '急停率', num: 1, get: r => (r.me_fire && r.me_stop != null)
        ? Math.round(r.me_stop / r.me_fire * 100) + '%' : '—' },
    { t: '首杀', num: 1, get: r => r.me_fk ?? '—' },
    { t: '', num: 1, get: r => {
        // 行内操作：看回放 / 控制台播放 / 重解析 / 移除
        const nm = esc(r.name);
        const tail = `<button class="mini" data-play="${nm}" title="把 demo 放进 CS2 目录并复制 playdemo 命令，粘进控制台就能看">⌨</button>` +
                     `<button class="mini" data-reparse="${nm}" title="只重新解析这一场（约 8 秒）">⟲</button>` +
                     (r.file_exists
                       ? `<button class="mini" data-trim="${nm}" title="只删原始 .dem，分析数据和回放缓存都保留（省空间；删了以后这场不能再重新解析）">↓</button>`
                       : '') +
                     `<button class="mini del" data-del="${nm}" title="删除这场：原始文件 + 分析数据 + 回放缓存，全部移除">✕</button>`;
        if (r.error) return `<span class="op"><span class="l" title="${esc(r.error)}">失败</span>${tail}</span>`;
        if (!r.analyzed) return `<span class="op"><button data-analyze="${nm}">分析</button>${tail}</span>`;
        return `<span class="op"><a href="/replay.html?m=${r.match_id}" title="看这场回放">回放 →</a>${tail}</span>`;
    } },
  ], rows);

  $$('#gameTable button[data-analyze]').forEach(b => {
    b.onclick = async () => {
      const nm = b.dataset.analyze;
      hint(`分析 ${nm}…`);
      const r = await post('/api/analyze', { names: [nm] });
      if (r.ok) pollJob(); else hint(r.error || '失败');
    };
  });

  /* 控制台看回放：生成 playdemo 绝对路径命令并复制 */
  $$('#gameTable button[data-play]').forEach(b => {
    b.onclick = async () => {
      const nm = b.dataset.play;
      const r = await post('/api/playdemo', { name: nm });
      if (!r.ok) { hint(r.error || '失败', false); return; }
      let copied = true;
      try { await navigator.clipboard.writeText(r.cmd); }
      catch (e) { copied = false; prompt('复制这行命令，粘进 CS2 控制台：', r.cmd); }
      hint(copied ? `已复制：${r.cmd}` : `命令：${r.cmd}`, true);
    };
  });

  /* 单场重新解析：只清这一场的回放缓存，其他场不受影响 */
  $$('#gameTable button[data-reparse]').forEach(b => {
    b.onclick = async () => {
      const nm = b.dataset.reparse;
      hint(`重新解析 ${nm}…`);
      const r = await post('/api/reparse', { names: [nm] });
      if (r.ok) pollJob('已重新解析这一场');
      else hint(r.error || '失败', false);
    };
  });

  /* 全删这一场：原始 .dem + 分析数据 + 回放缓存。删完列表行消失，不可恢复。 */
  $$('#gameTable button[data-del]').forEach(b => {
    b.onclick = async () => {
      const nm = b.dataset.del;
      const row = (S.demos || []).find(d => d.name === nm) || {};
      const mb = row.size ? (row.size / 1048576).toFixed(0) + ' MB' : '原始文件';
      if (!confirm(`删除这一场？\n\n${nm}\n\n` +
                   `将移除：原始文件（${mb}）+ 分析数据 + 回放缓存\n` +
                   '不可恢复。只想省空间、保留数据的话，请用旁边的 ↓ 只删原始文件。')) return;
      const r = await post('/api/delete_demo', { name: nm, mode: 'all' });
      if (r.ok) { hint(r.msg || '已删除', true); load(); }
      else hint(r.error || '失败', false);
    };
  });

  /* 只删原始文件：分析结果和回放缓存都留着，列表上文件灯变灭、解析灯照旧 */
  $$('#gameTable button[data-trim]').forEach(b => {
    b.onclick = async () => {
      const nm = b.dataset.trim;
      const row = (S.demos || []).find(d => d.name === nm) || {};
      const mb = row.size ? (row.size / 1048576).toFixed(0) + ' MB' : '原始文件';
      if (!confirm(`只删除原始文件？\n\n${nm}（${mb}）\n\n` +
                   '分析数据和回放缓存都保留，历史和图表不受影响。\n' +
                   '但删掉之后这场就再也不能重新解析了。')) return;
      const r = await post('/api/delete_demo', { name: nm, mode: 'file_only' });
      if (r.ok) { hint(r.msg || '已删除原始文件', true); load(); }
      else hint(r.error || '失败', false);
    };
  });
}

async function pollJob(doneMsg = '分析完成') {
  const t = setInterval(async () => {
    try {
      const s = await api('/api/state');
      S.job = s.job;
      // 解析是逐场推进的，列表也该逐场变：/api/state 已经带回最新 demos，
      // 直接重渲染即可（保留滚动位置，否则每 1.2 秒跳一次顶）
      if (s.demos && s.demos.length !== (S.demos || []).length ||
          (s.demos && JSON.stringify(s.demos) !== JSON.stringify(S.demos || []))) {
        S.demos = s.demos;
        const y = window.scrollY;
        renderGames();
        window.scrollTo(0, y);
      }
      jobUI(s.job);
      if (s.job && s.job.running) hint(`处理中 ${s.job.done}/${s.job.total}：${s.job.current || ''}`);
      else { clearInterval(t); hint(doneMsg, true); load(); }
    } catch (e) { clearInterval(t); }
  }, 1200);
}

/* 顶栏进度条 */
/* 顶栏那条进度换成全局进度带（jobs-bar.js + /api/jobs）。
   这个函数保留成空实现，只为不动各处调用点。 */
function jobUI() {}

$('#btnPull').onclick = async () => {
  hint('从 CS2 replays 目录拉取…');
  const r = await api('/api/pull');
  if (!r.ok) { hint(r.error || '失败'); return; }
  hint(`拉到 ${r.added} 个新 demo（已存在 ${r.skipped} 个）`, true);
  load();
};
// 从 Steam 拉新比赛：读设置里的 key/auth/steamid/start_code，
// 旧分享码链已移除：现在只有 AutoPull（GC 直取地址）和本地「从 CS2 拉取」两条路。
// 配置不全时后端返回 missing 列表，这里提示去哪儿填。
/* ================= AutoPull ================= */
// 只在装了 AutoPull 增量包时显示（load() 里按 S.gc_pull 控制）。
// 两条路：①取最近 8 场 ②按分享码指定场次（可以补很久以前的）。
function apSay(txt, ok) {
  const el = $('#apStatus');
  if (!el) return;
  el.textContent = txt || '';
  el.style.color = ok === false ? 'var(--bad, #d0554a)' : (ok ? 'var(--ok, #4a9e6a)' : '');
}

// 库里已有的跳过，剩下的交给 /api/http_pull 下载（断点续传、进度条都是现成的）
async function apDownload(urls) {
  const have = (S.demos || []).map(d => String(d.name || ''));
  const fresh = [];
  for (const u of (urls || [])) {
    const body = u.split('/730/')[1].replace(/\.dem\.bz2$/, '');
    if (!have.some(n => n.includes(body))) fresh.push(u);
  }
  if (!fresh.length) {
    apSay(`没有新场次（这 ${(urls || []).length} 场都已经在库里）`, true);
    return;
  }
  if (!confirm(`发现 ${fresh.length} 场新比赛，直接用工具下载？\n\n走断点续传，可关掉页面；每场 50-250 MB`)) {
    apSay(`已取消，${fresh.length} 场待下载`);
    return;
  }
  showPull();
  const hp = await post('/api/http_pull', { urls: fresh });
  if (hp.ok) {
    hint(`开始下载 ${fresh.length} 场…`);
    httpPullWatch();
    apSay(`已加入下载：${fresh.length} 场`, true);
  } else {
    apSay(hp.error || '启动下载失败', false);
  }
}

$('#apRecent').onclick = async () => {
  const b = $('#apRecent'), old = b.textContent;
  b.disabled = true;
  b.textContent = '查询中…';
  apSay('正在问 Steam（约 10 秒）…');
  let r = {};
  try { r = await post('/api/gc_pull', { mode: 'recent' }); } catch (e) { r = { ok: false, error: String(e) }; }
  b.disabled = false;
  b.textContent = old;
  if (r.need_patch) { apSay('需要 AutoPull 增量包', false); return; }
  if (!r.ok) { apSay(r.error || '取不到比赛列表', false); return; }
  const n = (r.matches || []).length;
  const have = (S.demos || []).map(d => String(d.name || ''));
  const missing = (r.urls || []).filter(u => {
    const body = u.split('/730/')[1].replace(/\.dem\.bz2$/, '');
    return !have.some(x => x.includes(body));
  }).length;
  apSay(`最近 ${n} 场，其中 ${missing} 场未下载`, true);
  await apDownload(r.urls);
};

$('#apByCodes').onclick = async () => {
  const raw = ($('#apCodes').value || '').trim();
  if (!raw) { apSay('先把分享码粘上面', false); return; }
  const codes = [...new Set((raw.match(/CSGO-[A-Za-z0-9-]{20,}/gi) || []).map(s => s.trim()))];
  if (!codes.length) { apSay('没认出分享码（形如 CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx）', false); return; }
  const b = $('#apByCodes'), old = b.textContent;
  b.disabled = true;
  b.textContent = `查询 ${codes.length} 场…`;
  apSay(`逐场查询，预计 ${codes.length * 10} 秒…`);
  let r = {};
  try { r = await post('/api/gc_pull', { mode: 'codes', codes }); } catch (e) { r = { ok: false, error: String(e) }; }
  b.disabled = false;
  b.textContent = old;
  if (r.need_patch) { apSay('需要 AutoPull 增量包', false); return; }
  if (!r.ok) {
    const f = (r.failed || [])[0];
    apSay((r.error || '查询失败') + (f ? `（${f[0]}）` : ''), false);
    return;
  }
  const nfail = (r.failed || []).length;
  apSay(`查到 ${(r.urls || []).length} 场可下载` + (nfail ? `，${nfail} 场失败` : ''), true);
  await apDownload(r.urls);
};

let _hpTimer = null;                 // HTTP 直下进度的定时器（hidePull 里要清，所以先声明）
function showPull() { const e = $('#pullBar'); if (e) e.hidden = false; }
function hidePull() {
  clearTimeout(_hpTimer);
  const e = $('#pullBar');
  if (e) {
    e.hidden = true;
    ['pullFill', 'pullFillOne'].forEach(id => {
      const f = document.getElementById(id);
      if (f) f.style.width = '0';
    });
    const a = $('#pullFillTxt'), b = $('#pullFillOneTxt');
    if (a) a.textContent = '';
    if (b) b.textContent = '';
  }
}

/* ===== HTTP 直下进度（工具自己下，不经过 CS2） ===== */
async function httpPullWatch() {
  clearTimeout(_hpTimer);
  const msg = $('#pullMsg');
  if (!msg) return;
  let p = null;
  try { p = await api('/api/http_pull_progress'); } catch (e) { return; }
  const total = Number(p.total || 0), done = Number(p.done || 0);
  const mb = n => (Number(n || 0) / 1048576).toFixed(1);

  // 上条：总场次。要算上「当前这一场已下的小数」，否则整场下载期间它一直停在 0%
  const bt = Number(p.bytes_total || 0), bb = Number(p.bytes || 0);
  const frac = bt > 0 ? Math.min(1, bb / bt) : 0;
  const fAll = $('#pullFill'), tAll = $('#pullFillTxt');
  if (fAll && total) fAll.style.width = `${Math.round(((done + frac) / total) * 100)}%`;
  if (tAll) tAll.textContent = total ? `${done}/${total} 场` : '';
  // 下条：当前这一场的字节进度（拿不到总长时只显示已下多少）
  const fOne = $('#pullFillOne'), tOne = $('#pullFillOneTxt');
  if (fOne) fOne.style.width = `${bt > 0 ? Math.round(bb / bt * 100) : 0}%`;
  if (tOne) tOne.textContent = bt > 0 ? `${mb(bb)}/${mb(bt)} MB`
                                      : (bb ? `${mb(bb)} MB` : '—');

  if (p.running) {
    msg.textContent = `正在下载第 ${Math.min(done + 1, total)} 场${p.current ? '：' + p.current : ''}`;
    _hpTimer = setTimeout(httpPullWatch, 1000);
    return;
  }
  const okc = Number(p.ok_count || 0), failc = Number(p.fail_count || 0);
  if (p.error) {
    msg.textContent = `下载出错：${p.error}`;
    hint(p.error, false);
  } else if (failc) {
    const first = (p.errors || [])[0] || '';
    msg.textContent = `完成 ${okc} 场，失败 ${failc} 场${first ? '：' + first : ''}`;
    hint(`有 ${failc} 场没下成，再点一次会从断点续传`, false);
  } else {
    msg.textContent = `${okc} 场已下载并解压到 demos`;
    hint('下载完成，点「分析未处理」开始解析', true);
    setTimeout(hidePull, 4000);
  }
  load();
}

/* ===== 下载进度 =====
   工具本身不下载 demo —— 下载是 CS2 干的（下载清单 cs2_new_download.bat 会逐个唤起）。
   能观测的只有「replays 目录里新落盘了几个 .dem」，所以进度就是 done/total。 */

$('#btnScan').onclick = async () => {
  hint('扫描中…');
  const r = await post('/api/scan');
  hint(r.ok ? `扫描完成，新增 ${r.added ?? 0}` : (r.error || '失败'), r.ok);
  load();
};
$('#btnAnalyze').onclick = async () => {
  hint('开始分析…');
  const r = await post('/api/analyze', {});
  if (r.ok) pollJob(); else hint(r.error || '失败');
};
$('#btnReparse').onclick = async () => {
  if (!confirm('重新解析全部 demo？\n\n会清空现有分析结果并重新解析，每场约 8 秒。')) return;
  hint('重新解析中…');
  const r = await post('/api/reparse', {});
  if (r.ok) pollJob(); else hint(r.error || '失败');
};
$('#btnExportCsv').onclick = () => { location.href = '/api/export/csv'; };


// 全部删除：后端 /api/reset_all 清 16 张表 + 回放缓存 + 导出报告 + 设置，
// 再重新扫描 demo 目录。demo 原始文件不动，但要重新分析。
// 二次确认要求手打 DELETE——点错一次的代价是几十分钟的解析。
$('#btnResetAll').onclick = async () => {
  const ans = prompt(
    '全部删除\n\n' +
    '会清空：所有分析数据、回放缓存、导出报告、设置。\n' +
    '不会删：demos 目录里的 .dem 原始文件（但需要重新分析）。\n\n' +
    '确认请输入 DELETE（全大写）：');
  if (ans === null) return;
  if (ans !== 'DELETE') { hint('已取消（输入不匹配）', false); return; }
  hint('正在清空…');
  const r = await post('/api/reset_all', {});
  if (!r.ok) { hint(r.error || '失败', false); return; }
  pollJob('已全部清空');
};

// 「计入」勾选框：取消 = 这局不算数。事件委托挂 document 上只绑一次，
// 避免每次重渲染重复叠加。
document.addEventListener('change', async (e) => {
  const cb = e.target.closest && e.target.closest('input[data-ex]');
  if (!cb) return;
  const mid = Number(cb.dataset.ex);
  const on = cb.checked ? 0 : 1;
  cb.disabled = true;
  let r = {};
  try { r = await post('/api/set_excluded', { match_id: mid, excluded: on }); }
  catch (err) { r = { ok: false, error: String(err) }; }
  cb.disabled = false;
  if (!r.ok) { cb.checked = !cb.checked; hint(r.error || '失败', false); return; }
  hint(on ? `match ${mid} 已排除，不计入平均与走势` : `match ${mid} 恢复计入`, true);
  load();
});

load();
