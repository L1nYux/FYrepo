(() => {
  const thread=document.querySelector('[data-personal-thread]');if(!thread)return;
  const fetch=(url,options)=>window.fetch(window.workbenchMessageURL(url,thread),options);
  const form=thread.querySelector('[data-thread-form]'),history=thread.querySelector('[data-history]'),status=thread.querySelector('[data-thread-status]'),input=form.elements.body,send=thread.querySelector('[data-thread-send]'),menu=thread.querySelector('[data-thread-menu]');
  let last=Math.max(0,...[...history.querySelectorAll('[data-message-id]')].map(n=>Number(n.dataset.messageId))),busy=false,refreshing=false,selected=null;
  const draftKey='zhiyu-chat-draft:'+document.documentElement.dataset.account+':'+thread.dataset.url;
  try{input.value=sessionStorage.getItem(draftKey)||'';}catch(_){}
  input.addEventListener('input',()=>{try{sessionStorage.setItem(draftKey,input.value);}catch(_){}});
  const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  function append(rows){const nearBottom=history.scrollHeight-history.scrollTop-history.clientHeight<80;
    for(const row of rows){last=Math.max(last,row.id);let card=history.querySelector('[data-message-id="'+row.id+'"]');
      if(card && !row.withdrawn && !row.gift)continue;
      if(row.withdrawn){
        const notice=node('article','message-system-note'),text=node('span',null,(row.mine?'你':row.author)+'撤回了一条消息');
        notice.dataset.messageId=row.id;notice.dataset.actionUrl=row.action_url;text.dataset.messageBody='';notice.append(text);
        if(row.mine){const button=node('button','link-button','重新编辑');button.type='button';button.dataset.threadReedit='';notice.append(button);}
        if(card)card.replaceWith(notice);else history.append(notice);continue;
      }
      if(card){const old=card.querySelector('[data-gift-id]');if(old&&window.workbenchPointCard){const fresh=window.workbenchPointCard(row.gift);fresh.dataset.giftSpace=row.gift.workspace;old.replaceWith(fresh);}continue;}
      if(row.kind==='notice'){card=node('article','message-system-note');card.dataset.messageId=row.id;const text=node('span',null,row.body);text.dataset.messageBody='';card.append(text);history.append(card);continue;}
      history.querySelector('[data-thread-empty]')?.remove();card=node('article','message-bubble-row personal-message-row'+(row.mine?' mine':''));card.dataset.messageId=row.id;card.dataset.actionUrl=row.action_url;
      const avatar=node('span','user-avatar conversation-avatar',row.author.slice(0,1));avatar.dataset.memberId=row.author_id;avatar.tabIndex=0;avatar.setAttribute('role','button');avatar.setAttribute('aria-label','查看 '+row.author+' 的资料');
      if(row.avatar_url){avatar.textContent='';const img=node('img');img.src=row.avatar_url;img.alt='';avatar.append(img);}
      const bubble=node('div','message-bubble'),meta=node('div','message-byline');meta.append(node('strong',null,row.author),node('small',null,row.at));const text=node('p',null,row.body);text.dataset.messageBody='';bubble.append(meta,text);
      if(row.quote?.body&&!row.withdrawn)bubble.append(node('blockquote',null,row.quote.author+'：'+row.quote.body));
      if(row.sticker){const img=node('img','message-sticker');img.src=row.sticker.url;img.alt=row.sticker.name;bubble.append(img);}
      if(row.gift&&window.workbenchPointCard){const card=window.workbenchPointCard(row.gift);card.dataset.giftSpace=row.gift.workspace;bubble.append(card);}
      for(const ref of row.references||[]){const refNode=node(ref.available?'a':'span','message-reference',ref.title);if(ref.available)refNode.href=ref.url;bubble.append(refNode);}
      for(const file of row.files||[]){const a=node('a','message-file',file.name);a.href=file.url;bubble.append(a);}const actions=node('button',null,'⋯');actions.type='button';actions.dataset.messageActions='';actions.setAttribute('aria-label','消息操作');card.append(avatar,bubble,actions);history.append(card);
    }if(nearBottom)history.scrollTop=history.scrollHeight;
  }
  async function refresh(){if(refreshing||document.hidden||window.workbenchActive===false)return;refreshing=true;try{const response=await fetch(thread.dataset.url+'?'+new URLSearchParams({after:String(last),known:[...history.querySelectorAll('[data-message-id]')].slice(-200).map(n=>n.dataset.messageId).join(',')}),{headers:{Accept:'application/json'},cache:'no-store'});const data=await response.json();if(!response.ok)throw Error(data.error||'聊天暂不可用，请重试。');for(const id of data.removed||[])history.querySelector('[data-message-id="'+id+'"]')?.remove();append(data.messages||[]);if(!busy)status.textContent='';}catch(error){status.textContent=error.message;}finally{refreshing=false;}}
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||(!input.value.trim()&&!form.elements.attachments.files.length&&!form.elements.sticker_id.value&&form.elements.references.value==='[]'&&!form.elements.resend_message.value))return;
    busy=true;send.disabled=true;const payload=new FormData(form),sent=input.value,controls=[...form.querySelectorAll('textarea,input[type=file],button')],disabled=controls.map(control=>control.disabled);controls.forEach(control=>control.disabled=true);
    try{const response=await fetch(form.action,{method:'POST',body:payload,headers:{Accept:'application/json'}});if(!response.headers.get('content-type')?.includes('application/json'))throw Error('登录或权限已变化，输入内容已保留，请重试。');const data=await response.json();if(!response.ok)throw Error(data.error||'发送失败，请重试。');if(input.value===sent){input.value='';try{sessionStorage.removeItem(draftKey);}catch(_){}}
      form.elements.sticker_id.value='';form.elements.resend_message.value='';thread.querySelector('[data-thread-draft]').hidden=true;rootResetReferences();form.elements.attachments.value='';thread.querySelector('[data-thread-file-names]').textContent='';form.elements.quoted_message.value='';thread.querySelector('[data-thread-quote]').hidden=true;status.textContent='';await refresh();
    }catch(error){status.textContent=error instanceof TypeError?'连接中断，输入内容已保留；请先查看消息再重试。':error.message;}
    finally{busy=false;controls.forEach((control,index)=>control.disabled=disabled[index]);send.disabled=false;}
  });
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.ctrlKey&&!event.altKey&&!event.metaKey&&!event.isComposing&&event.keyCode!==229&&!event.repeat&&!busy&&matchMedia('(hover:hover) and (pointer:fine)').matches){event.preventDefault();form.requestSubmit(send);}});
  function rootResetReferences(){thread.dispatchEvent(new CustomEvent('message-draft',{detail:{references:[]}}));}
  thread.addEventListener('point-gift-sent',()=>refresh());thread.addEventListener('point-gift-updated',()=>refresh());
  const files=form.elements.attachments;files.addEventListener('change',()=>thread.querySelector('[data-thread-file-names]').textContent=[...files.files].map(f=>f.name).join('、'));
  input.addEventListener('paste',event=>{const images=[...event.clipboardData.items].filter(i=>i.kind==='file'&&i.type.startsWith('image/')).map(i=>i.getAsFile()).filter(Boolean);if(!images.length)return;event.preventDefault();const dt=new DataTransfer();[...files.files,...images].forEach(f=>dt.items.add(f));files.files=dt.files;files.dispatchEvent(new Event('change'));});
  thread.addEventListener('click',async event=>{
    if(busy&&event.target.closest('[data-thread-reedit],[data-thread-quote-action],[data-thread-draft-cancel]')){status.textContent='正在发送，请稍后编辑。';return;}
    const reedit=event.target.closest('[data-thread-reedit]');
    if(reedit){try{const row=reedit.closest('[data-message-id]');const data=new FormData();data.set('action','draft');data.set('csrfmiddlewaretoken',form.elements.csrfmiddlewaretoken.value);const r=await fetch(row.dataset.actionUrl,{method:'POST',body:data,headers:{Accept:'application/json'}});if(!r.ok)throw Error('消息已不可用。');const {draft}=await r.json();input.value=draft.body;input.dispatchEvent(new Event('input'));form.elements.resend_message.value=draft.id;const note=thread.querySelector('[data-thread-draft]');note.querySelector('span').textContent='重新编辑'+(draft.attachments.length?' · '+draft.attachments.join('、'):'');note.hidden=false;input.focus();}catch(error){status.textContent=error.message;}}
    if(event.target.closest('[data-thread-draft-cancel]')){form.elements.resend_message.value='';thread.querySelector('[data-thread-draft]').hidden=true;}
    if(event.target.closest('[data-thread-quote-clear]')){form.elements.quoted_message.value='';thread.querySelector('[data-thread-quote]').hidden=true;}
    if(event.target.closest('[data-thread-quote-action]')&&selected){if(selected.classList.contains('message-system-note'))return;form.elements.quoted_message.value=selected.dataset.messageId;const quote=thread.querySelector('[data-thread-quote]');quote.querySelector('span').textContent=selected.querySelector('[data-message-body]').textContent;quote.hidden=false;menu.hidden=true;input.focus();}
    if(event.target.closest('[data-thread-copy-action]')&&selected){try{await navigator.clipboard.writeText(selected.querySelector('[data-message-body]').textContent);}catch(_){status.textContent='无法复制，请手动选择文字。';}menu.hidden=true;}
    if(event.target.closest('[data-thread-delete-action]')&&selected){try{const data=new FormData();data.set('action','delete');data.set('csrfmiddlewaretoken',form.elements.csrfmiddlewaretoken.value);const r=await fetch(selected.dataset.actionUrl,{method:'POST',body:data});if(!r.ok)throw Error('删除失败');selected.remove();}catch(error){status.textContent=error.message;}menu.hidden=true;}
    if(event.target.closest('[data-thread-withdraw-action]')&&selected){try{const data=new FormData();data.set('action','withdraw');data.set('csrfmiddlewaretoken',form.elements.csrfmiddlewaretoken.value);const response=await fetch(selected.dataset.actionUrl,{method:'POST',body:data,headers:{Accept:'application/json'}});if(!response.ok)throw Error('只能撤回两分钟内本人发送的消息。');await refresh();}catch(error){status.textContent=error.message;}menu.hidden=true;}
  });
  function openMenu(card,x,y){selected=card;menu.querySelector('[data-thread-withdraw-action]').hidden=!card.classList.contains('mine');menu.hidden=false;menu.style.left=Math.max(4,Math.min(x,innerWidth-150))+'px';menu.style.top=Math.max(4,Math.min(y,innerHeight-140))+'px';}
  history.addEventListener('click',event=>{const trigger=event.target.closest('[data-message-actions]');if(!trigger)return;const rect=trigger.getBoundingClientRect();openMenu(trigger.closest('[data-message-id]'),rect.left,rect.bottom);});
  history.addEventListener('contextmenu',event=>{const card=event.target.closest('[data-message-id]');if(!card)return;event.preventDefault();selected=card;menu.querySelector('[data-thread-withdraw-action]').hidden=!card.classList.contains('mine');menu.hidden=false;menu.style.left=Math.max(4,Math.min(event.clientX,innerWidth-150))+'px';menu.style.top=Math.max(4,Math.min(event.clientY,innerHeight-140))+'px';});
  document.addEventListener('click',event=>{if(!menu.contains(event.target)&&!event.target.closest('[data-message-actions]'))menu.hidden=true;});
  const historyDialog=thread.querySelector('[data-thread-history-dialog]'),historyForm=historyDialog.querySelector('form'),historyResults=historyDialog.querySelector('[data-thread-history-results]'),historyStatus=historyDialog.querySelector('[data-thread-history-status]'),more=historyDialog.querySelector('[data-thread-history-more]');
  let historyBusy=false,historyEpoch=0,nextBefore=null;
  async function searchHistory(older=false){
    if(historyBusy)return;historyBusy=true;more.disabled=true;const epoch=++historyEpoch;
    if(!older){historyResults.replaceChildren();nextBefore=null;}
    historyStatus.textContent='正在查找…';
    const url=new URL(thread.dataset.historyUrl,location.href);url.searchParams.set('q',historyForm.elements.q.value);if(older&&nextBefore)url.searchParams.set('before',nextBefore);
    try{const response=await fetch(url,{headers:{Accept:'application/json'},cache:'no-store'});const data=await response.json();if(!response.ok)throw Error(data.error||'无法读取聊天记录。');if(epoch!==historyEpoch)return;
      for(const row of data.messages){const result=node('article','history-result');result.append(node('strong',null,row.author+' · '+row.at),node('p',null,row.body));for(const file of row.files||[]){const link=node('a',null,file.name);link.href=file.url;result.append(link);}historyResults.append(result);}
      nextBefore=data.next_before;more.hidden=!nextBefore;historyStatus.textContent=historyResults.children.length?'已显示 '+historyResults.children.length+' 条记录。':'没有匹配的记录。';
    }catch(error){historyStatus.textContent=error.message;}finally{historyBusy=false;more.disabled=false;}
  }
  historyForm.addEventListener('submit',event=>{event.preventDefault();searchHistory();});more.addEventListener('click',()=>searchHistory(true));
  thread.addEventListener('click',async event=>{
    if(event.target.closest('[data-thread-history-open]')){thread.querySelector('[data-thread-header-menu]').open=false;historyDialog.showModal();searchHistory();historyForm.elements.q.focus();}
    if(event.target.closest('[data-thread-history-close]'))historyDialog.close();
    const button=event.target.closest('[data-thread-setting]');if(!button)return;
    const action=button.dataset.threadSetting;
    if(action==='clear'&&!confirm('清空你在这个会话中的记录？仅影响你的记录，清空后不能恢复。'))return;
    if(action==='remove'&&!confirm('从会话列表移除？聊天记录保留，收到新消息后重新出现。'))return;
    button.disabled=true;try{const response=await fetch(thread.dataset.settingsUrl,{method:'POST',headers:{'X-CSRFToken':form.elements.csrfmiddlewaretoken.value,Accept:'application/json'},body:new URLSearchParams({action,confirm:'yes'})});const data=await response.json();if(!response.ok)throw Error(data.error||'操作失败。');
      if(action==='remove'){location.href='/messages/social/';return;}
      if(action==='clear'){history.replaceChildren();historyResults.replaceChildren();historyDialog.close();}
      if(action==='mute'||action==='unmute'){button.dataset.threadSetting=data.muted?'unmute':'mute';button.textContent=(data.muted?'关闭':'开启')+'消息免打扰';}
      thread.querySelector('[data-thread-header-menu]').open=false;status.textContent='已保存';
    }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
  });
  history.scrollTop=history.scrollHeight;const timer=setInterval(refresh,6000);window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
})();
