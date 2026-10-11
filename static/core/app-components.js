/* Shared component contracts: one icon canvas and one message identity. */
(() => {
  'use strict';
  const solid = {
    forward: 'M14 2 23 10 14 18v-5C7 12 3 15 1 22c0-11 5-15 13-15V2Z',
    favorite: 'M12 2 2 7l10 5 10-5-10-5ZM2 9v10l9 5V14L2 9Zm11 5v10l9-5V9l-9 5Z',
    locate: 'M12 2C6 2 1 6 1 11c0 3 2 6 5 8l-1 4 6-3h1c6 0 11-4 11-9S18 2 12 2Zm-6 9a1 1 0 1 1 2 0 1 1 0 0 1-2 0Zm5 0a1 1 0 1 1 2 0 1 1 0 0 1-2 0Zm5 0a1 1 0 1 1 2 0 1 1 0 0 1-2 0Z',
    save: 'M11 2h2v11l4-4 1.5 1.5L12 17l-6.5-6.5L7 9l4 4V2ZM3 13h2v7h14v-7h2v9H3v-9Z',
    open: 'M3 4h8l2 3h8v2H3V4Zm0 7h20l-4 10H1l2-10Z',

    image: 'M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm12 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM5 18h14l-5-6-3 3-3-4-3 7Z',
    camera: 'M9 3h6l2 3h3a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3l2-3Zm3 5a5 5 0 1 0 0 10 5 5 0 0 0 0-10Zm0 2a3 3 0 1 1 0 6 3 3 0 0 1 0-6Z',
    file: 'M3 4h6l2 3h10a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z',
    project: 'M3 4h6l2 3h10a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z',
    document: 'M5 2h9l6 6v14H5V2Zm9 2v5h5l-5-5ZM8 12v2h9v-2H8Zm0 5v2h9v-2H8Z',
    task: 'M5 2h14v20H5V2Zm2 5 2 2 3-3-1-1-2 2-1-1-1 1Zm6-1v2h4V6h-4Zm-6 7 2 2 3-3-1-1-2 2-1-1-1 1Zm6-1v2h4v-2h-4Zm-6 6v2h10v-2H7Z',
    experiment: 'M8 2h8v2h-2v6l6 9a2 2 0 0 1-2 3H6a2 2 0 0 1-2-3l6-9V4H8V2Zm4 9-3 5h6l-3-5Z',
    announcement: 'M3 8h6l12-5v18L9 16H3V8Zm3 9h3l2 5H8l-2-5Z',
  };
  window.zhiyuComponents = {
    icon(kind, outline) {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      const path = document.createElementNS(svg.namespaceURI, 'path');
      svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
      svg.classList.add('experience-tool-icon');
      path.setAttribute('d', solid[kind] || outline);
      if (solid[kind]) { svg.dataset.iconStyle = 'solid'; path.setAttribute('fill-rule', 'evenodd'); }
      svg.append(path); return svg;
    },
    messageId(node) { return node.dataset.messageId || node.dataset.id || node.dataset.cachedId; },
  };
  window.zhiyuComponents.confirm = message => new Promise(resolve => {
    const dialog=document.createElement('dialog');dialog.className='delete-confirm-dialog';
    const title=document.createElement('h2');title.textContent='请确认';
    const text=document.createElement('p');text.textContent=message;
    const actions=document.createElement('div');actions.className='btn-row';
    const cancel=document.createElement('button');cancel.type='button';cancel.className='button';cancel.textContent='取消';cancel.autofocus=true;
    const ok=document.createElement('button');ok.type='button';ok.className='button primary';ok.textContent='确认';
    actions.append(cancel,ok);dialog.append(title,text,actions);document.body.append(dialog);
    cancel.onclick=()=>dialog.close('cancel');ok.onclick=()=>dialog.close('confirm');
    dialog.addEventListener('close',()=>{const accepted=dialog.returnValue==='confirm';dialog.remove();resolve(accepted);},{once:true});
    dialog.showModal();cancel.focus();
  });
  const approvedForms=new WeakSet();
  document.addEventListener('submit',async event=>{
    const form=event.target;
    if(!form.dataset.confirm||approvedForms.has(form))return;
    event.preventDefault();event.stopImmediatePropagation();
    const submitter=event.submitter;
    if(await window.zhiyuComponents.confirm(form.dataset.confirm)){
      approvedForms.add(form);form.requestSubmit(submitter);approvedForms.delete(form);
    }
  },true);
  const idOf = window.zhiyuComponents.messageId;
  window.workbenchFindMessage = (container, id) => [...container.children].find(n => idOf(n) === String(id));
  window.workbenchInsertMessage = (container, card) => {
    const id = idOf(card); if (!id) return;
    card.dataset.messageId = id; card.id = 'message-' + id;
    const old = window.workbenchFindMessage(container, id);
    if (old && old !== card) { old.replaceWith(card); return; }
    const at = Date.parse(card.dataset.createdAt) || 0;
    const next = [...container.children].find(n => {
      const other = idOf(n); if (!other || n === card) return false;
      const otherAt = Date.parse(n.dataset.createdAt) || 0;
      return at && otherAt ? otherAt > at || otherAt === at && Number(other) > Number(id) : Number(other) > Number(id);
    });
    container.insertBefore(card, next || null);
  };
})();
