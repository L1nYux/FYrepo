(() => {
  const newer=(a,b)=>{const aa=String(a).split('.').map(Number),bb=String(b).split('.').map(Number);for(let i=0;i<3;i++){if(aa[i]!==bb[i])return aa[i]>bb[i];}return false;};
  document.querySelectorAll('[data-release-info]').forEach(root=>{
    const node=document.getElementById(root.dataset.releaseInfo);if(!node)return;const info=JSON.parse(node.textContent),status=root.querySelector('.release-status'),button=root.querySelector('[data-release-update]'),progress=root.querySelector('[data-release-progress]');
    let state;
    function render(value){state=value;const installed=!newer(info.version,value.version);button.textContent=installed?'查看版本与更新':'立即更新';status.textContent=installed?'已安装此版本或更新版本':value.message||'';progress.hidden=value.state!=='downloading';progress.value=value.percent||0;if(!installed&&value.state==='downloading')status.textContent='下载中 '+(value.percent||0)+'%';if(value.size_bytes&&!installed)status.textContent+=' · '+(value.size_bytes/1048576).toFixed(1)+' MB';}
    if(window.workbenchUpdates){window.workbenchUpdates.status().then(v=>{if(v.ok)render(v.data);});window.workbenchUpdates.onState(render);button.addEventListener('click',()=>window.workbenchUpdates.open());}
    else {button.textContent='刷新使用新版';status.textContent='网页当前版本 '+root.dataset.serverVersion+'；桌面客户端可下载更新。';button.addEventListener('click',()=>location.reload());}
    root.querySelectorAll('[data-release-feature]').forEach(link=>link.addEventListener('click',event=>{
      if(window.workbenchUpdates&&(!state||newer(info.version,state.version))){event.preventDefault();status.textContent='请先更新客户端后使用此功能。';window.workbenchUpdates.open();}
      else if(newer(info.version,root.dataset.serverVersion)){event.preventDefault();status.textContent='此功能需要负责人同步升级服务器后使用。';}
    }));
  });
})();
