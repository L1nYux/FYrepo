// Reapplied on every document, including POST redirects. No remote desktop API.
const {ipcRenderer, webFrame, contextBridge} = require('electron');
contextBridge.exposeInMainWorld('workbenchBrowser',{open:url=>ipcRenderer.invoke('desktop:browser-open',url),onState:callback=>ipcRenderer.on('desktop:browser-state',(_,value)=>callback(value))});
contextBridge.exposeInMainWorld('workbenchUpdates',{open:()=>ipcRenderer.invoke('desktop:update-open'),status:()=>ipcRenderer.invoke('desktop:update-state'),onState:callback=>ipcRenderer.on('desktop:updates',(_,value)=>callback(value))});
let presentation, styleKey;
function paint() {
  if (!presentation || !document.body) return;
  if (!styleKey) styleKey=webFrame.insertCSS(presentation.css,{cssOrigin:'author'});
  document.documentElement.dataset.surface='desktop';
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
    if(!presentation)return;
    const readyGeneration=presentation.generation;
    await styleKey;
    await document.fonts.ready;
    // Hidden WebContentsViews can pause animation frames. Flush prepared layout
    // after CSS, fonts and appearance; visibility is released by the main process.
    document.documentElement.getBoundingClientRect();
    const projects=document.querySelector('.sidebar-projects');
    const link=element=>element?{title:element.dataset.title||element.textContent.replace(/^↳\s*/, '').trim(),path:new URL(element.href,location.href).pathname,owner:element.dataset.owner||'',space:element.dataset.space||''}:null;
    const sidebar=projects?{projects:[...projects.querySelectorAll('.sidebar-project')].slice(0,200).map(project=>({
      ...link(project.querySelector('.project-branch-link')),
      tasks:[...project.querySelectorAll('.sidebar-tasks details')].slice(0,100).map(task=>({
        ...link(task.querySelector('summary a')),open:task.open,
        children:[...task.querySelectorAll('.sidebar-child')].slice(0,200).map(link)
      }))
    }))}:null;
    if(sidebar){
      for(const kind of ['competitions','experiments'])sidebar[kind]=[...document.querySelectorAll('.sidebar-'+kind+' .project-branch-link')].map(link);
      const options=document.querySelector('#resource-space-options');
      try{sidebar.spaces=options?JSON.parse(options.textContent):[];}catch(_){sidebar.spaces=[];}
    }
    ipcRenderer.send('desktop:business-ready',{generation:readyGeneration,sidebar});
    new MutationObserver(()=>{
      if(presentation && document.documentElement.dataset.theme!==presentation.appearance.theme)
        document.documentElement.dataset.theme=presentation.appearance.theme;
    }).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
  }
  catch(error){console.error('无法应用桌面页面布局：',error.message);}
});
