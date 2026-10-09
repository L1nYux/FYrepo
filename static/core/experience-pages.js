(()=>{'use strict';
const root=document.querySelector('[data-experience-page]'),X=window.zhiyuExperience;if(!root||!X)return;
const key=root.dataset.channel,status=root.querySelector('[data-page-status]');
const link=view=>'/app/pages/?view='+view+'&channel='+encodeURIComponent(key);
const error=e=>status.textContent=e.message||'操作未完成。';
const post=(action,extra={})=>X.json('/app/preferences/',{channel:key,action,...extra});
for(const form of root.querySelectorAll('[data-group-page-form]'))form.onsubmit=async e=>{e.preventDefault();const b=e.submitter;if(b?.dataset.confirm&&!confirm(b.dataset.confirm))return;const body=new FormData(form);if(b?.name)body.set(b.name,b.value);if(b)b.disabled=true;try{await X.json(form.dataset.groupPageForm,body);location.reload();}catch(e){error(e);if(b)b.disabled=false;}};
root.querySelector('[data-experience-back]').onclick=e=>{if(history.length>1&&document.referrer&&new URL(document.referrer).origin===location.origin){e.preventDefault();history.back();}};
let saved={};
async function refresh(){saved=await X.json('/app/preferences/?channel='+encodeURIComponent(key));for(const button of root.querySelectorAll('[data-pref-toggle]')){const field=button.dataset.prefToggle;button.textContent=field==='pinned'?(saved.pinned?'取消置顶聊天':'置顶聊天'):(saved.blocked?'移出黑名单':'加入黑名单');button.setAttribute('aria-pressed',String(saved[field]));}const mode=root.querySelector('[data-notification-mode]');if(mode)mode.value=saved.notification_mode;}
const mute=root.querySelector('[data-notification-mute]'),switches=[...root.querySelectorAll('[data-pref-switch]')],choices=[...root.querySelectorAll('[data-notification-choice]')];
const originalRefresh=refresh;refresh=async()=>{await originalRefresh();if(mute)mute.checked=saved.notification_mode!=='all';for(const input of switches)input.checked=Boolean(saved[input.dataset.prefSwitch]);for(const input of choices)input.checked=input.value===saved.notification_mode;const caption=root.querySelector('[data-notification-caption]');if(caption)caption.textContent=({all:'全部',important:'仅重要消息',none:'已关闭'})[saved.notification_mode]||'';};
async function saveChoice(input,action,extra={}){input.disabled=true;try{await post(action,extra);await refresh();status.textContent='设置已保存';}catch(e){error(e);await refresh().catch(()=>{});}finally{input.disabled=false;}}
if(mute)mute.onchange=()=>saveChoice(mute,'notifications',{mode:mute.checked?(key.startsWith('person:')?'none':'important'):'all'});
for(const input of switches)input.onchange=()=>saveChoice(input,input.checked?'pin':'unpin');
for(const input of choices)input.onchange=()=>{if(input.checked)saveChoice(input,'notifications',{mode:input.value});};
if(root.dataset.experiencePage!=='profile')refresh().catch(error);
const profile=root.querySelector('[data-profile-page]');if(profile)window.workbenchRenderMember?.(profile.dataset.profilePage,profile);
const search=root.querySelector('[data-page-history]');
if(search){
  let before='',busy=false;const shown=new Set(),list=root.querySelector('[data-page-history-results]'),more=root.querySelector('[data-page-history-more]');
  function paint(message){
    if(shown.has(message.id))return;shown.add(message.id);
    const card=document.createElement('article');card.className='experience-history-row';
    const title=document.createElement('small');title.textContent=(message.author||message.sender||'')+' · '+(message.at||'');
    const body=document.createElement('p');body.textContent=message.body|| (message.sticker?'【动画表情】':message.files?.length?'【附件】':'【消息】');card.append(title,body);
    for(const file of message.files||[]){try{const url=new URL(file.url,location.origin);if(url.origin!==location.origin)continue;const a=document.createElement('a');a.href=url.href;a.textContent=/\.(png|jpe?g|gif|webp)$/i.test(file.name)?'【图片】':file.name;a.className='experience-row';card.append(a);}catch(_){} }
    list.append(card);
  }
  async function load(reset){
    if(busy)return;busy=true;more.disabled=true;
    if(reset){before='';shown.clear();list.replaceChildren();more.hidden=true;}
    try{
      if(reset){await window.zhiyuLocalChatLoaded;const channel=root.dataset.returnUrl,term=search.elements.q.value.trim().toLocaleLowerCase();
        const cached=await window.zhiyuReadLocalChat?.(channel)||[];
        cached.filter(row=>!term||[row.body,row.author,row.quote,...(row.files||[]).map(f=>f.name)].some(value=>(value||'').toLocaleLowerCase().includes(term))).sort((a,b)=>b.id-a.id).forEach(paint);
      }
      if(!navigator.onLine){status.textContent=list.childElementCount?'离线 · 本机聊天记录':'本机暂无匹配记录';return;}
      const url=new URL(search.dataset.pageHistory,location.origin);url.searchParams.set('q',search.elements.q.value);if(before)url.searchParams.set('before',before);
      const data=await X.json(url.pathname+url.search);(data.messages||[]).forEach(paint);before=data.next_before||'';more.hidden=!before;
      status.textContent=list.childElementCount?'':'没有找到聊天记录。';
    }catch(e){
      if(e.status===401||e.status===403){list.replaceChildren();shown.clear();more.hidden=true;error(e);}
      else if(list.childElementCount)status.textContent='当前显示本机聊天记录';else error(e);
    }finally{busy=false;more.disabled=false;}
  }
  search.onsubmit=e=>{e.preventDefault();load(true);};more.onclick=()=>load(false);load(true);
}
for(const button of root.querySelectorAll('[data-pref-toggle]'))button.onclick=async()=>{const field=button.dataset.prefToggle;if(field==='blocked'&&!saved.blocked&&!confirm('加入黑名单后将无法互相发送私聊消息。已有记录保留。'))return;button.disabled=true;try{await post(field==='pinned'?(saved.pinned?'unpin':'pin'):(saved.blocked?'unblock':'block'));await refresh();}catch(e){error(e);}finally{button.disabled=false;}};
const mode=root.querySelector('[data-notification-mode]');if(mode)mode.onchange=async()=>{mode.disabled=true;try{await post('notifications',{mode:mode.value});status.textContent='提醒设置已保存';}catch(e){error(e);await refresh();}finally{mode.disabled=false;}};
const edit=root.querySelector('[data-contact-edit-page]');if(edit)edit.onsubmit=async e=>{e.preventDefault();const b=edit.querySelector('button');b.disabled=true;try{await post('edit',Object.fromEntries(new FormData(edit)));location.href=link('profile')+'&member='+key.split(':')[1];}catch(e){error(e);b.disabled=false;}};
const remove=root.querySelector('[data-delete-friend]');if(remove)remove.onclick=async()=>{if(!confirm('删除好友关系？已有聊天记录保留。'))return;try{await post('delete_friend',{confirm:'yes'});location.href=root.dataset.returnUrl;}catch(e){error(e);}};
const clear=root.querySelector('[data-clear-chat]');if(clear)clear.onclick=async()=>{if(!confirm('清空自己的这段聊天记录？此操作无法恢复，对方记录保留。'))return;clear.disabled=true;try{await X.json(key.startsWith('team:')?'/messages/manage/?space='+root.dataset.space:root.dataset.returnUrl+'settings/',{channel:'developers',action:'clear',confirm:'yes'});status.textContent='已清空自己的记录';}catch(e){error(e);}finally{clear.disabled=false;}};
for(const form of root.querySelectorAll('[data-image-upload]')){const picker=form.elements.image;let previewURL;picker.onchange=()=>{if(previewURL)URL.revokeObjectURL(previewURL);if(!picker.files.length)return;previewURL=URL.createObjectURL(picker.files[0]);const target=root.querySelector('[data-background-preview] img,.experience-group-image');if(target)target.src=previewURL;else{const image=document.createElement('img');image.alt='待保存的背景';image.src=previewURL;root.querySelector('[data-background-preview]')?.prepend(image);}};form.onsubmit=async e=>{e.preventDefault();const b=form.querySelector('[type=submit]');b.disabled=true;try{const body=new FormData(form);body.set('channel',key);body.set('action','background');await X.json(form.dataset.imageUpload==='group'?'/app/groups/'+form.dataset.groupId+'/image/':'/app/preferences/',body);status.textContent='图片已保存';}catch(e){error(e);}finally{b.disabled=false;}};window.addEventListener('pagehide',()=>{if(previewURL)URL.revokeObjectURL(previewURL);},{once:true});}
const reset=root.querySelector('[data-background-reset]');if(reset)reset.onclick=async()=>{try{await post('background_clear');root.querySelector('[data-background-preview] img')?.remove();status.textContent='已恢复默认背景';}catch(e){error(e);}};
const groupReset=root.querySelector('[data-group-reset]');if(groupReset)groupReset.onclick=async()=>{try{const data=await X.json('/app/groups/'+groupReset.dataset.groupReset+'/image/',{action:'reset'});root.querySelector('.experience-group-image').src=data.avatar_url+'?v='+Date.now();status.textContent='已恢复成员组合头像';}catch(e){error(e);}};
})();
