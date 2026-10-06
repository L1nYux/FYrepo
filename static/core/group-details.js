(() => {
  const root=document.querySelector('[data-messages]');
  if(!root?.querySelector('[data-chat-details]'))return;
  const panel=()=>root.querySelector('[data-chat-details]');
  root.addEventListener('click',event=>{
    if(event.target.closest('[data-chat-details-toggle],[data-chat-details-close]')){
      panel().hidden=!panel().hidden;
      root.querySelector('[data-chat-details-toggle]')?.setAttribute('aria-expanded',String(!panel().hidden));
    }
  });
  root.addEventListener('submit',async event=>{
    const form=event.target;if(!form.matches('[data-group-form]'))return;
    event.preventDefault();const data=new FormData(form);
    if(event.submitter?.name)data.set(event.submitter.name,event.submitter.value);
    const status=root.querySelector('[data-message-status]');
    try{
      const response=await fetch(form.action,{method:'POST',body:data,headers:{Accept:'application/json'}});
      if(!response.ok)throw Error('操作未完成，请检查权限。');
      const html=await fetch(location.href,{cache:'no-store'}).then(r=>r.text());
      const fresh=new DOMParser().parseFromString(html,'text/html');
      panel().replaceWith(fresh.querySelector('[data-chat-details]'));panel().hidden=false;
      root.querySelector('.conversation-peer strong').textContent=fresh.querySelector('.conversation-peer strong').textContent;
      status.textContent='已保存';
    }catch(error){status.textContent=error.message;}
  });
  if(new URL(location.href).searchParams.get('details')==='1')panel().hidden=false;
})();
