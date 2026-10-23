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

async function api(path, opt) { return await (await fetch(path, opt)).json(); }
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
  }
  S = await api('/api/state');
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
    el.textContent = `上次检查 ${t}：查询失败 —— ${r.error || '未知错误'}`;
    el.style.color = 'var(--bad)';
  } else if (r.status === 'empty' || !(r.added)) {
    el.textContent = `上次检查 ${t}：没有新比赛（已是最新的）`;
    el.style.color = '';
  } else {
    el.textContent = `上次检查 ${t}：新增 ${r.added} 场，已生成 ${r.bat || '下载清单'}`;
    el.style.color = 'var(--ok)';
  }
}

function renderPlayers() {
  const sel = $('#player');
  if (!sel) return;
  const ps = S.players || [];
  if (!ps.length) { sel.innerHTML = '<option>暂无玩家</option>'; return; }
  sel.innerHTML = ps.map(p =>
    `<option value="${p.steamid}"${p.is_me ? ' selected' : ''}>${esc(p.name)}（${p.excluded ? `${p.matches}/${p.matches + p.excluded}` : p.matches} 场）</option>`
  ).join('');
  sel.title = `共 ${ps.length} 名玩家；括号里是计入统计的场次 / 总场次`;
  sel.onchange = async e => {
    await post('/api/set_me', { steamid: Number(e.target.value) });
    load();
  };
}

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

  $('#gameSub').textContent = `${rows.length} 个文件 · 已分析 ${rows.filter(r => r.analyzed).length}`;
  if (!rows.length) {
    $('#gameTable').innerHTML = '<div class="nil">目录里还没有 .dem 文件</div>';
    return;
  }

  /* demos[] 没有 st 子对象，统计字段直接挂在 r 上（me_kills / me_adr / ...）。
     比分 = 我方赢的回合 : 输的回合；加时局（>24 回合）单独标出来。 */
  const hasRes = r => (r.rounds || 0) > 0;
  /* 这场 demo 里没有我（不是我打的 / 我中途才进场）：不能把我的队算成 T 方，
     结果列直接写「无你」，不然会显示一个跟我无关的胜负。 */
  const noMe = r => r.match_id && r.me_in === 0;
  const resOf = r => {
    if (noMe(r)) {
      const a = r.team_a_wins ?? 0, tot = r.rounds || 0, b = tot - a;
      const who = a === b ? '平' : (a > b ? '先打 T 的队赢' : '先打 CT 的队赢');
      return `<span class="m" title="这场 demo 里没有你的 steamid（可能不是你打的，或你中途才进场）。本场 ${a}:${b}，${who}">无你</span>`;
    }
    if (!hasRes(r)) return '—';
    const w = r.wins || 0, t = r.rounds;
    if (w * 2 > t) return '<span class="w">胜</span>';
    if (w * 2 === t) return '<span class="d">平</span>';
    return '<span class="l">负</span>';
  };
  const scoreOf = r => {
    if (!hasRes(r)) return '—';
    const w = r.wins || 0, t = r.rounds;
    const ot = t > 24 ? '<span class="ot">加时</span>' : '';
    if (noMe(r)) {
      /* 没我的场：给队伍口径的比分。A 队 = 上半场打 T 的那队；
         不能用「T 阵营胜 : CT 阵营胜」求和，换边后那是两支不同的队。 */
      const a = r.team_a_wins ?? 0, tot = r.rounds || 0, b = tot - a;
      return `<span class="m" title="这场 demo 里没有你的 steamid。比分按队伍算：先打 T 的队 ${a} : 先打 CT 的队 ${b}">${a}:${b}</span>${ot}`;
    }
    return `${w}:${t - w}${ot}`;
  };

  $('#gameTable').innerHTML = table([
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
                     `<button class="mini del" data-del="${nm}" title="从列表移除这场（只删分析结果，原始 .dem 文件不动）">✕</button>`;
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

  /* 控制台看回放：把 demo 送进 CS2 的 csgo 目录，复制 playdemo 命令 */
  $$('#gameTable button[data-play]').forEach(b => {
    b.onclick = async () => {
      const nm = b.dataset.play;
      hint('准备 demo（可能要把文件复制到 CS2 目录，大文件要几秒）…');
      const r = await post('/api/playdemo', { name: nm });
      if (!r.ok) { hint(r.error || '失败', false); return; }
      let copied = true;
      try { await navigator.clipboard.writeText(r.cmd); }
      catch (e) { copied = false; prompt('复制这行命令，粘进 CS2 控制台：', r.cmd); }
      const extra = r.mode === 'abs' ? '　（没找到 CS2 目录，用的是绝对路径）' : '';
      hint(copied ? `已复制：${r.cmd}　粘进 CS2 控制台回车${extra}`
                  : `命令：${r.cmd}${extra}`, true);
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

  /* 单场移除：删库里的分析结果 + 回放缓存，原始 .dem 文件不动 */
  $$('#gameTable button[data-del]').forEach(b => {
    b.onclick = async () => {
      const nm = b.dataset.del;
      if (!confirm(`从列表移除这一场？\n\n${nm}\n\n` +
                   '只删工具里的分析结果和回放缓存；demos 目录里的原始 .dem 文件不动。\n' +
                   '（下次点「扫描目录」它会以「未分析」的身份回来）')) return;
      const r = await post('/api/delete_demo', { name: nm });
      if (r.ok) { hint(r.msg || '已移除', true); load(); }
      else hint(r.error || '失败', false);
    };
  });
}

async function pollJob(doneMsg = '分析完成') {
  const t = setInterval(async () => {
    try {
      const s = await api('/api/state');
      S.job = s.job;
      jobUI(s.job);
      if (s.job && s.job.running) hint(`处理中 ${s.job.done}/${s.job.total}：${s.job.current || ''}`);
      else { clearInterval(t); hint(doneMsg, true); load(); }
    } catch (e) { clearInterval(t); }
  }, 1200);
}

/* 顶栏进度条 */
function jobUI(j) {
  const el = $('#job');
  if (!el) return;
  if (j && j.running) {
    el.classList.add('on');
    const pct = j.total ? Math.round(j.done / j.total * 100) : 0;
    const nm = (j.current || '').replace(/\.dem$/i, '').slice(0, 24);
    $('#jobtext').textContent =
      `处理中 ${j.done}/${j.total} · ${pct}%${nm ? ' · ' + nm : ''}`;
    $('#progbar').style.width = pct + '%';
  } else {
    el.classList.remove('on');
  }
}

$('#btnPull').onclick = async () => {
  hint('从 CS2 replays 目录拉取…');
  const r = await api('/api/pull');
  if (!r.ok) { hint(r.error || '失败'); return; }
  hint(`拉到 ${r.added} 个新 demo（已存在 ${r.skipped} 个）`, true);
  load();
};
// 从 Steam 拉新比赛：读设置里的 key/auth/steamid/start_code，
// 跑 cs2_pull_new.py 生成 steam:// 批量下载 bat。
// 配置不全时后端返回 missing 列表，这里提示去哪儿填。
$('#btnPullNew').onclick = async () => {
  const b = $('#btnPullNew');
  const old = b.textContent;
  b.disabled = true;
  b.textContent = '查询中…';
  hidePull();
  let pv = {};
  try {
    pv = await post('/api/pull_preview', {});
  } catch (e) {
    pv = { ok: false, error: String(e) };
  }
  b.disabled = false;
  b.textContent = old;

  const PH = { steam_api_key: 'Steam Web API Key', steam_auth_code: '游戏认证码',
               steamid: 'SteamID64', start_code: '已处理到的分享码',
               'cs2_pull_new.py': '拉取脚本' };
  if (pv.need_setup) {
    const miss = (pv.missing || []).map(k => PH[k] || k).join('、');
    hint(`需要先配置：${miss}　→ 回主页点右上角「⚙ 设置」`, false);
    return;
  }
  // 四种结果分开说：网络不通 / 查询失败 / 确实没有新的 / 有 N 场
  if (pv.status === 'offline') {
    hint(`网络不通：${pv.error || '连不上 Steam API（直连和代理都试过）'}`, false);
    checkPull();                 // 自动跑一遍自检，别让人自己去命令行查
    return;
  }
  if (pv.status === 'error' || !pv.ok) {
    hint(`查询失败：${pv.error || '未知原因'}`, false);
    checkPull();
    return;
  }
  if (!pv.count) {
    hint('没有新比赛（已是最新的）', true);
    return;
  }

  // 先把场数报出来，让用户决定要不要拉
  const head = pv.codes.slice(0, 6).join('\n');
  const more = pv.count > 6 ? `\n… 还有 ${pv.count - 6} 场` : '';
  if (!confirm(`发现 ${pv.count} 场新比赛：\n\n${head}${more}\n\n` +
               '直接用工具下载？（走断点续传，可关掉页面；每场 150-250 MB）')) {
    hint(`已取消，保留 ${pv.count} 场在待拉队列`);
    return;
  }

  const r = await post('/api/pull_new', {});
  if (!r.ok) {
    if (r.need_setup) {
      const miss = (r.missing || []).map(k => PH[k] || k).join('、');
      hint(`需要先配置：${miss}`, false);
      return;
    }
    hint(r.error || '启动失败', false);
    return;
  }
  // 清单已写进 pull_pending.json，这里直接让工具去 Valve 的 CDN 下载
  showPull();
  const hp = await post('/api/http_pull', {});
  if (hp.ok) {
    hint('开始下载…');
    httpPullWatch();
  } else {
    // 下载模块不可用 → 退回老路：生成清单让你双击 bat
    hint(hp.error || '直连下载不可用，改用 CS2 下载', false);
    pollPull();
  }
};

let _dlTimer = null;                 // CS2 下载监视的定时器
let _hpTimer = null;                 // HTTP 直下进度的定时器（hidePull 里要清，所以先声明）
function showPull() { const e = $('#pullBar'); if (e) e.hidden = false; }
function hidePull() {
  clearTimeout(_dlTimer);
  clearTimeout(_hpTimer);
  const e = $('#pullBar');
  if (e) { e.hidden = true; const f = $('#pullFill'); if (f) f.style.width = '0'; }
}

/* ===== HTTP 直下进度（工具自己下，不经过 CS2） ===== */
async function httpPullWatch() {
  clearTimeout(_hpTimer);
  const msg = $('#pullMsg'), fill = $('#pullFill');
  if (!msg) return;
  let p = null;
  try { p = await api('/api/http_pull_progress'); } catch (e) { return; }
  const total = Number(p.total || 0), done = Number(p.done || 0);
  const mb = n => (Number(n || 0) / 1048576).toFixed(1);
  if (fill && total) fill.style.width = `${Math.round(done / total * 100)}%`;
  const cur = p.bytes_total ? ` · 当前 ${mb(p.bytes)}/${mb(p.bytes_total)} MB` : '';
  if (p.running) {
    msg.textContent = `下载中 ${done}/${total}${cur}`;
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
async function downloadWatch() {
  const bar = $('#pullBar'), msg = $('#pullMsg'), fill = $('#pullFill');
  if (!bar || !msg) return;
  bar.hidden = false;
  let r = null;
  try { r = await api('/api/download_progress'); } catch (e) { return; }
  if (!r || !r.ok) {
    msg.textContent = (r && r.error) || '查不到下载进度';
    return;
  }
  const total = Number(r.total || 0), done = Number(r.done || 0);
  if (!total) {
    msg.textContent = '清单已生成，双击工具目录里的 cs2_new_download.bat 让 CS2 开始下载';
    return;
  }
  if (fill) fill.style.width = `${Math.min(100, done / total * 100)}%`;
  if (done >= total) {
    msg.textContent = `${done}/${total} 场已下载完成 · 点「⇩ 从 CS2 拉取」把它导进 demos`;
    hint('下载完成：点「⇩ 从 CS2 拉取」，再点「分析未处理」', true);
    return;                                  // 到齐了就停，别一直轮询
  }
  msg.textContent = done
    ? `CS2 正在下载：已完成 ${done}/${total} 场`
    : `等待 CS2 开始下载（0/${total}）· 双击 cs2_new_download.bat，脚本会自动一场场触发`;
  clearTimeout(_dlTimer);
  _dlTimer = setTimeout(downloadWatch, 5000);
}

async function pollPull() {
  clearTimeout(_dlTimer);
  let p = {};
  try { p = await api('/api/pull_progress'); } catch (e) { p = { state: 'error' }; }
  const fill = $('#pullFill'), msg = $('#pullMsg');
  if (!fill || !msg) return;
  if (p.state === 'running') {
    const n = p.done || 0;
    // 查询阶段不知道总场数（Steam 只能一个个往后问），用推进式进度 + 实时场数
    fill.style.width = `${Math.min(90, 10 + n * 6)}%`;
    msg.textContent = `已查询 ${n} 场${p.current ? ' · ' + p.current : ''}`;
    setTimeout(pollPull, 700);
    return;
  }
  fill.style.width = '100%';
  if (p.state === 'done') {
    msg.textContent = p.msg || '完成';
    hint(p.msg || '完成', true);
    load();
    downloadWatch();          // 清单生成了，接着盯「CS2 下载到哪了」
  } else if (p.state === 'error') {
    msg.textContent = '失败：' + (p.error || '未知原因');
    hint('拉取失败：' + (p.error || ''), false);
    checkPull();                 // 失败就地自检，省得再点一次
    setTimeout(hidePull, 5000);
  } else {
    hidePull();
  }
}
/* ===== 拉取失败时就地自检，结论直接摊在下面 ===== */
async function checkPull() {
  const box = $('#pullDiag');
  if (!box) return;
  box.hidden = false;
  box.innerHTML = '<div class="inf">正在检测配置（会真的请求一次 Steam，十几秒）…</div>';
  let r = null;
  try {
    r = await post('/api/check_pull', {});
  } catch (e) {
    box.innerHTML = `<div class="vd bad">自检请求失败：${esc(String(e))}</div>`;
    return;
  }
  const rows = (r.steps || []).map(s => {
    const cls = s.ok === true ? 'ok' : (s.ok === false ? 'bad' : 'inf');
    const mark = s.ok === true ? '✓' : (s.ok === false ? '✗' : '·');
    return `<i class="${cls}">${mark}</i><span><span class="nm">${esc(s.name || '')}</span>` +
           `${esc(s.detail || '')}</span>`;
  }).join('');
  box.innerHTML = `<div class="dg">${rows || '<i class="inf">·</i><span class="inf">没有返回检查项</span>'}</div>
    <div class="vd${r.ok ? '' : ' bad'}">${esc(r.verdict || '')}</div>`;
}

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
