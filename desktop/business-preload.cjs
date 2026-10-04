// Reapplied on every document, including POST redirects. No remote desktop API.
const {ipcRenderer, webFrame} = require('electron');
let presentation, styleKey;
function paint() {
  if (!presentation || !document.body) return;
  if (!styleKey) styleKey=webFrame.insertCSS(presentation.css,{cssOrigin:'author'});
  document.body.classList.toggle('desktop-settings-view',presentation.settings);
  document.documentElement.dataset.theme=presentation.appearance.theme;
  let image=document.getElementById('desktop-wallpaper');
  if(!image){image=document.createElement('img');image.id='desktop-wallpaper';image.alt='';image.setAttribute('aria-hidden','true');document.body.prepend(image);}
  const value=presentation.appearance;
  image.hidden=!value.wallpaper;
  if(value.wallpaper)image.src=value.wallpaper;else image.removeAttribute('src');
  image.style.opacity=String(value.opacity/100);image.style.filter='blur('+value.blur+'px)';
  document.body.classList.toggle('has-local-wallpaper',Boolean(value.wallpaper));
}
ipcRenderer.on('desktop:business-presentation',(_,value)=>{presentation=value;paint();});
window.addEventListener('DOMContentLoaded',async()=>{
  try{presentation=await ipcRenderer.invoke('desktop:business-presentation');paint();
    new MutationObserver(()=>{
      if(presentation && document.documentElement.dataset.theme!==presentation.appearance.theme)
        document.documentElement.dataset.theme=presentation.appearance.theme;
    }).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
  }
  catch(error){console.error('无法应用桌面页面布局：',error.message);}
});
