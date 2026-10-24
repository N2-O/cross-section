/* 「我是谁」下拉：主页（index.html）与 Demo 页（demos.html）共用同一份实现。
 *
 * 两个页面各有一个 <select id="player">，但它们指向同一份后端状态
 * （settings.my_steamid，接口 /api/set_me），行为必须完全一致。
 * 历史上这里各写了一遍，结果：
 *   - Number() 截断 SteamID64 的修复只落在主页，Demo 页一直切不动；
 *   - 按场次分组只做在主页，Demo 页 200 多人平铺在一个下拉里翻不动。
 * 所以渲染和切换都收到这里，页面只负责喂数据、以及切换成功后刷新自己。
 *
 * 依赖页面已有的 esc()（没有就退化成 String）；可选 hint(msg, ok) 用于报错。
 */
(function () {
  'use strict';

  const ORDER = ['常一起打（3 场以上）', '同场过 2 场', '只同场过 1 场', '其他'];

  function groupOf(p) {
    const m = p.matches || 0;
    if (m >= 3) return ORDER[0];
    if (m === 2) return ORDER[1];
    if (m === 1) return ORDER[2];
    return ORDER[3];
  }

  function render(sel, players) {
    if (!sel) return;
    const ps = (players || []).slice().sort(
      (a, b) => (b.matches || 0) - (a.matches || 0) || String(a.name).localeCompare(String(b.name)));
    if (!ps.length) { sel.innerHTML = '<option>暂无玩家</option>'; return; }
    const escFn = typeof window.esc === 'function' ? window.esc
      : (s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])));
    const one = p => `<option value="${p.steamid}"${p.is_me ? ' selected' : ''}>` +
      `${escFn(p.name || '（无名字）')}（${p.excluded ? `${p.matches}/${p.matches + p.excluded}` : p.matches} 场）</option>`;
    const buckets = new Map(ORDER.map(k => [k, []]));
    ps.forEach(p => buckets.get(groupOf(p)).push(p));
    let html = '';
    for (const k of ORDER) {
      const list = buckets.get(k);
      if (!list.length) continue;
      html += `<optgroup label="${k} · ${list.length} 人">` + list.map(one).join('') + '</optgroup>';
    }
    sel.innerHTML = html;
    sel.title = `共 ${ps.length} 名玩家；括号里是计入统计的场次 / 总场次。按场次分组，常一起打的在最上面`;
  }

  /* 绑定切换。apiPost(path, bodyObj) 由页面提供（主页的 api / Demo 页的 post）。
     onDone() 在切换成功后调用，页面自己决定重载什么。
     steamid 必须原样传字符串：SteamID64 超出 JS 安全整数范围，
     Number('76561198789250031') → 76561198789250030，后端就查不到这个人。 */
  function bind(sel, apiPost, onDone) {
    if (!sel) return;
    sel.onchange = async e => {
      const sid = String(e.target.value);
      const say = (m, ok) => { if (typeof window.hint === 'function') window.hint(m, ok); };
      let r = null;
      try {
        r = await apiPost('/api/set_me', { steamid: sid });
      } catch (err) {
        say('切换失败：' + String(err), false);
        return;
      }
      if (r && r.ok === false) { say(r.error || '切换失败', false); return; }
      if (typeof onDone === 'function') await onDone();
    };
  }

  window.PlayerSelect = { render: render, bind: bind };
})();
