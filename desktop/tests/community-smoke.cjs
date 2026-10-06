const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),fixtures=path.join(root,'.test-scratch/render-pages');
app.setPath('userData',path.join(root,'.test-scratch/community-ui-'+Date.now()));app.disableHardwareAcceleration();
let win,server,posts=0;
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.whenReady().then(async()=>{
  const pages=['community-square.html','community-manage.html','community-resume.html','community-social.html','community-thread.html','community-team-permissions.html'];
  for(const name of pages)assert.ok(fs.existsSync(path.join(fixtures,name)),'Generate current community fixture: '+name);
  let selected=pages[0];
  server=http.createServer((request,response)=>{
    const location=new URL(request.url,'http://localhost');request.resume();
    if(location.pathname.startsWith('/static/')){
      const file=path.resolve(root,location.pathname.slice(1));if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){response.writeHead(404);response.end();return;}
      response.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/javascript');response.end(fs.readFileSync(file));return;
    }
    if(location.pathname.match(/^\/members\/\d+\/card\/$/)){response.setHeader('Content-Type','application/json');response.end(JSON.stringify({id:3,username:'outside-id',display_name:'测试昵称',initial:'测',role:'个人账号',friend_state:'none',friend_url:'/messages/friends/request/',csrf_token:'fixture-only',projects:[]}));return;}
    if(location.pathname==='/messages/friends/search/'){response.setHeader('Content-Type','application/json');response.end(JSON.stringify({id:3,username:'outside-id',display_name:'测试昵称',friend_state:'none',friend_url:'/messages/friends/request/',csrf_token:'fixture-only'}));return;}
    if(location.pathname==='/messages/friends/request/'){response.setHeader('Content-Type','application/json');response.end(JSON.stringify({state:'sent',message:'好友申请已发送，等待对方确认。'}));return;}
    if(request.headers.accept==='application/json'){
      response.setHeader('Content-Type','application/json');if(request.method==='POST')posts++;
      response.end(JSON.stringify({total:0,channels:{},messages:posts?[{id:99,author:'我',author_id:1,action_url:'/messages/personal/3/action/99/',mine:true,body:'<img src=x> 安全显示',at:'10-06 12:00'}]:[]}));return;
    }
    response.setHeader('Content-Type','text/html;charset=utf-8');response.end(fs.readFileSync(path.join(fixtures,selected)));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  win=new BrowserWindow({show:false,width:1200,height:850,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
  for(const file of pages){
    selected=file;await win.loadURL('http://127.0.0.1:'+server.address().port+'/');await wait(100);
    assert.equal(await win.webContents.executeJavaScript("!!document.querySelector('h1') && [...document.querySelectorAll('form[method=post]')].every(form=>!!form.querySelector('[name=csrfmiddlewaretoken]'))"),true,file+' heading and CSRF');
    win.setContentSize(390,760);await wait(80);assert.equal(await win.webContents.executeJavaScript('document.documentElement.scrollWidth<=innerWidth+1'),true,file+' mobile layout');win.setContentSize(1200,850);
    console.log('PASS current community page:',file);
  }
  selected='community-contacts.html';await win.loadURL('http://127.0.0.1:'+server.address().port+'/');
  await win.webContents.executeJavaScript("document.querySelector('[data-contact-id]').click()");await wait(180);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('[data-contact-details]').textContent.includes('测试昵称')&&!document.querySelector('.member-card-dialog').open"),true);
  await win.webContents.executeJavaScript("document.querySelector('[data-contact-details] form').requestSubmit()");await wait(150);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('[data-contact-details]').textContent.includes('申请已发送')"),true);
  await win.webContents.executeJavaScript("document.querySelector('[data-contact-add-open]').click();document.querySelector('[data-contact-search] input').value='outside-id';document.querySelector('[data-contact-search]').requestSubmit()");await wait(150);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('[data-contact-search-result]').textContent.includes('工作台号：outside-id')"),true);
  await win.webContents.executeJavaScript("document.querySelector('[data-contact-add-close]').click()");
  fs.writeFileSync(path.join(root,'.test-scratch/zhiyu-contacts.png'),(await win.webContents.capturePage()).toPNG());
  console.log('PASS unified contact detail, friend request and account search');
  selected='community-thread.html';await win.loadURL('http://127.0.0.1:'+server.address().port+'/');
  await win.webContents.executeJavaScript("document.querySelector('[data-thread-status]').textContent='上次发送失败';const textarea=document.querySelector('[data-thread-form] textarea');textarea.value='消息';textarea.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));");await wait(200);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('[data-thread-status]').textContent"),'');
  assert.equal(posts,1);assert.equal(await win.webContents.executeJavaScript("document.querySelector('[data-thread-form] textarea').value"),'');
  assert.equal(await win.webContents.executeJavaScript("[...document.querySelectorAll('.personal-message-row .message-bubble p')].some(node=>node.textContent.includes('<img src=x>')) && !document.querySelector('.personal-message-row .message-bubble img')"),true);
  fs.writeFileSync(path.join(root,'.test-scratch/community-ui.png'),(await win.webContents.capturePage()).toPNG());
  console.log('PASS Enter send, draft clearing and escaped message display');win.destroy();server.close();app.exit(0);
}).catch(error=>{console.error(error.stack);if(win&&!win.isDestroyed())win.destroy();server?.close();app.exit(1);});
