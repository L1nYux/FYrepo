(() => {
  window.applyWorkbenchAppearance=value=>{
    document.documentElement.dataset.theme=value.theme;
    let image=document.getElementById('desktop-wallpaper');
    if(!image){image=document.createElement('img');image.id='desktop-wallpaper';image.alt='';image.setAttribute('aria-hidden','true');document.body.prepend(image);}
    image.hidden=!value.wallpaper;if(value.wallpaper)image.src=value.wallpaper;else image.removeAttribute('src');
    image.style.opacity=String(value.opacity/100);image.style.filter='blur('+value.blur+'px)';
    document.body.classList.toggle('has-local-wallpaper',Boolean(value.wallpaper));
  };
  window.desktop?.onAppearance?.(window.applyWorkbenchAppearance);
})();
