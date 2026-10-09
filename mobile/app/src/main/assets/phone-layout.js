/* Bundled phone layout; remote responses supply authorized business data. */
(()=>{'use strict';if(window.zhiyuPhoneLayout)return;window.zhiyuPhoneLayout=true;
const X=window.zhiyuExperience,main=document.querySelector('main'),path=location.pathname;
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const row=(title,url)=>{const a=node('a',title,'phone-setting-row');a.href=url;const arrow=node('span','›');a.append(arrow);return a;};
const csrf=()=>document.querySelector('[name=csrfmiddlewaretoken]')?.value||'';
if(path==='/workspace/'&&main){
  main.querySelector('.heading')?.remove();const tools=node('section',undefined,'phone-work-tools');
  const filter=main.querySelector('.ownership-filter');if(filter)tools.append(filter);
  const owner=filter?.querySelector('select')?.value||'all',meta=main.querySelector('[data-workspace-owner]');
  const qualify=url=>url+(url.includes('?')?'&':'?')+'ownership='+encodeURIComponent(owner);
  const api=row(owner==='all'?'团队 API':'使用团队 API',owner==='all'?'/me/api/':qualify('/api-pool/'));api.classList.add('phone-team-api');api.hidden=owner!=='all'&&meta?.dataset.workspaceKind==='personal';tools.append(api);
  const grid=node('div',undefined,'experience-tool-grid');for(const [label,url,icon]of [['我的团队',owner!=='all'&&meta?.dataset.workspaceTeam?'/messages/teams/?team='+meta.dataset.workspaceTeam:'/messages/teams/','team'],['任务',qualify('/tasks/'),'task'],['项目',qualify('/projects/'),'project'],['实验',qualify('/experiments/'),'experiment'],['文档',qualify('/documents/'),'document']]){const a=row(label,url);a.prepend(X.toolIcon(icon));grid.append(a);}
  const announcements=main.querySelector('.announcement-list');if(announcements){announcements.id='team-announcements';const a=row('公告','#team-announcements');a.prepend(X.toolIcon('announcement'));grid.append(a);}tools.append(grid);main.prepend(tools);
}
if(/^\/(discover|team-square)(\/|$)/.test(path)&&!/^\/(?:discover\/(?:applications|offers)|team-square\/applications)(\/|$)/.test(path)&&main){const nav=node('nav',undefined,'phone-discovery-nav');for(const [label,url]of [['团队广场','/discover/'],['人才市场','/discover/talents/']])nav.append(row(label,url));main.prepend(nav);}
if(path==='/account/'&&!new URLSearchParams(location.search).has('tab')&&main){
  const logout=document.querySelector('form[action="/logout/"]')?.cloneNode(true);main.replaceChildren();
  for(const[title,items]of [['账号',[['个人资料','/account/?tab=profile'],['账号与安全','/account/?tab=security'],['登录设备','/app/devices/']]],['聊天',[['聊天记录管理','/me/?mobile=history']]],['帮助与关于',[['后台消息提醒','/__phone_background__/'],['检查更新','/__phone_update__/'],['连接设置','/__phone_connection__/'],['关于知域','/__phone_settings__/']]]]){const section=node('section',undefined,'phone-setting-section');section.append(node('h2',title));for(const[label,url]of items)section.append(row(label,url));main.append(section);}
  if(logout){logout.className='phone-logout';logout.querySelector('button')?.classList.add('phone-setting-row');main.append(logout);}
}else if(path==='/me/'&&!location.search)document.querySelector('.phone-logout')?.remove();

const root=document.querySelector('[data-personal-thread],[data-messages]'),composer=root?.querySelector('.conversation-composer'),input=composer?.querySelector('textarea'),log=root?.querySelector('[data-history],[data-message-log],.conversation-log')||document.getElementById('assistant-thread');
let atEnd=true,lastHeight=innerHeight,anchor,anchorOffset=0;
if(log){const measure=()=>{atEnd=log.scrollHeight-log.scrollTop-log.clientHeight<100;anchor=[...log.querySelectorAll('[data-message-id],[data-id],[data-cached-id],.assistant-row')].find(r=>r.getBoundingClientRect().bottom>log.getBoundingClientRect().top);anchorOffset=anchor?anchor.getBoundingClientRect().top-log.getBoundingClientRect().top:0;};log.addEventListener('scroll',measure,{passive:true});measure();}
window.zhiyuPhoneViewport=(height,keyboard)=>{
  if(!(height>0))return;document.documentElement.style.setProperty('--phone-view-height',height+'px');document.documentElement.classList.toggle('phone-keyboard',keyboard);if(height===lastHeight)return;lastHeight=height;
  const pinned=atEnd,old=anchor,offset=anchorOffset;
  requestAnimationFrame(()=>requestAnimationFrame(()=>{if(!log)return;if(pinned){log.scrollTop=log.scrollHeight;atEnd=true;}else if(old?.isConnected)log.scrollTop+=old.getBoundingClientRect().top-log.getBoundingClientRect().top-offset;}));
  if(keyboard)document.querySelectorAll('[data-composer-plus]').forEach(d=>d.open=false);
};
window.visualViewport?.addEventListener('resize',()=>{if(!/ZhiyuMobile/.test(navigator.userAgent))window.zhiyuPhoneViewport(visualViewport.height,innerHeight-visualViewport.height>150);});
if(composer&&input){
  const footer=composer.querySelector('.composer-footer'),tools=composer.querySelector('.composer-tools')||footer,plus=tools?.querySelector('[data-composer-plus]'),smile=tools?.querySelector('[data-sticker-open]'),send=footer?.querySelector('[data-thread-send],button.primary');
  if(footer&&plus&&smile&&send){const line=node('div',undefined,'phone-input-line');line.append(input,smile,plus,send);composer.insertBefore(line,footer);smile.textContent='☺';smile.setAttribute('aria-label','表情 / 键盘');
    const menu=plus.querySelector('.composer-plus-menu'),files=composer.querySelector('input[name=attachments]');
    if(files&&menu){const label=files.closest('label');label.querySelectorAll('span,svg').forEach(e=>e.remove());[...label.childNodes].filter(e=>e.nodeType===3).forEach(e=>e.remove());label.prepend(document.createTextNode('文件')); // retain the original input and its upload listeners
      const fileLabel=menu.querySelector('label');fileLabel.append(files);
      for(const[label,capture]of [['相册',false],['拍摄',true]]){const b=node('button',undefined,'phone-media-tool');const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');const shape=document.createElementNS('http://www.w3.org/2000/svg','path');shape.setAttribute('d',capture?'M4 6h4l2-3h4l2 3h4v14H4Z M16 13a4 4 0 1 1-8 0 4 4 0 0 1 8 0':'M3 3h18v18H3Z M3 17l6-7 5 5 3-3 4 5 M16 7h.01');icon.append(shape);b.append(icon,node('span',label));b.type='button';b.onclick=()=>{plus.open=false;const picker=node('input');picker.type='file';picker.accept='image/*';picker.hidden=true;if(capture)picker.setAttribute('capture','environment');else picker.multiple=true;composer.append(picker);picker.onchange=()=>{if(picker.files.length){const dt=new DataTransfer();for(const f of files.files)dt.items.add(f);for(const f of picker.files)dt.items.add(f);files.files=dt.files;files.dispatchEvent(new Event('change',{bubbles:true}));}picker.remove();};picker.click();};menu.prepend(b);}}
    X.decorateTools(menu);
    const sync=()=>{const content=!!input.value.trim()||!!files?.files.length||!!composer.querySelector('[name=sticker_id]')?.value||(()=>{try{return JSON.parse(composer.querySelector('[name=references]')?.value||'[]').length>0;}catch(_){return false;}})();send.hidden=!content;plus.hidden=content;input.style.height='0px';input.style.height=Math.max(40,Math.min(110,input.scrollHeight))+'px';};
    root.addEventListener('message-content-change',sync);composer.addEventListener('input',sync);composer.addEventListener('change',sync);new MutationObserver(sync).observe(composer,{childList:true,subtree:true});sync();
    plus.addEventListener('toggle',()=>{if(plus.open){input.blur();const panel=document.querySelector('[data-emoji-panel]');if(panel)panel.hidden=true;smile.setAttribute('aria-expanded','false');if(atEnd)requestAnimationFrame(()=>log.scrollTop=log.scrollHeight);}});
    input.addEventListener('focus',()=>{plus.open=false;document.querySelectorAll('[data-emoji-panel]').forEach(e=>e.hidden=true);smile.setAttribute('aria-expanded','false');});
    const previews=node('div',undefined,'phone-file-previews');footer.append(previews);let urls=[];
    const preview=()=>{urls.forEach(URL.revokeObjectURL);urls=[];previews.replaceChildren();[...files?.files||[]].forEach((file,index)=>{const chip=node('div',undefined,'phone-file-chip');if(file.type.startsWith('image/')){const image=node('img');image.src=URL.createObjectURL(file);image.alt=file.name;urls.push(image.src);chip.append(image);}else chip.append(node('span',file.name));const remove=node('button','×');remove.type='button';remove.setAttribute('aria-label','移除 '+file.name);remove.onclick=()=>{const dt=new DataTransfer();[...files.files].forEach((f,i)=>{if(i!==index)dt.items.add(f);});files.files=dt.files;files.dispatchEvent(new Event('change',{bubbles:true}));};chip.append(remove);previews.append(chip);});sync();};files?.addEventListener('change',preview);root.addEventListener('message-content-change',()=>{if(!files?.files.length&&previews.childElementCount){urls.forEach(URL.revokeObjectURL);urls=[];previews.replaceChildren();}});window.addEventListener('pagehide',()=>urls.forEach(URL.revokeObjectURL),{once:true});
  }
}
})();
