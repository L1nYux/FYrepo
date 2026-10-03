const {spawnSync} = require('node:child_process');
const path = require('node:path');

class Updates {
  constructor(app, publish) {
    this.app=app;this.publish=publish;this.busy=false;this.timer=null;this.initial=null;
    this.value={state:'disabled',version:app.getVersion(),message:'源码预览不执行自动更新。'};
    if(!app.isPackaged)return;
    if(process.platform==='darwin'){
      const bundle=path.resolve(path.dirname(process.execPath),'../..');
      const signature=spawnSync('/usr/bin/codesign',['--display','--verbose=2',bundle],{encoding:'utf8',timeout:5000});
      if(signature.status!==0||!/TeamIdentifier=(?!not set)[A-Z0-9]+/.test(signature.stderr||'')){
        this.value.message='此 macOS 预览未使用 Apple 团队证书签名，请从发布页手动更新。';return;
      }
    }
    this.updater=require('electron-updater').autoUpdater;
    // No forced restart: downloads happen in the background, installation is explicit.
    this.updater.autoDownload=true;this.updater.autoInstallOnAppQuit=false;
    this.updater.allowPrerelease=false;this.updater.allowDowngrade=false;
    this.updater.logger=null;
    this.value={...this.value,state:'idle',message:'启动时及每 4 小时检查更新，有新版本时自动下载。'};
    this.updater.on('checking-for-update',()=>this.set({state:'checking',message:'正在检查更新…'}));
    this.updater.on('update-available',info=>this.set({state:'available',nextVersion:info.version,message:'发现新版本 '+info.version+'，正在准备下载。'}));
    this.updater.on('update-not-available',()=>this.set({state:'current',message:'当前已是最新发布版本。'}));
    this.updater.on('download-progress',progress=>this.set({state:'downloading',percent:Math.round(progress.percent),message:'正在下载更新 '+Math.round(progress.percent)+'%'}));
    this.updater.on('update-downloaded',info=>this.set({state:'downloaded',nextVersion:info.version,message:'新版本 '+info.version+' 已下载，可以安装并重新启动。'}));
    this.updater.on('error',()=>this.set({state:'error',message:'更新暂时不可用，请稍后重试或到 GitHub 发布页查看。首次正式发布前此提示属于正常情况。'}));
  }
  snapshot(){return {...this.value};}
  set(value){this.value={...this.value,...value};this.publish(this.snapshot());}
  start(){if(!this.updater)return;this.initial=setTimeout(()=>this.check().catch(()=>{}),10000);this.timer=setInterval(()=>this.check().catch(()=>{}),4*60*60*1000);}
  stop(){clearTimeout(this.initial);clearInterval(this.timer);}
  async check(){
    if(!this.updater||this.busy||['downloading','downloaded','available'].includes(this.value.state))return this.snapshot();
    this.busy=true;try{await this.updater.checkForUpdates();}catch(_){/* error event provides the user-facing state */}finally{this.busy=false;}return this.snapshot();
  }
  async download(){
    if(!this.updater)throw Error(this.value.message);
    if(this.value.state==='downloading'||this.value.state==='downloaded')return this.snapshot();
    if(!this.value.nextVersion)throw Error('请先检查新版本。');
    await this.updater.downloadUpdate();return this.snapshot();
  }
  install(){if(this.value.state!=='downloaded')throw Error('更新还没有下载完成。');this.updater.quitAndInstall(false,true);}
}
module.exports={Updates};
