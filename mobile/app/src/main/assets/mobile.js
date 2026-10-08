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
        actions.append(link('积分红包', '团队额外积分与红包记录', '/me/?mobile=points', 'gift'));
        actions.append(link('设置', '个人资料、邮箱与密码', '/account/', 'settings'));
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
  async function renderWallet() {
    const main = document.querySelector('main');
    if (!main) return;
    const view = document.createElement('section'); view.className = 'phone-wallet';
    const heading = document.createElement('h1'); heading.textContent = '积分红包'; heading.className = 'phone-page-title';
    const teamLabel = document.createElement('label'); teamLabel.textContent = '团队';
    const select = document.createElement('select'); select.setAttribute('aria-label', '选择积分所属团队');
    teamLabel.append(select);
    const balance = document.createElement('section'); balance.className = 'card phone-wallet-balance';
    const caption = document.createElement('p'); caption.textContent = '可转赠的额外积分';
    const amount = document.createElement('strong'); amount.textContent = '—'; balance.append(caption, amount);
    const help = document.createElement('p'); help.className = 'muted'; help.textContent = '在聊天里发送或领取红包。基础额度和调用中预留的积分不能转赠。';
    const records = document.createElement('section'); records.className = 'phone-quick-card'; records.setAttribute('aria-label', '红包记录');
    const status = document.createElement('p'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'button'; retry.textContent = '重新加载'; retry.hidden = true;
    view.append(heading, teamLabel, balance, help, records, status, retry); main.replaceChildren(view);
    let generation = 0;
    const number = value => Number(value || 0).toLocaleString('zh-CN', {maximumFractionDigits: 2});
    async function json(url, signal) {
      const response = await fetch(url, {credentials:'same-origin', cache:'no-store', signal});
      if (!response.headers.get('content-type')?.includes('application/json')) throw Error('登录已失效，请重新登录。');
      const data = await response.json();
      if (!response.ok) throw Error(response.status === 403 ? '当前团队不可用，请重新选择团队。' : data.error || '暂时无法读取积分。');
      return data;
    }
    let controller;
    async function load() {
      controller?.abort(); controller = new AbortController(); const current = ++generation;
      if (!select.value) return;
      amount.textContent = '—'; records.replaceChildren(); retry.hidden = true; status.textContent = '正在读取积分…'; status.className = 'phone-fetch-status';
      const requestController = controller;
      const timeout = setTimeout(() => requestController.abort(), 20000);
      try {
        const data = await json('/messages/points/?space=' + encodeURIComponent(select.value), controller.signal);
        if (current !== generation) return;
        amount.textContent = number(data.available_points) + ' 点';
        const gifts = Array.isArray(data.gifts) ? data.gifts : [];
        if (!gifts.length) { const empty = document.createElement('p'); empty.className = 'phone-empty'; empty.textContent = '还没有红包记录'; records.append(empty); }
        for (const gift of gifts) {
          const row = document.createElement('button'); row.type = 'button'; row.className = 'phone-gift-record';
          const title = document.createElement('strong'); title.textContent = (gift.mine ? '发出的' : '收到的') + gift.title;
          const note = document.createElement('small'); note.textContent = gift.greeting || '积分红包';
          const state = document.createElement('span'); state.textContent = gift.state_label || gift.status;
          const points = document.createElement('b'); points.textContent = number(gift.claimed_points ?? gift.points) + ' 点';
          row.append(title, points, note, state); row.addEventListener('click', () => showGift(gift)); records.append(row);
        }
        status.textContent = ''; status.className = '';
      } catch (error) { if (current === generation) { status.className = ''; status.textContent = error.name === 'AbortError' ? '连接超时，请重试。' : error.message; retry.hidden = false; } }
      finally { clearTimeout(timeout); }
    }
    async function showGift(gift) {
      const dialog = document.createElement('dialog'); const title = document.createElement('h2'); title.textContent = gift.title;
      const body = document.createElement('div'); body.textContent = '正在读取…';
      const close = document.createElement('button'); close.type = 'button'; close.className = 'button'; close.textContent = '关闭'; close.addEventListener('click', () => dialog.close());
      dialog.append(title, body, close); document.body.append(dialog); dialog.addEventListener('close', () => dialog.remove(), {once:true}); dialog.showModal();
      const abort = new AbortController(); const timeout = setTimeout(() => abort.abort(), 20000);
      dialog.addEventListener('close', () => abort.abort(), {once:true});
      try {
        if (!/^[0-9a-f-]{36}$/i.test(gift.id)) throw Error('红包记录无效。');
        const data = await json('/messages/points/' + gift.id + '/?space=' + encodeURIComponent(select.value), abort.signal);
        body.replaceChildren();
        for (const value of [data.greeting, number(data.points) + ' 点 · ' + data.status, '已领取 ' + data.claimed_count + ' / ' + data.count + ' 份', ...(data.receipts || []).map(r => r.username + ' · ' + number(r.points) + ' 点')]) {
          const line = document.createElement('p'); line.textContent = value || ''; body.append(line);
        }
      } catch (error) { body.textContent = error.name === 'AbortError' ? '连接超时，请重试。' : error.message; }
      finally { clearTimeout(timeout); }
    }
    retry.addEventListener('click', () => select.options.length ? load() : teams()); select.addEventListener('change', load);
    async function teams() {
      status.textContent = '正在读取团队…'; status.className = 'phone-fetch-status'; retry.hidden = true;
      const abort = new AbortController(); const timeout = setTimeout(() => abort.abort(), 20000);
      try {
        // API usage lists authorized team workspaces only, excluding personal space.
        const response = await fetch('/api-pool/', {credentials:'same-origin', cache:'no-store', signal:abort.signal});
        if (!response.ok || !response.headers.get('content-type')?.includes('text/html') || new URL(response.url).pathname === '/login/') throw Error('请重新登录后查看团队积分。');
        const page = new DOMParser().parseFromString(await response.text(), 'text/html');
        const choices = page.querySelectorAll('.ownership-filter select[name="ownership"] option');
        for (const source of choices) {
          if (!/^\d+$/.test(source.value)) continue;
          const option = document.createElement('option'); option.value = source.value; option.textContent = source.textContent; option.selected = source.selected; select.append(option);
        }
        if (!select.options.length) { status.textContent = '加入团队后可查看团队积分。'; status.className = ''; teamLabel.hidden = true; balance.hidden = true; view.append(link('寻找团队', '', '/team-square/', 'team')); return; }
        await load();
      } catch (error) { status.className = ''; status.textContent = error.name === 'AbortError' ? '连接超时，请重试。' : error.message; retry.hidden = false; }
      finally { clearTimeout(timeout); }
    }
    teams();
  }
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
