(() => {
  const api=window.desktop, list=document.querySelector('#workspace-projects');
  let key='', currentPath='/workspace/';
  const toggle=document.querySelector('#workspace-collapse');
  function collapsed(value){
    document.documentElement.dataset.workspaceCollapsed=String(Boolean(value.workspaceCollapsed));
    toggle.textContent=value.workspaceCollapsed?'›':'‹';
    toggle.setAttribute('aria-expanded',String(!value.workspaceCollapsed));
    toggle.title=value.workspaceCollapsed?'展开侧边栏':'收起侧边栏';
    toggle.setAttribute('aria-label',toggle.title);
  }
  toggle.addEventListener('click',()=>guard(()=>api.collapseWorkspace(document.documentElement.dataset.workspaceCollapsed!=='true',matchMedia('(prefers-reduced-motion: reduce)').matches)));
  const guard=async callback=>{try{const result=await callback();if(!result.ok)toast(result.error);}catch(error){toast(error.message);}};
  function button(item,child=false){
    const node=document.createElement('button');node.type='button';node.className=child?'workspace-child':'workspace-project-link';
    node.dataset.workspacePath=item.path;node.title=item.title;node.textContent=item.title;
    return node;
  }
  function selection(){
    const clean=currentPath.split('?')[0];
    document.querySelectorAll('[data-workspace-path]').forEach(node=>{
      const path=node.dataset.workspacePath;
      const selected=node.closest('.workspace-fixed-navigation')?
        (path==='/workspace/'?clean==='/workspace/':clean.startsWith(path)):
        (path==='/manage/'?clean.startsWith('/manage/')&&!clean.startsWith('/manage/members/'):clean===path||clean.startsWith(path)&&path!=='/workspace/');
      node.classList.toggle('selected',selected);
      if(selected)node.setAttribute('aria-current','page');else node.removeAttribute('aria-current');
    });
  }
  document.querySelector('#workspace-space-select').addEventListener('change',event=>guard(()=>api.switchSpace(event.target.value)));
  function update(value){
    const selector=document.querySelector('#workspace-space-select');
    const choices=value.spaces||[{id:'personal',name:'个人空间'}];
    selector.replaceChildren(...choices.map(item=>{const option=document.createElement('option');option.value=item.id;option.textContent=item.name;return option;}));selector.value=value.teamId?String(value.teamId):'personal';
    collapsed(value);
    currentPath=value.workspacePath||'/workspace/';
    const menu=value.workspaceNavigation||{projects:[],loaded:false};
    const next=JSON.stringify(menu);
    if(next!==key){
      key=next;list.replaceChildren();
      for(const project of menu.projects){
        const group=document.createElement('div');group.className='workspace-project';group.append(button(project));
        for(const task of project.tasks){
          const details=document.createElement('details');details.open=task.open;
          const summary=document.createElement('summary');summary.append(button(task));details.append(summary);
          for(const child of task.children)details.append(button(child,true));
          group.append(details);
        }
        list.append(group);
      }
      if(!menu.projects.length){const empty=document.createElement('p');empty.className='workspace-empty';empty.textContent=menu.loaded?'创建项目后显示在这里':'项目列表加载中…';list.append(empty);}
    }
    selection();
  }
  document.querySelector('#workspace-sidebar').addEventListener('click',event=>{
    const target=event.target.closest('[data-workspace-path]');if(!target)return;
    event.preventDefault();event.stopPropagation();guard(()=>api.navigateWorkspace(target.dataset.workspacePath));
  });
  api.onState(update);api.info().then(result=>{if(result.ok)update(result.data);});
})();
