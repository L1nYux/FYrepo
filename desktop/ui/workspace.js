(() => {
  const api=window.desktop, sidebar=document.querySelector('#workspace-sidebar'), selector=document.querySelector('#workspace-space-select'), toggle=document.querySelector('#workspace-collapse');
  let currentPath='/workspace/', menu={projects:[],competitions:[],experiments:[],spaces:[],loaded:false},filter='all',key='';
  const guard=async callback=>{try{const result=await callback();if(!result.ok)toast(result.error);}catch(error){toast(error.message);}};
  toggle.addEventListener('click',()=>guard(()=>api.collapseWorkspace(document.documentElement.dataset.workspaceCollapsed!=='true',matchMedia('(prefers-reduced-motion: reduce)').matches)));
  function button(item,child=false){const node=document.createElement('button');node.type='button';node.className=child?'workspace-child':'workspace-project-link';node.dataset.workspacePath=item.path;node.title=item.title+(item.owner?' · '+item.owner:'');const title=document.createElement('span');title.textContent=item.title;node.append(title);if(item.owner){const tag=document.createElement('small');tag.className='workspace-owner';tag.textContent=item.owner;node.append(tag);}return node;}
  function paint(){
    for(const kind of ['projects','competitions','experiments']){
      const list=document.querySelector('#workspace-'+kind);list.replaceChildren();
      for(const item of menu[kind]||[]){if(filter!=='all'&&item.space!==filter)continue;const group=document.createElement('div');group.className='workspace-project';group.append(button(item));
        for(const task of item.tasks||[]){const details=document.createElement('details');details.open=task.open;const summary=document.createElement('summary');summary.append(button(task));details.append(summary);for(const child of task.children||[])details.append(button(child,true));group.append(details);}list.append(group);
      }
      if(!list.childElementCount){const empty=document.createElement('p');empty.className='workspace-empty';empty.textContent=menu.loaded?'暂无条目':'正在加载…';list.append(empty);}
    }
    selection();
  }
  function selection(){const clean=currentPath.split('?')[0];sidebar.querySelectorAll('[data-workspace-path]').forEach(node=>{const path=node.dataset.workspacePath;const top=node.closest('.workspace-fixed-navigation')&&!node.closest('.workspace-branches');const selected=top?(path==='/workspace/'?clean===path:clean.startsWith(path)):clean===path;node.classList.toggle('selected',selected);if(selected)node.setAttribute('aria-current','page');else node.removeAttribute('aria-current');});}
  selector.addEventListener('change',()=>{filter=selector.value;paint();const match=currentPath.match(/^\/(projects|competitions|experiments)\//);if(match)guard(()=>api.navigateWorkspace('/'+match[1]+'/'+(filter==='all'?'':'?ownership='+filter)));});
  function update(value){
    document.documentElement.dataset.workspaceCollapsed=String(Boolean(value.workspaceCollapsed));toggle.textContent=value.workspaceCollapsed?'›':'‹';toggle.setAttribute('aria-expanded',String(!value.workspaceCollapsed));toggle.title=value.workspaceCollapsed?'展开侧边栏':'收起侧边栏';toggle.setAttribute('aria-label',toggle.title);
    currentPath=value.workspacePath||'/workspace/';menu=value.workspaceNavigation||menu;
    const choices=menu.spaces||[];if(filter!=='all'&&!choices.some(item=>item.id===filter))filter='all';
    const next=JSON.stringify([menu,filter]);if(next!==key){key=next;selector.replaceChildren();const all=document.createElement('option');all.value='all';all.textContent='全部';selector.append(all);for(const item of choices){const option=document.createElement('option');option.value=item.id;option.textContent=item.name;selector.append(option);}selector.value=filter;paint();}selection();
    sidebar.querySelectorAll('.workspace-resource-section').forEach(section=>{const prefix=section.querySelector('[data-workspace-path]')?.dataset.workspacePath;if(prefix&&currentPath.startsWith(prefix))section.open=true;});
  }
  sidebar.addEventListener('click',event=>{const target=event.target.closest('[data-workspace-path]');if(!target)return;event.preventDefault();event.stopPropagation();let path=target.dataset.workspacePath;if(/^\/(projects|competitions|experiments)\/$/.test(path)&&filter!=='all')path+='?ownership='+filter;guard(()=>api.navigateWorkspace(path));});
  api.onState(update);api.info().then(result=>{if(result.ok)update(result.data);});
})();
