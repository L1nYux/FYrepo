(() => {
  const root=document.querySelector('[data-plugin-marketplace]');if(!root)return;
  const scope=window.zhiyuRuntime.mount('plugin-marketplace',root,()=>{});
  const notice=root.querySelector('[data-plugin-notice]'),search=root.querySelector('input[name=q]'),viewInput=root.querySelector('input[name=view]');
  const cards=[...root.querySelectorAll('.plugin-card')],tabs=[...root.querySelectorAll('[data-plugin-tab]')];
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
    const state=plugin.enabled,button=item.querySelector('[data-plugin-toggle]');
    item.dataset.enabled=String(state);button.textContent=state?'停用':'启用';button.setAttribute('aria-pressed',String(state));button.setAttribute('aria-label',(state?'停用':'启用')+plugin.label);button.classList.toggle('primary',!state);
    const label=item.querySelector('[data-plugin-state]');label.textContent=state?'已启用':'未启用';label.dataset.enabled=String(state);
    const configure=item.querySelector('[data-plugin-configure]'),help=item.querySelector('[data-plugin-disabled-help]');if(configure)configure.hidden=!state;if(help)help.hidden=state;
  }
  async function current(){
    if(saving||!scope.alive())return;
    try{
      const data=await refresh.run(signal=>window.zhiyuRuntime.json(root.dataset.stateUrl,undefined,{signal}));
      if(!scope.alive()||saving)return;
      for(const item of root.querySelectorAll('[data-plugin-id]')){
        const plugin=data.plugins.find(row=>row.id===item.dataset.pluginId);if(plugin&&typeof plugin.enabled==='boolean')paint(item,plugin);
      }
      if(root.dataset.pluginId){const plugin=data.plugins.find(row=>row.id===root.dataset.pluginId);if(plugin)paint(root,plugin);}
      filter();
    }catch(error){if(error.name!=='AbortError'&&scope.alive())message('插件状态刷新失败，显示上次状态。',true);}
  }
  scope.on(window,'pageshow',event=>{if(event.persisted)current();});
  scope.on(window,'focus',()=>current());
  scope.on(root,'click',async event=>{
    const button=event.target.closest('[data-plugin-toggle]');if(!button||button.disabled||saving)return;
    const item=button.closest('[data-plugin-id]'),enabled=item.dataset.enabled!=='true';
    const csrf=root.querySelector('[name=csrfmiddlewaretoken]').value;
    saving=true;refresh.cancel();button.disabled=true;item.setAttribute('aria-busy','true');message('');
    try{
      const value=await window.zhiyuRuntime.json(button.dataset.url,{enabled},{format:'json',csrf});
      if(!scope.alive())return;
      if(value.plugin.id!==item.dataset.pluginId||typeof value.plugin.enabled!=='boolean')throw Error('插件状态未确认，请刷新后重试。');
      paint(item,value.plugin);filter();message(value.plugin.label+(value.plugin.enabled?'已启用。':'已停用。'));
    }catch(error){if(scope.alive())message(error.message||'未能保存，请重试。',true);}
    finally{saving=false;if(scope.alive()){button.disabled=false;item.removeAttribute('aria-busy');}}
  });
  filter();
})();
