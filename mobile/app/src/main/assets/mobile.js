(function () {
  'use strict';
  if (window.zhiyuPhoneReady) return;
  window.zhiyuPhoneReady = true;
  document.addEventListener('input',()=>window.zhiyuPageEdited=true,{capture:true});
  document.addEventListener('change',()=>window.zhiyuPageEdited=true,{capture:true});
  const root = document.documentElement;
  root.classList.add('zhiyu-phone');
  root.dataset.theme = 'light';
  const viewport = document.querySelector('meta[name="viewport"]');
  if (viewport) viewport.content = 'width=device-width,initial-scale=1,viewport-fit=cover';
  const path = location.pathname;

  const chat = /^\/messages\/(personal|groups)\/\d+\/$/.test(path);
  root.classList.toggle('phone-chat', chat);
  root.classList.toggle('phone-inbox', path === '/messages/social/');
  root.classList.toggle('phone-ai', path === '/assistant/');

  function link(label, detail, href, icon) {
    const row = document.createElement('a');
    row.className = 'phone-row'; row.href = href;
    const glyph = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    glyph.classList.add('phone-icon'); glyph.setAttribute('viewBox', '0 0 24 24'); glyph.setAttribute('aria-hidden', 'true');
    const stroke = document.createElementNS(glyph.namespaceURI, 'path');
    const shapes = {api:'M5 8 1 12l4 4M19 8l4 4-4 4M14 4l-4 16', ai:'m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3Z', team:'M4 21v-3a5 5 0 0 1 10 0v3M17 21v-3a4 4 0 0 0-2-4M6 4a3 3 0 1 0 6 0 3 3 0 1 0-6 0M16 3a3 3 0 0 1 0 6', gift:'M3 8h18v4H3ZM5 12v9h14v-9M12 8v13M12 8C2 8 4 0 8 3l4 5c10 0 8-8 4-5Z', settings:'M4 7h16M4 17h16M8 4v6M16 14v6', notices:'M5 17h14l-2-4V8a5 5 0 0 0-10 0v5ZM10 21h4'};
    stroke.setAttribute('d', shapes[icon] || shapes.team); glyph.append(stroke);
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
    const api = link('使用团队 API', 'Key、模型与剩余额度', '/api-pool/', 'api'); api.classList.add('phone-primary-action'); actions.append(api);
    actions.append(link('打开 AI 助手', '选择团队和模型，开始对话', '/assistant/', 'ai'));
    actions.append(link('人才与招募', '寻找团队、查看招募机会', '/team-square/', 'team'));
    const tabs = team.querySelector('.team-context-tabs');
    if (tabs) {
      const management = card(); management.setAttribute('aria-label', '团队管理');
      for (const a of tabs.querySelectorAll('a')) {
        if (new URL(a.href).searchParams.get('tab') !== 'settings' && a.textContent.trim() === '概览') continue;
        management.append(link(a.textContent.trim() === '设置' ? '团队设置' : a.textContent.trim(), '', a.href, 'team'));
      }
      tabs.replaceWith(actions); team.append(management);
    } else team.prepend(actions);
  }
  if (path === '/messages/teams/' && !team) {
    const main = document.querySelector('main');
    const actions = card(); actions.append(link('寻找团队', '加入团队后即可使用团队 API', '/team-square/', 'team'));
    main?.prepend(actions);
  }

  if (path === '/me/' && new URLSearchParams(location.search).get('mobile') === 'points') {
    renderWallet();
  } else if (path === '/me/') {
    const main = document.querySelector('.personal-area');
    if (main) {
      const menu = main.querySelector('.personal-menu');
      if (menu) {
        const talent = menu.querySelector('a[href="/me/talent/"]');
        const actions = card();
        if (talent) actions.append(link('我的人才资料', '履历与求职意向', talent.href, 'team'));
        actions.append(link('我的积分', '团队额度与红包记录', '/me/?mobile=points', 'gift'));
        actions.append(link('设置', '', '/account/', 'settings'));
        menu.replaceWith(actions);
      }
      const original = document.querySelector('[data-account-menu] form[action="/logout/"]');
      if (original) {
        const logout = original.cloneNode(true); logout.className = 'phone-logout';
        const button = logout.querySelector('button');
        if (button) { button.className = 'button'; button.style.width = '100%'; }
        main.append(logout);
      }
    }
  }

  // The wallet endpoint is JSON, never a browser destination. All labels and
  // components are bundled in the APK; only authorized team data is fetched.
  async function renderWallet() { await window.zhiyuExperience?.wallet(document.querySelector('main')); }
  if (path === '/account/') {
    const tabs = document.createElement('nav'); tabs.className = 'phone-account-tabs';
    tabs.setAttribute('aria-label', '账户设置');
    for (const [name, tab] of [['个人资料','profile'],['账号安全','security']]) {
      const a = document.createElement('a'); a.textContent = name; a.href = '/account/?tab=' + tab; tabs.append(a);
    }
    document.querySelector('main')?.prepend(tabs);
  }
  // Native toolbar owns page titles. Keep the selected team's name visible.
  if (path === '/account/' || path === '/api-pool/' || path === '/messages/notices/' || path === '/me/talent/') {
    document.querySelector('main h1')?.classList.add('phone-page-title');
  }
  if (path.startsWith('/messages/teams/') && path !== '/messages/teams/') {
    document.querySelector('main .heading h1')?.classList.add('phone-page-title');
  }
  document.querySelectorAll('a[href="/messages/points/"]').forEach(a => { a.href = '/me/?mobile=points'; });
  document.querySelectorAll('.pool-scope-tabs').forEach(nav => nav.remove());
  if (path.startsWith('/messages/teams/') && path !== '/messages/teams/' || path === '/messages/teams/' && new URLSearchParams(location.search).get('tab') === 'settings') {
    document.querySelectorAll('.team-context-tabs').forEach(nav => nav.remove());
  }
  // No local repository, collector or administration flows on phones.
  document.querySelectorAll('a[href]').forEach(a => {
    let url; try { url = new URL(a.href, location.href); } catch (_) { return; }
    if (url.origin !== location.origin) return;
    if (/^\/(sampling|platform)\//.test(url.pathname) || /^\/api-pool\/manage\//.test(url.pathname)
        || /\/(office|web-preview)\//.test(url.pathname)) a.hidden = true;
  });
})();
