(() => {
  const account=document.documentElement.dataset.account;
  document.querySelectorAll('[data-project-tree]').forEach(tree=>{
    const content=tree.querySelector('[data-project-children]');let loaded=content.childElementCount>0,busy=false;
    const key='zhiyu-tree:'+account+':'+tree.dataset.projectTree;
    try{if(sessionStorage.getItem(key)==='open')tree.open=true;}catch(_){}
    const link=(item,child=false)=>{const a=document.createElement('a');a.href=item.path;a.textContent=item.title;a.title=item.title;if(child)a.className='sidebar-child';if(location.pathname===item.path)a.classList.add('selected');return a;};
    async function load(){if(loaded||busy)return;busy=true;content.textContent='正在加载…';try{const response=await fetch(tree.dataset.branchUrl,{cache:'no-store',headers:{Accept:'application/json'}});if(!response.ok)throw Error('任务暂不可用，点击项目查看详情。');const data=await response.json();content.replaceChildren();for(const task of data.project.tasks){const details=document.createElement('details'),summary=document.createElement('summary');summary.append(link(task));details.append(summary);for(const child of task.children)details.append(link(child,true));details.open=location.pathname===task.path||task.children.some(child=>location.pathname===child.path);content.append(details);}if(!content.childElementCount)content.textContent='暂无任务';if(data.truncated){const more=document.createElement('a');more.href=data.project.path;more.textContent='查看完整项目 ›';content.append(more);}loaded=true;}catch(error){content.textContent=error.message;}finally{busy=false;}}
    tree.addEventListener('toggle',()=>{try{sessionStorage.setItem(key,tree.open?'open':'closed');}catch(_){}if(tree.open)load();});
    if(tree.open)load();
  });
})();
