/* Chat-only sticker submission; member profiles have no emoji dependency. */
(() => {
  document.querySelectorAll('[data-messages], [data-personal-thread]').forEach(root=>{
    const form=root.querySelector('[data-message-form]'),opener=root.querySelector('[data-sticker-open]');if(!form||!opener)return;
    const box=form.querySelector('textarea');
    window.workbenchEmojiPicker({root,form,opener,box,onSticker:async sticker=>{
      if(box.matches(':disabled'))throw Error('当前会话不能发送消息。');
      if(root.dataset.messageSending==='true'||root.dataset.stickerSending==='true')throw Error('正在发送，请稍后选择。');
      // A sticker is a separate message. Never submit or reset the text/file/quote draft.
      const payload=new FormData();payload.set('csrfmiddlewaretoken',form.elements.csrfmiddlewaretoken.value);
      payload.set('body','');payload.set('references','[]');payload.set('sticker_id',String(sticker.id));
      root.dataset.stickerSending='true';
      try{
        const response=await fetch(window.workbenchMessageURL(form.action,root),{method:'POST',body:payload,headers:{Accept:'application/json'}});
        if(!response.headers.get('content-type')?.includes('application/json'))throw Error('未确认发送结果，请先查看聊天记录。');
        const result=await response.json();
        if(!response.ok||(!result.message&&!result.messages?.length))throw Error(result.error||Object.values(result.errors||{}).flat().map(e=>e.message||e).join(' ')||'表情发送失败，请重试。');
        root.dispatchEvent(new CustomEvent('sticker-sent',{detail:result}));
      }catch(error){throw Error(error instanceof TypeError?'连接中断，未确认发送结果，请先查看聊天记录。':error.message);}
      finally{delete root.dataset.stickerSending;}
    }});
  });
})();
