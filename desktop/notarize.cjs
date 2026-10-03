// Invoked on signed macOS release builds only; credentials stay in CI secrets.
module.exports=async context=>{
  if(context.electronPlatformName!=='darwin'||process.env.WORKBENCH_NOTARIZE!=='1')return;
  for(const key of ['APPLE_ID','APPLE_APP_SPECIFIC_PASSWORD','APPLE_TEAM_ID']){
    if(!process.env[key])throw Error('Missing macOS notarization secret: '+key);
  }
  const {notarize}=require('@electron/notarize');
  const path=require('node:path');
  await notarize({tool:'notarytool',appPath:path.join(context.appOutDir,context.packager.appInfo.productFilename+'.app'),
    appleId:process.env.APPLE_ID,appleIdPassword:process.env.APPLE_APP_SPECIFIC_PASSWORD,teamId:process.env.APPLE_TEAM_ID});
};
