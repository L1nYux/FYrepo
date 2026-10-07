(() => {
  const root=document.querySelector('[data-messages], [data-personal-thread]');
  if(!root?.querySelector('[data-chat-details]'))return;
  const panel=root.querySelector('[data-chat-details]'), status=panel.querySelector('[data-group-status]');
  const request=(url,options)=>fetch(window.workbenchMessageURL?window.workbenchMessageURL(url,root):url,options);
  function show(open){panel.hidden=!open;root.querySelector('[data-chat-details-toggle]')?.setAttribute('aria-expanded',String(open));}
  async function refreshMembers(){
    try{const response=await request(location.href,{cache:'no-store'});if(!response.ok)throw Error();const fresh=new DOMParser().parseFromString(await response.text(),'text/html');const grid=fresh.querySelector('.group-member-grid');if(!grid)throw Error();panel.querySelector('.group-member-grid').replaceWith(grid);for(const selector of ['[data-member-add-list]','[data-member-remove-list]']){const list=fresh.querySelector(selector),old=document.querySelector(selector);if(list&&old)old.replaceWith(list);}const heading=fresh.querySelector('.conversation-peer strong'),current=root.querySelector('.conversation-peer strong');if(heading&&current)current.textContent=heading.textContent;panel.querySelector('[data-group-member-search]')?.dispatchEvent(new Event('input'));return true;}catch(_){status.textContent='成员操作已完成，列表暂未刷新，请稍后重新打开群资料。';return false;}
  }
  const leavingWithFiles=()=>{const files=root.querySelector('input[type=file][name=attachments]');return !files?.files.length||confirm('当前聊天附件尚未发送。继续管理团队将离开聊天，附件需要重新选择。');};
  panel.addEventListener('click',event=>{if(event.target.closest('a.group-member-tile')&&!leavingWithFiles())event.preventDefault();});
  const memberDialog=document.querySelector('[data-group-member-dialog]');
  if(memberDialog){const memberForm=memberDialog.querySelector('form'),memberStatus=memberDialog.querySelector('[data-member-picker-status]');let mode='add',busy=false;
    panel.addEventListener('click',event=>{const button=event.target.closest('[data-group-members-open]');if(!button)return;mode=button.dataset.groupMembersOpen;memberForm.reset();memberStatus.textContent='';memberDialog.querySelector('[data-member-picker-search]').value='';memberDialog.querySelectorAll('[data-picker-name]').forEach(row=>row.hidden=false);memberDialog.querySelector('[data-member-add-list]').hidden=mode!=='add';memberDialog.querySelector('[data-member-remove-list]').hidden=mode==='add';memberForm.elements.action.value=mode==='add'?'add_many':'remove_many';memberDialog.querySelector('[data-member-picker-title]').textContent=mode==='add'?'添加群成员':mode==='team-remove'?'移出团队成员':'移出群成员';memberDialog.querySelector('[data-member-picker-note]').textContent=mode==='team-remove'?'选择一位成员，下一步确认团队资格与负责事项的交接。':'';memberDialog.querySelector('[data-member-picker-confirm]').textContent=mode==='team-remove'?'下一步':'确定';memberDialog.showModal();});
    memberDialog.querySelectorAll('[data-group-members-close]').forEach(button=>button.addEventListener('click',()=>{if(!busy)memberDialog.close();}));
    memberDialog.querySelector('[data-member-picker-search]').addEventListener('input',event=>{const q=event.target.value.toLocaleLowerCase();memberDialog.querySelectorAll('[data-picker-name]').forEach(row=>row.hidden=!row.dataset.pickerName.toLocaleLowerCase().includes(q));});
    memberForm.addEventListener('submit',async event=>{event.preventDefault();if(busy)return;const list=memberDialog.querySelector(mode==='add'?'[data-member-add-list]':'[data-member-remove-list]'),selected=[...list.querySelectorAll('input:checked')];if(!selected.length){memberStatus.textContent='请先选择成员。';return;}if(mode==='team-remove'){if(selected.length!==1){memberStatus.textContent='请每次选择一位成员，逐一确认交接。';return;}if(leavingWithFiles())location.href=selected[0].closest('[data-team-member-url]').dataset.teamMemberUrl;return;}if(mode==='remove'&&!confirm('将所选 '+selected.length+' 位成员移出群聊？'))return;busy=true;const submit=memberDialog.querySelector('[data-member-picker-confirm]');submit.disabled=true;memberStatus.textContent='正在保存…';try{const data=new FormData(memberForm);data.delete('users');selected.forEach(input=>data.append('users',input.value));const response=await request(memberForm.action,{method:'POST',body:data,headers:{Accept:'application/json'}});if(!response.headers.get('content-type')?.includes('application/json'))throw Error('操作失败，请检查群管理权限。');const result=await response.json();if(!response.ok)throw Error(result.error||'操作失败。');memberDialog.close();status.textContent='成员已更新';await refreshMembers();refreshNavigation();}catch(error){memberStatus.textContent=error.message;}finally{busy=false;submit.disabled=false;}});
    memberDialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  }
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
        if(heading)heading.textContent=value;await refreshMembers();
      }
      if(input.name==='nickname')await refreshMembers();
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
    if(event.target.closest('[data-emoji-panel],[data-chat-details-close]'))return;
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
      if(!form.matches('[data-group-toggle]'))await refreshMembers();
    }catch(error){status.textContent=error.message;if(check)check.checked=!check.checked;}
    finally{form.dataset.saving='false';if(check)check.disabled=false;}
  });
  panel.addEventListener('change',event=>{if(event.target.closest('[data-group-toggle]'))event.target.form.requestSubmit();});
  panel.querySelector('[data-group-member-search]')?.addEventListener('input',event=>{
    const q=event.target.value.toLocaleLowerCase();panel.querySelectorAll('[data-group-member-name]').forEach(item=>item.hidden=!item.dataset.groupMemberName.toLocaleLowerCase().includes(q));
  });
  if(new URL(location.href).searchParams.get('details')==='1')show(true);
})();
