/* 品牌名 Cross-Section —— 定期播一次电视短路（CRT glitch） */
(function () {
  'use strict';
  var xb = document.querySelector('.xb');
  if (!xb) return;                                   // replay.html 没有这个组件，安静退出
  var mq = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
  if (mq && mq.matches) return;                      // 用户要减少动效：一个定时器都不起

  var GLITCH = 840;                                  // 与 CSS 动画时长对齐
  function rnd(a, b) { return a + Math.random() * (b - a); }

  function fire() {
    xb.classList.add('glitch');                      // 硬切开始
    window.setTimeout(function () {
      xb.classList.remove('glitch');                 // 硬切回常态，不做淡出
      window.setTimeout(fire, rnd(14000, 26000));    // 每次播完重排下一次
    }, GLITCH);
  }

  window.setTimeout(fire, rnd(8000, 14000));         // 首播：8–14 秒后
})();
