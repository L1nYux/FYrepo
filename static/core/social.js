(() => {
  const memberDialog=document.createElement('dialog');memberDialog.className='member-card-dialog';document.body.append(memberDialog);
  let epoch=0;
  const node=(tag,text,className)=>{const value=document.createElement(tag);if(text)value.textContent=text;if(className)value.className=className;return value;};
  async function member(id, target){
    const dialog=target||memberDialog;const inline=Boolean(target);
    const showing=()=>inline||dialog.open;
    const version=++epoch;
    dialog.replaceChildren();dialog.setAttribute('aria-label','成员资料');
    const toolbar=node('div','', 'member-card-toolbar'),close=node('button','×','member-card-close');close.type='button';close.setAttribute('aria-label','关闭成员资料');close.addEventListener('click',()=>inline?dialog.replaceChildren():dialog.close());toolbar.append(close);
    const status=node('p','正在读取成员资料…');status.setAttribute('role','status');dialog.append(toolbar,status);if(!inline&&!dialog.open)dialog.showModal();
    try{
      const response=await fetch(window.workbenchMessageURL('/members/'+id+'/card/'),{cache:'no-store'});if(!response.ok)throw Error('成员资料不可用。');
      const data=await response.json();if(version!==epoch||!showing())return;status.remove();
      const header=node('div','', 'member-card-header'),avatar=node('span','', 'user-avatar');window.workbenchAvatar?.(avatar,data.avatar_url,data.initial);
      const identity=node('div'),name=node('h2',data.display_name||data.name||data.username);identity.append(name,node('small','工作台号：'+data.username));header.append(avatar,identity);dialog.append(header);
      const facts=node('dl','', 'member-card-facts');
      const fact=(label,value)=>{facts.append(node('dt',label),node('dd',value));};
      if(data.real_name)fact('姓名',data.real_name);
      fact('团队身份',data.role+(data.active===false?' · 已停用':''));
      fact('研究方向',data.research_area||'尚未公开');fact('个人简介',data.bio||'尚未公开');
      const projects=node('dd');for(const project of data.projects||[]){const link=node('a',project.name);link.href=project.url;projects.append(link);}if(!projects.childNodes.length)projects.textContent='暂无';facts.append(node('dt','负责项目'),projects);dialog.append(facts);
      const footer=node('div','', 'member-card-footer');
      if(data.chat_url){const link=node('a',data.self?'编辑我的资料':'发消息','button primary');link.href=data.chat_url;footer.append(link);}
      if(data.manage_url&&!data.self){const link=node('a','管理成员','button');link.href=data.manage_url;footer.append(link);}
      if(!data.self){
        if(data.friend_url){
          const form=node('form'),button=node('button',data.friend_state==='received'?'接受好友申请':'加好友','button');
          button.type='submit';form.append(button);footer.append(form);
          form.addEventListener('submit',async event=>{event.preventDefault();button.disabled=true;status.textContent='正在处理…';dialog.append(status);
            try{const response=await fetch(data.friend_url,{method:'POST',headers:{Accept:'application/json','X-CSRFToken':data.csrf_token},body:new URLSearchParams({username:data.username,action:'accept'})});
              if(!response.headers.get('content-type')?.includes('application/json'))throw Error('请重新登录后重试。');
              const result=await response.json();if(!response.ok)throw Error(result.error||'好友申请失败。');
              if(version!==epoch||!showing())return;if(result.state==='friends'){await member(id,target);return;}status.textContent=result.state==='friends'?'已成为好友':'好友申请已发送，等待对方确认。';button.textContent=result.state==='friends'?'已是好友':'申请已发送';
            }catch(error){if(version===epoch&&showing()){status.textContent=error.message;button.disabled=false;}}
          });
        }else if(data.friend_state==='sent'||data.friend_state==='friends')footer.append(node('small',data.friend_state==='friends'?'已是好友':'好友申请已发送'));
      }
      if(footer.childNodes.length)dialog.append(footer);
    }catch(error){if(version===epoch&&showing())status.textContent=error.message;}
  }
  document.addEventListener('click',event=>{const contact=event.target.closest('[data-contact-id]');if(contact){event.preventDefault();event.stopPropagation();member(contact.dataset.contactId,document.querySelector('[data-contact-details]'));return;}const avatar=event.target.closest('[data-member-id]');if(!avatar||!avatar.dataset.memberId)return;event.preventDefault();event.stopPropagation();member(avatar.dataset.memberId);});
  document.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('[data-member-id]')){event.preventDefault();member(event.target.dataset.memberId);}});
  memberDialog.addEventListener('close',()=>epoch++);
  document.querySelectorAll('[data-messages], [data-personal-thread]').forEach(root=>{
    const fetch=(url,options)=>window.fetch(window.workbenchMessageURL(url,root),options);
    const panel=document.createElement('dialog');panel.className='sticker-panel';panel.innerHTML='<div class="heading"><h2>表情与表情包</h2><button type="button" data-close aria-label="关闭">×</button></div><div class="emoji-grid"></div><h3>我的收藏</h3><div class="sticker-grid"></div><label class="button">上传图片 / GIF<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden></label><p role="status"></p>';
    root.append(panel);const status=panel.querySelector('[role=status]'), grid=panel.querySelector('.sticker-grid'), form=root.querySelector('[data-message-form]'), field=form.querySelector('[name=sticker_id]'), box=form.querySelector('textarea');
    const csrf=()=>form.querySelector('[name=csrfmiddlewaretoken]').value;
    async function request(body){const response=await fetch('/messages/stickers/',{method:body?'POST':'GET',headers:body?{'X-CSRFToken':csrf()}:undefined,body,cache:'no-store'});if(!response.headers.get('content-type')?.includes('application/json'))throw Error('请重新登录。');const data=await response.json();if(!response.ok)throw Error(data.error||'表情操作失败。');return data;}
    async function load(){status.textContent='正在读取…';try{const data=await request();grid.replaceChildren();for(const sticker of data.stickers){const item=document.createElement('div'),button=document.createElement('button');button.type='button';const image=document.createElement('img');image.src=sticker.url;image.alt=sticker.name;button.append(image);button.addEventListener('click',()=>{field.value=String(sticker.id);root.dispatchEvent(new CustomEvent('message-content-change'));panel.close();form.requestSubmit(form.querySelector('.composer-footer .primary'));});const remove=document.createElement('button');remove.type='button';remove.textContent='移除';remove.addEventListener('click',async()=>{remove.disabled=true;try{await request(new URLSearchParams({action:'remove',id:String(sticker.id)}));load();}catch(error){status.textContent=error.message;remove.disabled=false;}});item.append(button,remove);grid.append(item);}status.textContent=data.stickers.length?'点击表情包直接发送。':'上传图片，或在聊天消息菜单中收藏图片。';}catch(error){status.textContent=error.message;}}
    for(const emoji of (window.workbenchEmoji||['😀','😊','👍'])){const button=document.createElement('button');button.type='button';button.textContent=emoji;button.setAttribute('aria-label',emoji);button.addEventListener('click',()=>{box.setRangeText(emoji,box.selectionStart,box.selectionEnd,'end');box.dispatchEvent(new Event('input',{bubbles:true}));panel.close();box.focus();});panel.querySelector('.emoji-grid').append(button);}
    root.querySelector('[data-sticker-open]').addEventListener('click',()=>{panel.showModal();load();});panel.querySelector('[data-close]').addEventListener('click',()=>panel.close());
    async function upload(file){if(!file||file.size>5*1024*1024)throw Error('图片不能超过 5 MB。');const body=new FormData();body.set('file',file);await request(body);status.textContent='已加入收藏。';}
    panel.querySelector('input').addEventListener('change',async event=>{const file=event.target.files[0];event.target.value='';if(!file)return;status.textContent='正在上传…';try{await upload(file);load();}catch(error){status.textContent=error.message;}});
    root.addEventListener('sticker-favorite',async event=>{try{if(event.detail.id)await request(new URLSearchParams({action:'favorite',id:String(event.detail.id)}));else{const response=await fetch(event.detail.url);if(!response.ok)throw Error('图片不可用。');const blob=await response.blob();await upload(new File([blob],event.detail.name,{type:blob.type}));}root.querySelector('[data-message-status]').textContent='已收藏表情包';}catch(error){root.querySelector('[data-message-status]').textContent=error.message;}});
  });
})();
