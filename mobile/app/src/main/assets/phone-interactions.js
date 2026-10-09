/* Phone gestures and action sheets; no native bridge or added API permissions. */
(function () {
  'use strict';
  if (window.zhiyuPhone) return;
  let toastTimer;
  function toast(message) {
    let status = document.querySelector('.phone-toast');
    if (!status) { status = document.createElement('div'); status.className = 'phone-toast'; status.setAttribute('role','status'); document.body.append(status); }
    status.textContent = message; status.hidden = false; clearTimeout(toastTimer);
    toastTimer = setTimeout(() => status.hidden = true, 3000);
  }
  async function copy(text) {
    if(/ZhiyuMobile/.test(navigator.userAgent)){location.href="/__phone_copy__/?text="+encodeURIComponent(text.slice(0,30000));return;}
    try { if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); toast('已复制'); return; } } catch (_) { }
    const active=document.activeElement, scroll=[scrollX,scrollY];
    const input=document.createElement('textarea'); input.value=text; input.readOnly=true;
    input.style.cssText='position:fixed;left:-9999px;top:0;font-size:16px'; document.body.append(input); input.select();
    try { if(!document.execCommand('copy'))throw Error(); toast('已复制'); }
    catch (_) { toast('无法复制，请选择文字后复制。'); }
    finally { input.remove(); active?.focus({preventScroll:true}); window.scrollTo(...scroll); }
  }
  function select(element) {
    element.classList.add('phone-selectable');
    const range=document.createRange(); range.selectNodeContents(element);
    const selection=window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
  }
  function sheet(label, actions) {
    document.querySelector('.phone-action-sheet')?.close();
    const dialog=document.createElement('dialog'); dialog.className='phone-action-sheet'; dialog.setAttribute('aria-label',label);
    const heading=document.createElement('p'); heading.className='phone-action-sheet-title'; heading.textContent=label; dialog.append(heading);
    for(const action of actions){
      const button=document.createElement('button');button.type='button';button.textContent=action.label;
      if(action.danger)button.className='danger';button.disabled=!!action.disabled;
      button.onclick=async()=>{dialog.close();try{await action.run();}catch(error){toast(error.message||'操作未完成，请重试。');}};dialog.append(button);
    }
    const cancel=document.createElement('button');cancel.type='button';cancel.textContent='取消';cancel.className='phone-sheet-cancel';cancel.onclick=()=>dialog.close();dialog.append(cancel);
    dialog.addEventListener('click',event=>{const box=dialog.getBoundingClientRect();if(event.target===dialog&&(event.clientY<box.top||event.clientX<box.left||event.clientX>box.right))dialog.close();});
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});document.body.append(dialog);dialog.showModal();
    window.getSelection()?.removeAllRanges();
  }
  function hold(container, selector, action) {
    let timer, target, start, blocked, blockUntil=0, pointer;
    function stop(){clearTimeout(timer);timer=null;target=null;}
    container.addEventListener('pointerdown',event=>{
      stop();blocked=null;blockUntil=0;
      if(event.button!==0||!event.isPrimary||window.getSelection()?.toString())return;
      const element=event.target.closest(selector);if(!element||element.closest('.phone-selectable'))return;
      const control=event.target.closest('button,a,input,textarea,select,summary');if(control&&control!==element)return;
      target=element;pointer=event.pointerId;start=[event.clientX,event.clientY];
      timer=setTimeout(()=>{timer=null;if(!target?.isConnected)return;blocked=target;blockUntil=Date.now()+1000;action(target);target=null;},550);
    });
    container.addEventListener('pointermove',event=>{if(target&&(event.pointerId!==pointer||Math.hypot(event.clientX-start[0],event.clientY-start[1])>10))stop();},{passive:true});
    container.addEventListener('pointerup',stop,{passive:true});container.addEventListener('pointercancel',stop,{passive:true});
    container.addEventListener('click',event=>{if(blocked&&Date.now()<blockUntil&&blocked.contains(event.target)){event.preventDefault();event.stopImmediatePropagation();blocked=null;}},true);
    container.addEventListener('contextmenu',event=>{
      const element=event.target.closest(selector);if(!element||element.closest('.phone-selectable'))return;
      const control=event.target.closest('button,a,input,textarea,select,summary');if(control&&control!==element)return;
      event.preventDefault();event.stopImmediatePropagation();stop();if(blocked===element&&Date.now()<blockUntil)return;action(element);
    },true);
    container.addEventListener('scroll',stop,{passive:true,capture:true});window.addEventListener('blur',stop);
    document.addEventListener('visibilitychange',stop);window.addEventListener('pagehide',stop,{once:true});
  }
  window.zhiyuPhone={toast,copy,select,sheet,hold};
})();
