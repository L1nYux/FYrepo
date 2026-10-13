(() => {
  const root=document.querySelector('[data-plugin-marketplace]');if(!root)return;
  const scope=window.zhiyuRuntime.mount('plugin-marketplace',root,()=>{}),bridge=window.workbenchPlugins;
  const notice=root.querySelector('[data-plugin-notice]'),search=root.querySelector('input[name=q]'),viewInput=root.querySelector('input[name=view]');
  const cards=[...root.querySelectorAll('.plugin-card')],tabs=[...root.querySelectorAll('[data-plugin-tab]')];
  const items=[...root.querySelectorAll('[data-plugin-id]'),...(root.dataset.pluginId?[root]:[])];
  let view=root.dataset.view||'all';
  const refresh=scope.latest();let saving=false;
  const message=(text,error=false)=>{notice.textContent=text;notice.toggleAttribute('data-error',error);};
  function filter(save=false){
    if(!search)return;
    const query=search.value.trim().toLocaleLowerCase();let count=0;
    for(const card of cards){card.hidden=(view==='enabled'&&card.dataset.enabled!=='true')||!card.dataset.pluginSearch.toLocaleLowerCase().includes(query);if(!card.hidden)count++;}
    root.querySelector('[data-plugin-empty]').hidden=count>0;
    root.querySelector('[data-plugin-enabled-count]').textContent=cards.filter(c=>c.dataset.enabled==='true').length;
    for(const tab of tabs){if(tab.dataset.pluginTab===view)tab.setAttribute('aria-current','page');else tab.removeAttribute('aria-current');}
    viewInput.value=view;
    if(save){const url=new URL(location.href);if(query)url.searchParams.set('q',search.value.trim());else url.searchParams.delete('q');if(view==='enabled')url.searchParams.set('view',view);else url.searchParams.delete('view');history.replaceState(null,'',url);}
    for(const tab of tabs){const url=new URL(location.href);url.searchParams.set('view',tab.dataset.pluginTab);tab.href=url.pathname+url.search;}
  }
  if(search)scope.on(search,'input',()=>filter(true));
  const form=root.querySelector('.plugin-filters');if(form)scope.on(form,'submit',event=>{event.preventDefault();filter(true);});
  for(const tab of tabs)scope.on(tab,'click',event=>{if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();view=tab.dataset.pluginTab;filter(true);});
  const clear=root.querySelector('[data-plugin-clear]');if(clear)scope.on(clear,'click',event=>{event.preventDefault();search.value='';view='all';filter(true);search.focus();});
  function paint(item,plugin){
    const available=plugin.available!==false,state=available&&plugin.enabled===true,button=item.querySelector('[data-plugin-toggle]');
    item.dataset.enabled=String(state);item.dataset.available=String(available);
    button.disabled=!available;button.textContent=available?(state?'停用':'启用'):'电脑版配置';button.setAttribute('aria-pressed',String(state));button.setAttribute('aria-label',(available?(state?'停用':'启用'):'电脑版配置：')+plugin.label);button.classList.toggle('primary',available&&!state);
    const label=item.querySelector('[data-plugin-state]');label.textContent=available?(state?'已启用':'未启用'):'仅电脑版';label.dataset.enabled=String(state);
    const configure=item.querySelector('[data-plugin-configure]'),help=item.querySelector('[data-plugin-disabled-help]');
    if(configure)configure.hidden=!state;if(help){help.hidden=state;if(plugin.runtime==='desktop')help.textContent=available?'启用插件后可以在电脑版打开。':'在知域电脑版打开本页，可以读取本机状态并配置。';}
  }
  function local(value){
    if(!scope.alive())return;
    if(!value||value.client_account!==root.dataset.clientAccount||!Array.isArray(value.plugins)){
      for(const item of items.filter(row=>row.dataset.pluginRuntime==='desktop'))paint(item,{label:item.querySelector('h1,h2')?.textContent||'插件',runtime:'desktop',available:false});
      message('登录状态已变化，请重新打开插件商城。',true);return;
    }
    for(const item of items.filter(row=>row.dataset.pluginRuntime==='desktop')){
      const plugin=value.plugins.find(row=>row.id===item.dataset.pluginId);if(plugin&&typeof plugin.enabled==='boolean')paint(item,plugin);
    }
    filter();
  }
  async function localState(){if(bridge&&items.some(item=>item.dataset.pluginRuntime==='desktop'))local(await bridge.state());}
  async function current(){
    if(saving||!scope.alive())return;
    try{
      const data=await refresh.run(signal=>window.zhiyuRuntime.json(root.dataset.stateUrl,undefined,{signal}));
      if(!scope.alive()||saving)return;
      if(data.account_id&&data.account_id!==document.documentElement.dataset.account)throw Error('登录状态已变化，请重新打开插件商城。');
      for(const item of items.filter(row=>row.dataset.pluginRuntime!=='desktop')){
        const plugin=data.plugins.find(row=>row.id===item.dataset.pluginId);if(plugin&&typeof plugin.enabled==='boolean')paint(item,plugin);
      }
      await localState();filter();
    }catch(error){if(error.name!=='AbortError'&&scope.alive())message(error.message||'状态刷新失败，显示上次状态。',true);}
  }
  scope.on(window,'pageshow',event=>{if(event.persisted)current();});
  scope.on(window,'focus',()=>current());
  if(bridge){scope.cleanup(bridge.onState(local));localState().catch(error=>{if(scope.alive())message('本机插件状态读取失败，请重新打开商城。',true);});}
  scope.on(root,'click',async event=>{
    const open=event.target.closest('[data-plugin-open]');
    if(open){if(bridge&&!saving)try{await bridge.open(open.closest('[data-plugin-id]').dataset.pluginId);}catch(error){if(scope.alive())message(error.message||'打开失败，请重试。',true);}return;}
    const button=event.target.closest('[data-plugin-toggle]');if(!button||button.disabled||saving)return;
    const item=button.closest('[data-plugin-id]'),enabled=item.dataset.enabled!=='true';
    saving=true;refresh.cancel();button.disabled=true;item.setAttribute('aria-busy','true');message('');
    try{
      let plugin;
      if(item.dataset.pluginRuntime==='desktop'){
        if(!bridge)throw Error('请在知域电脑版配置这个插件。');
        const value=await bridge.set(item.dataset.pluginId,enabled);if(!scope.alive())return;
        if(value.client_account!==root.dataset.clientAccount)throw Error('登录状态已变化，请重新打开插件商城。');
        local(value);plugin=value.plugins.find(row=>row.id===item.dataset.pluginId);
      }else{
        const csrf=root.querySelector('[name=csrfmiddlewaretoken]').value;
        const value=await window.zhiyuRuntime.json(button.dataset.url,{enabled},{format:'json',csrf});if(!scope.alive())return;plugin=value.plugin;
      }
      if(!plugin||plugin.id!==item.dataset.pluginId||plugin.enabled!==enabled)throw Error('插件状态未确认，请刷新后重试。');
      paint(item,plugin);filter();message(plugin.label+(plugin.enabled?'已启用。':'已停用。'));
    }catch(error){if(scope.alive())message(error.message||'未能保存，请重试。',true);}
    finally{saving=false;if(scope.alive()){button.disabled=item.dataset.available==='false';item.removeAttribute('aria-busy');}}
  });
  filter();
})();
