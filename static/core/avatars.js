(() => {
  function attach(container, url, initial) {
    container.classList.add('user-avatar'); container.replaceChildren();
    const fallback=document.createElement('span'); fallback.textContent=initial;container.append(fallback);
    if (!/^\/accounts\/\d+\/avatar\/[a-f0-9]{32}\/$/.test(url || '')) return;
    const image=document.createElement('img');image.alt='';image.decoding='async';image.src=url;
    image.addEventListener('error',()=>image.remove(),{once:true});container.append(image);
  }
  window.workbenchAvatar=attach;
  document.querySelectorAll('[data-avatar-image]').forEach(image=>{
    image.addEventListener('error',()=>image.remove(),{once:true});
    if(image.complete&&!image.naturalWidth)image.remove();
  });
  document.querySelectorAll('[data-avatar-editor]').forEach(editor=>{
    const input=editor.querySelector('[data-avatar-file]'),preview=editor.querySelector('[data-avatar-preview]'),hint=editor.querySelector('[data-avatar-hint]');let url;
    input.addEventListener('change',()=>{
      if(url)URL.revokeObjectURL(url);preview.hidden=true;const file=input.files[0];
      if(!file){hint.textContent='';return;}
      if(file.size>5*1024*1024){hint.textContent='图片不能超过 5 MB。';input.value='';return;}
      url=URL.createObjectURL(file);preview.src=url;preview.hidden=false;hint.textContent='保存后更新头像，图片将从中央裁成正方形。';
    });
    editor.querySelector('form').addEventListener('submit',()=>{const button=editor.querySelector('button[type=submit]');button.disabled=true;button.textContent='上传中…';});
    window.addEventListener('pagehide',()=>{if(url)URL.revokeObjectURL(url);});
  });
})();
