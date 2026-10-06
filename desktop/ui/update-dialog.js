(() => {
  const api=window.desktop, dialog=document.createElement('dialog');
  dialog.id='application-update-dialog';dialog.className='application-update-dialog';dialog.setAttribute('aria-labelledby','application-update-heading');
  dialog.innerHTML='<header><div><small>知域 · 应用更新</small><h2 id="application-update-heading">正在读取版本…</h2></div><button type="button" data-update-close aria-label="关闭应用更新">×</button></header><p data-update-size class="muted"></p><div class="application-update-content"><h3>新功能</h3><div data-update-features></div><h3>修复与改进</h3><ul data-update-fixes></ul></div><p data-update-status role="status" aria-live="polite"></p><progress data-update-progress max="100" value="0" hidden></progress><footer><button type="button" class="button" data-update-check>检查更新</button><button type="button" class="button" data-update-close>稍后</button><button type="button" class="button primary" data-update-download hidden>下载更新</button><button type="button" class="button primary" data-update-install hidden>安装并重启</button></footer>';
  document.body.append(dialog);
  const find=selector=>dialog.querySelector(selector);
  let value={}, busy=false;
  function render(state){
    if(!state)return;value=state;
    find('#application-update-heading').textContent=state.nextVersion?'版本 '+state.nextVersion:'当前版本 '+(state.version||'');
    find('[data-update-size]').textContent=(state.size_bytes?'安装包 '+(state.size_bytes/1048576).toFixed(1)+' MB · ':'')+(state.mode==='manual-mac'?'Mac：下载后打开安装包':'Windows：下载后安装并重启');
    find('[data-update-status]').textContent=state.message||'正在检查更新…';
    const features=find('[data-update-features]');features.replaceChildren();
    for(const [index, feature] of (state.release?.features||[]).entries()){
      const row=document.createElement('article'), title=document.createElement('strong'), description=document.createElement('p'), button=document.createElement('button');
      title.textContent=feature.title;description.textContent=feature.description;button.type='button';button.className='button';button.textContent='打开功能';
      const a=(state.nextVersion||state.version||'').split('.').map(Number),b=(state.version||'').split('.').map(Number);
      button.disabled=a.some((n,i)=>n>b[i]&&a.slice(0,i).every((v,j)=>v===b[j]));button.title=button.disabled?'请先更新后使用新功能':'';
      button.addEventListener('click',()=>action(()=>api.updateFeature(index)));row.append(title,description,button);features.append(row);
    }
    if(!features.childElementCount)features.textContent='版本说明尚未获取，检查更新后会显示在这里。';
    const fixes=find('[data-update-fixes]');fixes.replaceChildren();
    for(const note of state.release?.fixes||[state.notes||'暂无补充说明。']){const row=document.createElement('li');row.textContent=note;fixes.append(row);}
    const progress=find('[data-update-progress]');progress.hidden=state.state!=='downloading';progress.value=state.percent||0;
    find('[data-update-download]').hidden=!['available','error'].includes(state.state)||!state.nextVersion;
    find('[data-update-install]').hidden=state.state!=='downloaded';find('[data-update-install]').textContent=state.mode==='manual-mac'?'打开安装包':'安装并重启';
    find('[data-update-check]').disabled=busy||['checking','downloading','disabled'].includes(state.state);
  }
  async function action(callback){if(busy)return;busy=true;render(value);try{const result=await callback();if(!result.ok)throw Error(result.error);if(result.data?.state)render(result.data);}catch(error){find('[data-update-status]').textContent=error.message;}finally{busy=false;render({...value,message:find('[data-update-status]').textContent});}}
  dialog.querySelectorAll('[data-update-close]').forEach(button=>button.addEventListener('click',()=>dialog.close()));
  dialog.addEventListener('close',()=>api.closeUpdateInfo());
  api.onUpdateClosed(()=>{if(dialog.open)dialog.close();});
  api.onUpdates(render);
  api.onUpdateOpen(async()=>{if(!dialog.open)dialog.showModal();await action(()=>api.updates());if(['idle','current','error'].includes(value.state))await action(()=>api.checkUpdates());});
  find('[data-update-check]').addEventListener('click',()=>action(()=>api.checkUpdates()));
  find('[data-update-download]').addEventListener('click',()=>action(()=>api.downloadUpdate()));
  find('[data-update-install]').addEventListener('click',()=>action(()=>api.installUpdate()));
})();
