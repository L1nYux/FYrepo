const {app,nativeImage}=require('electron');
const path=require('node:path');
const APP_ID='org.fyrepo.researchworkbench';
let cached;
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
  window.setAppDetails({appId:APP_ID,relaunchDisplayName:'知域',
    ...(app.isPackaged?{appIconPath:process.execPath,appIconIndex:0}:{}),
  });
}
module.exports={APP_ID,applicationIcon,configureWindowIdentity};
