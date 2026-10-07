(() => {
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const drawer = $('[data-sampling-drawer]');
  let returnFocus;
  const closeDrawer = () => { drawer?.close(); returnFocus?.focus(); };
  $$('[data-open-drawer]').forEach(b => b.addEventListener('click', e => {
    if (!drawer) return;
    e.preventDefault(); returnFocus = b; drawer.showModal(); $('[name=name]', drawer)?.focus();
  }));
  $$('[data-close-drawer]').forEach(b => b.addEventListener('click', closeDrawer));
  drawer?.addEventListener('click', e => { if (e.target === drawer) closeDrawer(); });
  $$('dialog[data-auto-open]').forEach(d => d.showModal());
  const bundle = $('[data-bundle-dialog]');
  $('[data-open-bundle]')?.addEventListener('click', () => bundle.showModal());
  $('[data-close-bundle]')?.addEventListener('click', () => bundle.close());

  const form = $('[data-scope-form]');
  if (form) {
    const registry = JSON.parse($('#sampling-journal-registry').textContent);
    const checked = name => $$(`input[name="${name}"]:checked`, form).map(x => x.value);
    const hold = $('[name=holdout_enabled]', form);
    const items = $$('[data-journal-item]', form);
    const search = $('[data-journal-search]', form);
    const all = $('[data-journal-all]', form);
    function journals(clearHidden = false) {
      const periods = checked('periods');
      if (hold.checked) periods.push('P3');
      const tiers = new Set(checked('selected_tiers'));
      const query = search.value.trim().toLowerCase();
      items.forEach(item => {
        const box = $('input', item), journal = box.value;
        const base = Object.keys(registry.tiers).find(t => registry.tiers[t].includes(journal));
        const allowed = [...new Set(periods.map(p => registry.period_tier_overrides?.[journal]?.[p] || base))].filter(t => tiers.has(t));
        if (clearHidden && !allowed.length) box.checked = false;
        item.hidden = !(allowed.length && journal.toLowerCase().includes(query)) && !(box.checked && !clearHidden);
        $('[data-journal-tier]', item).textContent = allowed.join(' / ');
      });
      const visible = items.filter(x => !x.hidden).map(x => $('input', x));
      all.checked = visible.length > 0 && visible.every(x => x.checked);
      all.indeterminate = visible.some(x => x.checked) && !all.checked;
      all.disabled = !visible.length;
      $('[data-journal-empty]', form).hidden = visible.length > 0;
      $('[data-journal-count]', form).textContent = `已选择 ${checked('selected_journals').length} 本期刊`;
    }
    function holdout() {
      $('[data-holdout-fields]', form).hidden = !hold.checked;
      ['holdout_n', 'holdout_start', 'holdout_end'].forEach(name => {
        const field = $(`[data-field="${name}"]`, form), input = $('input', field);
        input.disabled = !hold.checked; input.required = hold.checked;
        let star = $('.sampling-required', field);
        if (!star) { star = document.createElement('span'); star.className = 'sampling-required'; star.textContent = ' *'; $('label', field).append(star); }
        star.hidden = !hold.checked;
        if (!hold.checked) setError(field, '');
      });
    }
    function setError(field, message) {
      field.classList.toggle('has-error', !!message);
      $('.sampling-field-errors', field).textContent = message;
      $$('input, select', field).forEach(x => x.setAttribute('aria-invalid', message ? 'true' : 'false'));
    }
    function firstError() {
      const field = $('.sampling-field.has-error', form);
      if (!field) return;
      field.scrollIntoView({block: 'center'});
      $$('input,select', field).find(x => !x.disabled && x.getClientRects().length)?.focus({preventScroll: true});
    }
    holdout(); journals();
    hold.addEventListener('change', () => { holdout(); journals(true); });
    $$('input[name=periods],input[name=selected_tiers]', form).forEach(x => x.addEventListener('change', () => journals(true)));
    $$('input[name=selected_journals]', form).forEach(x => x.addEventListener('change', () => journals()));
    search.addEventListener('input', () => journals());
    all.addEventListener('change', () => { items.filter(x => !x.hidden).forEach(x => $('input', x).checked = all.checked); journals(); });
    $('[data-journal-clear]', form).addEventListener('click', () => { items.forEach(x => $('input', x).checked = false); journals(); });
    form.addEventListener('input', e => {
      const field = e.target.closest('[data-field]');
      if (field && field.classList.contains('has-error') && e.target.validity?.valid && (e.target.value || e.target.checked)) setError(field, '');
    });
    form.addEventListener('submit', e => {
      let errors = 0;
      $$('[data-field]', form).forEach(field => {
        const name = field.dataset.field;
        let message = '';
        if (['periods', 'selected_tiers', 'selected_journals'].includes(name)) {
          if (!checked(name).length) message = ({periods: '请至少选择一个研究时期', selected_tiers: '请至少选择一个期刊层级', selected_journals: '请至少选择一本期刊'})[name];
        } else {
          const input = $('input,select', field);
          if (input && !input.disabled) {
            if ((input.required || input.dataset.required) && !input.value.trim()) message = name === 'name' ? '请输入样本集名称' : '请填写此必填内容';
            else if (!input.validity.valid) message = input.type === 'number' ? `请输入 ${input.min}–${input.max} 范围内的整数` : '请检查填写内容';
          }
        }
        if (hold.checked && name === 'holdout_end') {
          const start = $('[name=holdout_start]', form).value, end = $('[name=holdout_end]', form).value;
          if (start && end && Number(start) > Number(end)) message = '结束年份不能早于开始年份';
        }
        setError(field, message); if (message) errors++;
      });
      const summary = $('[data-error-summary]', form);
      summary.hidden = !errors; summary.textContent = `还有 ${errors} 项内容需要完善`;
      if (errors) { e.preventDefault(); firstError(); }
    });
    if ($('.has-error', form)) { $$('[data-field].has-error', form).forEach(field => $$('input,select', field).forEach(x => x.setAttribute('aria-invalid', 'true'))); requestAnimationFrame(firstError); }
  }

  const tabs = $$('[data-sampling-tab]');
  const showTab = key => {
    if (!tabs.some(b => b.dataset.samplingTab === key)) key = 'overview';
    tabs.forEach(b => { const active = b.dataset.samplingTab === key; b.classList.toggle('active', active); b.setAttribute('aria-selected', String(active)); });
    $$('[data-sampling-panel]').forEach(p => p.hidden = p.dataset.samplingPanel !== key);
  };
  tabs.forEach(b => b.addEventListener('click', () => { showTab(b.dataset.samplingTab); history.replaceState(null, '', '#' + b.dataset.samplingTab); }));
  showTab(location.hash.slice(1) || new URLSearchParams(location.search).get('tab') || 'overview');
  $$('[data-sampling-go]').forEach(b => b.addEventListener('click', () => showTab(b.dataset.samplingGo)));
  const freeze = $('[data-freeze-submit]'), freezeDialog = $('[data-freeze-dialog]');
  freeze?.addEventListener('click', e => { e.preventDefault(); freezeDialog.showModal(); });
  $('[data-freeze-cancel]')?.addEventListener('click', () => freezeDialog.close());
  $('[data-freeze-confirm]')?.addEventListener('click', () => { freezeDialog.close(); freeze.form.submit(); });
  const reviewForm = $('[data-review-form]');
  $('[data-review-all]')?.addEventListener('click', () => $$('[data-review-check]').forEach(c => c.checked = true));
  $('[data-review-none]')?.addEventListener('click', () => $$('[data-review-check]').forEach(c => c.checked = false));
  $$('[data-review-submit]').forEach(b => b.addEventListener('click', () => {
    const count = $$('[data-review-check]:checked').length;
    if (!count) { alert('请至少勾选一篇待复核论文'); return; }
    if (confirm(`确认将 ${count} 篇论文设为${b.dataset.reviewSubmit === 'include' ? '选入' : '排除'}？`)) { $('[name=action]', reviewForm).value = b.dataset.reviewSubmit; reviewForm.submit(); }
  }));
  const docs = $('[data-document-status-url]');
  if (docs && docs.dataset.processing === 'true') {
    const timer = setInterval(async () => {
      try { const r = await fetch(docs.dataset.documentStatusUrl); if (!r.ok) throw Error(); const d = await r.json();
        $('[data-document-progress]', docs).textContent = `等待 ${d.queued} · 转换中 ${d.running} · 已完成 ${d.ready} · 需检查 ${d.review} · 失败 ${d.failed}`;
        if (d.queued + d.running === 0) { clearInterval(timer); location.reload(); }
      } catch { clearInterval(timer); $('[data-document-progress]', docs).textContent = '状态暂不可用，请刷新页面重试'; }
    }, 2500);
  }
})();
