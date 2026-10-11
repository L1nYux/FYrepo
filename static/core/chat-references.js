(() => {
  document.querySelectorAll('[data-messages], [data-personal-thread]').forEach(root => {
    const dialog = root.querySelector('[data-reference-picker]');
    const form = root.querySelector('[data-message-form]');
    if(!dialog||!form)return;
    window.zhiyuRuntime.mount('chat-references', root, scope => {
    const lookup = scope.latest();
    const input = form.querySelector('[name=references]');
    const chosen = form.querySelector('[data-chosen-references]');
    const results = dialog.querySelector('[data-reference-results]');
    const search = dialog.querySelector('[data-reference-search]');
    const initial = document.getElementById('selected-chat-references');
    const selected = new Map((initial ? JSON.parse(initial.textContent) : []).map(item => [item.key, item]));
    let kind = 'task', timer;
    scope.cleanup(() => clearTimeout(timer));
    function renderSelected() {
      input.value = JSON.stringify([...selected.keys()]);dialog.querySelector('[data-reference-count]').textContent=selected.size+'/5';
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
    scope.on(root,'message-draft', event => {
      selected.clear(); event.detail.references.forEach(item => selected.set(item.key, item)); renderSelected();
    });
    async function load() {
      const url = new URL(dialog.dataset.searchUrl, location.origin);
      url.searchParams.set('kind', kind); url.searchParams.set('q', search.value);
      notice('正在查找…');
      try {
        const data = await lookup.run(signal => window.zhiyuRuntime.json(window.workbenchMessageURL(url,root), undefined, {signal}));
        if (dialog.hidden) return;
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
            selected.set(item.key, item); renderSelected(); closePage();
          });
          results.append(button);
        });
        if (!data.results.length) notice('没有找到可引用的内容。');
      } catch (error) { if (error.name !== 'AbortError' && scope.alive() && !dialog.hidden) notice(error.message); }
    }
    function chooseKind(value) {
      kind = value;
      dialog.querySelectorAll('[data-reference-kind]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.referenceKind === kind)));
      search.placeholder = kind === 'finance' ? '搜索账目说明或报销事由…' : '搜索名称、项目或编号…';dialog.querySelector('h2').textContent=({project:'项目',task:'任务',document:'文档',experiment:'实验',finance:'财务',announcement:'公告'}[kind]||'内容');
      load();
    }
    root.querySelectorAll('[data-add-reference]').forEach(button => scope.on(button,'click', () => {
      button.closest('details').open = false;
      search.value='';openPage(button.dataset.addReference);
    }));
    dialog.querySelectorAll('[data-reference-kind]').forEach(button => scope.on(button,'click', () => chooseKind(button.dataset.referenceKind)));
    let returnFocus;
    function openPage(value,push=true){returnFocus=document.activeElement;dialog.hidden=false;dialog.dataset.active='true';root.querySelector('textarea')?.blur();if(push){const url=new URL(location.href);url.searchParams.set('picker','references');url.searchParams.set('kind',value);history.pushState({zhiyuPicker:true},'',url);}chooseKind(value);dialog.querySelector('[data-reference-close]').focus();}
    function hidePage(){dialog.hidden=true;delete dialog.dataset.active;clearTimeout(timer);lookup.cancel();returnFocus?.focus({preventScroll:true});}
    function closePage(){if(history.state?.zhiyuPicker)history.back();else{hidePage();const url=new URL(location.href);url.searchParams.delete('picker');url.searchParams.delete('kind');history.replaceState(null,'',url);}}
    scope.on(dialog.querySelector('[data-reference-close]'),'click',closePage);
    scope.on(window,'popstate',()=>{const url=new URL(location.href);if(url.searchParams.get('picker')==='references')openPage(url.searchParams.get('kind')||'task',false);else hidePage();});
    scope.on(dialog,'keydown',e=>{if(e.key==='Escape'){e.preventDefault();closePage();}});
    scope.on(window,'pagehide',()=>{clearTimeout(timer);lookup.cancel();});
    const entry=new URL(location.href);if(entry.searchParams.get('picker')==='references')openPage(entry.searchParams.get('kind')||'task',false);
    scope.on(search,'input', () => { clearTimeout(timer); lookup.cancel(); timer = setTimeout(load, 250); });
    scope.on(search,'keydown', event => { if (event.key === 'Enter') { event.preventDefault(); clearTimeout(timer); load(); } });
    const menu = root.querySelector('[data-composer-plus]');
    scope.on(document,'click', event => { if (!menu.contains(event.target)) menu.open = false; });
    scope.on(menu.querySelector('input[type=file]'),'change', () => { menu.open = false; });
    renderSelected();
    });
  });
})();
