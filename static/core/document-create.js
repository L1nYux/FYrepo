(() => {
 const form=document.querySelector('.document-create');if(!form)return;
 let automaticTitle='';
 form.elements.file?.addEventListener('change',()=>{
  const file=form.elements.file.files[0];if(!file)return;
  const kind=file.name.split('.').pop().toLowerCase();
  if(!['docx','xlsx','pdf'].includes(kind))return;
  form.elements.kind.value=kind;
  if(!form.elements.title.value||form.elements.title.value===automaticTitle){
   automaticTitle=file.name.replace(/\.[^.]+$/,'').slice(0,200);
   form.elements.title.value=automaticTitle;
  }
 });
})();
