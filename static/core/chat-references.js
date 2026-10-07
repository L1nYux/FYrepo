(() => {
  document.querySelectorAll('[data-messages], [data-personal-thread]').forEach(root => {
    const fetch=(url,options)=>window.fetch(window.workbenchMessageURL(url,root),options);
    const dialog = root.querySelector('[data-reference-picker]');
    const form = root.querySelector('[data-message-form]');
    const input = form.querySelector('[name=references]');
    const chosen = form.querySelector('[data-chosen-references]');
    const results = dialog.querySelector('[data-reference-results]');
    const search = dialog.querySelector('[data-reference-search]');
    const initial = document.getElementById('selected-chat-references');
    const selected = new Map((initial ? JSON.parse(initial.textContent) : []).map(item => [item.key, item]));
    let kind = 'task', timer, sequence = 0, controller;
    function renderSelected() {
      input.value = JSON.stringify([...selected.keys()]);
      chosen.replaceChildren(); chosen.hidden = !selected.size;
      selected.forEach(item => {
        const chip = document.createElement('div'); chip.className = 'chosen-reference';
        const text = document.createElement('span'); text.textContent = item.label + ' · ' + item.title;
        const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'icon-button';
        remove.textContent = '×'; remove.setAttribute('aria-label', '移除引用：' + item.title);
        remove.addEventListener('click', () => { selected.delete(item.key); renderSelected(); });
        chip.append(text, remove); chosen.append(chip);
      });
      root.dispatchEvent(new Event('message-content-change'));
    }
    function notice(text) {
      const p = document.createElement('p'); p.className = 'reference-search-notice'; p.textContent = text; results.replaceChildren(p);
    }
    root.addEventListener('message-draft', event => {
      selected.clear(); event.detail.references.forEach(item => selected.set(item.key, item)); renderSelected();
    });
    async function load() {
      const current = ++sequence;
      if (controller) controller.abort(); controller = new AbortController();
      const url = new URL(dialog.dataset.searchUrl, location.origin);
      url.searchParams.set('kind', kind); url.searchParams.set('q', search.value);
      notice('正在查找…');
      try {
        const response = await fetch(url, {signal: controller.signal});
        if (!response.ok) throw Error('unavailable');
        const data = await response.json(); if (current !== sequence || !dialog.open) return;
        results.replaceChildren();
        data.results.forEach(item => {
          const button = document.createElement('button'); button.type = 'button'; button.className = 'reference-search-item';
          const label = document.createElement('small'); label.textContent = item.label + ' · ' + item.status;
          const title = document.createElement('strong'); title.textContent = item.title;
          const added = selected.has(item.key); button.disabled = added;
          if (added) label.textContent += ' · 已添加';
          button.append(label, title);
          button.addEventListener('click', () => {
            if (selected.size >= 5) { notice('最多引用 5 条，请先移除一条已选内容。'); return; }
            selected.set(item.key, item); renderSelected(); dialog.close(); form.querySelector('textarea').focus();
          });
          results.append(button);
        });
        if (!data.results.length) notice('没有找到可引用的内容。');
      } catch (error) { if (error.name !== 'AbortError' && current === sequence) notice('暂时无法加载，请重新选择类型或搜索。'); }
    }
    function chooseKind(value) {
      kind = value;
      dialog.querySelectorAll('[data-reference-kind]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.referenceKind === kind)));
      search.placeholder = kind === 'finance' ? '搜索账目说明或报销事由…' : '搜索标题或编号…';
      load();
    }
    root.querySelectorAll('[data-add-reference]').forEach(button => button.addEventListener('click', () => {
      button.closest('details').open = false;
      search.value = ''; dialog.showModal(); chooseKind(button.dataset.addReference); search.focus();
    }));
    dialog.querySelectorAll('[data-reference-kind]').forEach(button => button.addEventListener('click', () => chooseKind(button.dataset.referenceKind)));
    dialog.querySelector('[data-reference-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => { clearTimeout(timer); ++sequence; if (controller) controller.abort(); });
    search.addEventListener('input', () => { clearTimeout(timer); ++sequence; if (controller) controller.abort(); timer = setTimeout(load, 250); });
    search.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); clearTimeout(timer); load(); } });
    const menu = root.querySelector('[data-composer-plus]');
    document.addEventListener('click', event => { if (!menu.contains(event.target)) menu.open = false; });
    menu.querySelector('input[type=file]').addEventListener('change', () => { menu.open = false; });
    renderSelected();
  });
})();
