const {app,BrowserWindow,webContents}=require('electron');
require('./runtime.cjs').installRuntime(app,{timeoutMs:90000});
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const directory=process.env.WORKBENCH_DESKTOP_STATE;
assert.ok(directory && directory.includes('.test-scratch'));
app.disableHardwareAcceleration();app.on('browser-window-created',(_event,win)=>win.on('show',()=>win.hide()));
require('../updates.cjs').Updates.prototype.start=function(){};
const cold=process.env.CACHE_SMOKE_PHASE==='cold',file=path.join(directory,'server-connection.json');
let server,chrome,origin,authenticated=true;const counts={};
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(label,predicate){const end=Date.now()+22000;while(Date.now()<end){if(await predicate())return;await delay(80);}throw Error('Timed out: '+label);}
const info=async()=> (await chrome.executeJavaScript('window.desktop.info()')).data;
const navigate=name=>chrome.executeJavaScript(`window.desktop.navigate(${JSON.stringify(name)})`);
function pane(address){return webContents.getAllWebContents().find(c=>c.getURL()===origin+address);}
function startServer(port=0){return new Promise(resolve=>{
  server=http.createServer((request,response)=>{
    const address=new URL(request.url,'http://local').pathname;counts[address]=(counts[address]||0)+1;
    if(address==='/desktop/api/logout/')authenticated=false;
    if(address.startsWith('/desktop/api/')){
      response.writeHead(200,{'Content-Type':'application/json','Set-Cookie':'csrftoken=test-token; Path=/'});
      response.end(JSON.stringify({protocol:1,authenticated,username:'cache-test',accountId:1,nickname:'缓存验收',csrfToken:'test-token',teamId:1,spaceId:1,teamName:'验收团队',spaceName:'验收团队',apiSpaceId:1,spaces:[{id:1,teamId:1,name:'验收团队'}],hasEmail:true,needsTeam:false,serverVersion:'0.5.4'}));return;
    }
    if(address==='/messages/unread/'||address==='/app/notifications/'||address==='/workspace/navigation/'){
      response.writeHead(200,{'Content-Type':'application/json'});response.end(JSON.stringify({total:0,conversations:[],projects:[]}));return;
    }
    response.writeHead(200,{'Content-Type':'text/html;charset=utf-8'});
    response.end('<!doctype html><html data-account="1"><body style="height:2600px"><h1>'+address+'</h1><input id="retained"><p id="cached">本地缓存页面</p></body></html>');
  }).listen(port,'127.0.0.1',resolve);
});}
(async()=>{
  if(!cold){await startServer();origin='http://127.0.0.1:'+server.address().port;fs.mkdirSync(directory,{recursive:true});fs.writeFileSync(file,JSON.stringify({mode:'remote',url:origin}));}
  else origin=JSON.parse(fs.readFileSync(file)).url;
  require('../main.cjs');await app.whenReady();
  await until('desktop renderer',async()=>{chrome=BrowserWindow.getAllWindows()[0]?.webContents;return chrome&&!chrome.isLoading()&&await chrome.executeJavaScript('Boolean(window.desktop)').catch(()=>false);});
  await until('authenticated workspace',async()=>{const state=await info();return state.authenticated&&pane('/workspace/')&&!pane('/workspace/').isLoading();});
  if(!cold){
    await navigate('messages');await until('messages pane',()=>pane('/messages/social/')&&!pane('/messages/social/').isLoading());
    await pane('/messages/social/').executeJavaScript("document.getElementById('retained').value='保持草稿';scrollTo(0,500)");
    const before=counts['/messages/social/'];await navigate('ai');await navigate('workspace');await navigate('messages');
    assert.equal(counts['/messages/social/'],before,'returning to messages must reuse the component');
    assert.equal(await pane('/messages/social/').executeJavaScript("document.getElementById('retained').value"),'保持草稿');
    assert.equal(await pane('/messages/social/').executeJavaScript('scrollY'),500);
    console.log('PASS: navigation reuses the page, draft and scroll without requesting it again.');
    await until('cached HTML',()=>fs.existsSync(path.join(directory,'page-cache','v1')));
    await delay(400);server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  }else{
    assert.equal((await info()).backend,'offline');
    assert.ok(await pane('/workspace/').executeJavaScript("document.body.textContent.includes('本地缓存页面')"));
    await navigate('messages');await until('offline messages',()=>pane('/messages/social/')&&!pane('/messages/social/').isLoading());
    assert.ok(await pane('/messages/social/').executeJavaScript("document.body.textContent.includes('本地缓存页面')"));
    console.log('PASS: offline cold start restores the account and original workspace/message routes.');
    await startServer(Number(new URL(origin).port));
    await until('automatic reconnect',async()=> (await info()).backend==='ready');
    assert.equal((await info()).current,'messages','reconnection must keep the current page');
    console.log('PASS: automatic reconnect keeps the current conversation tab.');
    await chrome.executeJavaScript('window.desktop.logout()');
    assert.equal((await info()).authenticated,false);
    const snapshot=path.join(directory,'offline-account');assert.equal(fs.existsSync(snapshot)?fs.readdirSync(snapshot).length:0,0);
    console.log('PASS: logout removes cached account authorization.');
    server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  }
  app.exit(0);
})().catch(async error=>{console.error(error.stack);console.error(JSON.stringify({counts,info:chrome?await info().catch(()=>null):null,contents:webContents.getAllWebContents().map(c=>({url:c.getURL(),loading:c.isLoading()}))}));server?.closeAllConnections();server?.close();app.exit(1);});
