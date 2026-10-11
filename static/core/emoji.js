/* Shared, locally hosted Emoji Mart picker. No runtime CDN or remote artwork. */
(() => {
  const asset=document.querySelector('[data-emoji-assets]');if(!asset)return;
  let resources,active;
  // Emoji Mart exposes its storage adapter; scope preferences to the signed-in account.
  const storeKey=key=>'zhiyu-emoji:'+document.documentElement.dataset.account+':'+key;
  EmojiMart.Store.get=key=>{try{return JSON.parse(localStorage.getItem(storeKey(key))||'null');}catch(_){return undefined;}};
  EmojiMart.Store.set=(key,value)=>{try{localStorage.setItem(storeKey(key),JSON.stringify(value));}catch(_){}};
  const data=()=>resources||(resources=Promise.all([asset.dataset.emojiData,asset.dataset.emojiLocale].map(async url=>{const response=await fetch(url,{credentials:'same-origin'});if(!response.ok)throw Error('表情加载失败，请重试。');return response.json();})).catch(error=>{resources=null;throw error;}));
  window.workbenchEmojiPicker=({opener,box,form,root,onSticker})=>{
    const panel=document.createElement('div');panel.className='expression-picker';panel.hidden=true;panel.dataset.emojiPanel='';panel.setAttribute('role','dialog');panel.setAttribute('aria-label','表情');
    panel.innerHTML='<div data-emoji-content></div><section data-favorites hidden><div class="expression-favorites"></div></section><footer><button type="button" data-tab="emoji" aria-label="默认表情">☺</button><button type="button" data-tab="favorites" aria-label="收藏表情">♡</button><button type="button" data-upload aria-label="添加表情">＋</button><button type="button" data-edit-favorites>整理</button><button type="button" data-close aria-label="关闭表情">×</button></footer><p role="status" aria-live="polite"></p>';
    document.body.append(panel);opener.setAttribute('aria-haspopup','dialog');opener.setAttribute('aria-expanded','false');
    if(typeof onSticker!=='function')panel.querySelectorAll('[data-tab="favorites"],[data-upload],[data-edit-favorites]').forEach(button=>button.hidden=true);
    const status=panel.querySelector('[role=status]'),favorites=panel.querySelector('.expression-favorites');let picker,start=0,end=0,epoch=0;
    const requestURL=url=>window.workbenchMessageURL?window.workbenchMessageURL(url,root):url;
    const csrf=()=>form.querySelector('[name=csrfmiddlewaretoken]')?.value||'';
    const libraryURL=()=>{const match=location.pathname.match(/^\/messages\/(personal|groups)\/([1-9]\d*)\/$/);let channel=match?(match[1]==='personal'?'person:':'group:')+match[2]:root?.dataset.channel||'';if(channel.startsWith('dm:'))channel='person:'+channel.slice(3);if(channel==='developers'&&root?.dataset.team)channel='team:'+root.dataset.team;return '/app/pages/?view=stickers'+(/^(person|group|team):[1-9]\d*$/.test(channel)?'&channel='+encodeURIComponent(channel):'');};
    async function request(body){const response=await fetch(requestURL('/messages/stickers/'),{method:body?'POST':'GET',headers:{Accept:'application/json',...(body?{'X-CSRFToken':csrf()}:{})},body,cache:'no-store'});if(!response.headers.get('content-type')?.includes('application/json'))throw Error('请重新登录后重试。');const value=await response.json();if(!response.ok)throw Error(value.error||'表情操作失败。');return value;}
    function close(focus=!/ZhiyuMobile/.test(navigator.userAgent)){++epoch;panel.hidden=true;opener.setAttribute('aria-expanded','false');if(active===close)active=null;if(focus)box.focus();}
    function position(){if(/ZhiyuMobile/.test(navigator.userAgent)){const host=root?.querySelector('.conversation-composer,.assistant-composer');if(host&&panel.parentNode!==host)host.append(panel);panel.style.left='';panel.style.top='';return;}const rect=opener.getBoundingClientRect();panel.style.left=Math.max(8,Math.min(rect.left,innerWidth-panel.offsetWidth-8))+'px';panel.style.top=Math.max(8,Math.min(rect.top-panel.offsetHeight-8,innerHeight-panel.offsetHeight-8))+'px';}
    function tab(name){++favoritesSequence;panel.querySelector('[data-emoji-content]').hidden=name!=='emoji';panel.querySelector('[data-favorites]').hidden=name!=='favorites';panel.querySelector('[data-edit-favorites]').hidden=name!=='favorites';panel.querySelectorAll('[data-tab]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.tab===name)));status.textContent='';position();if(name==='favorites')load();}
    let stickerValues=[],stickerBusy=false,favoritesSequence=0;
    async function load(){
      const token=epoch,sequence=++favoritesSequence;status.textContent='正在读取…';
      try{
        const value=await request();if(token!==epoch||sequence!==favoritesSequence||panel.hidden||panel.querySelector('[data-favorites]').hidden)return;
        stickerValues=value.stickers;favorites.replaceChildren();
        const add=document.createElement('button');add.type='button';add.className='sticker-add';add.textContent='＋';add.setAttribute('aria-label','添加表情');add.onclick=()=>location.href=libraryURL();favorites.append(add);
        for(const sticker of stickerValues){
          const item=document.createElement('div'),button=document.createElement('button'),image=document.createElement('img');
          button.type='button';button.dataset.stickerId=sticker.id;button.disabled=stickerBusy;image.src=requestURL(sticker.url);image.alt=sticker.name;button.title=sticker.name;button.append(image);item.append(button);favorites.append(item);
          button.onclick=async()=>{
            if(stickerBusy)return;stickerBusy=true;status.textContent='';
            favorites.querySelectorAll('[data-sticker-id]').forEach(b=>b.disabled=true);
            try{await onSticker(sticker);}catch(error){status.textContent=error.message;}
            finally{stickerBusy=false;favorites.querySelectorAll('[data-sticker-id]').forEach(b=>b.disabled=false);}
          };
        }
        status.textContent=stickerValues.length?'':'点击“＋”添加表情';
      }catch(error){if(token===epoch&&sequence===favoritesSequence&&!panel.hidden)status.textContent=error.message;}
    }
    const bindHold=()=>window.zhiyuExperience.hold(favorites,'[data-sticker-id]',chosen=>{
      if(stickerBusy)return;
      const sticker=stickerValues.find(item=>String(item.id)===chosen.dataset.stickerId);if(!sticker)return;
      window.zhiyuChatUI.stickerActions(chosen,{...sticker,url:requestURL(sticker.url)},[
        {label:'移到前面',run:async()=>{await request(new URLSearchParams({action:'move',ids:sticker.id}));await load();}},
        {label:'删除',danger:true,run:async()=>{await request(new URLSearchParams({action:'remove',id:sticker.id}));await load();}}
      ]);
    });
    if(window.zhiyuExperience)bindHold();else document.addEventListener('DOMContentLoaded',bindHold,{once:true});
    async function upload(file){if(!file||file.size>5*1024*1024)throw Error('图片不能超过 5 MB。');const body=new FormData();body.set('file',file);return request(body);}
    opener.addEventListener('click',async()=>{
      if(!panel.hidden){close();return;}active?.(false);active=close;start=box.selectionStart;end=box.selectionEnd;panel.hidden=false;opener.setAttribute('aria-expanded','true');const token=++epoch;if(/ZhiyuMobile/.test(navigator.userAgent)){box.blur();root?.querySelectorAll('[data-composer-plus]').forEach(d=>d.open=false);window.dispatchEvent(new CustomEvent('phone-panel',{detail:'emoji'}));}tab('emoji');status.textContent='正在加载…';
      try{const [catalog,locale]=await data();if(token!==epoch||panel.hidden)return;const theme=document.documentElement.dataset.theme==='dark'?'dark':'light',columns=Math.max(1,Math.min(8,Math.floor((Math.min(416,panel.clientWidth||innerWidth-16)-30)/40)));if(picker&&(picker.dataset.theme!==theme||picker.dataset.columns!==String(columns))){picker.remove();picker=null;}if(!picker){picker=new EmojiMart.Picker({data:catalog,i18n:locale,locale:'zh',emojiVersion:15,set:'native',categories:['frequent','people','nature','foods','activity','places','objects','symbols','flags'],emojiSize:26,emojiButtonSize:40,theme:document.documentElement.dataset.theme==='dark'?'dark':'light',autoFocus:!/ZhiyuMobile/.test(navigator.userAgent),dynamicWidth:true,navPosition:'bottom',previewPosition:'none',skinTonePosition:'search',maxFrequentRows:2,perLine:columns,onEmojiSelect:emoji=>{if(box.matches(':disabled')){status.textContent='正在发送，请稍后选择。';return;}box.setRangeText(emoji.native,Math.min(start,box.value.length),Math.min(end,box.value.length),'end');box.dispatchEvent(new Event('input',{bubbles:true}));start=end=box.selectionEnd;if(!/ZhiyuMobile/.test(navigator.userAgent))close();}});const geometry=document.createElement('style');geometry.textContent='#root{height:100%;max-height:100%;min-height:0;overflow:hidden}#root>.scroll{flex:1 1 0%;min-height:0;overflow-y:auto}#root>nav{flex:none}';picker.shadowRoot.append(geometry);picker.dataset.theme=theme;picker.dataset.columns=String(columns);panel.querySelector('[data-emoji-content]').append(picker);}if(!panel.querySelector('[data-emoji-content]').hidden)status.textContent='';position();}catch(error){if(token===epoch)status.textContent=error.message;}
    });
    panel.addEventListener('click',event=>{const button=event.target.closest('[data-tab]');if(button)tab(button.dataset.tab);if(event.target.closest('[data-close]'))close();if(event.target.closest('[data-upload],[data-edit-favorites]'))location.href=libraryURL()+(event.target.closest('[data-edit-favorites]')?'&manage=1':'');});
    document.addEventListener('pointerdown',event=>{if(!panel.hidden&&!panel.contains(event.target)&&!opener.contains(event.target)&&!event.target.closest('.chat-sticker-popover'))close(false);});panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();}});
    new ResizeObserver(()=>{if(!panel.hidden)position();}).observe(panel);
    window.addEventListener('resize',()=>{if(!panel.hidden)position();});window.addEventListener('scroll',()=>{if(!panel.hidden)position();},true);
    root?.addEventListener('sticker-favorite',async event=>{try{if(event.detail.id)await request(new URLSearchParams({action:'favorite',id:event.detail.id}));else{const response=await fetch(requestURL(event.detail.url));if(!response.ok)throw Error('图片不可用。');const blob=await response.blob();await upload(new File([blob],event.detail.name,{type:blob.type}));}(root.querySelector('[data-message-status],[data-thread-status]')||status).textContent='已收藏表情';}catch(error){(root.querySelector('[data-message-status],[data-thread-status]')||status).textContent=error.message;}});
  };
})();
