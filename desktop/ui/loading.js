(() => {
  const api=window.desktop, overlay=document.querySelector('#interface-loading');
  let lastGeneration=-1, initialized=false, latest;
  function update(value) {
    latest=value;
    const loading=value.loading;
    if(!loading){overlay.hidden=true;document.body.classList.remove('interface-starting');return;}
    const pending=loading.phase!=='idle';
    const wasHidden=overlay.hidden;
    overlay.hidden=!pending;overlay.classList.toggle('full',loading.full);
    overlay.classList.toggle('error',loading.phase==='error');
    overlay.setAttribute('aria-busy',String(loading.phase==='loading'));
    document.body.classList.toggle('interface-starting',pending&&loading.full);
    document.querySelector('#loading-message').textContent=loading.message||'正在准备工作台…';
    document.querySelector('#loading-actions').hidden=loading.phase!=='error';
    document.querySelector('#loading-connection').hidden=!loading.full;
    overlay.style.left=loading.full?'0':String(value.loadingLeft||0)+'px';
    if(!pending&&!wasHidden){document.querySelector('main').classList.remove('interface-fade');requestAnimationFrame(()=>document.querySelector('main').classList.add('interface-fade'));}
    if(!initialized||loading.phase==='idle'||lastGeneration===loading.generation)return;
    lastGeneration=loading.generation;const generation=loading.generation;
    document.fonts.ready.then(()=>{
      document.documentElement.getBoundingClientRect();
      if(latest.loading?.generation===generation)api.presentationReady(generation);
    });
  }
  window.updateInterfaceLoading=update;
  // Info is applied after native preferences and the initial controls are prepared.
  window.prepareInterfaceLoading=async value=>{
    await Promise.all([...document.querySelectorAll('.brand-mark,.login-mark')].map(image=>image.decode().catch(()=>{})));
    initialized=true;update(latest?.loading?.generation>=value.loading?.generation?latest:value);
  };
  document.querySelector('#loading-retry').addEventListener('click',async event=>{
    event.target.disabled=true;
    try{const result=await api.retryLoading();if(!result.ok)document.querySelector('#loading-message').textContent=result.error;}
    finally{event.target.disabled=false;}
  });
  document.querySelector('#loading-connection').addEventListener('click',()=>api.dismissLoading());
})();
