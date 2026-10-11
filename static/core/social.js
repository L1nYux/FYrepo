(() => {
  const memberDialog=document.createElement('dialog');memberDialog.className='member-card-dialog';document.body.append(memberDialog);
  let epoch=0;
  const memberScope=window.zhiyuRuntime.mount('member-card',memberDialog,()=>{}), lookup=memberScope.latest();
  const node=(tag,text,className)=>{const value=document.createElement(tag);if(text)value.textContent=text;if(className)value.className=className;return value;};
  async function member(id, target){
    const dialog=target||memberDialog;const inline=Boolean(target);
    const showing=()=>inline?dialog.isConnected:dialog.open;
    const version=++epoch;
    dialog.replaceChildren();dialog.setAttribute('aria-label','成员资料');if(inline)dialog.closest('.experience-page')?.querySelector('.experience-page-heading .member-card-toolbar')?.remove();
    const toolbar=node('div','', 'member-card-toolbar'),close=node('button','×','member-card-close');close.type='button';close.setAttribute('aria-label','关闭成员资料');close.addEventListener('click',()=>inline?dialog.replaceChildren():dialog.close());toolbar.append(close);
    const status=node('p','正在读取成员资料…');status.setAttribute('role','status');dialog.append(toolbar,status);if(!inline&&!dialog.open)dialog.showModal();
    try{
      const data=await lookup.run(signal=>window.zhiyuRuntime.json(window.workbenchMessageURL('/members/'+id+'/card/'),undefined,{signal}));if(version!==epoch||!showing())return;status.remove();
      const header=node('div','', 'member-card-header'),avatar=node('span','', 'user-avatar');window.workbenchAvatar?.(avatar,data.avatar_url,data.initial);
      const identity=node('div'),name=node('h2',data.display_name||data.name||data.username);identity.append(name,node('small','工作台号：'+data.username));header.append(avatar,identity);dialog.append(header);
      const facts=node('dl','', 'member-card-facts');
      const fact=(label,value)=>{facts.append(node('dt',label),node('dd',value));};
      if(data.real_name)fact('姓名',data.real_name);
      fact('团队身份',data.role+(data.active===false?' · 已停用':''));
      fact('研究方向',data.research_area||'尚未公开');fact('个人简介',data.bio||'尚未公开');
      const projects=node('dd');for(const project of data.projects||[]){const link=node('a',project.name);link.href=project.url;projects.append(link);}if(!projects.childNodes.length)projects.textContent='暂无';facts.append(node('dt','负责项目'),projects);dialog.append(facts);
      if(!data.self&&window.zhiyuExperience){const edit=node('button','','member-card-edit');edit.type='button';edit.setAttribute('aria-label','编辑联系人备注');edit.append(window.zhiyuExperience.toolIcon('reference'));edit.onclick=()=>window.zhiyuExperience.contactEdit(data,()=>member(id,target));const more=node('button','⋯','member-card-more');more.type='button';more.setAttribute('aria-label','联系人设置');more.onclick=()=>window.zhiyuExperience.contactSettings(data,()=>member(id,target));toolbar.prepend(edit,more);if(inline)dialog.closest('.experience-page').querySelector('.experience-page-heading').append(toolbar);}
      if(data.nickname&&data.display_name!==data.nickname)identity.append(node('small','昵称：'+data.nickname));
      const footer=node('div','', 'member-card-footer');
      if(data.chat_url){const link=node('a',data.self?'编辑我的资料':'发消息','button primary');link.href=data.chat_url;footer.append(link);}
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
    }catch(error){if(error.name!=='AbortError'&&version===epoch&&showing())status.textContent=error.message;}
  }
  window.workbenchRenderMember=member;
  function openMember(id,anchor){
    const conversation=anchor?.closest('[data-conversation-key]');if(conversation){location.href=conversation.href;return;}
    location.href='/app/pages/?view=profile&member='+id;
  }
  window.workbenchMemberCard=openMember;
  document.addEventListener('click',event=>{const contact=event.target.closest('[data-contact-id]');if(contact){event.preventDefault();event.stopPropagation();openMember(contact.dataset.contactId,contact);return;}const avatar=event.target.closest('[data-member-id]');if(!avatar||!avatar.dataset.memberId)return;event.preventDefault();event.stopPropagation();openMember(avatar.dataset.memberId,avatar);});
  document.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('[data-member-id]')){event.preventDefault();openMember(event.target.dataset.memberId,event.target);}});
  memberDialog.addEventListener('close',()=>{epoch++;lookup.cancel();});
})();
