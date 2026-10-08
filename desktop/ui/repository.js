(() => {
  'use strict';
  const api = window.desktop, $ = id => document.getElementById(id);
  const normalize = text => text.replace(/\r\n|\r/g, '\n');
  let status, paths = [], file, base = '', dirty = false, mode = 'files', diffMode = false;
  let config = {}, loading, activationSequence = 0, busy = false, openSequence = 0, searchSequence = 0, searchTimer, toastTimer;
  let preview, action, retryPreview = false;
  const expanded = new Set();
  const call = async promise => { const result = await promise; if (!result.ok) throw Error(result.error); return result.data; };
  function toast(text) { $('toast').textContent = text; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 6000); }
  const guard = callback => async event => { try { await callback(event); } catch (error) { toast(error.message); } };
  function element(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
  const changed = name => status?.files.find(item => item.file === name);
  const label = item => item.conflict ? '冲突' : /D/.test(item.code) ? '删除' : item.code === '??' || /A/.test(item.code) ? '新增' : /R/.test(item.code) ? '重命名' : '修改';
  function configure(value) { config = {...config, ...value}; renderStatus(); }
  function renderStatus() {
    if (!status) return;
    $('repo-name').textContent = status.name; $('repo-name').title = status.path;
    $('repo-branch').textContent = status.branch;
    $('change-count').textContent = status.files.length;
    $('repo-status').textContent = status.conflicts ? `${status.conflicts} 个文件有冲突，请修正后保存` : status.files.length ? `${status.files.length} 个文件有改动` : status.ahead ? `${status.ahead} 个本地版本等待同步` : '文件已保存到本机';
    $('open-github').hidden = !status.github || !config.githubEnabled;
    $('repo-sync').disabled = busy || !config.githubEnabled || !status.hasRemote || status.detached;
    $('repo-sync').title = !config.githubEnabled ? '在设置中启用远程同步' : !status.hasRemote ? '当前仓库尚未关联远程' : '查看要提交的改动并同步';
    $('repo-pull').disabled = busy || !config.githubEnabled || !status.hasRemote;
    $('repo-commit-local').disabled = busy || status.detached;
    $('repo-save').disabled = busy || !file?.editable || (!dirty && !changed(file.file)?.conflict);
    $('repo-save').textContent = file && changed(file.file)?.conflict ? '保存并标记已解决' : '保存';
    $('repo-file-state').textContent = file ? dirty ? '有未保存的修改' : changed(file.file)?.conflict ? '需要解决冲突' : '已保存' : '直接查看和编辑内容';
    $('repo-editor').readOnly = busy;for(const id of ['repo-remove','repo-delete','open-repo','repo-history','refresh-repo'])$(id).disabled=busy||status.empty;
    ['choose-repo','repo-new-file','refresh-repo'].forEach(id => $(id).disabled = busy);
  }
  function clearFile() {
    file = undefined; base = ''; dirty = false; diffMode = false;
    $('repo-editor').value = ''; $('repo-editor').hidden = true; $('repo-diff').hidden = true;
    $('repo-image-wrap').hidden = true; $('repo-image').removeAttribute('src');
    $('repo-file-empty').hidden = false; $('repo-file-title').textContent = '选择一个文件';
    $('repo-file-empty').querySelector('h2').textContent = '文件就在这里';
    $('repo-empty-hint').textContent = '从左侧打开文件；文本和源码可直接编辑，Ctrl+S 保存。';
    $('repo-view-diff').hidden = true; $('repo-open-file').hidden = true;
    $('repo-path').textContent = ''; $('repo-file-meta').textContent = '';
  }
  function displayFile(value) {
    file = value; base = value.editable ? normalize(value.text) : ''; dirty = false; diffMode = false;
    $('repo-file-title').textContent = value.file.split('/').pop(); $('repo-file-title').title = value.file;
    $('repo-path').textContent = value.file;
    $('repo-file-meta').textContent = value.size < 1024 ? `${value.size} B` : `${(value.size / 1024).toFixed(1)} KB`;
    $('repo-editor').hidden = !value.editable; $('repo-editor').value = base;
    $('repo-diff').hidden = true; $('repo-view-diff').textContent = '查看差异';
    $('repo-image-wrap').hidden = value.kind !== 'image';
    if (value.kind === 'image') $('repo-image').src = value.url; else $('repo-image').removeAttribute('src');
    $('repo-file-empty').hidden = value.editable || value.kind === 'image';
    $('repo-file-empty').querySelector('h2').textContent = value.file.split('/').pop();
    $('repo-empty-hint').textContent = value.hint || '可在本机软件中打开。';
    $('repo-open-file').hidden = !value.canOpen;
    $('repo-view-diff').hidden = !changed(value.file);
    renderStatus(); renderTree();
  }
  async function activate() {
    if (loading) return loading;
    const sequence=activationSequence;
    const pending = (async () => {
      const [next, manifest,registry] = await Promise.all([call(api.repoStatus()), call(api.repoFiles()),call(api.repoList())]);
      if(sequence!==activationSequence)return;
      if (manifest.context !== next.context) throw Error('仓库正在切换，请稍后刷新。');
      const list=$('repository-list');list.replaceChildren();for(const item of registry.items){const button=element('button','repository-choice',item.name);button.type='button';button.title=item.path;button.setAttribute('aria-current',String(item.path===registry.selected));button.addEventListener('click',guard(async()=>{if(await call(api.repoSelect(item.path))){clearFile();await activate();}}));list.append(button);}
      if (status && next.context !== status.context) { clearFile(); expanded.clear(); $('repo-search').value = ''; }
      status = next; paths = manifest.files;
      renderStatus(); renderTree();
      if (manifest.truncated) toast('文件较多，仅显示前 20000 个；可使用内容搜索。');
    })();
    loading=pending;
    try { return await pending; } catch (error) { if(sequence!==activationSequence)return; $('repo-status').textContent = error.message; throw error; } finally { if(loading===pending)loading = undefined; }
  }
  function leaf(name, text, line, excerpt) {
    const row = element('button', 'repository-file-row' + (file?.file === name ? ' selected' : ''));
    row.type = 'button'; row.title = name; row.disabled = busy;
    row.append(element('span', 'repository-file-icon', '·'), element('span', 'repository-file-name', text));
    const item = changed(name); if (item) row.append(element('small', 'repository-change' + (item.conflict ? ' conflict' : ''), label(item)));
    if (excerpt !== undefined) { const wrapper = element('div','repository-search-hit'); wrapper.append(row, element('small','', `${line} · ${excerpt}`)); row.addEventListener('click', guard(() => openFile(name,line))); return wrapper; }
    row.addEventListener('click', guard(() => openFile(name,line))); return row;
  }
  function renderTree() {
    const root = $('repo-file-tree'); root.replaceChildren();
    $('repo-files-tab').setAttribute('aria-current',mode === 'files' ? 'page' : 'false');
    $('repo-changes-tab').setAttribute('aria-current',mode === 'changes' ? 'page' : 'false');
    if (!status) return;
    const query = $('repo-search').value.trim();
    if (mode === 'changes') {
      const matches = status.files.filter(item => !query || item.file.toLowerCase().includes(query.toLowerCase()));
      matches.forEach(item => root.append(leaf(item.file,item.file)));
      if (!matches.length) root.append(element('p','repository-tree-empty','暂无改动'));
      return;
    }
    if (query && $('repo-search-mode').value === 'content') { scheduleSearch(query); return; }
    searchSequence++;
    if (query) {
      const matches = paths.filter(name => name.toLowerCase().includes(query.toLowerCase()));
      matches.slice(0,500).forEach(name => root.append(leaf(name,name)));
      if (!matches.length) root.append(element('p','repository-tree-empty','没有找到文件'));
      else if (matches.length > 500) root.append(element('p','repository-tree-empty','请缩小搜索范围'));
      return;
    }
    const tree = {folders:new Map(),files:[]};
    for (const name of paths) {
      const parts = name.split('/'); let node = tree;
      for (let i=0;i<parts.length-1;i++) { if (!node.folders.has(parts[i])) node.folders.set(parts[i], {folders:new Map(),files:[]}); node = node.folders.get(parts[i]); }
      node.files.push({name,text:parts.at(-1)});
    }
    function append(node, parent, prefix) {
      for (const [name, child] of [...node.folders].sort(([a],[b]) => a.localeCompare(b))) {
        const directory = prefix + name + '/', open = expanded.has(directory);
        const button = element('button','repository-folder',`${open ? '▾' : '▸'}  ${name}`); button.type='button'; button.setAttribute('aria-expanded',open); button.disabled=busy;
        const container = element('div','repository-folder-children'); container.hidden = !open;
        button.addEventListener('click',() => { if (expanded.has(directory)) expanded.delete(directory); else expanded.add(directory); renderTree(); });
        parent.append(button,container); if (open) append(child,container,directory);
      }
      node.files.forEach(item => parent.append(leaf(item.name,item.text)));
    }
    append(tree,root,'');
    if (!paths.length) root.append(element('p','repository-tree-empty','仓库中还没有文件，点击 ＋ 创建'));
  }
  function scheduleSearch(query) {
    clearTimeout(searchTimer); const sequence = ++searchSequence, context = status.context;
    $('repo-file-tree').append(element('p','repository-tree-empty','正在搜索…'));
    searchTimer = setTimeout(async () => {
      try {
        const matches = await call(api.repoSearch(query,context));
        if (sequence !== searchSequence || status.context !== context) return;
        $('repo-file-tree').replaceChildren(); matches.forEach(item => $('repo-file-tree').append(leaf(item.file,item.file,item.line,item.text)));
        if (!matches.length) $('repo-file-tree').append(element('p','repository-tree-empty','没有找到内容'));
        else if (matches.length >= 120) $('repo-file-tree').append(element('p','repository-tree-empty','显示前 120 处，请缩小搜索范围'));
      } catch (error) { if (sequence === searchSequence) $('repo-file-tree').replaceChildren(element('p','repository-tree-empty',error.message)); }
    },300);
  }
  function draftValue() { return {file:file.file,context:file.context,version:file.version,text:$('repo-editor').value,resolveConflict:Boolean(changed(file.file)?.conflict)}; }
  async function openFile(name,line) {
    if (busy) return;
    if (!await call(api.repoLeave())) return;
    const sequence = ++openSequence, context = status.context;
    busy=true; renderStatus(); renderTree();
    try {
      const value = await call(api.repoRead(name));
      if (sequence !== openSequence || value.context !== context || status.context !== context) return;
      displayFile(value); jump(line);
    } catch (error) {
      if (sequence !== openSequence) return;
      if (!changed(name) || !/D/.test(changed(name).code)) throw error;
      clearFile(); file = {file:name,context,editable:false};
      $('repo-file-title').textContent = name; $('repo-path').textContent = name;
      $('repo-file-empty').hidden = true; diffMode = true;
      await displayDiff(); renderStatus(); renderTree();
    } finally { busy=false; renderStatus(); renderTree(); }
  }
  function jump(line) {
    if (!file?.editable || !line) return;
    const lines = $('repo-editor').value.split('\n'); const offset = lines.slice(0,line-1).reduce((sum,text) => sum+text.length+1,0);
    $('repo-editor').focus(); $('repo-editor').setSelectionRange(offset,offset+(lines[line-1]?.length || 0));
    $('repo-editor').scrollTop = Math.max(0,(line-3)*22);
  }
  async function save() {
    if (busy || !file?.editable) return;
    const name = file.file, context=file.context;
    busy=true; renderStatus(); renderTree();
    try {
      const value = await call(api.repoSave(draftValue()));
      if (file?.file === name && file.context === context) displayFile(value);
      await activate(); toast('文件已保存到本机');
    } finally { busy=false; renderStatus(); renderTree(); }
  }
  async function displayDiff() {
    if (!file) return; const name=file.file, context=file.context;
    const text = await call(api.repoDiff(name));
    if (file?.file !== name || file.context !== context) return;
    $('repo-diff').replaceChildren();
    text.split('\n').forEach(line => $('repo-diff').append(element('span','diff-line'+(line.startsWith('+') ? ' add' : line.startsWith('-') ? ' remove' : line.startsWith('@@') ? ' hunk' : ''),line || ' ')));
    $('repo-diff').hidden=false; $('repo-editor').hidden=true; $('repo-image-wrap').hidden=true; $('repo-file-empty').hidden=true;
    $('repo-view-diff').hidden=false; $('repo-view-diff').textContent = file.editable || file.kind === 'image' ? '返回文件' : '刷新差异';
  }
  async function toggleDiff() {
    if (!file || busy) return;
    if (diffMode && (file.editable || file.kind === 'image')) { diffMode=false; $('repo-diff').hidden=true; $('repo-editor').hidden=!file.editable; $('repo-image-wrap').hidden=file.kind !== 'image'; $('repo-view-diff').textContent='查看差异'; return; }
    if (dirty) { await save(); toast('已保存当前文件，展示保存后的差异'); }
    diffMode=true; await displayDiff();
  }
  function closeMore() { $('repo-more').open=false; }
  async function prepareSync(nextAction, keepValues=false) {
    if (busy) return; closeMore();
    if (dirty) await save();
    await activate(); action=nextAction; preview=status; retryPreview=false;
    const title = action === 'pull' ? '拉取更新' : action === 'commit' ? '保存本地版本' : '提交并同步';
    $('repo-sync-title').textContent=title; $('repo-sync-confirm').textContent=title;
    $('repo-sync-target').textContent = action === 'commit' ? `${status.branch} · 仅保存在这台电脑` : `${status.remoteDisplay || '尚未关联远程仓库'} · ${status.remoteBranch}`;
    $('repo-sync-files').replaceChildren();
    if (action === 'pull') $('repo-sync-files').append(element('p','muted',status.files.length ? '有本地改动，请先保存本地版本或同步。' : '获取并合并当前分支的团队更新。'));
    else {
      status.files.forEach(item => { const row=element('div','repository-preview-row'); row.append(element('span','',item.file),element('small',item.conflict ? 'repository-error' : 'muted',label(item))); $('repo-sync-files').append(row); });
      if (!status.files.length) $('repo-sync-files').append(element('p','muted',status.ahead ? `已保存的 ${status.ahead} 个本地版本将同步` : status.mergePending ? '完成当前合并版本' : '没有新的文件改动'));
    }
    $('repo-commit-note').hidden = action === 'pull' || !status.files.length && !status.mergePending;
    const identityNeeded=status.needsIdentity && (status.files.length || status.mergePending || action !== 'commit');
    $('repo-identity-fields').hidden=!identityNeeded;
    $('repo-author-name').required=Boolean(identityNeeded); $('repo-author-email').required=Boolean(identityNeeded);
    if (!keepValues) { $('repo-sync-note').value=''; $('repo-author-name').value=status.authorName; $('repo-author-email').value=status.authorEmail; }
    $('repo-sync-error').textContent=status.conflicts ? '请先修正冲突文件，再提交。' : action !== 'commit' && !status.hasRemote ? '当前仓库尚未关联远程仓库。' : '';
    $('repo-sync-progress').textContent='';
    if (!$('repo-sync-dialog').open) $('repo-sync-dialog').showModal();
    renderStatus();
    $('repo-sync-confirm').disabled=Boolean(status.conflicts || status.detached || action === 'pull' && status.files.length || action !== 'commit' && !status.hasRemote);
  }
  $('repo-sync-form').addEventListener('submit',guard(async event => {
    event.preventDefault(); if (busy) return;
    if (retryPreview) { await prepareSync(action,true); return; }
    busy=true; renderStatus(); renderTree();
    $('repo-sync-dialog').querySelectorAll('button,input').forEach(node => node.disabled=true);
    $('repo-sync-progress').textContent=action === 'commit' ? '正在保存版本…' : '正在连接远程…'; $('repo-sync-error').textContent='';
    try {
      const result=await call(api.repoPerform(action,{context:preview.context,snapshot:preview.snapshot,message:$('repo-sync-note').value,identity:{name:$('repo-author-name').value,email:$('repo-author-email').value}}));
      $('repo-sync-dialog').close(); status=result.status; toast(result.message);
      await activate();
      if (file && !dirty) { const name=file.file; try { displayFile(await call(api.repoRead(name))); } catch (_) { clearFile(); renderStatus(); } }
    } catch (error) {
      $('repo-sync-error').textContent=error.message; retryPreview=true;
      $('repo-sync-confirm').textContent='重新查看改动';
      try { await activate(); } catch (_) {}
    } finally {
      busy=false; $('repo-sync-progress').textContent='';
      $('repo-sync-dialog').querySelectorAll('button,input').forEach(node => node.disabled=false);
      renderStatus(); renderTree();
    }
  }));
  $('repo-editor').addEventListener('input',() => {
    dirty=normalize($('repo-editor').value) !== base; renderStatus();
    call(api.repoDraft(dirty ? draftValue() : null)).catch(error => toast(error.message));
  });
  document.addEventListener('keydown',guard(async event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && !$('git-page').hidden) { event.preventDefault(); if (dirty || file && changed(file.file)?.conflict) await save(); }
  }));
  api.onRepositorySaved(value => { if (value.file === file?.file && value.context === file.context) { displayFile(value); activate().catch(error => toast(error.message)); } });
  api.onRepositoryDiscard(() => { if (file?.editable) { $('repo-editor').value=base; dirty=false; renderStatus(); } });
  $('repo-save').addEventListener('click',guard(save));
  $('repo-view-diff').addEventListener('click',guard(toggleDiff));
  $('repo-search').addEventListener('input',renderTree); $('repo-search-mode').addEventListener('change',renderTree);
  $('repo-files-tab').addEventListener('click',() => { mode='files'; renderTree(); });
  $('repo-changes-tab').addEventListener('click',() => { mode='changes'; renderTree(); });
  $('refresh-repo').addEventListener('click',guard(async () => { closeMore(); await activate(); }));
  $('repo-new').addEventListener('click',guard(async()=>{if(await call(api.repoChoose(true))){clearFile();await activate();}}));
  for(const [id,physical] of [['repo-remove',false],['repo-delete',true]])$(id).addEventListener('click',guard(async()=>{closeMore();if(status?.path&&await call(api.repoRemove(status.path,physical))){clearFile();await activate();}}));
  $('choose-repo').addEventListener('click',guard(async () => { if (busy) return; const selected=await call(api.repoChoose()); if (selected) { clearFile(); expanded.clear(); await activate(); } }));
  $('repo-new-file').addEventListener('click',guard(async () => { if (busy || !await call(api.repoLeave())) return;if(!status||status.empty){const value=await call(api.repoNewFile());if(value){displayFile(value);await activate();}return;} $('repo-new-path').value=''; $('repo-create-error').textContent=''; $('repo-create-dialog').showModal(); $('repo-new-path').focus(); }));
  $('repo-create-form').addEventListener('submit',async event => {
    event.preventDefault(); if (busy) return; const submit=event.submitter; submit.disabled=true;
    try { const value=await call(api.repoCreate($('repo-new-path').value.trim().replaceAll('\\','/'),status.context)); $('repo-create-dialog').close(); const parts=value.file.split('/'); for (let i=1;i<parts.length;i++) expanded.add(parts.slice(0,i).join('/')+'/'); displayFile(value); await activate(); $('repo-editor').focus(); }
    catch (error) { $('repo-create-error').textContent=error.message; } finally { submit.disabled=false; }
  });
  document.querySelectorAll('[data-close-repo-dialog]').forEach(button => button.addEventListener('click',() => { if (!busy) button.closest('dialog').close(); }));
  document.querySelectorAll('.repository-dialog').forEach(dialog => dialog.addEventListener('cancel',event => { if (busy) event.preventDefault(); }));
  $('repo-sync').addEventListener('click',guard(() => prepareSync('sync')));
  $('repo-pull').addEventListener('click',guard(() => prepareSync('pull')));
  $('repo-commit-local').addEventListener('click',guard(() => prepareSync('commit')));
  $('repo-history').addEventListener('click',guard(async () => {
    closeMore(); const history=await call(api.repoHistory()); $('repo-history-list').replaceChildren();
    history.forEach(item => { const row=element('article','repository-history-row'); row.append(element('strong','',item.subject),element('small','muted',`${item.hash} · ${item.author} · ${item.ago}`)); $('repo-history-list').append(row); });
    if (!history.length) $('repo-history-list').append(element('p','muted','还没有提交记录'));
    $('repo-history-dialog').showModal();
  }));
  $('repo-open-file').addEventListener('click',guard(async () => { if (file && await call(api.repoLeave())) await call(api.repoOpen(file.file)); }));
  $('open-repo').addEventListener('click',guard(async () => { closeMore(); await call(api.repoOpen()); }));
  $('open-github').addEventListener('click',guard(async () => { closeMore(); if (status?.github) await call(api.openExternal(status.github)); }));
  function reset() { activationSequence++; loading=undefined; openSequence++; searchSequence++; clearTimeout(searchTimer); status=undefined; paths=[]; expanded.clear(); clearFile(); $('repository-list').replaceChildren(); $('repo-name').textContent='本地仓库'; $('repo-name').title=''; $('repo-branch').textContent=''; $('repo-status').textContent=''; $('change-count').textContent='0'; $('repo-file-tree').replaceChildren(); $('repo-search').value=''; }
  window.repositoryWorkbench={activate,configure,reset};
})();
