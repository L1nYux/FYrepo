(() => {
  const api=window.desktop,sidebar=document.querySelector('#workspace-sidebar'),selector=document.querySelector('#workspace-space-select'),toggle=document.querySelector('#workspace-collapse');
  const expanded=new Map(),branches=new Map();
  let currentPath='/workspace/',lastPath='',menu={projects:[],competitions:[],experiments:[],spaces:[],loaded:false},filter='all',key='',accountKey='';
  const guard=async callback=>{try{const result=await callback();if(!result.ok)toast(result.error);}catch(error){toast(error.message);}};
  toggle.addEventListener('click',()=>guard(()=>api.collapseWorkspace(document.documentElement.dataset.workspaceCollapsed!=='true',matchMedia('(prefers-reduced-motion: reduce)').matches)));
  function button(item,child=false){const node=document.createElement('button');node.type='button';node.className=child?'workspace-child':'workspace-project-link';node.dataset.workspacePath=item.path;node.title=item.title+(item.owner?' · '+item.owner:'');const icon=document.createElement('span');icon.className='workspace-item-icon';icon.textContent=child?'↳':'▱';icon.setAttribute('aria-hidden','true');const title=document.createElement('span');title.className='workspace-item-title';title.textContent=item.title;node.append(icon,title);if(item.owner){const tag=document.createElement('small');tag.className='workspace-owner';tag.textContent=item.owner;node.append(tag);}return node;}
  function tasks(content,items,truncated=false,path=''){
    content.replaceChildren();for(const task of items){const details=document.createElement('details'),summary=document.createElement('summary');details.open=expanded.get(task.path)??task.open;summary.append(button(task));details.append(summary);for(const child of task.children||[])details.append(button(child,true));details.addEventListener('toggle',()=>expanded.set(task.path,details.open));content.append(details);}
    if(!content.childElementCount){const empty=document.createElement('p');empty.className='workspace-empty';empty.textContent='暂无任务';content.append(empty);}
    if(truncated)content.append(button({title:'查看完整项目 ›',path}));selection();
  }
  function project(item){
    const tree=document.createElement('details');tree.className='workspace-project';tree.open=expanded.get(item.path)||false;const summary=document.createElement('summary'),content=document.createElement('div');content.className='workspace-task-branches';summary.append(button(item));tree.append(summary,content);let busy=false,loaded=false;
    const cached=branches.get(item.path);if(cached){tasks(content,cached.tasks,cached.truncated,item.path);loaded=Date.now()-cached.at<30000;}else tasks(content,item.tasks||[],false,item.path);
    async function load(){if(loaded||busy)return;busy=true;const identity=accountKey;content.textContent='正在加载…';try{const result=await api.workspaceBranch(item.path);if(!result.ok)throw Error(result.error);if(identity!==accountKey||!tree.isConnected)return;const data=result.data;branches.set(item.path,{tasks:data.project.tasks,truncated:data.truncated,at:Date.now()});tasks(content,data.project.tasks,data.truncated,item.path);loaded=true;}catch(error){if(tree.isConnected)content.textContent=error.message;}finally{busy=false;}}
    tree.addEventListener('toggle',()=>{expanded.set(item.path,tree.open);if(tree.open)load();});if(tree.open)queueMicrotask(load);return tree;
  }
  function paint(){const scroll=sidebar.scrollTop;
    for(const kind of ['projects','competitions','experiments']){const list=document.querySelector('#workspace-'+kind);list.replaceChildren();for(const item of menu[kind]||[]){if(filter!=='all'&&item.space!==filter)continue;if(kind==='projects')list.append(project(item));else{const group=document.createElement('div');group.className='workspace-project';group.append(button(item));list.append(group);}}
      if(!list.childElementCount){const empty=document.createElement('p');empty.className='workspace-empty';empty.textContent=menu.loaded?'暂无条目':'正在加载…';list.append(empty);}}
    selection();sidebar.scrollTop=scroll;
  }
  function selection(){const clean=currentPath.split('?')[0];
    sidebar.querySelectorAll('[data-workspace-path]').forEach(node=>{const selected=clean===node.dataset.workspacePath || clean.startsWith('/sampling/') && node.dataset.workspacePath==='/sampling/';node.classList.toggle('selected',selected);if(selected)node.setAttribute('aria-current','page');else node.removeAttribute('aria-current');});
  }
  selector.addEventListener('change',()=>{filter=selector.value;paint();const match=currentPath.match(/^\/(workspace|projects|competitions|experiments|sampling)\//);if(match)guard(()=>api.navigateWorkspace('/'+match[1]+'/'+(filter==='all'?'':'?ownership='+filter)));});
  function update(value){
    document.documentElement.dataset.workspaceCollapsed=String(Boolean(value.workspaceCollapsed));toggle.textContent=value.workspaceCollapsed?'›':'‹';toggle.setAttribute('aria-expanded',String(!value.workspaceCollapsed));toggle.title=value.workspaceCollapsed?'展开侧边栏':'收起侧边栏';toggle.setAttribute('aria-label',toggle.title);
    const identity=(value.serverUrl||'local')+':'+(value.accountId||value.username||'');if(identity!==accountKey){accountKey=identity;expanded.clear();branches.clear();filter='all';key='';lastPath='';}
    currentPath=value.workspacePath||'/workspace/';menu=value.workspaceNavigation||menu;const url=new URL(currentPath,'http://local.invalid');
    if(/^\/(workspace|projects|competitions|experiments|sampling)\/$/.test(url.pathname))filter=url.searchParams.get('ownership')||'all';
    const choices=menu.spaces||[];if(filter!=='all'&&!choices.some(item=>item.id===filter))filter='all';
    if(lastPath!==currentPath){lastPath=currentPath;let section=url.pathname.split('/')[1];for(const item of menu.projects){const items=branches.get(item.path)?.tasks||item.tasks||[];if(item.path===url.pathname||items.some(task=>task.path===url.pathname||task.children?.some(child=>child.path===url.pathname))){expanded.set(item.path,true);for(const task of items)if(task.children?.some(child=>child.path===url.pathname))expanded.set(task.path,true);section='projects';if(filter!=='all'&&item.space!==filter)filter='all';}}
      sidebar.querySelectorAll('.workspace-resource-section').forEach(node=>{if(node.querySelector('[data-workspace-path]')?.dataset.workspacePath==='/'+section+'/')node.open=true;});key='';}
    const next=JSON.stringify([menu,filter]);if(next!==key){key=next;selector.replaceChildren();const all=document.createElement('option');all.value='all';all.textContent='全部';selector.append(all);for(const item of choices){const option=document.createElement('option');option.value=item.id;option.textContent=item.name;selector.append(option);}selector.value=filter;paint();}selection();
  }
  sidebar.addEventListener('click',event=>{const target=event.target.closest('[data-workspace-path]');if(!target)return;event.preventDefault();event.stopPropagation();let path=target.dataset.workspacePath;if(/^\/(workspace|projects|competitions|experiments|sampling)\/$/.test(path)&&filter!=='all')path+='?ownership='+filter;guard(()=>api.navigateWorkspace(path));});
  api.onState(update);api.info().then(result=>{if(result.ok)update(result.data);});
})();
