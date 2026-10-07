(() => {
  document.querySelectorAll('[data-messages]').forEach(root=>{
    const box=root.querySelector('textarea[name=body]');if(!box)return;
    const key='zhiyu-team-draft:'+document.documentElement.dataset.account+':'+root.dataset.workspace+':'+root.dataset.channel;
    try{if(!box.value)box.value=sessionStorage.getItem(key)||'';}catch(_){}
    const remember=()=>{try{if(box.value)sessionStorage.setItem(key,box.value);else sessionStorage.removeItem(key);}catch(_){}};
    box.addEventListener('input',remember);window.addEventListener('pagehide',remember);
  });
})();
