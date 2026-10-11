/* Keep the same authorized forms reachable on narrow screens and in WebView. */
(()=>{
  const inspector=document.querySelector('.task-inspector');
  const heading=document.querySelector('.task-thread .thread-heading');
  if(!inspector||!heading)return;
  window.zhiyuRuntime.mount('task-layout',inspector,scope=>{
  const marker=document.createComment('task inspector desktop position');
  inspector.before(marker);
  const compact=matchMedia('(max-width:760px)');
  const sync=()=>{
    const inline=compact.matches||document.documentElement.classList.contains('zhiyu-phone');
    document.querySelector('.task-layout').classList.toggle('task-mobile-layout',inline);
    if(inline){
      heading.after(inspector);
      inspector.classList.add('task-inspector-inline');
    }else{
      marker.after(inspector);
      inspector.classList.remove('task-inspector-inline');
    }
  };
  scope.on(compact,'change',sync);
  sync();
  });
})();
