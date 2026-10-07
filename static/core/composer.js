/* One keyboard policy for conversational fields, including embedded comments. */
(() => {
  const desktopKeyboard=()=>matchMedia('(hover:hover) and (pointer:fine)').matches;
  document.querySelectorAll('textarea[data-message-input]').forEach(box=>{
    const form=box.form;if(!form)return;
    box.setAttribute('enterkeyhint','enter');
    const hint=document.createElement('small');hint.className='composer-keyboard-hint';
    const update=()=>{hint.textContent=desktopKeyboard()?'Enter 发送 · Shift + Enter 换行':'点击发送 · 回车换行';};
    update();box.insertAdjacentElement('afterend',hint);
    matchMedia('(hover:hover) and (pointer:fine)').addEventListener('change',update);
    let composing=false,compositionEnded=-Infinity;box.addEventListener('compositionstart',()=>composing=true);box.addEventListener('compositionend',()=>{composing=false;compositionEnded=Date.now();});
    box.addEventListener('keydown',event=>{
      if(event.key!=='Enter'||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing||event.keyCode===229||composing||Date.now()-compositionEnded<100||!desktopKeyboard())return;
      event.preventDefault();if(event.repeat||box.disabled)return;
      const button=form.querySelector('button[type=submit],button:not([type])');
      if(button?.disabled)return;form.requestSubmit(button||undefined);
    });
  });
})();
