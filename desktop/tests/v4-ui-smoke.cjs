// Real rendered templates and local Emoji Mart in a hidden Electron window.
const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch'),fixtures=path.join(scratch,'render-pages');
app.setPath('userData',path.join(scratch,'v4-ui-client'));app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
let win,server;const errors=[];const pause=ms=>new Promise(r=>setTimeout(r,ms));
const js=code=>win.webContents.executeJavaScript(code);
async function until(label,code){for(let i=0;i<100;i++){if(await js(code)){console.log('PASS:',label);return;}await pause(50);}throw Error(label);}
async function screenshot(name){await js("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))");await pause(120);fs.writeFileSync(path.join(scratch,name+'.png'),(await win.webContents.capturePage()).toPNG());}
app.whenReady().then(async()=>{
 server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost'),json=data=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify(data));};
  if(url.pathname.startsWith('/static/')){
   const file=path.resolve(root,url.pathname.slice(1));
   if(!file.startsWith(path.join(root,'static')+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
   res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':file.endsWith('.json')?'application/json':'image/svg+xml');res.end(fs.readFileSync(file));return;
  }
  if(url.pathname==='/api-pool/catalog/')return json({models:[{id:1,configured:true,provider_id:1,provider:'测试连接',label:'测试模型'}],budget:{member_week:{limit:null},extra:{remaining_points:100}},funding:1,funding_name:'个人'});
  if(url.pathname==='/assistant/conversations/')return json({conversations:[],history_days:0});
  if(url.pathname.endsWith('/stickers/'))return json({stickers:[]});
  if(url.pathname.endsWith('/unread/'))return json({total:0,channels:{}});
  if(url.pathname.includes('/poll/')||url.pathname.endsWith('/settings/'))return json({messages:[],updates:[],removed:[]});
  if(/^\/v4-[a-z]+\.html$/.test(url.pathname)){
   res.setHeader('Content-Type','text/html; charset=utf-8');res.end(fs.readFileSync(path.join(fixtures,url.pathname.slice(1))));return;
  }
  res.writeHead(404);res.end();
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 win=new BrowserWindow({show:false,width:1380,height:880,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
 win.webContents.on('console-message',(_event,details)=>{if(details.level==='error')errors.push(details.message);});
 win.webContents.on('render-process-gone',()=>{throw Error('Renderer stopped');});
 for(const name of ['home','talents','project','team','assistant','group','me','ledger','ledgerform','contacts']){
  await win.loadURL(origin+'/v4-'+name+'.html');await pause(160);
  await js("for(let n=0;n<3&&document.documentElement.dataset.theme!=='light';n++)document.querySelector('[data-theme-toggle]').click()");
  await pause(80);
  await screenshot('v4-'+name+'-light');
  if(name==='home')assert.equal(await js("document.body.textContent.includes('团队公告')"),false);
  if(name==='me')assert.equal(await js("!document.querySelector('.sidebar-projects')&&document.querySelector('[aria-label=我的导航]')&&document.querySelector('.personal-profile-card').clientHeight>110"),true);
  if(name==='ledger')assert.equal(await js("document.querySelectorAll('.personal-ledger-summary .stat').length===3&&!document.body.textContent.includes('待审报销')"),true);
  if(name==='ledgerform')assert.equal(await js("document.querySelector('#id_kind').options.length===2&&!document.querySelector('#id_memo').required"),true);
  if(name==='contacts')assert.equal(await js("document.querySelectorAll('details.contact-category').length===4&&!document.querySelector('.communication-categories')"),true);
  if(name==='talents')assert.equal(await js("Boolean(document.querySelector('[aria-label=发现]'))"),true);
  if(name==='team')assert.equal(await js("document.querySelectorAll('.team-context-tabs a').length>=4"),true);
  if(name==='assistant')await until('funding source and model selectors are ready',"document.getElementById('assistant-funding').options.length>0&&document.getElementById('assistant-model').value==='1'");
  if(name==='group'){
   await js("document.querySelector('[data-chat-details-toggle]').click()");
   await until('member plus/minus remain in group details',"!document.querySelector('[data-chat-details]').hidden&&document.querySelectorAll('[data-group-members-open]').length===2");
   await screenshot('v4-group-details-light');
   assert.equal(await js("(()=>{const form=document.querySelector('[data-message-form]'),send=form.querySelector('[type=submit]').getBoundingClientRect(),emoji=form.querySelector('[data-sticker-open]').getBoundingClientRect();return send.x>emoji.x+300;})()"),true);
   await js("document.querySelector('[data-sticker-open]').click()");
   await until('full local emoji picker is visible',"document.querySelector('em-emoji-picker')?.shadowRoot?.querySelectorAll('button').length>100&&document.querySelector('.expression-picker').clientHeight>300");
   await screenshot('v4-emoji-light');
   await js("document.querySelector('.expression-picker [data-close]').click();for(let n=0;n<3&&document.documentElement.dataset.theme!=='dark';n++)document.querySelector('[data-theme-toggle]').click();document.querySelector('[data-sticker-open]').click()");
   await until('dark emoji picker is ready',"document.querySelector('em-emoji-picker')?.dataset.theme==='dark'&&document.querySelector('em-emoji-picker')?.shadowRoot?.querySelectorAll('button').length>100");
   await screenshot('v4-emoji-dark');
  }
 }
 const fatal=errors.filter(text=>/Uncaught|SyntaxError|ReferenceError|TypeError/.test(text));assert.deepEqual(fatal,[]);
 console.log('PASS: all ten surfaces rendered without script errors');server.close();app.exit(0);
}).catch(async error=>{console.error(error);if(win&&!win.isDestroyed())await screenshot('v4-ui-failure');server?.close();app.exit(1);});
