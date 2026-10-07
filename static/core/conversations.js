(() => {
  function paint(data) {
    if (!data || !Array.isArray(data.hidden_channels)) return;
    document.querySelectorAll('[data-conversation-key]').forEach(link=>{
      const key=link.dataset.conversationKey;
      link.hidden=data.hidden_channels.includes(key);
      const icon=link.querySelector('[data-muted-marker]');if(icon)icon.hidden=!(data.muted_channels||[]).includes(key);
      link.classList.toggle('conversation-muted',(data.muted_channels||[]).includes(key));
    });
    document.querySelectorAll('[data-messages]').forEach(root=>{
      const muted=(data.muted_channels||[]).includes(root.dataset.channel),button=root.querySelector('[data-conversation-action="mute"]'),marker=root.querySelector('[data-current-muted]');
      if(button){button.setAttribute('aria-pressed',String(muted));button.textContent=muted?'关闭消息免打扰':'开启消息免打扰';}if(marker)marker.hidden=!muted;
    });
  }
  window.workbenchConversations={paint};
  document.querySelectorAll('[data-conversation-start]').forEach(form=>form.addEventListener('submit',event=>{event.preventDefault();const id=form.querySelector('select').value;if(/^\d+$/.test(id))location.href='/messages/to/'+id+'/';}));
  const initial=document.getElementById('conversation-state');if(initial){try{paint(JSON.parse(initial.textContent));}catch(_){}}
  document.querySelectorAll('[data-messages]').forEach(root=>{
    const fetch=(url,options)=>window.fetch(window.workbenchMessageURL(url,root),options);
    const dialog=root.querySelector('[data-history-dialog]');if(!dialog)return;
    const form=dialog.querySelector('[data-history-form]'),results=dialog.querySelector('[data-history-results]'),status=dialog.querySelector('[data-history-status]'),more=dialog.querySelector('[data-history-more]');
    let busy=false,epoch=0,next=null,query=null,pendingSearch=false;
    const csrf=()=>root.querySelector('[name=csrfmiddlewaretoken]').value;
    async function read(params){const url=new URL(root.dataset.historyUrl,location.origin);url.searchParams.set('channel',root.dataset.channel);for(const[k,v]of params)if(v)url.searchParams.set(k,v);const response=await fetch(url,{cache:'no-store'});if(!response.headers.get('content-type')?.includes('application/json'))throw Error('登录已失效，请重新登录。');const data=await response.json();if(!response.ok)throw Error(data.error||'无法读取聊天记录。');return data;}
    async function search(append=false){
      if(busy){if(!append)pendingSearch=true;return;}busy=true;const version=++epoch;status.textContent='正在查找…';more.disabled=true;
      if(!append){results.replaceChildren();query=new URLSearchParams(new FormData(form));next=null;}
      const params=new URLSearchParams(query);if(append&&next)params.set('before',next);
      try{const data=await read(params);if(version!==epoch)return;
        for(const item of data.messages){const button=document.createElement('button');button.type='button';button.className='history-result';
          const byline=document.createElement('strong');byline.textContent=item.author+' · '+item.at;
          const body=document.createElement('span');body.textContent=(item.body||'').slice(0,500)||'附件 / 引用';
          const files=document.createElement('small');files.textContent=[...(item.attachments||[]).map(f=>f.name),...(item.references||[]).map(r=>r.title)].join(' · ');
          button.append(byline,body,files);button.addEventListener('click',async()=>{if(busy)return;busy=true;status.textContent='正在定位消息…';try{const context=await read(new URLSearchParams({around:String(item.id)}));dialog.close();root.dispatchEvent(new CustomEvent('conversation-jump',{detail:context}));}catch(error){status.textContent=error.message;}finally{busy=false;}});results.append(button);
        }
        next=data.next_before;more.hidden=!next;status.textContent=results.children.length?'找到 '+results.children.length+' 条记录，点击查看上下文。':'没有匹配的记录。';
      }catch(error){status.textContent=error.message;}finally{busy=false;more.disabled=false;if(pendingSearch){pendingSearch=false;search();}}
    }
    form.addEventListener('submit',event=>{event.preventDefault();search();});more.addEventListener('click',()=>search(true));
    dialog.querySelector('[data-history-close]').addEventListener('click',()=>dialog.close());
    root.querySelectorAll('[data-conversation-action]').forEach(button=>button.addEventListener('click',async()=>{
      const action=button.dataset.conversationAction;root.querySelector('[data-conversation-menu]').open=false;
      if(action==='search'){dialog.showModal();form.querySelector('input').focus();search();return;}
      if(busy)return;
      if(action==='clear'&&!confirm('清空你在当前聊天中的全部历史记录？这只影响你的记录，对方仍可查看；清空后不能恢复。'))return;
      if(action==='remove'&&!confirm('从你的列表移除当前会话？聊天记录会保留，收到新消息后会重新出现。'))return;
      busy=true;button.disabled=true;
      try{const response=await fetch(root.dataset.manageUrl,{method:'POST',headers:{'X-CSRFToken':csrf()},body:new URLSearchParams({channel:root.dataset.channel,action:action==='mute'&&button.getAttribute('aria-pressed')==='true'?'unmute':action,confirm:'yes'}),cache:'no-store'});
        if(!response.headers.get('content-type')?.includes('application/json'))throw Error('登录已失效，请重新登录。');const data=await response.json();if(!response.ok)throw Error(data.error||'操作未完成。');paint(data);root.dispatchEvent(new CustomEvent('conversation-state-change',{detail:data}));
        if(action==='clear'){root.dispatchEvent(new CustomEvent('conversation-cleared',{detail:data}));root.querySelector('[data-message-status]').textContent='已清空自己的聊天记录';}
        if(action==='mute'){button.setAttribute('aria-pressed',String(data.muted));button.textContent=data.muted?'关闭消息免打扰':'开启消息免打扰';root.querySelector('[data-current-muted]').hidden=!data.muted;}
        if(action==='remove')location.href='/workspace/';
      }catch(error){root.querySelector('[data-message-status]').textContent=error.message;}finally{busy=false;button.disabled=false;}
    }));
    const latest=root.querySelector('[data-conversation-latest]'),older=root.querySelector('[data-conversation-older]');
    latest.addEventListener('click',async()=>{if(busy)return;busy=true;try{const data=await read(new URLSearchParams());data.messages.reverse();root.dispatchEvent(new CustomEvent('conversation-latest',{detail:data}));latest.hidden=true;older.disabled=false;}catch(error){root.querySelector('[data-message-status]').textContent=error.message;}finally{busy=false;}});
    older.addEventListener('click',async()=>{if(busy)return;const first=root.querySelector('[data-message-log] [data-id]');if(!first)return;busy=true;older.disabled=true;try{const data=await read(new URLSearchParams({before:first.dataset.id}));data.messages.reverse();root.dispatchEvent(new CustomEvent('conversation-older',{detail:data}));if(!data.messages.length)older.textContent='已到最早消息';else older.disabled=false;}catch(error){older.disabled=false;root.querySelector('[data-message-status]').textContent=error.message;}finally{busy=false;}});
  });
})();
