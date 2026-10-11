(() => {
  'use strict';
  const root=document.querySelector('[data-file-view]');if(!root)return;
  const X=window.zhiyuExperience,status=root.querySelector('.file-download-status'),save=root.querySelector('[data-file-save]'),cancel=root.querySelector('[data-file-cancel]');
  const label=status.querySelector('span'),bar=status.querySelector('progress');let transfer,downloadId,started=false,desktopActive=false;
  window.workbenchDownloads?.onState(data=>{
    if(!started||(data.url&&data.url!==save.href)||(!data.url&&downloadId&&data.id!==downloadId))return;downloadId=data.id;status.hidden=false;desktopActive=data.state==='progress';
    if(data.percent==null)bar.removeAttribute('value');else bar.value=data.percent;
    label.textContent=data.state==='completed'?'已保存到 下载 / 知域':data.state==='cancelled'?'已取消':data.state==='failed'?'下载失败，请重试':data.percent==null?'正在下载…':data.percent+'%';
    cancel.hidden=data.state!=='progress';
  });
  save.addEventListener('click',event=>{
    if(/ZhiyuMobile/.test(navigator.userAgent))return; // Native downloads own progress and the app folder.
    event.preventDefault();if(transfer||desktopActive)return;started=true;status.hidden=false;label.textContent='正在下载…';bar.removeAttribute('value');
    if(window.workbenchDownloads){desktopActive=true;window.workbenchDownloads.save(save.href).catch(error=>{desktopActive=false;label.textContent=error.message;});return;}
    const xhr=new XMLHttpRequest();transfer=xhr;cancel.hidden=false;xhr.open('GET',save.href);xhr.responseType='blob';
    xhr.onprogress=event=>{if(event.lengthComputable){bar.value=event.loaded/event.total*100;label.textContent=Math.round(bar.value)+'%';}else label.textContent=(event.loaded/1048576).toFixed(1)+' MB';};
    const finish=text=>{transfer=null;cancel.hidden=true;label.textContent=text;};
    xhr.onload=()=>{
      if(xhr.status!==200){finish('下载失败，请重试');return;}
      const a=document.createElement('a'),url=URL.createObjectURL(xhr.response);a.href=url;a.download=root.dataset.name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);bar.value=100;finish('文件已下载');
    };
    xhr.onerror=()=>finish('下载失败，请重试');xhr.onabort=()=>finish('已取消下载');xhr.send();
  });
  cancel.onclick=()=>{transfer?.abort();if(downloadId)window.workbenchDownloads?.action(downloadId,'cancel');};
  const openOther=window.workbenchDownloads?()=>{if(desktopActive)return;started=true;desktopActive=true;return window.workbenchDownloads.save(save.href,true).catch(error=>{desktopActive=false;throw error;});}:/ZhiyuMobile/.test(navigator.userAgent)?()=>{location.href='/__phone_file_open__/?url='+encodeURIComponent(save.href)+'&name='+encodeURIComponent(root.dataset.name);}:null;
  const fallback=root.querySelector('[data-file-fallback-save]');if(fallback)fallback.onclick=()=>save.click();
  const open=root.querySelector('[data-file-fallback-open]');if(open&&openOther){open.hidden=false;open.onclick=()=>Promise.resolve(openOther()).catch(error=>X.toast(error.message));}
  root.querySelector('[data-file-menu]').onclick=()=>{
    const source=root.querySelector('.file-source'),actions=[];
    if(source)actions.push({label:'转发给朋友',icon:'forward',run:()=>X.forward(root,root)});
    actions.push({label:root.dataset.saved==='true'?'取消收藏':'收藏',icon:'favorite',run:async()=>{
      const data=await X.json(root.dataset.favoriteUrl,{action:root.dataset.saved==='true'?'remove':'add'});root.dataset.saved=String(data.saved);X.toast(data.saved?'已收藏':'已取消收藏');
    }});
    if(openOther)actions.push({label:'用其他应用打开',icon:'open',run:openOther});
    actions.push({label:'保存',icon:'save',run:()=>save.click()});
    if(source)actions.push({label:'定位到聊天位置',icon:'locate',run:()=>{location.href=source.href;}});
    window.zhiyuChatUI.fileActions(root,actions);
  };
  window.addEventListener('pagehide',()=>transfer?.abort(),{once:true});
})();
