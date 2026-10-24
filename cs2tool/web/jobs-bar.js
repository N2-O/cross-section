/* 全局后台任务进度带：解析 / 下载各一行，垂直堆叠。
 *
 * 数据页与 Demo 页共用；replay.html 是独立页面，不引这个。
 * 数据来自 /api/jobs —— 后端把 _jobs（解析）和 _http_pull（下载）归一后返回。
 *
 * 为什么单独做一条带子而不是各页面自己画：
 * 以前进度只在页面内轮询，切页/刷新就断，看起来像"任务被打断了"，
 * 其实后端线程一直在跑。放在这条共用带子上之后，只要服务窗口没关，
 * 换到哪个页面都能看到当前进度。
 */
(function () {
  'use strict';

  const el = document.getElementById('jobsBar');
  if (!el) return;

  const MB = n => (Number(n || 0) / 1048576).toFixed(1);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function row(j, kind) {
    let icon, label, pct, extra;
    if (kind === 'download') {
      icon = '⇣'; label = '下载';
      const bt = Number(j.bytes_total || 0);
      const bb = Number(j.bytes || 0);
      const frac = bt > 0 ? Math.min(1, bb / bt) : 0;
      pct = j.total ? Math.round(((Number(j.done || 0) + frac) / j.total) * 100) : 0;
      extra = j.total ? `${j.done || 0}/${j.total} 场` : '';
      if (bt > 0) extra += ` · ${MB(bb)}/${MB(bt)} MB`;
      else if (bb > 0) extra += ` · ${MB(bb)} MB`;
    } else {
      icon = '⟲'; label = '解析';
      pct = j.total ? Math.round((Number(j.done || 0) / j.total) * 100) : 0;
      extra = j.total ? `${j.done || 0}/${j.total} 场` : '';
      if (j.stage) extra += ` · ${j.stage}`;
      if (j.elapsed) extra += ` · ${j.elapsed}s`;
    }
    const nm = String(j.current || '').replace(/\.dem$/i, '').slice(0, 22);
    return `<div class="jbrow" data-kind="${kind}">`
      + `<span class="jbico">${icon}</span>`
      + `<span class="jblab">${label}</span>`
      + `<span class="jbtrack"><i style="width:${pct}%"></i></span>`
      + `<span class="jbtxt">${esc(extra)}</span>`
      + (nm ? `<span class="jbname" title="${esc(j.current)}">${esc(nm)}</span>` : '')
      + `</div>`;
  }

  async function tick() {
    let j = null;
    try {
      const r = await fetch('/api/jobs', { cache: 'no-store' });
      if (!r.ok) return;                 // 后端还是旧版：静默不显示
      j = await r.json();
    } catch (e) {
      return;                            // 断网 / 服务停了：静默
    }
    const rows = [];
    // 下载在前（有字节进度，信息更密），解析在后
    if (j.download && j.download.running) rows.push(row(j.download, 'download'));
    if (j.analyze && j.analyze.running) rows.push(row(j.analyze, 'analyze'));
    if (!rows.length) {
      if (!el.hidden) { el.hidden = true; el.innerHTML = ''; }
      return;
    }
    el.hidden = false;
    el.innerHTML = rows.join('');
  }

  tick();
  setInterval(tick, 1000);
})();
