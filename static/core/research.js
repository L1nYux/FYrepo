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
  document.querySelectorAll('[data-inline-experiment]').forEach(root => {
    const toggle = root.querySelector('[data-inline-experiment-toggle]');
    const fields = root.querySelector('[data-inline-experiment-fields]');
    function sync() {
      fields.hidden = fields.disabled = !toggle.checked;
      root.closest('.task-composer').classList.toggle('has-inline-record', toggle.checked);
    }
    toggle.addEventListener('change', sync); sync();
  });
  document.querySelectorAll('[data-compare-form]').forEach(form => form.addEventListener('submit', event => {
    const count = form.querySelectorAll('[name=ids]:checked').length;
    if (count < 2 || count > 3) { event.preventDefault(); alert('请选择 2–3 条记录。'); }
  }));
  function paintUnread(data) {
    document.querySelectorAll('[data-total-unread]').forEach(badge => { badge.textContent = data.total > 99 ? '99+' : data.total; badge.hidden = !data.total; });
    document.querySelectorAll('[data-channel-unread]').forEach(badge => { const count = data.channels[badge.dataset.channelUnread] || 0; badge.textContent = count > 99 ? '99+' : count; badge.hidden = !count; });
  }
  const unread = document.querySelector('[data-unread-url]');
  let reading = false;
  function refreshUnread() {
    if (!unread || document.hidden || reading) return;
    reading = true;
    fetch(unread.dataset.unreadUrl).then(response => { if (!response.ok) throw Error('offline'); return response.json(); }).then(paintUnread).catch(() => {}).finally(() => { reading = false; });
  }
  if (unread) { refreshUnread(); setInterval(refreshUnread, 12000); }
  document.querySelectorAll('[data-messages]').forEach(root => {
    const log = root.querySelector('[data-message-log]');
    const status = root.querySelector('[data-message-status]');
    const form = root.querySelector('[data-message-form]');
    let busy = false;
    function append(item) {
      const row = document.createElement('article'); row.className = 'message-bubble-row' + (item.mine ? ' mine' : ''); row.dataset.id = item.id;
      const avatar = document.createElement('span'); avatar.className = 'conversation-avatar'; avatar.textContent = item.initial;
      const bubble = document.createElement('div'); bubble.className = 'message-bubble';
      const byline = document.createElement('div'); byline.className = 'message-byline';
      const author = document.createElement('strong'); author.textContent = item.author;
      const at = document.createElement('small'); at.textContent = item.at;
      byline.append(author, at); bubble.append(byline);
      if (item.body) { const text = document.createElement('p'); text.textContent = item.body; bubble.append(text); }
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
      row.append(avatar, bubble); log.append(row);
    }
    function poll() {
      if (busy || document.hidden) return;
      busy = true;
      const last = log.querySelector('[data-id]:last-of-type');
      const url = new URL(root.dataset.pollUrl, location.origin); url.searchParams.set('after', last ? last.dataset.id : '0');
      fetch(url).then(response => { if (!response.ok) throw Error('offline'); return response.json(); }).then(data => {
        const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 70;
        if (data.messages.length) { const empty = log.querySelector('[data-message-empty]'); if (empty) empty.remove(); }
        data.messages.forEach(append);
        if (stick) log.scrollTop = log.scrollHeight;
        status.textContent = '已连接';
        if (data.messages.length) refreshUnread();
      }).catch(() => { status.textContent = '正在重新连接…'; }).finally(() => { busy = false; });
    }
    const box = form.querySelector('textarea');
    box.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
    });
    form.querySelector('input[type=file]').addEventListener('change', event => {
      form.querySelector('[data-message-files]').textContent = [...event.target.files].map(file => file.name).join('、');
    });
    log.scrollTop = log.scrollHeight; poll(); setInterval(poll, 4000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) { poll(); refreshUnread(); } });
  });
})();
