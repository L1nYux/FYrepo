const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('readerControls',{
  action:(action,url)=>ipcRenderer.invoke('public-browser:action',{action,url}),
  onState:callback=>ipcRenderer.on('public-browser:state',(_event,value)=>callback(value)),
  ready:()=>ipcRenderer.invoke('public-browser:action',{action:'status'})
});
