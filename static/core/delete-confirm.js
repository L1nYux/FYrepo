// The signed server preview remains the fallback when JavaScript is disabled.
const confirmedDeleteForms=new WeakSet();
document.querySelectorAll('form[data-confirm-delete]').forEach(form=>form.addEventListener('submit',async event=>{
  if(event.submitter?.value!=='delete' || confirmedDeleteForms.has(form))return;
  event.preventDefault();const submitter=event.submitter;
  const dialog=document.createElement('dialog');dialog.className='delete-confirm-dialog';
  const title=document.createElement('h2');title.textContent='确认彻底删除';
  const description=document.createElement('p');description.textContent=form.dataset.confirmDelete+'。删除后无法恢复。';
  const actions=document.createElement('div');actions.className='btn-row';
  const cancel=document.createElement('button');cancel.type='button';cancel.className='button';cancel.textContent='取消';cancel.autofocus=true;
  const remove=document.createElement('button');remove.type='button';remove.className='button danger';remove.textContent='彻底删除';
  actions.append(cancel,remove);dialog.append(title,description,actions);document.body.append(dialog);
  cancel.addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>dialog.remove());
  remove.addEventListener('click',()=>{confirmedDeleteForms.add(form);dialog.close();form.requestSubmit(submitter);});
  dialog.showModal();cancel.focus();
}));
