const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('desktop',{
 onState:fn=>ipcRenderer.on('social:test-state',(_event,value)=>fn(value)),
 onAppearance:fn=>fn({theme:'light'}),
 info:()=>ipcRenderer.invoke('social:test-info'),
 accountReady:()=>{},accountMenu:()=>{},usage:async()=>({ok:false}),usageOpen:()=>{},navigate:()=>{},window:()=>{},logout:async()=>({ok:true})
});
