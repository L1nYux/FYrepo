(() => {
  const app=document.querySelector('#assistant-app'),dialog=document.querySelector('#assistant-capabilities-dialog');
  if(!app||!dialog)return;
  const scope=window.zhiyuRuntime.mount('agent-delegation',dialog,()=>{}),lookup=scope.latest();
  const find=name=>dialog.querySelector('[data-agent-'+name+']'),button=document.querySelector('#assistant-capabilities');
  const modeLabel=document.createElement('span');modeLabel.className='agent-mode-label';modeLabel.textContent=button.textContent;button.replaceChildren(modeLabel);
  let catalog=null,selected=null,loading=false;
  const requestedPlugin=new URLSearchParams(location.search).get('authorize');
  const csrf=app.querySelector('[name=csrfmiddlewaretoken]').value;
  const request=body=>window.zhiyuRuntime.json(app.dataset.capabilities,body,{format:'json',csrf});
  const error=value=>{find('error').textContent=value||'';};
  function select(grant){selected=grant;modeLabel.textContent=grant?'执行 · '+grant.title:'执行授权';button.title=grant?'当前授权项目：'+grant.title+'，有效至 '+new Date(grant.expires_at).toLocaleString():'管理执行授权';}
  window.zhiyuDelegation={authorization:()=>selected?.id||null};
  function renderActions(){
    const project=catalog?.projects.find(value=>String(value.id)===find('project').value),field=find('actions');
    field.querySelectorAll('label,p').forEach(node=>node.remove());
    if(!project){const p=document.createElement('p');p.textContent='没有可授权的项目操作。请检查项目权限和插件开关。';field.append(p);return;}
    const wanted=catalog.plugins.find(plugin=>plugin.id===requestedPlugin)?.tools.map(tool=>tool.name);
    for(const name of project.actions){if(wanted&&!wanted.includes(name))continue;const tool=catalog.plugins.flatMap(plugin=>plugin.tools).find(value=>value.name===name);const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.name='actions';input.value=name;label.append(input,document.createTextNode(tool.label));field.append(label);}
  }
  function render(){
    const project=find('project'),prior=project.value;project.replaceChildren();
    const configured=catalog.plugins.find(plugin=>plugin.id===requestedPlugin);
    const wanted=configured?.tools.map(tool=>tool.name);
    for(const item of catalog.projects){if(wanted&&!item.actions.some(name=>wanted.includes(name)))continue;const option=document.createElement('option');option.value=item.id;option.textContent=item.title+' · '+item.workspace;project.append(option);}
    if([...project.options].some(item=>item.value===prior))project.value=prior;
    renderActions();find('grant-form').querySelector('[type=submit]').disabled=!project.options.length;
    const list=find('grants');list.replaceChildren();
    for(const grant of catalog.grants){const row=document.createElement('div');row.className='agent-grant-row';const use=document.createElement('button');use.type='button';use.textContent=grant.title;use.dataset.agentUse=grant.id;const meta=document.createElement('small');meta.textContent='剩余 '+grant.remaining+' 次 · '+new Date(grant.expires_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})+' 到期';use.append(meta);const revoke=document.createElement('button');revoke.type='button';revoke.className='button compact';revoke.textContent='撤销';revoke.dataset.agentRevoke=grant.id;row.append(use,revoke);list.append(row);}
    if(!catalog.grants.length){const p=document.createElement('p');p.className='muted';p.textContent='暂无有效授权';list.append(p);}
    if(selected){const active=catalog.grants.find(value=>value.id===selected.id);select(active||null);}
  }
  async function load(){
    loading=true;error('');
    try{catalog=await lookup.run(signal=>window.zhiyuRuntime.query(app.dataset.capabilities,{signal}));render();}
    catch(failure){if(failure.name!=='AbortError')error(failure.message);throw failure;}
    finally{loading=false;}
  }
  scope.on(button,'click',()=>{dialog.showModal();load().catch(()=>{});});
  scope.on(find('close'),'click',()=>dialog.close());
  scope.on(dialog,'close',()=>lookup.cancel());
  scope.on(find('project'),'change',renderActions);
  scope.on(find('readonly'),'click',()=>{select(null);dialog.close();});
  scope.on(find('grant-form'),'submit',async event=>{
    event.preventDefault();if(loading)return;
    const form=event.currentTarget,submit=form.querySelector('[type=submit]'),actions=[...form.querySelectorAll('[name=actions]:checked')].map(input=>input.value);
    if(!actions.length){error('请勾选允许的操作。');return;}
    submit.disabled=true;error('');try{const value=await request({action:'grant',project:Number(find('project').value),actions,hours:Number(form.elements.hours.value),max_operations:Number(form.elements.max_operations.value)});await load();const grant=catalog.grants.find(item=>item.id===value.id);if(!grant)throw new Error('授权未加载，请重新打开后选择。');select(grant);dialog.close();}
    catch(failure){error(failure.message);}finally{submit.disabled=false;}
  });
  scope.on(find('grants'),'click',async event=>{
    const use=event.target.closest('[data-agent-use]'),revoke=event.target.closest('[data-agent-revoke]');
    if(use){select(catalog.grants.find(value=>value.id===use.dataset.agentUse));dialog.close();return;}
    if(!revoke)return;revoke.disabled=true;error('');try{await request({action:'revoke',id:revoke.dataset.agentRevoke});if(selected?.id===revoke.dataset.agentRevoke)select(null);await load();}
    catch(failure){error(failure.message);revoke.disabled=false;}
  });
  if(requestedPlugin){dialog.showModal();load().catch(()=>{});}
})();
