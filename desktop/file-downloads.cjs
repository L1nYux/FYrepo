'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
class FileDownloads {
  constructor(session,root,context,open){this.root=root;this.context=context;this.open=open;this.pending=new Map();this.jobs=new Map();this.indexFile=path.join(root,'file-downloads.json');try{this.index=JSON.parse(fs.readFileSync(this.indexFile,'utf8'));}catch(_){this.index={};}session.on('will-download',(_event,item,contents)=>this.receive(item,contents));}
  key(url,c){return crypto.createHash('sha256').update(c.origin+'\n'+c.account+'\n'+url).digest('hex');}
  valid(url,c){try{const u=new URL(url);return c.authenticated&&u.origin===c.origin&&/^\/(?:messages\/(?:files|legacy-files)\/[1-9]\d*\/|attachments\/[1-9]\d*\/download\/)$/.test(u.pathname);}catch(_){return false;}}
  start(contents,url,open=false){const c=this.context();if(!this.valid(url,c))throw Error('文件地址不可用。');const key=this.key(url,c),prior=this.index[key];if(prior&&path.resolve(prior.path).startsWith(path.resolve(this.root)+path.sep)&&fs.existsSync(prior.path)){const id=crypto.randomUUID();this.jobs.set(id,{path:prior.path,account:c.account,origin:c.origin,contents});contents.send('desktop:file-progress',{id,state:'completed',percent:100});if(open)this.open(prior.path);return;}this.pending.set(contents.id+'\n'+url,{open});contents.downloadURL(url);}
  receive(item,contents){
    const c=this.context(),url=item.getURLChain()[0]||item.getURL();
    let trusted=false;try{trusted=new URL(contents?.getURL()).origin===c.origin;}catch(_){}
    if(!contents||!trusted||!this.valid(url,c)){item.cancel();return;}
    const pending=this.pending.get(contents.id+'\n'+url)||{};this.pending.delete(contents.id+'\n'+url);
    const key=this.key(url,c),id=crypto.randomUUID();fs.mkdirSync(this.root,{recursive:true});
    let name=path.basename(item.getFilename()).replace(/[\\/:*?"<>|\x00-\x1f]/g,'_')||'附件';name=name.slice(0,180);
    let target=path.join(this.root,name),serial=1;while(fs.existsSync(target))target=path.join(this.root,path.parse(name).name+' ('+(serial++)+')'+path.extname(name));
    item.setSavePath(target);this.jobs.set(id,{item,path:target,account:c.account,origin:c.origin,contents});
    const currentAccount=()=>{const current=this.context();return current.authenticated&&current.account===c.account&&current.origin===c.origin;};
    const notify=data=>{if(!contents.isDestroyed()&&currentAccount())contents.send('desktop:file-progress',{id,...data});};
    notify({state:'progress',percent:0});item.on('updated',()=>{const total=item.getTotalBytes(),bytes=item.getReceivedBytes();notify({state:'progress',percent:total>0?Math.round(bytes*100/total):null,bytes,total});});
    item.once('done',(_event,state)=>{
      if(state==='completed'){
        this.index[key]={path:target};try{fs.writeFileSync(this.indexFile,JSON.stringify(this.index),{mode:0o600});}catch(_){}
        notify({state:'completed',percent:100});if(pending.open&&currentAccount())this.open(target);
      }else{notify({state:state==='cancelled'?'cancelled':'failed'});fs.rmSync(target,{force:true});}
    });
  }
  action(contents,id,action){const c=this.context(),job=this.jobs.get(id);if(!job||job.contents!==contents||job.account!==c.account||job.origin!==c.origin)throw Error('下载不可用。');if(action==='cancel')job.item?.cancel();else if(action==='open'&&fs.existsSync(job.path))this.open(job.path);}
  close(){for(const job of this.jobs.values())if(job.item&&job.item.getState()==='progressing')job.item.cancel();this.pending.clear();this.jobs.clear();}
}
module.exports={FileDownloads};
