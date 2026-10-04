/* 站点交互：深色模式切换、右上角个人中心菜单、报销折叠表单、聊天室轮询。
   主题只保存在浏览器本地（localStorage），不上报服务器；默认工作台深色、公开页浅色，用户选择后全站生效。
   聊天室不引入 WebSocket，用轮询按自增主键增量拉新消息，保持零新依赖。 */
(function () {
  'use strict';

  var KEY = 'workbench-theme';
  var root = document.documentElement;
  var toggles = document.querySelectorAll('[data-theme-toggle]');
  var systemTheme=window.matchMedia('(prefers-color-scheme: dark)');
  var preference=root.dataset.theme;
  try{var savedTheme=localStorage.getItem(KEY);if(['dark','light','system'].indexOf(savedTheme)!==-1)preference=savedTheme;}catch(e){}

  function remember(theme) {
    try { localStorage.setItem(KEY, theme); } catch (e) { /* 无痕模式下忽略 */ }
  }

  function paint(theme) {
    var dark = theme === 'system' ? systemTheme.matches : theme === 'dark';
    root.dataset.theme = dark ? 'dark' : 'light';
    Array.prototype.forEach.call(toggles, function (button) {
      button.setAttribute('aria-pressed', dark ? 'true' : 'false');
      button.setAttribute('title', '主题：'+(theme==='system'?'跟随系统':dark?'深色':'浅色')+'；点击切换');
      var icon = button.querySelector('.theme-icon');
      var text = button.querySelector('.theme-text');
      if (icon) { icon.textContent = dark ? '☀️' : '🌙'; }
      if (text) { text.textContent = theme==='system'?'跟随系统':dark?'深色':'浅色'; }
    });
  }

  paint(preference);
  systemTheme.addEventListener('change',function(){if(preference==='system')paint(preference);});

  Array.prototype.forEach.call(toggles, function (button) {
    button.addEventListener('click', function () {
      var next = preference==='dark'?'light':preference==='light'?'system':'dark';
      preference=next;
      remember(next);
      paint(next);
    });
  });


  // 个人中心菜单：点击别处或按 Esc 收起。
  var menus = document.querySelectorAll('details.user-menu');
  document.addEventListener('click', function (event) {
    Array.prototype.forEach.call(menus, function (menu) {
      if (menu.open && !menu.contains(event.target)) { menu.open = false; }
    });
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      Array.prototype.forEach.call(menus, function (menu) { menu.open = false; });
    }
  });

  // 验证码按钮的发送冷却：服务端渲染一个静态秒数，这里让它逐秒递减，归零后恢复可点。
  Array.prototype.forEach.call(document.querySelectorAll('[data-countdown]'), function (button) {
    var left = parseInt(button.getAttribute('data-countdown'), 10);
    var value = button.querySelector('[data-countdown-value]');
    var ready = button.getAttribute('data-ready-label') || '重新发送';
    if (!(left > 0)) { return; }
    var timer = window.setInterval(function () {
      left -= 1;
      if (left > 0) {
        if (value) { value.textContent = left; }
        return;
      }
      window.clearInterval(timer);
      button.disabled = false;
      button.textContent = ready;
    }, 1000);
  });

  // 从「提交报销」链接（#claim-new）进来时展开折叠表单。
  function openClaimFold() {
    if (window.location.hash !== '#claim-new') { return; }
    var fold = document.getElementById('claim-new');
    if (fold && fold.tagName === 'DETAILS') { fold.open = true; }
  }
  openClaimFold();
  window.addEventListener('hashchange', openClaimFold);

  // ---- 聊天室：定时拉取新消息 ----
  var POLL_MS = 4000;

  function setupChat(root) {
    var log = root.querySelector('[data-chat-log]');
    var url = root.getAttribute('data-poll-url');
    if (!log || !url) { return; }
    var status = root.querySelector('[data-chat-status]');
    var form = root.querySelector('[data-chat-form]');
    var busy = false;

    function lastId() {
      var items = log.querySelectorAll('[data-id]');
      if (!items.length) { return 0; }
      return parseInt(items[items.length - 1].getAttribute('data-id'), 10) || 0;
    }

    function atBottom() {
      return log.scrollHeight - log.scrollTop - log.clientHeight < 60;
    }

    function toBottom() { log.scrollTop = log.scrollHeight; }

    function setStatus(text) { if (status) { status.textContent = text; } }

    // 全部用 createElement/textContent 拼节点：消息正文绝不当作 HTML 插入。
    function build(item) {
      var article = document.createElement('article');
      article.className = 'chat-msg' + (item.mine ? ' mine' : '');
      article.setAttribute('data-id', item.id);

      var avatar = document.createElement('span');
      avatar.className = 'avatar';
      avatar.setAttribute('aria-hidden', 'true');
      avatar.textContent = item.initial;

      var bubble = document.createElement('div');
      bubble.className = 'chat-bubble';

      var meta = document.createElement('div');
      meta.className = 'chat-meta';
      var who = document.createElement('strong');
      who.textContent = item.author;
      var when = document.createElement('small');
      when.textContent = item.at;
      meta.appendChild(who);
      meta.appendChild(when);

      var body = document.createElement('p');
      body.textContent = item.body;

      bubble.appendChild(meta);
      bubble.appendChild(body);
      article.appendChild(avatar);
      article.appendChild(bubble);
      return article;
    }

    function poll() {
      if (busy || document.hidden) { return; }
      busy = true;
      window.fetch(url + '?after=' + lastId(), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (response) {
          if (!response.ok) { throw new Error('HTTP ' + response.status); }
          return response.json();
        })
        .then(function (data) {
          setStatus('已连接');
          var stick = atBottom();
          var empty = log.querySelector('[data-chat-empty]');
          if (data.messages.length && empty) { empty.remove(); }
          data.messages.forEach(function (item) { log.appendChild(build(item)); });
          if (data.messages.length && stick) { toBottom(); }
        })
        .catch(function () { setStatus('暂时连不上，正在重试…'); })
        .then(function () { busy = false; });
    }

    if(form)form.addEventListener('submit',()=>window.setTimeout(poll,400));
    toBottom();
    poll();
    window.setInterval(poll, POLL_MS);
  }

  Array.prototype.forEach.call(document.querySelectorAll('[data-chat]'), setupChat);
})();
