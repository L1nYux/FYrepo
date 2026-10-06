(() => {
  let panel, history = [], position = -1, controller;
  function create() {
    if (panel) return;
    panel = document.createElement('aside');
    panel.className = 'web-source-panel';
    panel.setAttribute('aria-label', '网页来源');
    panel.innerHTML = '<header><button type="button" data-back aria-label="返回上一来源">←</button><button type="button" data-reload aria-label="刷新来源">↻</button><button type="button" data-expand aria-pressed="false">放大</button><a data-external target="_blank" rel="noopener noreferrer">新窗口打开原网页 ↗</a><button type="button" data-close aria-label="收起网页">×</button></header><p class="web-source-address"></p><div class="web-source-content" role="status"></div>';
    document.body.append(panel);
    panel.querySelector('[data-expand]').addEventListener('click', event => {
      const expanded = panel.classList.toggle('is-expanded');
      event.currentTarget.textContent = expanded ? '还原' : '放大';
      event.currentTarget.setAttribute('aria-pressed', String(expanded));
    });
    panel.querySelector('[data-close]').addEventListener('click', () => {
      panel.hidden = true;
      document.body.classList.remove('web-source-open');
      controller?.abort();
    });
    panel.querySelector('[data-back]').addEventListener('click', () => {
      if (position > 0) read(history[--position], false);
    });
    panel.querySelector('[data-reload]').addEventListener('click', () => read(history[position], false));
  }
  function show(url) {
    create();
    panel.hidden = false;
    document.body.classList.add('web-source-open');
    panel.querySelector('[data-back]').disabled = position <= 0;
    panel.querySelector('[data-external]').href = url;
    panel.querySelector('.web-source-address').textContent = url;
    return panel.querySelector('.web-source-content');
  }
  async function read(url, push = true) {
    if (!url) return;
    controller?.abort();
    const request = controller = new AbortController();
    const current = () => controller === request && !request.signal.aborted;
    if (window.workbenchBrowser) {
      try {
        const value = await window.workbenchBrowser.open(url);
        if (current() && value?.ok === false) show(url).textContent = value.error || '网页无法打开。';
      } catch (_) {
        if (current()) show(url).textContent = '浏览器暂不可用，请重试或打开原网页。';
      }
      return;
    }
    if (push) {
      history = history.slice(0, position + 1);
      history.push(url);
      position = history.length - 1;
    }
    const body = show(url);
    body.textContent = '正在读取网页…';
    try {
      const response = await fetch('/assistant/web-preview/?' + new URLSearchParams({ url }), {
        signal: request.signal, cache: 'no-store'
      });
      if (!current()) return;
      if (!response.headers.get('content-type')?.includes('application/json')) throw Error('请重新登录。');
      const data = await response.json();
      if (!current()) return;
      if (!response.ok) throw Error(data.error || '页面无法预览，请打开原网页。');
      body.replaceChildren();
      const title = document.createElement('h2');
      title.textContent = data.source.title;
      const text = document.createElement('div');
      text.textContent = data.content;
      body.append(title, text);
      if (data.truncated) {
        const hint = document.createElement('p');
        hint.textContent = '预览已截取，可打开原网页查看完整内容。';
        body.append(hint);
      }
    } catch (error) {
      if (current() && error.name !== 'AbortError') body.textContent = error.message;
    }
  }
  document.addEventListener('click', event => {
    const link = event.target.closest('a[data-web-source],.assistant-text a');
    if (!link || !/^https?:\/\//.test(link.href) || new URL(link.href).origin === location.origin) return;
    event.preventDefault();
    read(link.href);
  });
  window.addEventListener('pagehide', () => controller?.abort(), { once: true });
})();
