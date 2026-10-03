(() => {
  const presetsNode = document.getElementById('experiment-presets');
  const presets = presetsNode ? JSON.parse(presetsNode.textContent) : [];
  document.querySelectorAll('[data-parameters]').forEach(editor => {
    const rows = editor.querySelector('[data-parameter-rows]');
    const prefix = editor.dataset.prefix ? editor.dataset.prefix + '-' : '';
    function addRow(name = '', value = '') {
      const row = document.createElement('div'); row.className = 'parameter-row';
      const key = document.createElement('input'); key.name = prefix + 'parameter_name'; key.value = name; key.maxLength = 80; key.placeholder = '参数名，例如设备、样本量'; key.setAttribute('aria-label', '参数名');
      const field = document.createElement('input'); field.name = prefix + 'parameter_value'; field.value = value; field.maxLength = 2000; field.placeholder = '值或说明'; field.setAttribute('aria-label', '参数值');
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'icon-button'; remove.dataset.removeParameter = ''; remove.textContent = '×'; remove.setAttribute('aria-label', '删除参数');
      row.append(key, field, remove); rows.append(row);
    }
    editor.querySelector('[data-add-parameter]').addEventListener('click', () => { if (rows.children.length < 40) addRow(); });
    rows.addEventListener('click', event => {
      const remove = event.target.closest('[data-remove-parameter]');
      if (remove) { remove.closest('.parameter-row').remove(); if (!rows.children.length) addRow(); }
    });
    const apply = editor.querySelector('[data-apply-preset]');
    if (apply) apply.addEventListener('click', () => {
      const selected = presets.find(item => String(item.id) === editor.querySelector('[data-parameter-preset]').value);
      if (!selected) return;
      if ([...rows.querySelectorAll('input')].some(input => input.value.trim()) && !confirm('用模板参数替换当前参数？')) return;
      rows.replaceChildren(); selected.parameters.forEach(item => addRow(item.name, item.value));
      if (!rows.children.length) addRow();
    });
  });
  document.querySelectorAll('[data-compare-form]').forEach(form => form.addEventListener('submit', event => {
    const count = form.querySelectorAll('[name=ids]:checked').length;
    if (count < 2 || count > 3) { event.preventDefault(); alert('请选择 2–3 条记录。'); }
  }));
  function paintUnread(data) {
    document.querySelectorAll('[data-total-unread]').forEach(badge => { badge.textContent = data.total > 99 ? '99+' : data.total; badge.hidden = !data.total; });
    document.querySelectorAll('[data-channel-unread]').forEach(badge => { const count = data.channels[badge.dataset.channelUnread] || 0; badge.textContent = count > 99 ? '99+' : count; badge.hidden = !count; });
    if (data.presence) document.querySelectorAll('[data-user-presence]').forEach(dot => {
      const online = Boolean(data.presence[dot.dataset.userPresence]);
      dot.classList.toggle('online', online); dot.title = online ? '在线' : '离线'; dot.setAttribute('aria-label', dot.title);
    });
  }
  function csrfToken() {
    const cookie = document.cookie.split('; ').find(item => item.startsWith('csrftoken='));
    return cookie ? decodeURIComponent(cookie.slice(10)) : document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  }
  function pageActive() { return !document.hidden && window.workbenchActive !== false; }
  const unread = document.querySelector('[data-unread-url]');
  let reading = false;
  function refreshUnread() {
    if (!unread || !pageActive() || reading || window.workbenchDesktop === true) return;
    reading = true;
    fetch(unread.dataset.unreadUrl, {method: 'POST', headers: {'X-CSRFToken': csrfToken()}, cache: 'no-store'}).then(response => { if (!response.ok) throw Error('offline'); return response.json(); }).then(paintUnread).catch(() => {}).finally(() => { reading = false; });
  }
  if (unread) { refreshUnread(); setInterval(refreshUnread, 12000); }
  window.addEventListener('workbench:presence', event => paintUnread(event.detail));
  document.querySelectorAll('[data-messages]').forEach(root => {
    const log = root.querySelector('[data-message-log]');
    const status = root.querySelector('[data-message-status]');
    const form = root.querySelector('[data-message-form]');
    let busy = false;
    let lastSeen = Math.max(0, ...[...log.querySelectorAll('[data-id]')].map(row => Number(row.dataset.id)));
    const locallyRemoved = new Set();
    let feedbackUntil = 0;
    function feedback(text) { status.textContent = text; feedbackUntil = Date.now() + 5000; }
    function syncEmpty() {
      const empty = log.querySelector('[data-message-empty]');
      if (log.querySelector('[data-id]')) { empty?.remove(); return; }
      if (!empty) { const hint = document.createElement('div'); hint.className = 'conversation-empty'; hint.dataset.messageEmpty = ''; hint.textContent = '还没有消息，发条消息开始讨论。'; log.append(hint); }
    }
    function removeMessage(id) { log.querySelector('[data-id="' + id + '"]')?.remove(); syncEmpty(); }
    let lastAcknowledged = 0, acknowledging = false;
    function acknowledge() {
      if (!pageActive() || !document.hasFocus() || acknowledging || log.scrollHeight - log.scrollTop - log.clientHeight > 70) return;
      const rows = log.querySelectorAll('[data-id]');
      const last = Number(rows[rows.length - 1]?.dataset.id || 0);
      if (!last || last <= lastAcknowledged) return;
      acknowledging = true;
      fetch(root.dataset.readUrl, {method:'POST', headers: {'X-CSRFToken':csrfToken()},
        body: new URLSearchParams({channel:root.dataset.channel, last:String(last)})})
        .then(response => { if (!response.ok) throw Error('offline'); return response.json(); })
        .then(data => { lastAcknowledged = last; paintUnread(data); })
        .catch(() => {}).finally(() => acknowledging = false);
    }
    function append(item) {
      if (locallyRemoved.has(item.id)) { removeMessage(item.id); return; }
      const row = document.createElement(item.withdrawn ? 'div' : 'article'); row.className = (item.withdrawn ? 'message-system-note' : 'message-bubble-row') + (item.mine ? ' mine' : ''); row.dataset.id = item.id;
      row.dataset.withdrawn = String(Boolean(item.withdrawn)); row.dataset.actionUrl = item.action_url; row.tabIndex = 0;
      row.setAttribute('aria-label', item.withdrawn ? '撤回提示' : item.author + '的消息，右键打开菜单');
      if (item.withdrawn) {
        const text = document.createElement('span'); text.textContent = (item.mine ? '你' : item.author) + '撤回了一条消息'; row.append(text);
        if (item.mine) { const edit = document.createElement('button'); edit.type = 'button'; edit.dataset.messageAction = 'draft'; edit.textContent = '重新编辑'; row.append(edit); }
      } else {
      const avatar = document.createElement('span'); avatar.className = 'conversation-avatar'; avatar.textContent = item.initial;
      const bubble = document.createElement('div'); bubble.className = 'message-bubble';
      const byline = document.createElement('div'); byline.className = 'message-byline';
      const author = document.createElement('strong'); author.textContent = item.author;
      const at = document.createElement('small'); at.textContent = item.at;
      byline.append(author, at); bubble.append(byline);
      if (item.body) { const text = document.createElement('p'); text.dataset.messageBody = ''; text.textContent = item.body; bubble.append(text); }
      (item.references || []).forEach(ref => {
        const card = document.createElement(ref.available ? 'a' : 'div');
        card.className = 'chat-reference-card' + (ref.available ? '' : ' unavailable');
        if (ref.available) card.href = ref.url;
        const label = document.createElement('small'); label.textContent = ref.label + (ref.status ? ' · ' + ref.status : '');
        const title = document.createElement('strong'); title.textContent = ref.title; card.append(label, title);
        if (ref.available) { const hint = document.createElement('span'); hint.textContent = '查看详情 ↗'; card.append(hint); }
        bubble.append(card);
      });
      item.attachments.forEach(file => { const link = document.createElement('a'); link.className = 'attach'; link.textContent = file.name; link.href = file.url; bubble.append(link); });
      row.append(avatar, bubble);
      }
      const previous = log.querySelector('[data-id="' + item.id + '"]');
      if (previous) previous.replaceWith(row);
      else { const next = [...log.querySelectorAll('[data-id]')].find(old => Number(old.dataset.id) > item.id); log.insertBefore(row, next || null); }
      const visibleRows = [...log.querySelectorAll('[data-id]')];
      visibleRows.slice(0, Math.max(0, visibleRows.length - 200)).forEach(old => old.remove());
      syncEmpty();
      return row;
    }
    function poll() {
      if (busy || !pageActive()) return;
      busy = true;
      const url = new URL(root.dataset.pollUrl, location.origin); url.searchParams.set('after', String(lastSeen));
      url.searchParams.set('known', [...log.querySelectorAll('[data-id]')].slice(-200).map(row => row.dataset.id).join(','));
      fetch(url, {cache:'no-store'}).then(response => { if (!response.ok) throw Error('offline'); return response.json(); }).then(data => {
        const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 70;
        data.messages.forEach(item => { lastSeen = Math.max(lastSeen, item.id); if (!locallyRemoved.has(item.id) && !log.querySelector('[data-id="' + item.id + '"]')) append(item); });
        (data.updates || []).forEach(item => { const row = log.querySelector('[data-id="' + item.id + '"]'); if (row && row.dataset.withdrawn !== 'true') append(item); });
        (data.removed || []).forEach(removeMessage);
        if (stick) log.scrollTop = log.scrollHeight;
        if (Date.now() > feedbackUntil) status.textContent = '已连接';
        if (data.messages.length || data.removed?.length) refreshUnread();
        acknowledge();
      }).catch(() => { status.textContent = '正在重新连接…'; }).finally(() => { busy = false; });
    }
    const box = form.querySelector('textarea');
    const menu = document.createElement('div'); menu.className = 'message-context-menu'; menu.dataset.messageMenu = ''; menu.hidden = true; menu.setAttribute('role', 'menu'); root.append(menu);
    let menuRow, actionBusy = false;
    const draftId = form.querySelector('[name=resend_message]');
    let retainedFiles = Number(draftId.dataset.retainedFiles || 0);
    const draftNotice = form.querySelector('[data-message-draft-notice]');
    const draftText = form.querySelector('[data-message-draft-text]');
    function closeMenu() { menu.hidden = true; menuRow = null; }
    async function copyMessage(row) {
      const text = row.querySelector('[data-message-body]')?.textContent || '';
      if (navigator.clipboard && window.isSecureContext) { try { await navigator.clipboard.writeText(text); return; } catch (_) {} }
      const focused = document.activeElement;
      const temporary = document.createElement('textarea'); temporary.value = text; temporary.style.cssText = 'position:fixed;left:-9999px'; document.body.append(temporary); temporary.select();
      const copied = document.execCommand('copy'); temporary.remove(); focused?.focus(); if (!copied) throw Error('复制失败，请选中文字复制。');
    }
    async function action(row, name) {
      if (actionBusy) return; closeMenu();
      if (name === 'draft' && sending) { feedback('正在发送，请稍后重新编辑。'); return; }
      if (name === 'draft' && (box.value.trim() || form.querySelector('input[type=file]').files.length || hasReferences()) && !confirm('用这条撤回的消息替换当前输入内容？')) return;
      actionBusy = true;
      const removing = name === 'delete' || name === 'withdraw';
      const id = Number(row.dataset.id), next = row.nextSibling, scrollTop = log.scrollTop;
      let committed = false;
      if (removing) { locallyRemoved.add(id); row.remove(); syncEmpty(); }
      try {
        if (name === 'copy') { await copyMessage(row); feedback('已复制'); return; }
        const response = await fetch(row.dataset.actionUrl, {method:'POST', headers:{'X-CSRFToken':csrfToken()}, body:new URLSearchParams({action:name}), cache:'no-store'});
        const result = response.headers.get('content-type')?.includes('application/json') ? await response.json() : {};
        if (!response.ok) throw Error(result.error || '操作失败，消息可能已不可用或你无权操作。');
        if (result.deleted) { committed = true; feedback('已从你的记录中删除'); refreshUnread(); }
        if (result.message) { committed = true; locallyRemoved.delete(result.message.id); append(result.message); feedback('已撤回'); refreshUnread(); }
        if (result.draft) {
          box.value = result.draft.body; draftId.value = result.draft.id;
          retainedFiles = result.draft.attachments.length;
          form.querySelector('input[type=file]').value = ''; form.querySelector('[data-message-files]').textContent = '';
          root.dispatchEvent(new CustomEvent('message-draft', {detail:result.draft}));
          draftText.textContent = '重新编辑消息' + (result.draft.attachments.length ? ' · 保留附件：' + result.draft.attachments.join('、') : ''); draftNotice.hidden = false;
          box.focus(); updateComposer(); feedback('修改后发送一条新消息');
        }
      } catch (error) {
        if (removing && !committed) { locallyRemoved.delete(id); if (!log.querySelector('[data-id="' + id + '"]')) log.insertBefore(row, next?.parentNode === log ? next : null); syncEmpty(); log.scrollTop = scrollTop; }
        feedback(error.message);
      }
      finally { actionBusy = false; }
    }
    function openMenu(row, x, y) {
      closeMenu(); menuRow = row; menu.replaceChildren();
      const choices = [];
      if (row.querySelector('[data-message-body]')) choices.push(['copy', '复制']);
      if (row.classList.contains('mine') && row.dataset.withdrawn !== 'true') choices.push(['withdraw', '撤回']);
      choices.push(['delete', '删除']);
      choices.forEach(([name, text]) => { const button = document.createElement('button'); button.type = 'button'; button.role = 'menuitem'; button.textContent = text; if (name === 'delete') button.className = 'danger'; button.addEventListener('click', () => action(row, name)); menu.append(button); });
      menu.hidden = false; const rect = row.getBoundingClientRect();
      menu.style.left = Math.max(6, Math.min(x || rect.left + 20, window.innerWidth - menu.offsetWidth - 6)) + 'px';
      menu.style.top = Math.max(6, Math.min(y || rect.top + 20, window.innerHeight - menu.offsetHeight - 6)) + 'px'; menu.querySelector('button').focus();
    }
    log.addEventListener('contextmenu', event => { const row = event.target.closest('[data-id]'); if (!row) return; event.preventDefault(); event.stopPropagation(); openMenu(row, event.clientX, event.clientY); });
    log.addEventListener('click', event => { const edit = event.target.closest('[data-message-action="draft"]'); if (edit) action(edit.closest('[data-id]'), 'draft'); });
    log.addEventListener('keydown', event => { if (event.key === 'F10' && event.shiftKey) { const row = event.target.closest('[data-id]'); if (row) { event.preventDefault(); openMenu(row, 0, 0); } } });
    menu.addEventListener('keydown', event => {
      if (event.key === 'Escape') { const row = menuRow; closeMenu(); row?.focus(); event.preventDefault(); }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { const buttons = [...menu.querySelectorAll('button')]; const index = buttons.indexOf(document.activeElement); buttons[(index + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length].focus(); event.preventDefault(); }
    });
    document.addEventListener('pointerdown', event => { if (!menu.contains(event.target)) closeMenu(); }, true);
    log.addEventListener('scroll', closeMenu); window.addEventListener('blur', closeMenu); window.addEventListener('resize', closeMenu);
    form.querySelector('[data-message-draft-cancel]').addEventListener('click', () => { draftId.value = ''; retainedFiles = 0; draftNotice.hidden = true; updateComposer(); });
    const fileInput = form.querySelector('input[type=file]');
    const sendButton = form.querySelector('.composer-footer button.primary');
    let sending = false;
    function hasReferences() { try { return JSON.parse(form.querySelector('[name=references]').value || '[]').length > 0; } catch (_) { return false; } }
    function updateComposer() {
      sendButton.disabled = sending || !(box.value.trim() || fileInput.files.length || hasReferences() || retainedFiles);
      sendButton.textContent = sending ? '发送中…' : '发送 ↑';
      box.style.height = 'auto'; box.style.height = Math.min(160, Math.max(48, box.scrollHeight)) + 'px';
    }
    box.addEventListener('input', updateComposer); root.addEventListener('message-content-change', updateComposer);
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (sending) return;
      if (!(box.value.trim() || fileInput.files.length || hasReferences() || retainedFiles)) { box.focus(); return; }
      const picker = root.querySelector('[data-reference-picker]'); if (picker?.open) picker.close();
      const payload = new FormData(form); sending = true; updateComposer();
      form.querySelectorAll('textarea,input[type=file],button,[data-chosen-references]').forEach(node => { if ('disabled' in node) node.disabled = true; });
      try {
        const response = await fetch(form.action, {method:'POST', headers:{'X-CSRFToken':csrfToken(), Accept:'application/json'}, body:payload});
        const result = response.headers.get('content-type')?.includes('application/json') ? await response.json() : {};
        if (!response.ok || !result.message) {
          const errors = Object.values(result.errors || {}).flat().map(error => error.message).join(' ');
          throw Error(errors || '未确认发送结果，输入内容已保留；请先查看消息再重试。');
        }
        append(result.message); box.value = ''; fileInput.value = ''; draftId.value = ''; retainedFiles = 0; draftNotice.hidden = true;
        form.querySelectorAll('.errorlist').forEach(node => node.remove());
        root.dispatchEvent(new CustomEvent('message-draft', {detail:{references:[]}}));
        form.querySelector('[data-message-files]').textContent = ''; log.scrollTop = log.scrollHeight; feedback('已发送'); refreshUnread();
      } catch (error) { feedback(error instanceof TypeError ? '连接中断，输入内容已保留；请先查看消息再重试。' : error.message); }
      finally {
        sending = false; form.querySelectorAll('textarea,input[type=file],button').forEach(node => node.disabled = false); updateComposer(); box.focus();
      }
    });
    box.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
    });
    fileInput.addEventListener('change', event => {
      form.querySelector('[data-message-files]').textContent = [...event.target.files].map(file => file.name).join('、');
      updateComposer();
    });
    updateComposer();
    log.scrollTop = log.scrollHeight; poll(); setInterval(poll, 2000);
    log.addEventListener('scroll', acknowledge);
    window.addEventListener('focus', () => { poll(); acknowledge(); refreshUnread(); });
    document.addEventListener('workbench-visibility', () => { if (pageActive()) { poll(); acknowledge(); refreshUnread(); } });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) { poll(); refreshUnread(); } });
  });
  function positionKey() { return 'workbench-position:' + location.pathname + location.search; }
  function rememberPosition() {
    const value = {y:window.scrollY};
    ['.sidebar-scroll','.conversation-list','.conversation-log'].forEach(selector => {
      const node=document.querySelector(selector); if(node) value[selector]=node.scrollTop;
    });
    try { sessionStorage.setItem(positionKey(),JSON.stringify(value)); } catch (_) {}
  }
  window.restoreWorkbenchPosition = () => {
    try {
      const value=JSON.parse(sessionStorage.getItem(positionKey()) || 'null'); if(!value) return;
      window.scrollTo(0,value.y || 0);
      ['.sidebar-scroll','.conversation-list','.conversation-log'].forEach(selector => {
        const node=document.querySelector(selector); if(node && value[selector] !== undefined) node.scrollTop=value[selector];
      });
    } catch (_) {}
  };
  window.addEventListener('pagehide',rememberPosition);
  window.addEventListener('beforeunload',rememberPosition);
  requestAnimationFrame(window.restoreWorkbenchPosition);
})();
