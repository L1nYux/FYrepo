const fs=require('node:fs/promises');
const {createReadStream}=require('node:fs');
const path=require('node:path');
const {createHash,randomUUID}=require('node:crypto');
const REPO='https://github.com/L1nYux/FYrepo';
const versionParts=value=>{if(typeof value!=='string'||! /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(value))return null;const parts=value.split('.').map(Number);return parts.every(Number.isSafeInteger)?parts:null;};
function newer(next,current){const a=versionParts(next),b=versionParts(current);if(!a||!b)return false;for(let i=0;i<3;i++){if(a[i]!==b[i])return a[i]>b[i];}return false;}
function validateManifest(data,version,arch){
  if(!versionParts(version)||!['arm64','x64'].includes(arch)||data?.version!==version)throw Error('更新清单版本不匹配。');
  const file=data.files?.[arch],name=`ResearchWorkbench-${version}-mac-${arch}.dmg`;
  if(!file||file.name!==name||!Number.isSafeInteger(file.size)||file.size<1024||file.size>512*1024*1024||!(/^[A-Za-z0-9+/]{86}==$/.test(file.sha512||'')))throw Error('更新清单无效。');
  return {...file,version,url:`${REPO}/releases/download/v${version}/${name}`};
}
class FreeMacUpdate{
  constructor(app,publish,{fetch:fetcher=global.fetch,arch=process.arch,shell=require('electron').shell}={}){
    this.app=app;this.publish=publish;this.fetch=fetcher;this.arch=arch;this.shell=shell;this.controllers=new Set();this.file=null;this.installer=null;
  }
  async request(url,fn,timeoutMs=20000){
    const controller=new AbortController();this.controllers.add(controller);
    const timer=setTimeout(()=>controller.abort(),timeoutMs);timer.unref();
    try{
      const res=await this.fetch(url,{signal:controller.signal,headers:{Accept:'application/json','User-Agent':'ResearchWorkbench/'+this.app.getVersion()}});
      if(res.status===404)return null;
      if(!res.ok)throw Error('更新服务暂时不可用。');
      return await fn(res);
    }finally{clearTimeout(timer);this.controllers.delete(controller);}
  }
  async json(url){return this.request(url,async res=>{let bytes=0,parts=[];for await(const chunk of res.body){bytes+=chunk.length;if(bytes>256*1024)throw Error('更新清单过大。');parts.push(Buffer.from(chunk));}return JSON.parse(Buffer.concat(parts).toString('utf8'));});}
  async check(){
    this.publish({state:'checking',percent:0,nextVersion:null,message:'正在检查更新…'});
    const release=await this.json('https://api.github.com/repos/L1nYux/FYrepo/releases/latest');
    const version=release?.tag_name?.slice(1);
    if(!release){this.publish({state:'current',message:'暂时没有新的正式版本。'});return;}
    if(release.draft||release.prerelease||release.tag_name!=='v'+version||!versionParts(version))throw Error('发布信息无效。');
    if(!newer(version,this.app.getVersion())){this.publish({state:'current',message:'当前已是最新发布版本。'});return;}
    const data=await this.json(`${REPO}/releases/download/v${version}/free-mac-update.json`);
    this.file=validateManifest(data,version,this.arch);
    if(!release.assets?.some(asset=>asset.name===this.file.name&&asset.size===this.file.size))throw Error('此版本的 Mac 安装包尚未就绪。');
    this.publish({state:'available',nextVersion:version,message:'发现新版本 '+version+'，正在准备下载。'});
    await this.download();
  }
  async download(){
    if(!this.file)throw Error('请先检查新版本。');
    const dir=path.join(this.app.getPath('userData'),'verified-updates');await fs.mkdir(dir,{recursive:true});
    const destination=path.join(dir,this.file.name),temporary=destination+'.'+randomUUID()+'.part';
    if(await this.verified(destination)){this.installer=destination;this.downloaded();return;}
    this.publish({state:'downloading',nextVersion:this.file.version,percent:0,message:'正在下载更新 0%'});
    let handle;
    try{
      handle=await fs.open(temporary,'wx',0o600);
      const result=await this.request(this.file.url,async res=>{
        let size=0,lastPercent=-1;const hash=createHash('sha512');
        for await(const chunk of res.body){
          size+=chunk.length;if(size>this.file.size)throw Error('安装包大小不匹配。');
          hash.update(chunk);await handle.writeFile(chunk);
          const percent=Math.min(99,Math.floor(size/this.file.size*100));
          if(percent!==lastPercent){lastPercent=percent;this.publish({state:'downloading',percent,message:'正在下载更新 '+percent+'%'});}
        }
        if(size!==this.file.size||hash.digest('base64')!==this.file.sha512)throw Error('安装包校验失败，请重试。');
        return true;
      },10*60*1000);
      if(!result)throw Error('安装包暂时不可用。');
      await handle.close();handle=null;
      // Windows test hosts cannot replace an existing file with rename; remove only our validated cache file.
      await fs.rm(destination,{force:true});await fs.rename(temporary,destination);this.installer=destination;
      this.downloaded();
    }finally{if(handle)await handle.close();await fs.rm(temporary,{force:true});}
  }
  downloaded(){this.publish({state:'downloaded',percent:100,message:'新版本 '+this.file.version+' 已下载，点击打开安装包并覆盖安装。'});}
  async verified(file){
    try{
      const stat=await fs.lstat(file);if(!stat.isFile()||stat.size!==this.file.size)return false;
      const hash=createHash('sha512');let size=0;
      for await(const chunk of createReadStream(file)){size+=chunk.length;if(size>this.file.size)return false;hash.update(chunk);}
      return size===this.file.size&&hash.digest('base64')===this.file.sha512;
    }catch(_){return false;}
  }
  async install(){
    if(!this.installer)throw Error('安装包尚未下载。');
    if(!await this.verified(this.installer))throw Error('安装包校验失败，请重新下载。');
    const error=await this.shell.openPath(this.installer);if(error)throw Error('无法打开安装包，请重试。');
  }
  stop(){for(const controller of this.controllers)controller.abort();}
}
module.exports={FreeMacUpdate,newer,validateManifest};
