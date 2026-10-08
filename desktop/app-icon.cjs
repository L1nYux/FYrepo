const {app,nativeImage,shell}=require('electron');
const fs=require('node:fs');
const path=require('node:path');
const APP_ID='org.fyrepo.researchworkbench'+(app.isPackaged?'':'.development');
let cached;
function windowsIconPath(){
  // Windows Shell cannot read an icon inside app.asar.
  return app.isPackaged?path.join(process.resourcesPath,'zhiyu.ico'):path.join(__dirname,'assets','team-logo-rounded.ico');
}
function applicationIcon(){
  // Pass a decoded image to Electron and use the executable resource for Windows identity.
  if(!cached){
    cached=nativeImage.createFromPath(path.join(__dirname,'assets','team-logo.png'));
    if(cached.isEmpty())throw Error('知域图标资源缺失，请重新安装客户端。');
    cached=cached.resize({width:256,height:256,quality:'best'});
  }
  return cached;
}
function configureWindowIdentity(window){
  if(process.platform!=='win32')return;
  const icon=windowsIconPath();
  const command=app.isPackaged?'"'+process.execPath+'"':'"'+process.execPath+'" "'+app.getAppPath()+'"';
  window.setAppDetails({appId:APP_ID,relaunchDisplayName:'知域',
    relaunchCommand:command,appIconPath:icon,appIconIndex:0,
  });
  window.setIcon(icon);
}
function refreshInstalledShortcuts(){
  if(process.platform!=='win32'||!app.isPackaged)return;
  const folders=[app.getPath('desktop'),path.join(app.getPath('appData'),'Microsoft','Windows','Start Menu','Programs'),
    path.join(app.getPath('appData'),'Microsoft','Internet Explorer','Quick Launch','User Pinned','TaskBar')];
  for(const folder of folders){
    let names;try{names=fs.readdirSync(folder);}catch(_){continue;}
    for(const name of names.filter(value=>value.toLowerCase().endsWith('.lnk'))){
      const shortcut=path.join(folder,name);
      try{
        const details=shell.readShortcutLink(shortcut);
        if(path.resolve(details.target).toLowerCase()!==path.resolve(process.execPath).toLowerCase())continue;
        shell.writeShortcutLink(shortcut,'update',{icon:windowsIconPath(),iconIndex:0,appUserModelId:APP_ID});
      }catch(error){console.warn('Unable to refresh application shortcut:',error.message);}
    }
  }
}
module.exports={APP_ID,applicationIcon,configureWindowIdentity,refreshInstalledShortcuts};
