(() => {
  const body = document.body;
  const closeSidebar = () => body.classList.remove('sidebar-open');
  document.querySelectorAll('[data-sidebar-toggle]').forEach(button => button.addEventListener('click', () => body.classList.toggle('sidebar-open')));
  document.querySelectorAll('[data-sidebar-close]').forEach(button => button.addEventListener('click', closeSidebar));
  document.querySelectorAll('.shell-sidebar a').forEach(link => link.addEventListener('click', closeSidebar));
  const compact = matchMedia('(max-width: 1180px)');
  const detailButtons = document.querySelectorAll('[data-details-toggle]');
  const syncDetails = () => detailButtons.forEach(button => button.setAttribute('aria-expanded', String(compact.matches ? body.classList.contains('details-open') : !body.classList.contains('details-hidden'))));
  detailButtons.forEach(button => button.addEventListener('click', () => {
    body.classList.toggle(compact.matches ? 'details-open' : 'details-hidden');
    syncDetails();
  }));
  compact.addEventListener('change', () => { body.classList.remove('details-open'); syncDetails(); });
  syncDetails();
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { closeSidebar(); body.classList.remove('details-open'); syncDetails(); document.querySelectorAll('[data-account-menu],.action-menu').forEach(menu => menu.open = false); }
  });
  document.addEventListener('click', event => {
    document.querySelectorAll('[data-account-menu],.action-menu').forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
  });
  // Keep old bookmarked section links working with the new server-rendered tabs.
  const locationUrl = new URL(window.location.href);
  if (!locationUrl.searchParams.has('tab')) {
    const hash = locationUrl.hash;
    let targetTab;
    if (/^\/projects\/\d+\/$/.test(locationUrl.pathname)) {
      if (hash === '#tree') targetTab = 'tasks';
      else if (hash === '#results' || hash === '#review' || hash.startsWith('#submission-')) targetTab = 'results';
    } else if (locationUrl.pathname === '/finance/' && (hash === '#claims' || hash === '#claim-new')) targetTab = 'claims';
    else if (locationUrl.pathname === '/account/' && hash === '#password') targetTab = 'security';
    if (targetTab) { locationUrl.searchParams.set('tab', targetTab); window.location.replace(locationUrl.href); }
  }
  document.querySelectorAll('.task-composer').forEach(composer => {
    const tabs = composer.querySelectorAll('[data-compose-tab]');
    tabs.forEach(tab => {
      tab.setAttribute('aria-pressed', String(tab.classList.contains('selected')));
      tab.addEventListener('click', () => {
        tabs.forEach(item => { item.classList.toggle('selected', item === tab); item.setAttribute('aria-pressed', String(item === tab)); });
        composer.querySelectorAll('[data-compose-panel]').forEach(panel => { panel.hidden = panel.dataset.composePanel !== tab.dataset.composeTab; });
      });
    });
    composer.querySelectorAll('input[type=file][name=attachments]').forEach(input => input.addEventListener('change', () => {
      const names = input.closest('form').querySelector('[data-file-names]');
      if (names) { names.textContent = Array.from(input.files).map(file => file.name).join('、'); names.title = names.textContent; }
    }));
  });
})();
