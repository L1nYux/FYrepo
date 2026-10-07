(() => {
  const bar=document.createElement('div');bar.className='page-loading-bar';bar.hidden=true;
  bar.setAttribute('role','status');bar.setAttribute('aria-label','正在加载');document.body.append(bar);
  let delay,slow,submitter,original,form;
  function reset(){
    clearTimeout(delay);clearTimeout(slow);bar.hidden=true;
    if(submitter){submitter.removeAttribute('aria-busy');submitter.textContent=original;}
    if(form)delete form.dataset.submitting;
    submitter=form=null;
  }
  function start(button,currentForm){
    clearTimeout(delay);
    delay=setTimeout(()=>{
      bar.hidden=false;
      if(button){submitter=button;original=button.textContent;button.setAttribute('aria-busy','true');
        button.textContent=currentForm.querySelector('input[type=file]')?'上传中…':'提交中…';}
    },300);
    // Keep the page usable when navigation was cancelled, or the request stalls.
    slow=setTimeout(reset,30000);
  }
  document.addEventListener('click',event=>{
    const a=event.target.closest('a[href]');
    if(!a||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||a.download||a.target==='_blank')return;
    const url=new URL(a.href,location.href);
    if(url.origin!==location.origin||!['http:','https:'].includes(url.protocol)||(url.pathname===location.pathname&&url.search===location.search))return;
    setTimeout(()=>{if(!event.defaultPrevented)start();},0);
  });
  document.addEventListener('submit',event=>{
    if(event.target.dataset.submitting){event.preventDefault();return;}
    // Let existing AJAX handlers own their loading state; retain submitter name/value.
    setTimeout(()=>{
      if(event.defaultPrevented||event.target.target==='_blank')return;
      form=event.target;form.dataset.submitting='1';start(event.submitter,form);
    },0);
  });
  window.addEventListener('pageshow',reset);
  window.addEventListener('pagehide',reset);
})();
