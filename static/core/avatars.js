(() => {
  function attach(container, url, initial) {
    container.classList.add('user-avatar'); container.replaceChildren();
    const fallback=document.createElement('span'); fallback.textContent=initial;container.append(fallback);
    if (!/^\/accounts\/\d+\/avatar\/[a-f0-9]{32}\/$/.test(url || '')) return;
    const image=document.createElement('img');image.alt='';image.decoding='async';image.src=url;
    image.addEventListener('error',()=>image.remove(),{once:true});container.append(image);
  }
  window.workbenchAvatar=attach;
  document.querySelectorAll('[data-avatar-image]').forEach(image=>{
    image.addEventListener('error',()=>image.remove(),{once:true});
    if(image.complete&&!image.naturalWidth)image.remove();
  });
})();
