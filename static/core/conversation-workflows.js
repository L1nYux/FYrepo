/* Conversation components share geometry and explicit interaction states. */
(() => {
  'use strict';
  const X = window.zhiyuExperience;
  const el = (tag, text, cls) => {
    const value = document.createElement(tag);
    if (text !== undefined) value.textContent = text;
    if (cls) value.className = cls;
    return value;
  };
  const button = (text, cls) => { const value = el('button', text, cls); value.type = 'button'; return value; };
  const icon = kind => X.toolIcon(kind);
  const token = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
  function modal(cls, label) {
    const value = el('dialog', undefined, cls);
    value.setAttribute('aria-label', label);
    value.addEventListener('close', () => value.remove(), {once:true});
    value.addEventListener('click', event => { if (event.target === value && value.dataset.busy !== 'true') {
      const r = value.getBoundingClientRect();
      if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) value.close();
    }});
    document.body.append(value); return value;
  }
  function avatar(item) {
    const box = el('span', undefined, 'chat-recipient-avatar');
    if (item.avatar_url) {
      const img = el('img'); img.src = item.avatar_url; img.alt = ''; img.loading = 'lazy';
      img.onerror = () => { img.remove(); box.textContent = (item.title || '群').slice(0, 1); }; box.append(img);
    } else box.textContent = (item.title || '群').slice(0, 1);
    return box;
  }
  function recipient(item, quick = false) {
    const value = button(undefined, quick ? 'chat-recipient-quick' : 'chat-recipient-row');
    value.append(avatar(item), el('span', item.title)); return value;
  }
  const recipients = () => window.zhiyuRuntime.query('/app/forward/', {ttl:30000});
  function fileCard(file) {
    const value = el('div', undefined, 'chat-share-file'), copy = el('span', undefined, 'chat-share-file-copy');
    const type = file.type || file.name.split('.').pop().toUpperCase();
    const bytes = Number(file.size);
    copy.append(el('strong', file.name));
    if (file.size != null) copy.append(el('small', bytes < 1048576 ? (bytes / 1024).toFixed(1) + ' KB' : (bytes / 1048576).toFixed(1) + ' MB'));
    const mark = el('span', type === 'DOCX' || type === 'DOC' ? 'W' : type, 'file-type-icon');
    mark.dataset.fileType = type; value.append(copy, mark); return value;
  }
  function summary(cards, root) {
    if (root.hasAttribute('data-file-view')) return {file:{name:root.dataset.name, size:root.dataset.size || null, type:root.dataset.type}};
    const card = cards[0], file = card.querySelector('.file-card');
    if (cards.length > 1) return {text:cards.length + ' 条聊天消息'};
    if (file) return {file:{name:file.dataset.fileName, size:file.dataset.size || null, type:file.dataset.fileType}};
    const image = card.querySelector('.message-sticker,.message-photo,.message-image img');
    return image ? {image:image.src} : {text:card.querySelector('[data-message-body]')?.innerText || '聊天消息'};
  }
  function renderSummary(value) {
    if (value.file) return fileCard(value.file);
    if (value.image) { const img = el('img', undefined, 'chat-share-image'); img.src = value.image; img.alt = '转发的图片'; return img; }
    return el('p', value.text, 'chat-share-text');
  }
  function sourceKey(root) {
    if (root.hasAttribute('data-file-view')) return root.dataset.channel;
    if (root.dataset.channel === 'developers') return 'team:' + root.dataset.team;
    const path = location.pathname.match(/^\/messages\/(personal|groups)\/(\d+)\/$/);
    if (path) return (path[1] === 'personal' ? 'person:' : 'group:') + path[2];
    return root.dataset.channel?.replace(/^dm:/, 'person:');
  }
  async function forward(rows, root, options = {}) {
    const cards = Array.isArray(rows) ? rows : [rows], source = sourceKey(root);
    if (!source || !cards.length) { X.toast('原消息不可用。'); return; }
    const value = summary(cards, root), tokens = new Map(cards.map(card => [card, token()])), completed = new Set();
    let page, confirmation, busy = false, selected, fixedNote, lockedTarget, destroyed = false;
    const id = card => card.dataset.messageId || card.dataset.id || card.dataset.cachedId;
    const finish = () => { destroyed = true; confirmation?.close(); page?.close(); root.dispatchEvent(new Event('experience-selection-clear')); X.toast('已转发'); };
    function confirm(item) {
      if(busy)return;
      if(lockedTarget&&lockedTarget!==item.key){X.toast('请向原接收人重试，以确认上一次的转发结果。');return;}
      selected = item;
      confirmation?.close();
      confirmation = modal('chat-bottom-sheet chat-forward-confirm', '确认转发');
      const current = confirmation, heading = el('p', '发送给：', 'chat-sheet-label'), target = recipient(item), note = el('textarea'), status = el('p', '', 'chat-workflow-status');
      target.append(el('span', '›', 'chat-recipient-arrow'));
      target.onclick = () => { if (!busy && !completed.size) { current.close(); choose(); } };
      note.placeholder = '留言'; note.setAttribute('aria-label', '转发留言'); note.maxLength = 2000; note.rows = 1;
      if (fixedNote !== undefined) note.value = fixedNote;
      const actions = el('div', undefined, 'chat-confirm-actions'), cancel = button('取消'), send = button(completed.size ? '继续发送' : '发送', 'primary');
      actions.append(cancel, send); current.append(heading, target, renderSummary(value), note, status, actions);
      cancel.onclick = () => current.close();
      current.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
      send.onclick = async () => {
        if (busy) return; busy = true; current.dataset.busy='true'; lockedTarget=item.key; fixedNote ??= note.value.trim();
        send.disabled = cancel.disabled = target.disabled = note.disabled = true; send.textContent = '发送中…'; status.textContent = '';
        try {
          for (const card of cards) {
            if (completed.has(card)) continue;
            await X.json('/app/forward/', {source, id:id(card), target:selected.key, token:tokens.get(card), confirm:'yes',
              body:card.querySelector('[data-message-body]')?.innerText || '',
              attachment:root.hasAttribute('data-file-view') ? root.dataset.fileKind + ':' + root.dataset.fileId : '',
              note:card === cards[0] ? fixedNote : ''});
            completed.add(card);
          }
          finish();
        } catch (error) {
          status.textContent = (cards.length > 1 ? '已转发 ' + completed.size + '/' + cards.length + ' 条。' : '') + error.message;
          send.textContent = '重试'; send.disabled = false; cancel.disabled = false;
          // Retrying uses the same destination, note and request tokens.
        } finally { busy = false; delete current.dataset.busy; }
      };
      current.showModal(); send.focus({preventScroll:true});
    }
    async function choose() {
      if (page?.isConnected) { page.focus(); return; }
      page = modal('chat-recipient-page', '选择转发对象');
      const current = page;
      const header = el('header', undefined, 'chat-page-header'), back = button('‹', 'chat-back'), title = el('h2', '选择聊天');
      back.setAttribute('aria-label', '取消转发'); back.onclick = () => current.close(); header.append(back, title, el('span'));
      const search = el('input'), searchBox = el('div', undefined, 'chat-recipient-search'), tabs = el('nav', undefined, 'chat-recipient-tabs'), list = el('div', undefined, 'chat-recipient-list'), status = el('p', '正在读取…', 'chat-workflow-status');
      search.type = 'search'; search.placeholder = '搜索联系人或群聊'; search.setAttribute('aria-label', search.placeholder); searchBox.append(search);
      current.append(header, searchBox, tabs, list, status); current.showModal();
      let category = 'recent', catalog;
      function paint() {
        if (!catalog || !current.isConnected || page !== current) return;
        tabs.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.category === category)));
        list.replaceChildren(); const query = search.value.trim().toLocaleLowerCase();
        const items = query ? catalog.all : catalog[category];
        for (const item of items.filter(i => !query || (i.title + ' ' + (i.account || '')).toLocaleLowerCase().includes(query))) {
          const row = recipient(item); row.onclick = () => confirm(item); list.append(row);
        }
        status.textContent = list.children.length ? '' : query ? '没有匹配的联系人或群聊' : '暂无会话，可以从联系人或群聊中选择';
      }
      for (const [name, label] of [['recent', '最近聊天'], ['contacts', '联系人'], ['groups', '群聊']]) {
        const b = button(label); b.dataset.category = name; b.onclick = () => { category = name; paint(); }; tabs.append(b);
      }
      search.oninput = paint;
      try { catalog = options.directory || await recipients(); if (!destroyed) paint(); }
      catch (error) { if (current.isConnected && page === current) { status.textContent = error.message; const retry = button('重新加载'); retry.onclick = () => { current.close(); window.zhiyuRuntime.invalidate(); choose(); }; list.append(retry); } }
    }
    if (options.recipient) confirm(options.recipient); else await choose();
  }
  async function fileActions(root, actions) {
    document.querySelector('.chat-file-actions')?.close();
    const sheet = modal('chat-bottom-sheet chat-file-actions', '文件操作');
    const recent = el('section', undefined, 'chat-share-recent'), label = el('h2', '转发给'), quick = el('div', undefined, 'chat-share-quick'), status = el('p', '', 'chat-workflow-status');
    recent.append(label, quick, status);
    if (root.dataset.channel) sheet.append(recent);
    const grid = el('div', undefined, 'chat-file-action-grid');
    for (const action of actions) {
      const b = button(undefined); b.append(el('span', undefined, 'chat-action-icon'), el('span', action.label));
      b.firstChild.append(icon(action.icon)); b.disabled = !!action.disabled; b.dataset.action=action.icon;
      b.onclick = async () => { sheet.close(); try { await action.run(); } catch (error) { X.toast(error.message); } };
      grid.append(b);
    }
    const cancel = button('取消', 'chat-sheet-cancel'); cancel.onclick = () => sheet.close(); sheet.append(grid, cancel); sheet.showModal();
    if (root.dataset.channel) try {
      const data = await recipients(); if (!sheet.isConnected) return;
      for (const item of data.recent.slice(0, 8)) {
        const b = recipient(item, true); b.onclick = () => { sheet.close(); forward(root, root, {recipient:item, directory:data}); }; quick.append(b);
      }
      status.textContent = data.recent.length ? '' : '通过“转发给朋友”选择联系人或群聊';
    } catch (error) { if (sheet.isConnected) status.textContent = error.message; }
  }
  let stickerBox, closeSticker;
  function stickerActions(anchor, sticker, actions) {
    closeSticker?.();
    const box = el('div', undefined, 'chat-sticker-popover'), img = el('img'), menu = el('div', undefined, 'chat-sticker-actions');
    img.src = sticker.url; img.alt = sticker.name; box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', '表情操作');
    const dismiss = () => { box.remove(); document.removeEventListener('pointerdown', away, true); window.removeEventListener('resize', dismiss); window.removeEventListener('scroll', dismiss, true); if (stickerBox === box) stickerBox = null; };
    const away = event => { if (!box.contains(event.target)) dismiss(); };
    for (const action of actions) { const b = button(action.label, action.danger ? 'danger' : ''); b.onclick = async () => { dismiss(); try { await action.run(); } catch (error) { X.toast(error.message); } }; menu.append(b); }
    box.append(img, menu); document.body.append(box); stickerBox = box; closeSticker = dismiss;
    const rect = anchor.getBoundingClientRect(), width = box.offsetWidth, height = box.offsetHeight;
    const above = rect.top - height - 12 >= 8;
    box.style.left = Math.max(8, Math.min(rect.left + (rect.width - width) / 2, innerWidth - width - 8)) + 'px';
    box.style.top = Math.max(8, Math.min(above ? rect.top - height - 12 : rect.bottom + 12, innerHeight - height - 8)) + 'px';
    box.dataset.placement = above ? 'above' : 'below';
    box.style.setProperty('--pointer-x', Math.max(18, Math.min(width - 18, rect.left + rect.width / 2 - parseFloat(box.style.left))) + 'px');
    document.addEventListener('pointerdown', away, true); window.addEventListener('resize', dismiss); window.addEventListener('scroll', dismiss, true);
    box.addEventListener('keydown', event => { if (event.key === 'Escape') dismiss(); }); menu.firstChild?.focus({preventScroll:true});
  }
  function previewSticker(sticker) {
    const box = modal('chat-sticker-preview', '表情预览'), img = el('img'), close = button('×', 'chat-preview-close');
    img.src = sticker.url; img.alt = sticker.name; close.setAttribute('aria-label', '关闭预览'); close.onclick = () => box.close(); box.append(close, img); box.showModal();
  }
  window.zhiyuChatUI = {forward, fileActions, stickerActions, previewSticker};
})();
