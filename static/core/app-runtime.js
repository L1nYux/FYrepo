/* Page-local infrastructure. Business permissions remain authoritative on the server. */
(() => {
  'use strict';
  if (window.zhiyuRuntime) return;
  const reads = new Map(), pendingReads = new Set(), mounts = new WeakMap(), scopes = new Set();
  let revision = 0;
  const cancelled = () => new DOMException('操作已取消', 'AbortError');
  const identity = () => [document.documentElement.dataset.account || '', document.documentElement.dataset.resourceOwner || document.documentElement.dataset.workspace || ''].join(':');
  const clone = value => typeof structuredClone === 'function' ? structuredClone(value) : JSON.parse(JSON.stringify(value));
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || decodeURIComponent(document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] || '');

  class RequestError extends Error {
    constructor(message, status = 0, uncertain = false) {
      super(message); this.name = 'RequestError'; this.status = status; this.uncertain = uncertain;
    }
  }
  function invalidate() { revision++; reads.clear(); }

  async function json(address, body, options = {}) {
    const url = new URL(address, location.href), writing = body !== undefined && body !== null;
    if (url.origin !== location.origin) throw new RequestError('请求地址不属于当前服务。');
    const controller = new AbortController(), owner = identity();
    let timedOut = false;
    const cancel = () => controller.abort();
    const timer = setTimeout(() => { timedOut = true; cancel(); }, options.timeout ?? 20000);
    if (!writing) pendingReads.add(controller);
    options.signal?.addEventListener('abort', cancel, {once:true});
    if (options.signal?.aborted) cancel();
    try {
      const response = await window.fetch(url.href, {
        credentials:'same-origin', cache:'no-store', method:writing ? 'POST' : 'GET',
        headers:{Accept:'application/json', ...(!writing ? options.headers : {}), ...(writing ? {'X-CSRFToken':options.csrf ?? csrf(), ...(options.format === 'json' ? {'Content-Type':'application/json'} : {})} : {})},
        body:writing && options.format === 'json' ? JSON.stringify(body) : body instanceof FormData || body instanceof URLSearchParams ? body : writing ? new URLSearchParams(body) : undefined,
        signal:controller.signal,
      });
      if (response.status === 401 || response.redirected && new URL(response.url).pathname === '/login/') {
        invalidate(); throw new RequestError('登录已失效，请重新登录。', 401);
      }
      if ([403,404].includes(response.status)) invalidate();
      if (!response.headers.get('content-type')?.includes('application/json')) {
        throw new RequestError(response.status === 403 ? '当前账号没有此操作权限。' : response.status === 404 ? '服务器需要同步升级才能使用此功能。' : '服务器返回异常，请重试。', response.status, writing && (response.ok || response.status >= 500));
      }
      const result = await response.json();
      if (controller.signal.aborted || owner !== identity()) throw cancelled();
      if (!response.ok) {
        const error = new RequestError(result.error || (response.status === 403 ? '当前账号没有此操作权限。' : '操作失败，请重试。'), response.status, writing && response.status >= 500);
        error.code = result.code; error.result = result; throw error;
      }
      // Also invalidate pending query generations: an older response cannot restore pre-write data.
      if (writing) invalidate();
      return result;
    } catch (error) {
      if (writing) invalidate();
      if (error.name === 'AbortError') {
        if (!timedOut) throw error;
        throw new RequestError(writing ? '连接超时，未确认操作结果，请先查看记录。' : '连接超时，请重试。', 0, writing);
      }
      if (error instanceof TypeError) throw new RequestError(writing ? '连接中断，未确认操作结果，请先查看记录。' : '网络暂不可用，请重试。', 0, writing);
      if (error instanceof SyntaxError) throw new RequestError('服务器返回的数据无法读取。', 0, writing);
      throw error;
    } finally {
      clearTimeout(timer); pendingReads.delete(controller); options.signal?.removeEventListener('abort', cancel);
    }
  }

  // Only explicit GET queries share work. Writes are never cached, merged or automatically retried.
  function query(address, options = {}) {
    const url = new URL(address, location.href), owner = identity(), deliveryGeneration = revision;
    const headers = Object.fromEntries(Object.entries(options.headers || {}).map(([name,value]) => [name.toLowerCase(),String(value)]));
    const variant = JSON.stringify(Object.entries(headers).sort(([a],[b]) => a.localeCompare(b)));
    const key = owner + '\n' + url.href + '\n' + variant;
    let row = reads.get(key);
    if (!row || row.expires && row.expires <= Date.now()) {
      const generation = revision;
      row = {expires:0}; reads.set(key, row);
      while (reads.size > 128) reads.delete(reads.keys().next().value);
      row.promise = json(url.href, undefined, {headers}).then(value => {
        if (generation !== revision || owner !== identity()) throw cancelled();
        const ttl = Math.max(0, Math.min(60000, Number(options.ttl) || 0));
        if (ttl) row.expires = Date.now() + ttl;
        else if (reads.get(key) === row) reads.delete(key);
        return value;
      }).catch(error => { if (reads.get(key) === row) reads.delete(key); throw error; });
    }
    // A subscriber may leave without cancelling another component's shared request.
    return new Promise((resolve, reject) => {
      const signal = options.signal, abort = () => reject(cancelled());
      signal?.addEventListener('abort', abort, {once:true});
      if (signal?.aborted) abort();
      row.promise.then(value => {
        try {
          if (signal?.aborted || owner !== identity() || deliveryGeneration !== revision) throw cancelled();
          resolve(clone(value));
        } catch (error) { reject(error); }
        finally { signal?.removeEventListener('abort', abort); }
      }, error => { signal?.removeEventListener('abort', abort); reject(error); });
    });
  }

  function latest(alive = () => true) {
    let sequence = 0, current;
    return {
      cancel() { sequence++; current?.abort(); current = null; },
      async run(work) {
        this.cancel(); const token = sequence, controller = new AbortController(); current = controller;
        try {
          const result = await work(controller.signal);
          if (token !== sequence || controller.signal.aborted || !alive()) throw cancelled();
          return result;
        } catch (error) {
          if (token !== sequence || controller.signal.aborted || !alive()) throw cancelled();
          throw error;
        } finally { if (current === controller) current = null; }
      },
    };
  }

  function mount(name, root, setup) {
    if (!root) return null;
    let entries = mounts.get(root); if (!entries) { entries = new Map(); mounts.set(root, entries); }
    if (entries.has(name)) return entries.get(name);
    const cleanups = [], requests = new Set(); let disposed = false;
    const scope = {
      alive:() => !disposed && root.isConnected,
      on(target, event, listener, options) {
        target.addEventListener(event, listener, options);
        cleanups.push(() => target.removeEventListener(event, listener, options));
      },
      cleanup(fn) { cleanups.push(fn); },
      latest() { const task = latest(scope.alive); requests.add(task); return task; },
      cancel() { requests.forEach(task => task.cancel()); },
      dispose() {
        if (disposed) return; disposed = true; scope.cancel();
        const errors = [];
        cleanups.reverse().forEach(fn => { try { fn(); } catch (error) { errors.push(error); } });
        entries.delete(name); scopes.delete(scope);
        if (errors.length) throw new AggregateError(errors, '组件清理失败');
      },
    };
    entries.set(name, scope); scopes.add(scope);
    try { setup(scope); } catch (error) { scope.dispose(); throw error; }
    return scope;
  }
  function unmount(root) {
    const errors = [];
    for (const scopeRoot of [root, ...root.querySelectorAll('*')]) {
      [...(mounts.get(scopeRoot)?.values() || [])].forEach(scope => { try { scope.dispose(); } catch (error) { errors.push(error); } });
    }
    if (errors.length) throw new AggregateError(errors, '组件清理失败');
  }
  window.addEventListener('pagehide', () => {
    pendingReads.forEach(controller => controller.abort()); scopes.forEach(scope => scope.cancel()); invalidate();
    // Keep event bindings for native back/forward cache restoration.
  });
  window.zhiyuRuntime = {json, query, invalidate, latest, mount, unmount, RequestError};
})();
