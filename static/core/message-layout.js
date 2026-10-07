/* Keep initial history and arriving messages in the same compact layout. */
(() => {
  document.querySelectorAll('[data-messages],[data-personal-thread]').forEach(root=>{
    const history=root.querySelector('.conversation-log');if(!history)return;
    root.classList.toggle('group-conversation',Boolean(root.querySelector('[data-chat-details]')));
    const arrange=()=>history.querySelectorAll('.message-bubble-row').forEach(row=>{
      if(row.querySelector('.message-body-stack'))return;
      const bubble=row.querySelector('.message-bubble');if(!bubble)return;
      const stack=document.createElement('div');stack.className='message-body-stack';bubble.before(stack);
      const byline=bubble.querySelector('.message-byline');if(byline)stack.append(byline);stack.append(bubble);
    });
    arrange();new MutationObserver(arrange).observe(history,{childList:true,subtree:true});
  });
})();
