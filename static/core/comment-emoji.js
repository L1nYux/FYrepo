(() => {
  const targets=[...document.querySelectorAll('form')].filter(form=>/\/(?:projects|tasks|submissions)\/\d+\/comment\/$/.test(new URL(form.action,location.href).pathname));
  for(const form of targets){
    const box=form.querySelector('textarea[name=body]'),files=form.querySelector('input[type=file][name=attachments]');if(!box||!files)continue;box.required=false;
    const tools=document.createElement('div');tools.className='comment-emoji-tools';const opener=document.createElement('button');opener.type='button';opener.textContent='☺';opener.setAttribute('aria-label','表情');tools.append(opener);box.after(tools);
    window.workbenchEmojiPicker({opener,box,form,onSticker:async sticker=>{const response=await fetch(sticker.url);if(!response.ok)throw Error('图片表情已不可用。');const blob=await response.blob();if(blob.size>5*1024*1024)throw Error('图片不能超过 5 MB。');const ext=({'image/gif':'gif','image/png':'png','image/jpeg':'jpg','image/webp':'webp'})[blob.type];if(!ext)throw Error('图片格式不支持。');if(files.files.length>=5)throw Error('一次留言最多添加 5 个附件。');const transfer=new DataTransfer();for(const old of files.files)transfer.items.add(old);transfer.items.add(new File([blob],'表情-'+sticker.id+'.'+ext,{type:blob.type}));files.files=transfer.files;files.dispatchEvent(new Event('change',{bubbles:true}));}});
  }
})();
