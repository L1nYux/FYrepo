const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch'),fixtures=path.join(scratch,'render-pages');
app.setPath('userData',path.join(scratch,'email-thinking-client'));app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
let server,win,phase=0,starts=0,polls=0,checks=0;const errors=[];
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const js=code=>win.webContents.executeJavaScript(code);
async function until(label,code){const deadline=Date.now()+12000;while(Date.now()<deadline){if(await js(code))return;await delay(40);}throw Error('Timed out: '+label);}
async function check(label,code){const value=await js(code);if(!value){console.log(await js("JSON.stringify({width:innerWidth,scroll:document.documentElement.scrollWidth,buttons:[...document.querySelectorAll('button')].map(b=>({text:b.textContent,height:b.getBoundingClientRect().height,min:getComputedStyle(b).minHeight})),wide:[...document.querySelectorAll('body *')].filter(n=>n.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(n=>({tag:n.tagName,class:n.className,width:n.getBoundingClientRect().width,right:n.getBoundingClientRect().right}))})"));fs.writeFileSync(path.join(scratch,'email-thinking-failure.png'),(await win.webContents.capturePage()).toPNG());}assert.equal(value,true,label);console.log('PASS:',label);checks++;}
app.whenReady().then(async()=>{
  server=http.createServer(async(req,res)=>{
    const url=new URL(req.url,'http://localhost');
    const json=(data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
    if(url.pathname==='/assistant/start/'){for await(const _ of req){}starts++;await delay(180);json({job:'live-job',conversation:1,title:'Streaming'},202);return;}
    if(url.pathname.startsWith('/assistant/jobs/')){polls++;json(phase===2?{state:'done',result:{text:'最终正文',reasoning:'真实厂商思考 <script>bad()</script>',calls:1,tokens:30,cost_cny:'0.001'}}:{state:'running',activity:[{label:'读取项目'}],result:{progress:{stage:phase===1?'replying':'thinking',text:phase===1?'逐步正文':'',reasoning:'真实厂商思考 <script>bad()</script>'}}});return;}
    if(url.pathname==='/assistant/conversations/'){json({conversations:[],history_days:0});return;}
    if(url.pathname==='/api-pool/catalog/'){json({models:[{id:1,configured:true,provider:'Test',label:'Test'}],budget:{member_week:{limit:null},extra:{remaining_points:0}}});return;}
    if(url.pathname==='/messages/unread/'){json({total:0});return;}
    if(url.pathname==='/composer/'){res.setHeader('Content-Type','text/html');res.end('<form id="short"><textarea data-message-input required></textarea><button type="submit">Send</button></form><form id="long"><textarea></textarea><button>Save</button></form><script>window.submits=0;document.querySelector("#short").addEventListener("submit",e=>{e.preventDefault();window.submits++});</script><script src="/static/core/composer.js"></script>');return;}
    const pages={'/assistant/':'assistant.html','/binding/start/':'binding-start.html','/binding/code/':'binding-code.html','/recovery/code/':'recovery.html','/recovery/password/':'recovery-verified.html'};
    const file=url.pathname.startsWith('/static/')?path.join(root,url.pathname.slice(1)):path.join(fixtures,pages[url.pathname]||'workspace.html');
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');res.end(fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
  win=new BrowserWindow({show:false,width:1100,height:850,useContentSize:true,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
  win.webContents.on('console-message',(_e,details)=>{if(details?.level==='error')errors.push(details.message);});
  await win.loadURL(origin+'/assistant/');await until('models',"!document.querySelector('#assistant-send').disabled");
  await js("document.querySelector('#assistant-input').value='测试';document.querySelector('#assistant-form').requestSubmit()");
  await check('wait bubble appears immediately',"Boolean(document.querySelector('.assistant-pending .assistant-wait')) && document.querySelector('.assistant-wait').textContent.includes('正在思考')");
  await until('vendor thinking',"document.querySelector('.assistant-pending .assistant-thinking-text')?.textContent.includes('真实厂商')");
  await check('reasoning is folded and treated as text',"!document.querySelector('.assistant-pending details').open && !document.querySelector('.assistant-thinking-text script')");
  await js("document.querySelector('.assistant-pending details').open=true");phase=1;
  await until('partial reply',"document.querySelector('.assistant-pending .assistant-text')?.textContent==='逐步正文'");
  await check('stream preserves user expansion and shows reply state',"document.querySelector('.assistant-pending details').open && document.querySelector('.assistant-wait').textContent.includes('正在回复')");
  await delay(150);fs.writeFileSync(path.join(scratch,'thinking-desktop.png'),(await win.webContents.capturePage()).toPNG());
  phase=2;await until('final reply',"!document.querySelector('.assistant-pending') && document.querySelector('.assistant-row.assistant .assistant-text')?.textContent==='最终正文'");
  await check('one final bubble and one billable start',"document.querySelectorAll('.assistant-row.assistant').length===1 && !document.querySelector('.assistant-wait')");assert.equal(starts,1);assert.ok(polls>=3);
  win.setContentSize(390,780);
  await check('assistant fits phone width',"document.documentElement.scrollWidth<=innerWidth");
  for(const [url,button] of [['/binding/start/','发送验证码'],['/binding/code/','验证并绑定邮箱'],['/recovery/code/','验证验证码'],['/recovery/password/','保存新密码']]){
    await win.loadURL(origin+url);await delay(120);
    await check(url+' fits phone and has readable controls',`document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('button')].some(b=>b.textContent==='${button}'&&b.getBoundingClientRect().height>=44)`);
    if(url==='/binding/code/'){
      await check('binding has numeric auto-fill code and countdown',"document.querySelector('input[name=code]').getAttribute('inputmode')==='numeric' && document.querySelector('[data-countdown]').disabled");
      await js("document.querySelector('#email-binding').scrollIntoView({block:'start'})");await delay(150);fs.writeFileSync(path.join(scratch,'binding-phone.png'),(await win.webContents.capturePage()).toPNG());
    }
    if(url==='/recovery/code/')await check('password fields absent before proof',"!document.querySelector('input[name=new_password1]')");
    if(url==='/recovery/password/'){
      await check('reset no longer asks for code twice',"!document.querySelector('input[name=code]') && Boolean(document.querySelector('input[name=new_password1]'))");
      fs.writeFileSync(path.join(scratch,'recovery-password-phone.png'),(await win.webContents.capturePage()).toPNG());
    }
  }
  win.setContentSize(1000,800);await win.loadURL(origin+'/composer/');
  await js("document.querySelector('#short textarea').value='Hello'");
  await check('Enter sends conversational input',"(()=>{const e=new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true});document.querySelector('#short textarea').dispatchEvent(e);return e.defaultPrevented&&window.submits===1})()");
  await check('Shift Enter and input method confirmation do not send',"(()=>{const box=document.querySelector('#short textarea');box.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',shiftKey:true}));box.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true}));box.dispatchEvent(new CompositionEvent('compositionstart'));box.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}));box.dispatchEvent(new CompositionEvent('compositionend'));return window.submits===1})()");
  await check('held Enter does not submit again',"(()=>{document.querySelector('#short textarea').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',repeat:true}));return window.submits===1})()");
  await check('long document input has no send handler',"(()=>{const e=new KeyboardEvent('keydown',{key:'Enter',cancelable:true});document.querySelector('#long textarea').dispatchEvent(e);return !e.defaultPrevented})()");
  await delay(120);await js("window.nativeMatchMedia=window.matchMedia;window.matchMedia=q=>q.includes('(hover:hover)')?{matches:false}:window.nativeMatchMedia(q);void 0");
  await check('phone Enter retains newline behavior',"(()=>{const e=new KeyboardEvent('keydown',{key:'Enter',cancelable:true});document.querySelector('#short textarea').dispatchEvent(e);return !e.defaultPrevented&&window.submits===1})()");
  assert.deepEqual(errors,[]);console.log('ALL_EMAIL_THINKING_CHECKS_PASSED',checks);win.destroy();server.close();app.exit(0);
}).catch(error=>{console.error(error);if(win)win.destroy();server?.close();app.exit(1);});
