const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('editMenu',{
  action:value=>ipcRenderer.invoke('desktop:edit-action',value),
  onOpen:callback=>ipcRenderer.on('desktop:edit-menu',(_,value)=>callback(value)),
});
