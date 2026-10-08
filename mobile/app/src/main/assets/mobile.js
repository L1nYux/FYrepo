(function () {
  'use strict';
  if (window.zhiyuPhoneReady) return;
  window.zhiyuPhoneReady = true;
  const root = document.documentElement;
  root.classList.add('zhiyu-phone');
  root.dataset.theme = 'light';
  const viewport = document.querySelector('meta[name="viewport"]');
  if (viewport) viewport.content = 'width=device-width,initial-scale=1,viewport-fit=cover';
  const path = location.pathname;
  if (path === '/workspace/' || path === '/workbench/') {
    location.replace('/messages/social/');
    return;
  }
  const chat = /^\/messages\/(personal|groups)\/\d+\/$/.test(path);
  root.classList.toggle('phone-chat', chat);
  root.classList.toggle('phone-inbox', path === '/messages/social/');
  root.classList.toggle('phone-ai', path === '/assistant/');

  function link(label, detail, href, icon) {
    const row = document.createElement('a');
    row.className = 'phone-row'; row.href = href;
    const glyph = document.createElement('span'); glyph.textContent = icon || '›';
    const title = document.createElement('strong'); title.textContent = label;
    if (detail) { const sub = document.createElement('small'); sub.textContent = detail; title.append(sub); }
    const chevron = document.createElement('span'); chevron.className = 'phone-chevron'; chevron.textContent = '›';
    row.append(glyph, title, chevron); return row;
  }
  function card() { const el = document.createElement('section'); el.className = 'phone-quick-card'; return el; }
  document.querySelectorAll('a[target="_blank"]').forEach(a => { a.target = '_self'; });
  const observer = new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) {
      if (node.nodeType !== 1) continue;
      if (node.matches('a[target="_blank"]')) node.target = '_self';
      node.querySelectorAll('a[target="_blank"]').forEach(a => { a.target = '_self'; });
    }
  });
  observer.observe(document.body, {childList: true, subtree: true});

  if (chat) {
    const header = document.querySelector('.conversation-top');
    if (header) {
      const back = document.createElement('a'); back.href = '/messages/social/';
      back.className = 'phone-chat-back'; back.textContent = '‹'; back.setAttribute('aria-label', '返回消息列表');
      header.prepend(back);
    }
    const textarea = document.querySelector('.conversation-composer textarea');
    if (textarea) {
      textarea.rows = 1;
      textarea.addEventListener('input', () => { textarea.style.height = '48px'; textarea.style.height = Math.min(120, textarea.scrollHeight) + 'px'; });
    }
  }
  document.querySelectorAll('.communication-rail a').forEach(a => {
    const label = document.createElement('span'); label.textContent = a.getAttribute('aria-label') || a.title;
    a.append(label);
  });
  // Contact cards on desktop fill the other column; use the existing profile
  // dialog handler on a phone so "send message" stays reachable.
  document.querySelectorAll('[data-contact-id]').forEach(el => {
    el.dataset.memberId = el.dataset.contactId; delete el.dataset.contactId;
  });

  const assistant = document.getElementById('assistant-app');
  if (assistant) {
    assistant.classList.add('sidebar-collapsed');
    document.getElementById('assistant-sidebar-toggle')?.setAttribute('aria-expanded', 'false');
    const scrim = document.createElement('button'); scrim.type = 'button';
    scrim.className = 'phone-drawer-scrim'; scrim.setAttribute('aria-label', '收起历史对话');
    scrim.addEventListener('click', () => document.getElementById('assistant-sidebar-close')?.click());
    assistant.prepend(scrim);
    const fresh = document.createElement('button'); fresh.type = 'button'; fresh.className = 'phone-new-chat';
    fresh.textContent = '＋'; fresh.setAttribute('aria-label', '新建 AI 对话');
    fresh.addEventListener('click', () => { document.getElementById('assistant-new')?.click(); document.getElementById('assistant-sidebar-close')?.click(); });
    document.querySelector('.assistant-heading')?.append(fresh);
    const textarea = document.getElementById('assistant-input');
    if (textarea) { textarea.rows = 2; textarea.placeholder = '给 AI 助手发送消息'; }
  }

  const team = document.querySelector('[data-message-team]:not([data-message-team=""])');
  if (team && path === '/messages/teams/' && !new URLSearchParams(location.search).has('tab')) {
    const actions = card();
    actions.append(link('使用团队 API', '生成 Key、复制模型与查看剩余额度', '/api-pool/', '✦'));
    actions.append(link('打开 AI 助手', '选择团队和模型，开始对话', '/assistant/', '◇'));
    actions.append(link('人才与招募', '寻找团队、查看招募机会', '/team-square/', '♙'));
    const tabs = team.querySelector('.team-context-tabs');
    if (tabs) tabs.after(actions); else team.prepend(actions);
  }
  if (path === '/messages/teams/' && !team) {
    const main = document.querySelector('main');
    const actions = card(); actions.append(link('寻找团队', '加入团队后即可使用团队 API', '/team-square/', '♙'));
    main?.prepend(actions);
  }

  if (path === '/me/') {
    const main = document.querySelector('.personal-area');
    if (main) {
      const actions = card();
      actions.append(link('系统通知', '邀请与申请进度', '/messages/notices/', '♧'));
      actions.append(link('积分红包', '查看团队积分与红包记录', '/messages/points/', '◇'));
      actions.append(link('账号与安全', '资料、邮箱与密码', '/account/?tab=security', '⚙'));
      main.append(actions);
      const original = document.querySelector('[data-account-menu] form[action="/logout/"]');
      if (original) {
        const logout = original.cloneNode(true); logout.className = 'card';
        const button = logout.querySelector('button');
        if (button) { button.className = 'button'; button.style.width = '100%'; }
        main.append(logout);
      }
    }
  }
  if (path === '/account/') {
    const tabs = document.createElement('nav'); tabs.className = 'phone-account-tabs';
    tabs.setAttribute('aria-label', '账户设置');
    for (const [name, tab] of [['个人资料','profile'],['账号安全','security']]) {
      const a = document.createElement('a'); a.textContent = name; a.href = '/account/?tab=' + tab; tabs.append(a);
    }
    document.querySelector('main')?.prepend(tabs);
  }
  // No local repository, collector or administration flows on phones.
  document.querySelectorAll('a[href]').forEach(a => {
    let url; try { url = new URL(a.href, location.href); } catch (_) { return; }
    if (url.origin !== location.origin) return;
    if (/^\/(sampling|platform)\//.test(url.pathname) || /^\/api-pool\/manage\//.test(url.pathname)
        || /\/(office|web-preview)\//.test(url.pathname)) a.hidden = true;
  });
})();
