// Real Django group templates and browser events; no production accounts or APIs.
const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch');
app.setPath('userData',path.join(scratch,'group-preferences-client'));app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
let win,server,html,prefs,memberId,key,managePath,failNext=false;const errors=[],posts=[];
const pause=ms=>new Promise(r=>setTimeout(r,ms)),js=code=>win.webContents.executeJavaScript(code);
async function until(label,code){for(let n=0;n<100;n++){if(await js(code))return;await pause(50);}throw Error(label);}
function page(){
 let result=html.replace(/<input type="checkbox" role="switch" name="(muted|pinned|show_nicknames)"[^>]*>/g,(_,field)=>`<input type="checkbox" role="switch" name="${field}" ${prefs[field]?'checked':''}>`);
 if(!prefs.show_nicknames)result=result.replace('class="conversation-main','class="conversation-main hide-group-nicknames');
 if(prefs.pinned){const links=[...result.matchAll(/<a class="conversation-link[^]*?<\/a>/g)];const selected=links.find(m=>m[0].includes(`data-conversation-key="${key}"`));if(selected){result=result.replace(selected[0],'');result=result.replace('<div class="communication-items">','<div class="communication-items">'+selected[0].replace('<time>','<span data-pinned-marker>置顶</span><time>'));}}
 if(prefs.muted)result=result.replace(new RegExp(`(data-conversation-key="${key}"[^]*?data-muted-marker) hidden`),'$1');
 return result;
}
app.whenReady().then(async()=>{
 server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost');const json=(value,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(value));};
  if(url.pathname.startsWith('/static/')){const file=path.resolve(root,url.pathname.slice(1));if(!file.startsWith(path.join(root,'static')+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'image/svg+xml');return res.end(fs.readFileSync(file));}
  if(req.method==='POST'){
   let body='';req.setEncoding('utf8');req.on('data',chunk=>body+=chunk);req.on('end',()=>{
    posts.push(url.pathname);if(url.pathname!==managePath)return json({error:'错误的表单地址'},404);
    if(failNext){failNext=false;return json({error:'测试保存失败'},503);}
    const fields=Object.fromEntries([...body.matchAll(/name="([^"]+)"\r\n\r\n([^]*?)\r\n--/g)].map(m=>[m[1],m[2]]));
    if(fields.action!=='settings')return json({error:'错误的操作'},400);
    if('nickname' in fields)prefs.nickname=fields.nickname.trim();
    for(const name of ['muted','pinned','show_nicknames'])if(name in fields||fields.setting===name)prefs[name]=fields[name]==='on';
    json({ok:true,preferences:prefs,member:{id:memberId,display_name:prefs.nickname||'group-member'}});
   });return;
  }
  if(url.pathname==='/fixture.html'){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end(page());}
  if(url.pathname.endsWith('/unread/'))return json({total:0,channels:{},hidden_channels:[],muted_channels:[]});
  if(url.pathname.endsWith('/stickers/'))return json({stickers:[]});
  return json({messages:[],updates:[],removed:[],next_before:null});
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 win=new BrowserWindow({show:false,width:1280,height:900,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
 win.webContents.on('console-message',event=>{if(event.level==='error'&&/Uncaught|ReferenceError|TypeError/.test(event.message))errors.push(event.message);});
 for(const type of ['group','team']){
  html=fs.readFileSync(path.join(scratch,'render-pages','preferences-'+type+'.html'),'utf8');prefs={nickname:'',remark:'',muted:false,pinned:false,show_nicknames:true};
  managePath=html.match(/action="(\/messages\/groups\/\d+\/manage\/)"/)[1];
  await win.loadURL(origin+'/fixture.html');await pause(200);
  memberId=await js("Number(document.querySelector('.message-bubble-row.mine [data-member-id]').dataset.memberId)");
  key=await js("document.querySelector('.communication-item.selected').dataset.conversationKey");
  // Prove the browser collision that caused all preference requests to fail.
  assert.equal(await js("document.querySelector('[data-group-toggle]').action instanceof HTMLInputElement"),true);
  await js("document.querySelector('[data-chat-details-toggle]').click()");
  for(const field of ['muted','pinned','show_nicknames']){
   await js(`document.querySelector('[data-group-toggle] input[name=${field}]').click()`);
   await until(type+' '+field+' saved',`document.querySelector('input[name=${field}]').form.dataset.saving==='false'`);
   assert.equal(prefs[field],field!=='show_nicknames');
  }
  await until('pin visibly updates navigation',"Boolean(document.querySelector('[data-pinned-marker]'))");
  assert.equal(await js("document.querySelector('.communication-item').dataset.conversationKey"),key);
  assert.equal(await js("document.querySelector('[data-messages],[data-personal-thread]').classList.contains('hide-group-nicknames')"),true);
  await js("(()=>{const form=document.querySelector('[data-inline-edit] input[name=nickname]').form;form.querySelector('[data-edit-start]').click();form.querySelector('input[name=nickname]').value='  本群新昵称  ';form.querySelector('input[name=nickname]').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));})()");
  await until('nickname applied to existing message',"document.querySelector('.message-bubble-row.mine .message-byline strong').textContent==='本群新昵称'");
  assert.equal(prefs.nickname,'本群新昵称');
  await js("document.querySelector('[data-conversation-action=search],[data-thread-history-open]').click()");
  assert.equal(await js("document.querySelector('[data-history-dialog]').open"),true);
  await js("document.querySelector('[data-history-dialog]').close()");
  failNext=true;await js("document.querySelector('input[name=muted]').click()");
  await until('failed save shows error and rolls back',"document.querySelector('[data-group-status]').textContent==='测试保存失败'&&document.querySelector('input[name=muted]').checked");
  await win.reload();await pause(200);
  assert.equal(await js("document.querySelector('input[name=muted]').checked&&document.querySelector('input[name=pinned]').checked&&!document.querySelector('input[name=show_nicknames]').checked&&document.querySelector('[data-messages],[data-personal-thread]').classList.contains('hide-group-nicknames')"),true);
  console.log('PASS:',type,'nickname, mute, pin, visibility, search, reload and failed save');
 }
 assert.deepEqual(errors,[]);assert.equal(posts.filter(value=>/\/groups\/\d+\/manage\/$/.test(value)).length,10);server.close();app.exit(0);
}).catch(error=>{console.error(error);console.error('POST paths:',posts);server?.close();app.exit(1);});
