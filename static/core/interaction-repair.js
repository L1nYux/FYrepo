/* Small shared presentation primitives; account-scoped preferences work offline. */
(() => {
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const palette={green:['#079b61','#057849','#e4f5ed'],blue:['#3679d5','#215dae','#e9f1ff'],purple:['#8654c7','#68409d','#f1eafa'],orange:['#bf6415','#914709','#fff0df'],pink:['#c14c83','#973560','#fce9f2']};
  const key='zhiyu-accent:'+document.documentElement.dataset.account;
  function apply(name){const p=palette[name]||palette.green;if(document.documentElement.dataset.accent!==name)document.documentElement.dataset.accent=name;document.documentElement.style.setProperty('--accent',document.documentElement.dataset.theme==='dark'?p[0]:p[1]);document.documentElement.style.setProperty('--accent-solid',p[0]);document.documentElement.style.setProperty('--accent-soft',p[2]);document.documentElement.style.setProperty('--accent-ink','#fff');}
  try{apply(localStorage.getItem(key)||'green');}catch(_){apply('green');}
  new MutationObserver(()=>apply(document.documentElement.dataset.accent)).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','data-accent']});
  window.addEventListener('storage',e=>{if(e.key===key)apply(e.newValue||'green');});
  document.querySelectorAll('[data-accent-choice]').forEach(button=>{button.style.setProperty('--swatch',palette[button.dataset.accentChoice][0]);button.onclick=()=>{const value=button.dataset.accentChoice;apply(value);try{localStorage.setItem(key,value);}catch(_){}window.workbenchDownloads?.accent(value).catch(()=>{});document.querySelectorAll('[data-accent-choice]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));};button.setAttribute('aria-pressed',String(button.dataset.accentChoice===document.documentElement.dataset.accent));});
  if(/ZhiyuMobile/.test(navigator.userAgent)){
    let last;
    const sync=()=>{
      // A native command must wait for the page's deferred feature scripts.
      if(document.readyState!=='complete')return;
      const name=document.documentElement.dataset.accent;
      if(name!==last){last=name;location.href='/__phone_accent__/?name='+encodeURIComponent(name);}
    };
    new MutationObserver(sync).observe(document.documentElement,{attributes:true,attributeFilter:['data-accent']});
    if(document.readyState==='complete')setTimeout(sync,0);
    else window.addEventListener('load',()=>setTimeout(sync,0),{once:true});
  }
  window.workbenchFileCard=file=>{const a=node('a',undefined,'message-file file-card'),copy=node('span',undefined,'file-card-copy'),name=node('strong',file.name),meta=node('small',(file.size==null?'':format(file.size)+' · ')+(file.type||file.name.split('.').pop().toUpperCase()));copy.append(name,meta);a.append(copy,node('span',file.type||file.name.split('.').pop().toUpperCase(),'file-type-icon'));a.href=file.preview_url||file.url;a.dataset.downloadUrl=file.url;a.dataset.fileName=file.name;a.dataset.fileType=file.type||file.name.split('.').pop().toUpperCase();if(file.size!=null)a.dataset.size=file.size;a.querySelector('.file-type-icon').dataset.fileType=a.dataset.fileType;return a;};
  function format(bytes){return bytes<1024?bytes+' B':bytes<1048576?(bytes/1024).toFixed(1)+' KB':(bytes/1048576).toFixed(1)+' MB';}
  document.querySelectorAll('[data-message-id],[data-id],[data-cached-id]').forEach(n=>{if(n.closest('.conversation-log'))n.id='message-'+(n.dataset.messageId||n.dataset.id||n.dataset.cachedId);});
  if(location.hash.startsWith('#message-'))requestAnimationFrame(()=>document.getElementById(location.hash.slice(1))?.scrollIntoView({block:'center'}));
  let closeMessagePopover;
  document.addEventListener('selectionchange',()=>{
    const selection=window.getSelection();
    document.querySelectorAll('.experience-selectable,.phone-selectable').forEach(text=>{if(!selection||selection.isCollapsed||!selection.containsNode(text,true))text.classList.remove('experience-selectable','phone-selectable');});
  });
  window.workbenchMessagePopover=(anchor,actions)=>{
    closeMessagePopover?.();const box=node('div',undefined,'message-action-popover');box.setAttribute('role','dialog');box.setAttribute('aria-label','消息操作');
    const icons={'复制':'document','选择文字':'reference','转发':'forward','引用':'reference','撤回':'transfer','删除':'file','多选':'task','移到前面':'transfer','取消收藏':'file','下载文件':'save','保存图片 / GIF':'image','添加到表情':'image'};
    for(const action of actions){const b=node('button',undefined,action.danger?'danger':'');b.type='button';b.disabled=!!action.disabled;const icon=window.zhiyuExperience?.toolIcon(icons[action.label]||'reference');if(icon)b.append(icon);b.append(node('span',action.label));b.onclick=async()=>{dismiss();try{await action.run();}catch(e){window.zhiyuExperience?.toast(e.message||'操作未完成');}};box.append(b);}
    const close=node('button','关闭','popover-close');close.type='button';close.onclick=()=>dismiss();box.append(close);document.body.append(box);
    const rect=anchor.getBoundingClientRect(),height=box.offsetHeight,width=box.offsetWidth;box.style.left=Math.max(8,Math.min(rect.left+(rect.width-width)/2,innerWidth-width-8))+'px';box.style.top=Math.max(8,Math.min(rect.top-height-10>8?rect.top-height-10:rect.bottom+10,innerHeight-height-8))+'px';
    function dismiss(){box.remove();document.removeEventListener('pointerdown',away,true);document.removeEventListener('keydown',escape,true);window.removeEventListener('resize',dismiss);window.removeEventListener('scroll',dismiss,true);if(closeMessagePopover===dismiss)closeMessagePopover=null;}
    const away=e=>{if(!box.contains(e.target))dismiss();},escape=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();dismiss();}};
    closeMessagePopover=dismiss;setTimeout(()=>{if(box.isConnected)document.addEventListener('pointerdown',away,true);},0);document.addEventListener('keydown',escape,true);window.addEventListener('resize',dismiss);window.addEventListener('scroll',dismiss,true);
  };
})();
