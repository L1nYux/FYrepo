/* 站点交互：深色模式切换、右上角个人中心菜单、报销折叠表单、聊天室轮询。
   主题只保存在浏览器本地（localStorage），不上报服务器；首次访问跟随系统偏好。
   聊天室不引入 WebSocket，用轮询按自增主键增量拉新消息，保持零新依赖。 */
(function () {
  'use strict';

  var KEY = 'workbench-theme';
  var root = document.documentElement;
  var toggles = document.querySelectorAll('[data-theme-toggle]');
  var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function remember(theme) {
    try { localStorage.setItem(KEY, theme); } catch (e) { /* 无痕模式下忽略 */ }
  }

  function paint(theme) {
    var dark = theme === 'dark';
    root.dataset.theme = dark ? 'dark' : 'light';
    Array.prototype.forEach.call(toggles, function (button) {
      button.setAttribute('aria-pressed', dark ? 'true' : 'false');
      button.setAttribute('title', dark ? '切换为浅色模式' : '切换为深色模式');
      var icon = button.querySelector('.theme-icon');
      var text = button.querySelector('.theme-text');
      if (icon) { icon.textContent = dark ? '☀️' : '🌙'; }
      if (text) { text.textContent = dark ? '浅色模式' : '深色模式'; }
    });
  }

  paint(root.dataset.theme === 'dark' ? 'dark' : 'light');

  Array.prototype.forEach.call(toggles, function (button) {
    button.addEventListener('click', function () {
      var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
      remember(next);
      paint(next);
    });
  });

  // 用户没手动选过时，系统主题变化要跟着走。
  if (media) {
    var follow = function (event) {
      if (!stored()) { paint(event.matches ? 'dark' : 'light'); }
    };
    if (media.addEventListener) { media.addEventListener('change', follow); }
    else if (media.addListener) { media.addListener(follow); }
  }

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

    // 回车发送、Shift+回车换行，省得每次都去点按钮。
    if (form) {
      var box = form.querySelector('textarea');
      if (box) {
        box.addEventListener('keydown', function (event) {
          if (event.key !== 'Enter' || event.shiftKey || event.isComposing) { return; }
          event.preventDefault();
          if (form.requestSubmit) { form.requestSubmit(); } else { form.submit(); }
        });
      }
      form.addEventListener('submit', function () { window.setTimeout(poll, 400); });
    }

    toBottom();
    poll();
    window.setInterval(poll, POLL_MS);
  }

  Array.prototype.forEach.call(document.querySelectorAll('[data-chat]'), setupChat);
})();

(function(){
  const dialog=document.getElementById('auth-dialog');
  if(!dialog)return;
  function switchTab(name){
    dialog.querySelectorAll('[data-auth-panel]').forEach(panel=>panel.hidden=panel.dataset.authPanel!==name);
    dialog.querySelectorAll('[data-auth-tab]').forEach(tab=>tab.setAttribute('aria-selected',String(tab.dataset.authTab===name)));
    dialog.querySelector('#auth-title').textContent=name==='register'?'邀请码注册':'进入团队工作台';
  }
  window.openAuth=function(name){switchTab(name);if(!dialog.open)dialog.showModal();};
  document.querySelectorAll('[data-auth-open]').forEach(button=>button.addEventListener('click',()=>window.openAuth(button.dataset.authOpen)));
  dialog.querySelectorAll('[data-auth-tab]').forEach(button=>button.addEventListener('click',()=>switchTab(button.dataset.authTab)));
  dialog.querySelector('[data-auth-close]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
  const defaultTab=document.body.dataset.authDefault;
  if(defaultTab)window.openAuth(defaultTab);
})();
