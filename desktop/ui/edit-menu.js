window.editMenu.onOpen(value=>{
  document.documentElement.dataset.theme=value.theme;
  document.querySelectorAll('[data-edit]').forEach(button=>button.disabled=!value.allowed[button.dataset.edit]);
  document.querySelector('[data-edit]:not(:disabled)')?.focus();
});
document.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',()=>window.editMenu.action(button.dataset.edit)));
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'){event.preventDefault();window.editMenu.action('close');return;}
  const buttons=[...document.querySelectorAll('[data-edit]:not(:disabled)')];
  if(event.ctrlKey||event.metaKey){const action={x:'cut',c:'copy',v:'paste',a:'selectAll'}[event.key.toLowerCase()];if(action){event.preventDefault();window.editMenu.action(action);}return;}
  if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)&&buttons.length){
    event.preventDefault();const index=buttons.indexOf(document.activeElement),next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;
    buttons[next].focus();
  }
});
