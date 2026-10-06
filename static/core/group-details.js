(() => {
  const root=document.querySelector('[data-messages], [data-personal-thread]');
  if(!root?.querySelector('[data-chat-details]'))return;
  const panel=root.querySelector('[data-chat-details]'), status=panel.querySelector('[data-group-status]');
  const request=(url,options)=>fetch(window.workbenchMessageURL?window.workbenchMessageURL(url,root):url,options);
  function show(open){panel.hidden=!open;root.querySelector('[data-chat-details-toggle]')?.setAttribute('aria-expanded',String(open));}
  const editors=()=>[...panel.querySelectorAll('[data-inline-edit]')];
  function end(form,cancel=false){const input=form.querySelector('[data-edit-input]');if(cancel)input.value=form.dataset.original;form.querySelector('[data-edit-value]').textContent=input.value||form.dataset.empty||'未设置';form.dataset.editing='false';input.hidden=true;form.querySelector('[data-edit-value]').hidden=false;form.querySelector('[data-edit-start]').hidden=false;}
  let navigationEpoch=0;
  async function refreshNavigation(){
    const epoch=++navigationEpoch;
    try{const response=await request(location.href,{cache:'no-store'});if(!response.ok)return;const fresh=new DOMParser().parseFromString(await response.text(),'text/html');if(epoch!==navigationEpoch)return;const items=fresh.querySelector('.communication-items'),current=document.querySelector('.communication-items');if(items&&current)current.replaceWith(items);}catch(_){}
  }
  async function save(form){
    if(form.dataset.saving==='true')return false;
    const input=form.querySelector('[data-edit-input]');
    if(!input.reportValidity())return false;
    const value=input.value;
    if(value===form.dataset.original){end(form);return true;}
    form.dataset.saving='true';status.textContent='正在保存…';
    try{const response=await request(form.action,{method:'POST',body:new FormData(form),headers:{Accept:'application/json'}});
      if(!response.headers.get('content-type')?.includes('application/json'))throw Error('操作失败，请检查权限或重新登录。');
      const data=await response.json();if(!response.ok)throw Error(data.error||'保存失败，请重试。');
      form.dataset.original=value;status.textContent='已保存';
      if(input.name==='name'){
        const heading=root.querySelector('.conversation-peer strong');
        if(heading)heading.textContent=value;
      }
      if(input.value===value)end(form);else form.dataset.retry='true';
      refreshNavigation();return true;
    }catch(error){status.textContent=error.message;input.hidden=false;form.dataset.editing='true';show(true);return false;}
    finally{form.dataset.saving='false';if(form.dataset.retry==='true'){delete form.dataset.retry;save(form);}}
  }
  root.addEventListener('click',async event=>{
    if(event.target.closest('[data-chat-details-toggle]'))show(panel.hidden);
    if(event.target.closest('[data-chat-details-close]')){const results=await Promise.all(editors().filter(f=>f.dataset.editing==='true').map(save));if(results.every(Boolean))show(false);}
    const button=event.target.closest('[data-edit-start]');
    if(button){const form=button.closest('form'),input=form.querySelector('[data-edit-input]');form.dataset.original=input.value;form.dataset.editing='true';input.hidden=false;form.querySelector('[data-edit-value]').hidden=true;button.hidden=true;input.focus();input.setSelectionRange(input.value.length,input.value.length);}
  });
  document.addEventListener('pointerdown',event=>{
    if(event.target.closest('.sticker-panel,[data-emoji-panel],[data-chat-details-close]'))return;
    editors().forEach(form=>{if(form.dataset.editing==='true'&&!form.contains(event.target))save(form);});
  });
  panel.addEventListener('keydown',event=>{
    const form=event.target.closest('[data-inline-edit]');if(!form||event.isComposing)return;
    if(event.key==='Escape'){event.preventDefault();if(form.dataset.saving!=='true')end(form,true);}
    else if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();save(form);}
  });
  panel.addEventListener('submit',async event=>{
    const form=event.target;if(!form.matches('[data-group-form]'))return;
    event.preventDefault();if(form.matches('[data-inline-edit]')){save(form);return;}
    if(form.dataset.saving==='true')return;
    const data=new FormData(form);if(event.submitter?.name)data.set(event.submitter.name,event.submitter.value);
    form.dataset.saving='true';const check=form.querySelector('input[type=checkbox]');if(check)check.disabled=true;
    try{const response=await request(form.action,{method:'POST',body:data,headers:{Accept:'application/json'}});
      if(!response.headers.get('content-type')?.includes('application/json'))throw Error('操作未完成，请检查权限或重新登录。');
      const result=await response.json();if(!response.ok)throw Error(result.error||'操作未完成，请检查群管理权限。');
      status.textContent='已保存';
      const nicknames=form.querySelector('[name=show_nicknames]');if(nicknames)root.classList.toggle('hide-group-nicknames',!nicknames.checked);
      refreshNavigation();
      if(!form.matches('[data-group-toggle]'))location.reload();
    }catch(error){status.textContent=error.message;if(check)check.checked=!check.checked;}
    finally{form.dataset.saving='false';if(check)check.disabled=false;}
  });
  panel.addEventListener('change',event=>{if(event.target.closest('[data-group-toggle]'))event.target.form.requestSubmit();});
  panel.querySelector('[data-group-member-search]')?.addEventListener('input',event=>{
    const q=event.target.value.toLocaleLowerCase();panel.querySelectorAll('[data-group-member-name]').forEach(item=>item.hidden=!item.dataset.groupMemberName.toLocaleLowerCase().includes(q));
  });
  if(new URL(location.href).searchParams.get('details')==='1')show(true);
})();
