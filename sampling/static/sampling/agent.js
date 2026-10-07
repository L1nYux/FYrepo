/* 本机连接码只发往 loopback；工作台写入始终使用同源 CSRF。 */
(() => {
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  const decode = async response => {
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('服务未返回可读取的结果，请检查连接或重新登录工作台。'); }
    if (!response.ok || data.ok === false || data.error) throw new Error(data.error || `请求失败 (${response.status})`);
    return data;
  };
  document.querySelectorAll('[data-agent-root]').forEach(root => {
    const find = name => root.querySelector(`[data-agent-${name}]`);
    const key = `fyrepo-agent-job:${root.dataset.runId}`;
    let job = null, polling = false, syncing = false;
    try { job = JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) { /* 存储不可用时仍可采集 */ }
    const save = () => { try { localStorage.setItem(key, JSON.stringify(job)); } catch (_) {} };
    const status = (message, connected = false) => {
      if (find('status')) find('status').textContent = message;
      if (find('dot')) find('dot').classList.toggle('ok', connected);
    };
    const progress = message => { if (find('progress')) find('progress').textContent = message; };
    const local = async (path, options = {}) => {
      const token = find('token')?.value.trim();
      if (!token) throw new Error('请先填写本机终端显示的连接码。');
      const origin = new URL(root.dataset.agentOrigin);
      if (!['127.0.0.1', 'localhost'].includes(origin.hostname) || origin.protocol !== 'http:') throw new Error('采集器地址须为本机 HTTP loopback。');
      try {
        return await fetch(new URL(path, origin), {...options, cache: 'no-store', credentials: 'omit',
          headers: {'X-Sampling-Agent-Token': token, ...(options.body && !(options.body instanceof FormData) ? {'Content-Type':'application/json'} : {}), ...options.headers},
          signal: AbortSignal.timeout(30000)});
      } catch (_) { throw new Error('无法连接本机采集器。请确认已启动、工作台地址已授权，并允许浏览器访问本地网络。'); }
    };
    const workbench = async (url, options = {}) => {
      if (new URL(url, location.href).origin !== location.origin) throw new Error('工作台回传地址必须同源。');
      return decode(await fetch(url, {...options, credentials:'same-origin',
        headers: {'Accept':'application/json', 'X-CSRFToken':csrf(), ...(options.body && !(options.body instanceof FormData) ? {'Content-Type':'application/json'} : {}), ...options.headers}}));
    };
    const action = (name, callback) => find(name)?.addEventListener('click', async event => {
      const button = event.currentTarget;
      button.disabled = true;
      try { await callback(); } catch (error) { status(error.message); progress(error.message); }
      finally { button.disabled = false; }
    });
    const sync = async state => {
      if (syncing || job?.synced) return;
      syncing = true;
      if (find('sync')) find('sync').hidden = true;
      try {
        const result = await decode(await local(`/jobs/${job.id}/result`));
        if (String(result.run_id) !== String(root.dataset.runId)) throw new Error('任务不属于当前样本集，已停止回传。');
        if (state.kind === 'collect') {
          if (!result.records.length) throw new Error('采集完成但没有题录。请检查知网查询和权限后重新采集。');
          // 小批回传；重试仍以稳定键去重，不制造重复候选。
          for (let offset = job.offset || 0; offset < result.records.length; offset += 25) {
            await workbench(root.dataset.importUrl, {method:'POST', body:JSON.stringify({records:result.records.slice(offset, offset + 25), scope_signature:result.scope_signature})});
            job.offset = offset + 25; save();
            progress(`已写回 ${Math.min(job.offset, result.records.length)} / ${result.records.length} 条题录`);
          }
        } else if (state.kind === 'pdf') {
          await workbench(root.dataset.pdfReportUrl, {method:'POST', body:JSON.stringify({records:result.records.map(r => ({paper_id:r.paper_id, status:r.status}))})});
          const rows = result.records.filter(row => row.pdf_file);
          for (let offset = job.offset || 0; offset < rows.length; offset++) {
            const row = rows[offset];
            const response = await local(`/jobs/${job.id}/files/${row.paper_id}`);
            if (!response.ok) throw new Error(`无法读取 ${row.paper_id} 的本机 PDF`);
            const file = await response.blob();
            const form = new FormData();
            form.append('paper_id', row.paper_id);
            form.append('file', file, row.original_name || row.pdf_file.split(/[\\/]/).pop());
            await workbench(root.dataset.pdfUploadUrl, {method:'POST', body:form});
            job.offset = offset + 1; save();
            progress(`已上传 ${job.offset} / ${rows.length} 份 PDF，正在排队转换`);
          }
        }
        job.synced = true; save();
        progress(state.kind === 'pdf' ? '下载报告与取得的 PDF 已写回；未取得的全文请人工补充。' : '真实候选题录已写入工作台。');
        location.hash = state.kind === 'pdf' ? 'documents' : 'candidates';
        location.reload();
      } catch (error) {
        status(error.message); progress(`写回未完成：${error.message}`);
        if (find('sync')) find('sync').hidden = false;
      } finally { syncing = false; }
    };
    const poll = async () => {
      if (!job || polling) return;
      polling = true;
      try {
        const state = await decode(await local(`/jobs/${job.id}`));
        if (String(state.run_id) !== String(root.dataset.runId)) throw new Error('任务不属于当前样本集。');
        status(state.message || state.status, true);
        if (find('log')) { find('log').textContent = (state.log || []).join('\n') || state.message; find('log').scrollTop = find('log').scrollHeight; }
        if (state.status === 'completed' && !job.synced) {
          if (state.kind === 'install') { job.synced = true; save(); progress('组件已安装，可以打开知网登录。'); }
          else await sync(state);
        } else if (['queued','running'].includes(state.status)) {
          progress(state.kind === 'pdf' ? '本机正在下载，任务结束后上传可用 PDF。' : '本机任务执行中，保持采集器运行。');
          setTimeout(poll, 2000);
        } else if (state.status === 'failed' || state.status === 'stopped') progress(state.message || '任务已停止，重新开始可续接已完成批次。');
      } catch (error) { status(error.message); progress('任务保存在本机。恢复连接后点击“检查连接”继续。'); }
      finally { polling = false; }
    };
    const start = async (kind, body) => {
      const response = await decode(await local(`/${kind}`, {method:'POST', body:JSON.stringify(body)}));
      job = {id:response.job_id, offset:0, synced:false}; save();
      poll();
    };
    action('check', async () => {
      const data = await decode(await local('/status'));
      status(data.package?.integrity_error || data.package?.installed_error || (!data.engine_available && data.message) ||
        (data.engine_ready ? (data.login_ready ? '采集器已连接，登录资料已就绪' : '采集器已连接，请完成知网登录') : '采集器已连接，请安装 / 修复采集组件'), true);
      if (job && !job.synced) await poll();
    });
    action('install', () => start('install', {run_id:Number(root.dataset.runId)}));
    action('login', async () => { const data = await decode(await local('/login/open', {method:'POST', body:'{}'})); status(data.message || '请在本机打开的浏览器中完成登录和验证码。', true); });
    action('login-done', async () => { const data = await decode(await local('/login/finish', {method:'POST', body:'{}'})); status(data.message || '本机登录资料已保存。', true); });
    action('start', async () => {
      const data = await workbench(root.dataset.configUrl);
      await start('collect', {...data.config, concurrency:Number(find('concurrency')?.value || 2), year_chunk_size:Number(find('year-chunk')?.value || 2)});
    });
    action('pdf', async () => { const data = await workbench(root.dataset.pdfConfigUrl); await start('pdf', {run_id:data.run_id, records:data.records}); });
    action('stop', async () => {
      if (!job) throw new Error('当前没有本机任务。');
      const data = await decode(await local(`/jobs/${job.id}/stop`, {method:'POST', body:'{}'}));
      progress(data.message || '已请求停止。');
    });
    action('sync', async () => { if (job) await sync(await decode(await local(`/jobs/${job.id}`))); });
    if (job && !job.synced) progress('有一个未完成的本机任务，填写连接码并检查连接后继续。');
  });
})();
