const {spawnSync} = require('node:child_process');
const path = require('node:path');
const {fetchInfo,validateInfo}=require('./release-details.cjs');
const {currentMessage}=require('./update-channel.cjs');

class Updates {
  constructor(app, publish, options={}) {
    this.app=app;this.publish=publish;this.busy=false;this.timer=null;this.initial=null;this.fetch=options.fetch||global.fetch;this.detailsRequest=null;
    this.value={state:'disabled',version:app.getVersion(),message:'源码预览不执行自动更新。',release:require('./release-info.json')};
    if(!app.isPackaged)return;
    if((options.platform||process.platform)==='darwin'){
      const bundle=path.resolve(path.dirname(process.execPath),'../..');
      const signature=(options.signature||spawnSync)('/usr/bin/codesign',['--display','--verbose=2',bundle],{encoding:'utf8',timeout:5000});
      if(signature.status!==0||!/TeamIdentifier=(?!not set)[A-Z0-9]+/.test(signature.stderr||'')){
        this.value={...this.value,state:'idle',mode:'manual-mac',message:'自动检查更新，确认下载后再打开安装包并覆盖安装。'};
        const {FreeMacUpdate}=require('./free-mac-update.cjs');
        this.mac=new FreeMacUpdate(app,value=>this.set(value),options);return;
      }
    }
    this.updater=options.updater||require('electron-updater').autoUpdater;
    // No forced restart: downloads happen in the background, installation is explicit.
    this.updater.autoDownload=false;this.updater.autoInstallOnAppQuit=false;
    this.updater.allowPrerelease=false;this.updater.allowDowngrade=false;
    this.updater.logger=null;
    this.value={...this.value,state:'idle',message:'启动时及每 4 小时检查更新，由你决定下载与安装。'};
    this.updater.on('checking-for-update',()=>this.set({state:'checking',message:'正在检查更新…'}));
    this.updater.on('update-available',info=>{const file=info.files?.find(v=>/\.exe(?:$|\?)/.test(v.url))||info.files?.[0];this.set({state:'available',nextVersion:info.version,size_bytes:file?.size||null,notes:typeof info.releaseNotes==='string'?info.releaseNotes:'',release:null,message:'发现新版本 '+info.version+'，可查看说明后决定下载。'});this.detailsRequest=fetchInfo(info.version,this.fetch).then(release=>{if(this.value.nextVersion===info.version)this.set({release});}).catch(()=>{});});
    this.updater.on('update-not-available',info=>this.set({state:'current',nextVersion:null,channelVersion:info?.version||null,size_bytes:null,release:require('./release-info.json'),message:currentMessage(this.app.getVersion(),info?.version)}));
    this.updater.on('download-progress',progress=>this.set({state:'downloading',percent:Math.round(progress.percent),message:'正在下载更新 '+Math.round(progress.percent)+'%'}));
    this.updater.on('update-downloaded',info=>this.set({state:'downloaded',nextVersion:info.version,message:'新版本 '+info.version+' 已下载，可以安装并重新启动。'}));
    this.updater.on('error',()=>this.failure());
  }
  snapshot(){return {...this.value};}
  currentRelease(){return validateInfo(require('./release-info.json'),this.app.getVersion());}
  set(value){this.value={...this.value,...value};this.publish(this.snapshot());}
  start(){if(!this.updater&&!this.mac)return;this.initial=setTimeout(()=>this.check().catch(()=>{}),10000);this.timer=setInterval(()=>this.check().catch(()=>{}),4*60*60*1000);}
  stop(){clearTimeout(this.initial);clearInterval(this.timer);this.mac?.stop();}
  failure(){this.set({state:'error',message:'更新失败，请点击更新按钮重试。'});}
  async check(){
    if((!this.updater&&!this.mac)||this.busy||['downloading','downloaded','available'].includes(this.value.state))return this.snapshot();
    this.busy=true;try{if(this.mac)await this.mac.check();else {await this.updater.checkForUpdates();await this.detailsRequest;}}catch(_){this.failure();}finally{this.busy=false;}return this.snapshot();
  }
  async download(){
    if(!this.updater&&!this.mac)throw Error(this.value.message);
    if(this.value.state==='downloading'||this.value.state==='downloaded')return this.snapshot();
    if(!this.value.nextVersion)throw Error('请先检查新版本。');
    if(this.busy)return this.snapshot();
    this.busy=true;try{if(this.mac)await this.mac.download();else await this.updater.downloadUpdate();}catch(_){this.failure();}finally{this.busy=false;}return this.snapshot();
  }
  async install(){if(this.value.state!=='downloaded')throw Error('更新还没有下载完成。');if(this.mac){try{await this.mac.install();}catch(error){this.failure();throw error;}}else this.updater.quitAndInstall(true,true);}
}
module.exports={Updates};
