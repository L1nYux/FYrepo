'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto');
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
async function sessionRequest(session,input,options={}){
  const {net}=require('electron'),{Readable}=require('node:stream');
  const request=input instanceof Request?input:new Request(input,options);
  const body=['GET','HEAD'].includes(request.method)?null:Buffer.from(await request.arrayBuffer());
  return new Promise((resolve,reject)=>{
    let settled=false;
    const client=net.request({session,url:request.url,method:request.method,
      headers:Object.fromEntries(request.headers),credentials:'include',
      bypassCustomProtocolHandlers:true,redirect:'manual'});
    const signal=options.signal||request.signal;
    const abort=()=>{client.abort();if(!settled){settled=true;reject(signal.reason||Error('Request aborted'));}};
    const done=value=>{if(settled)return;settled=true;signal?.removeEventListener('abort',abort);resolve(value);};
    const headers=values=>{const result=new Headers();for(const[key,value]of Object.entries(values||{}))for(const part of Array.isArray(value)?value:[value])result.append(key,String(part));return result;};
    client.on('redirect',(status,_method,url,responseHeaders)=>{
      const result=headers(responseHeaders);result.set('location',url);
      done(new Response(null,{status,headers:result}));client.abort();
    });
    client.on('response',incoming=>{
      const result=headers(incoming.headers);
      // Chromium has already decoded the stream; omit transport metadata.
      result.delete('content-encoding');result.delete('content-length');result.delete('transfer-encoding');
      done(new Response([204,205,304].includes(incoming.statusCode)||request.method==='HEAD'?null:Readable.toWeb(incoming),{status:incoming.statusCode,headers:result}));
    });
    client.on('error',error=>{if(!settled){settled=true;signal?.removeEventListener('abort',abort);reject(error);}});
    if(signal?.aborted){abort();return;}signal?.addEventListener('abort',abort,{once:true});
    if(body)client.write(body);client.end();
  });
}
function readable(url){
  const p=url.pathname;
  if(/^\/files\/(upload|legacy|attachment)\/[1-9]\d*\/(?:content\/)?$/.test(p)||p==="/me/appearance/"||p==="/me/files/"||p==="/assistant/")return true;
  return /^\/(?:workspace\/|projects\/(?:[1-9]\d*\/)?|tasks\/(?:[1-9]\d*\/)?|experiments\/(?:[1-9]\d*\/)?|documents\/(?:[1-9]\d*\/)?|messages\/(?:social\/|notices\/|teams\/|personal\/[1-9]\d*\/|groups\/[1-9]\d*\/)?|me\/|account\/|discover\/(?:talents\/(?:[1-9]\d*\/)?|applications\/|offers\/(?:[1-9]\d*\/)?)?|team-square\/(?:[1-9]\d*\/)?|app\/pages\/)$/u.test(p)
    || /^\/static\/(?:core|aihub|vendor)\/.+\.(?:css|js|svg|png|json)$/u.test(p)
    || /^\/(?:workspace\/navigation\/[1-9]\d*\/|messages\/(?:files|legacy-files)\/[1-9]\d*\/|accounts\/[1-9]\d*\/avatar\/[^/]+\/|app\/groups\/[1-9]\d*\/avatar\/|app\/background\/|members\/[1-9]\d*\/card\/|app\/preferences\/|messages\/stickers\/(?:[1-9]\d*\/file\/)?)$/u.test(p);
}
class PageCache{
  constructor(root,context,fetch,online=()=>true,onMutation=()=>{}){this.root=path.resolve(root);this.context=context;this.fetch=fetch;this.online=online;this.onMutation=onMutation;this.refreshing=new Set();this.epoch=0;this.forceUntil=0;}
  identity(){const c=this.context();return c.authenticated&&c.account&&c.origin?c:null;}
  folder(c){return path.join(this.root,hash(c.origin+'\n'+c.account));}
  file(c,url){return path.join(this.folder(c),hash(url)+'.json');}
  async read(c,url){try{const file=this.file(c,url);if((await fs.stat(file)).size>8*1024*1024)return null;const row=JSON.parse(await fs.readFile(file,'utf8'));return row.url===url&&typeof row.body==='string'&&row.headers?row:null;}catch(_){return null;}}
  async store(c,url,response,epoch){
    const type=response.headers.get('content-type')||'';
    if(!response.ok||response.status!==200||!/(?:text\/html|text\/css|javascript|application\/json|image\/)/.test(type))return;
    if(Number(response.headers.get('content-length'))>5*1024*1024)return;
    const data=Buffer.from(await response.clone().arrayBuffer());if(data.length>5*1024*1024)return;
    if(type.includes('text/html')&&!/data-account=["'][1-9]\d*["']/.test(data.toString('utf8')))return;
    if(epoch!==this.epoch||JSON.stringify(c)!==JSON.stringify(this.identity()))return;
    const headers=Object.fromEntries(response.headers);for(const key of ['set-cookie','content-length','content-encoding','transfer-encoding'])delete headers[key];
    const row={url,type,headers,savedAt:Date.now(),body:data.toString('base64')},folder=this.folder(c);
    await fs.mkdir(folder,{recursive:true});const file=this.file(c,url),tmp=file+'.'+crypto.randomUUID()+'.tmp';
    await fs.writeFile(tmp,JSON.stringify(row),{mode:0o600});
    if(epoch!==this.epoch){await fs.unlink(tmp).catch(()=>{});return;}
    await fs.rename(tmp,file).catch(async()=>{await fs.unlink(tmp).catch(()=>{});});
    const files=await fs.readdir(folder);let total=0;const records=[];
    for(const name of files.filter(n=>/^[a-f0-9]{64}\.json$/.test(n))){try{const target=path.join(folder,name),stat=await fs.stat(target);total+=stat.size;records.push({target,size:stat.size,at:stat.mtimeMs});}catch(_){}}
    for(const record of records.sort((a,b)=>a.at-b.at)){if(total<=80*1024*1024)break;await fs.unlink(record.target).catch(()=>{});total-=record.size;}
  }
  response(row,offline){
    let body=Buffer.from(row.body,'base64');
    if(row.type.includes('text/html')&&offline){const mark='<div role="status" style="padding:6px 12px;background:#eef3ef;color:#526257;font-size:12px">离线 · 本地缓存</div>';body=Buffer.from(body.toString('utf8').replace(/(<body\b[^>]*>)/i,'$1'+mark));}
    return new Response(body,{status:200,headers:{...row.headers,'X-Zhiyu-Cache':'local'}});
  }
  async invalidate(c,changed){
    this.epoch++;
    if(!c)return;
    const folder=this.folder(c);
    for(const name of await fs.readdir(folder).catch(()=>[])){if(!/^[a-f0-9]{64}\.json$/.test(name))continue;const target=path.join(folder,name);try{const row=JSON.parse(await fs.readFile(target,'utf8'));const p=new URL(row.url).pathname;const domain=changed?.startsWith('/messages/stickers/')?'stickers':changed?.startsWith('/messages/')||changed?.startsWith('/app/forward/')?'messages':changed?.startsWith('/assistant/')?'ai':null;const affected=!domain||domain==='messages'&&(/^\/messages\//.test(p)||p==='/app/notifications/')||domain==='ai'&&p.startsWith('/assistant/')||domain==='stickers'&&p.includes('stickers');if(affected&&!p.startsWith('/static/')&&!row.type.startsWith('image/'))await fs.unlink(target);}catch(_){}}
  }
  force(){this.forceUntil=Date.now()+10000;}
  async network(request,options={}){
    return this.fetch(request,{bypassCustomProtocolHandlers:true,...options});
  }
  async retrieve(request,c,epoch){
    const result=await this.network(request,{signal:AbortSignal.timeout(12000)});
    const location=result.headers.get('location')||'';
    if(result.status===401||result.status===403||result.status===404||/\/login\//.test(location)){
      if(result.status===401||/\/login\//.test(location))await this.invalidate(c);
      else await fs.unlink(this.file(c,request.url)).catch(()=>{});
    }else await this.store(c,request.url,result,epoch).catch(()=>{});
    return result;
  }
  async handle(request){
    const c=this.identity(),url=new URL(request.url);
    const own=c&&url.origin===c.origin&&(!request.initiatorOrigin||request.initiatorOrigin===c.origin||request.initiatorOrigin==='null');
    if(request.method!=='GET'||!own||!readable(url)){
      const response=await this.network(request);
      if(own&&!['GET','HEAD'].includes(request.method)&&!/^\/messages\/(?:local-records\/ack|unread|read)\/$/.test(url.pathname)&&response.status<400){await this.invalidate(c,url.pathname);this.onMutation(url.pathname);}
      return response;
    }
    const epoch=this.epoch,row=await this.read(c,request.url);
    if(row&&Date.now()>this.forceUntil){
      const age=url.pathname.startsWith('/static/')&&/\.[a-f0-9]{12}\./.test(url.pathname)?Infinity:row.type.startsWith('image/')?86400000:120000;
      if(this.online()&&Date.now()-row.savedAt>age&&!this.refreshing.has(request.url)){
        this.refreshing.add(request.url);this.retrieve(request.clone(),c,epoch).catch(()=>{}).finally(()=>this.refreshing.delete(request.url));
      }
      return this.response(row,!this.online());
    }
    try{return await this.retrieve(request,c,epoch);}catch(error){if(row&&epoch===this.epoch)return this.response(row,true);throw error;}
  }
  install(session){for(const scheme of ['http','https'])session.protocol.handle(scheme,request=>this.handle(request));}
}
module.exports={PageCache,readable,sessionRequest};
