(() => {
  window.applyWorkbenchAppearance=value=>{
    document.documentElement.dataset.theme=value.theme;document.documentElement.dataset.accent=value.accent||'green';const colors={green:'#079b61',blue:'#3679d5',purple:'#8654c7',orange:'#bf6415',pink:'#c14c83'};document.documentElement.style.setProperty('--accent',colors[value.accent]||colors.green);
    let image=document.getElementById('desktop-wallpaper');
    if(!image){image=document.createElement('img');image.id='desktop-wallpaper';image.alt='';image.setAttribute('aria-hidden','true');document.body.prepend(image);}
    image.hidden=!value.wallpaper;if(value.wallpaper)image.src=value.wallpaper;else image.removeAttribute('src');
    image.style.opacity=String(value.opacity/100);image.style.filter='blur('+value.blur+'px)';
    document.body.classList.toggle('has-local-wallpaper',Boolean(value.wallpaper));
  };
  window.desktop?.onAppearance?.(window.applyWorkbenchAppearance);
})();
