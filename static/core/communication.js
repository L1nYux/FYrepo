(() => {
  const dialog=document.querySelector('[data-contact-add-dialog]');if(!dialog)return;
  const status=dialog.querySelector('[data-contact-search-status]'),result=dialog.querySelector('[data-contact-search-result]');
  document.querySelector('[data-contact-add-open]').addEventListener('click',()=>dialog.showModal());
  dialog.querySelector('[data-contact-add-close]').addEventListener('click',()=>dialog.close());
  let epoch=0;
  dialog.querySelector('[data-contact-search]').addEventListener('submit',async event=>{
    event.preventDefault();const token=++epoch;status.textContent='正在查找…';result.replaceChildren();
    try{const response=await fetch(event.target.action+'?'+new URLSearchParams(new FormData(event.target)),{cache:'no-store',headers:{Accept:'application/json'}});
      if(!response.headers.get('content-type')?.includes('application/json'))throw Error('请重新登录后重试。');const data=await response.json();if(!response.ok)throw Error(data.error||'查找失败。');if(token!==epoch)return;
      status.textContent='';const card=document.createElement('article'),title=document.createElement('h3'),account=document.createElement('p'),form=document.createElement('form'),note=document.createElement('input'),button=document.createElement('button');
      title.textContent=data.display_name;account.textContent='工作台号：'+data.username;note.name='note';note.placeholder='申请说明（可选）';note.maxLength=200;note.setAttribute('aria-label','好友申请说明');button.type='submit';button.className='button primary';button.textContent=data.friend_state==='friends'?'已是好友':data.friend_state==='sent'?'申请已发送':'发送好友申请';button.disabled=['friends','sent'].includes(data.friend_state);form.append(note,button);card.append(title,account,form);result.append(card);
      form.addEventListener('submit',async e=>{e.preventDefault();button.disabled=true;try{const response=await fetch(data.friend_url,{method:'POST',headers:{Accept:'application/json','X-CSRFToken':data.csrf_token},body:new URLSearchParams({username:data.username,note:note.value})});const value=await response.json();if(!response.ok)throw Error(value.error||'申请失败。');if(token!==epoch)return;status.textContent=value.message;button.textContent='申请已发送';}catch(error){if(token===epoch){status.textContent=error.message;button.disabled=false;}}});
    }catch(error){if(token===epoch)status.textContent=error.message;}
  });
  dialog.addEventListener('close',()=>epoch++);
})();

(()=>{const target=document.querySelector('[data-team-application-dot]');if(!target)return;let timer=setInterval(async()=>{if(document.hidden)return;try{const data=await fetch('/messages/unread/',{headers:{Accept:'application/json'},cache:'no-store'}).then(r=>r.json());target.hidden=!data.team_application_count;const friend=document.querySelector('[data-friend-request-dot]');if(friend)friend.hidden=!data.friend_request_count;}catch(_){}},6000);window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});})();
