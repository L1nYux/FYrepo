// Run the real main process and all three sandboxed renderers against a local fixture server.
const {app,BrowserWindow,shell}=require('electron');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch');
const state=path.join(scratch,'loading-client-'+Date.now());
fs.mkdirSync(state,{recursive:true});process.env.WORKBENCH_DESKTOP_STATE=state;
app.disableHardwareAcceleration();
// Keep debug windows hidden; production main code and IPC remain unchanged.
app.on('browser-window-created',(_event,window)=>{window.show=()=>{};window.focus=()=>{};});
let win,server,authenticated=true,serviceFailed=false,pageFailed=false,blocked=new Map();
const external=[];shell.openExternal=async url=>{external.push(url);};let legacyPosts=0;
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(label,fn){const deadline=Date.now()+15000;while(Date.now()<deadline){if(await fn())return;await wait(50);}throw Error('Timed out: '+label);}
async function info(){const result=await win.webContents.executeJavaScript('window.desktop.info()');assert.equal(result.ok,true);return result.data;}
async function check(label,fn){assert.equal(await fn(),true,label);console.log('PASS:',label);}
function hold(name){let release;const ready=new Promise(resolve=>release=resolve);blocked.set(name,ready);return ()=>{blocked.delete(name);release();};}
const releaseStartup=hold('/startup-delay.css');
server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(req.method==='POST'&&url.pathname==='/manage/contact/'){
    legacyPosts++;req.resume();res.writeHead(302,{Location:'/contact/'});res.end();return;
  }
  if(url.pathname.startsWith('/desktop/api/')){
    if(serviceFailed){res.writeHead(503);res.end('Unavailable');return;}
    if(url.pathname.endsWith('/logout/'))authenticated=false;
    if(url.pathname.endsWith('/login/'))authenticated=true;
    req.resume();res.setHeader('Content-Type','application/json');
    res.end(JSON.stringify({protocol:1,csrfToken:'fixture-only',authenticated,username:authenticated?'Debug':'',isAdmin:true,canManageApi:false,hasEmail:true}));return;
  }
  if(url.pathname==='/messages/unread/'){req.resume();res.setHeader('Content-Type','application/json');res.end('{"total":0}');return;}
  if(url.pathname.endsWith('-delay.css')){
    if(blocked.has(url.pathname))await blocked.get(url.pathname);
    res.setHeader('Content-Type','text/css');res.end('/* critical stylesheet prepared */');return;
  }
  if(url.pathname.startsWith('/static/')){
    const file=path.join(root,url.pathname.slice(1));if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'image/png');res.end(fs.readFileSync(file));return;
  }
  if(pageFailed){res.writeHead(500);res.end('Fixture error');return;}
  const fixture=url.pathname==='/manage/contact/'?'contact.html':url.pathname==='/account/forgot/'?'recovery-bound.html':'workspace.html';
  let html=fs.readFileSync(path.join(scratch,'render-pages',fixture),'utf8');
  const style=url.pathname==='/workspace/'?'/startup-delay.css':'/page-delay.css';
  html=html.replace('</head>','<link rel="stylesheet" href="'+style+'"></head>');
  res.setHeader('Content-Type','text/html; charset=utf-8');res.end(html);
});
server.listen(0,'127.0.0.1',async()=>{
  try{
    const origin='http://127.0.0.1:'+server.address().port;
    fs.writeFileSync(path.join(state,'server-connection.json'),JSON.stringify({mode:'remote',url:origin}));
    fs.writeFileSync(path.join(state,'appearance.json'),JSON.stringify({mode:'light',opacity:18,blur:4}));
    require('../main.cjs');
    await until('native UI',async()=>{win=BrowserWindow.getAllWindows()[0];return win&&!win.webContents.isLoading()&&await win.webContents.executeJavaScript('Boolean(window.desktop && window.updateInterfaceLoading)');});
    await until('authenticated startup pending',async()=>{const value=await info();return value.authenticated&&value.loading.phase==='loading';});
    const [business,account]=win.contentView.children;
    await until('local shell prepared',async()=>!(await info()).loading.full);
    await check('startup reveals account with fully prepared local navigation',()=>account.getVisible()&&!business.getVisible()&&win.webContents.executeJavaScript("getComputedStyle(document.querySelector('#workspace-sidebar')).display!=='none' && getComputedStyle(document.querySelector('.app-navigation')).visibility==='visible'"));
    await check('content shows themed logo without hiding prepared chrome',()=>win.webContents.executeJavaScript("!document.querySelector('#interface-loading').hidden && !document.body.classList.contains('interface-starting') && document.documentElement.dataset.theme==='light' && document.querySelector('#interface-loading').style.left==='248px'"));
    await wait(3200);
    await check('slow content loading explains the wait',()=>win.webContents.executeJavaScript("document.querySelector('#loading-message').textContent.includes('页面加载较慢')"));
    await wait(250);
    fs.writeFileSync(path.join(scratch,'loading-logo-light.png'),(await win.webContents.capturePage()).toPNG());
    releaseStartup();
    await until('first complete reveal',async()=>(await info()).loading.phase==='idle');
    await check('prepared content joins the existing native shell',()=>business.getVisible()&&account.getVisible());
    await check('server project data populates the local sidebar',()=>win.webContents.executeJavaScript("document.querySelector('#workspace-projects').textContent.includes('蛋白结构预测')"));
    await win.webContents.executeJavaScript("window.desktop.navigate('contact')");
    await until('contact page ready',async()=>(await info()).loading.phase==='idle'&&(await info()).current==='contact'&&business.webContents.getURL().endsWith('/manage/contact/'));
    const beforeSaveGeneration=(await info()).loading.generation;
    await business.webContents.executeJavaScript("document.querySelector('.form-card form').requestSubmit()");
    await until('legacy save restored',async()=>legacyPosts===1&&(await info()).loading.generation>beforeSaveGeneration&&(await info()).loading.phase==='idle'&&(await info()).current==='contact'&&business.webContents.getURL().endsWith('/manage/contact/'));
    await check('legacy save redirect stays inside workspace',()=>business.getVisible()&&external.length===0);
    await business.webContents.executeJavaScript("document.querySelector('.form-card [data-public-preview]').click()");
    await until('explicit preview opens outside',()=>external.length===1);
    await check('preview is explicit and preserves internal page',()=>external[0].endsWith('/public/members/')&&business.webContents.getURL().endsWith('/manage/contact/'));
    await business.webContents.executeJavaScript("const a=document.createElement('a');a.href='/contact/';document.body.append(a);a.click()");
    await wait(200);await check('ordinary visitor link cannot replace business page',()=>business.webContents.getURL().endsWith('/manage/contact/')&&external.length===1);
    await business.webContents.executeJavaScript("const recover=document.createElement('a');recover.href='/account/forgot/';document.body.append(recover);recover.click()");
    await until('signed-in recovery ready',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/account/forgot/'));
    await check('signed-in recovery retains settings layout',()=>business.webContents.executeJavaScript("Boolean(document.querySelector('.settings-content.recovery-content')) && !document.querySelector('.public-header') && document.documentElement.dataset.theme==='light'"));
    await win.webContents.executeJavaScript("window.desktop.navigateWorkspace('/workspace/')");
    await until('workspace after boundaries',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/workspace/'));
    await wait(250);
    const releasePage=hold('/page-delay.css');
    await win.webContents.executeJavaScript("window.desktop.navigateWorkspace('/projects/999/')");
    await until('page pending',async()=>(await info()).loading.phase==='loading');
    await wait(200);
    await check('later navigation retains account and fixed navigation',()=>account.getVisible()&&!business.getVisible()&&win.webContents.executeJavaScript("!document.body.classList.contains('interface-starting') && !document.querySelector('.app-navigation').hidden && getComputedStyle(document.querySelector('#workspace-sidebar')).display!=='none'"));
    await check('local sidebar reflects the pending destination immediately',async()=>(await info()).workspacePath==='/projects/999/');
    await win.webContents.executeJavaScript("window.desktop.saveAppearance({mode:'dark',opacity:18,blur:4})");
    await check('local theme updates while the remote document is blocked',()=>win.webContents.executeJavaScript("document.documentElement.dataset.theme==='dark'"));
    await check('loading background follows the dark preference',()=>win.webContents.executeJavaScript("getComputedStyle(document.querySelector('#interface-loading')).backgroundColor==='rgb(32, 32, 32)'"));
    await wait(250);
    fs.writeFileSync(path.join(scratch,'loading-logo-dark.png'),(await win.webContents.capturePage()).toPNG());
    await win.webContents.executeJavaScript("document.querySelector('[data-settings-section=appearance]').click()");
    await until('local settings open immediately',async()=>(await info()).current==='plugins'&&(await info()).loading.phase==='idle');
    await check('local appearance settings cancel remote loading without waiting',()=>!business.getVisible()&&account.getVisible()&&win.webContents.executeJavaScript("!document.querySelector('#plugins-page').hidden && document.querySelector('#interface-loading').hidden"));
    await win.webContents.executeJavaScript("window.desktop.navigateWorkspace('/projects/999/')");
    await until('return to pending content',async()=>(await info()).loading.phase==='loading');
    releasePage();
    await until('page reveal',async()=>(await info()).loading.phase==='idle');
    await check('completed page restores business content',()=>business.getVisible()&&account.getVisible());
    await win.webContents.executeJavaScript("window.desktop.navigateWorkspace('/projects/997/')");
    await until('second destination',async()=>(await info()).loading.phase==='idle');
    await win.webContents.executeJavaScript("window.desktop.window('back')");
    await until('back destination',async()=>(await info()).loading.phase==='idle');
    await check('back restores previous page with asynchronous preparation',async()=>(await info()).workspacePath==='/projects/999/');
    await win.webContents.executeJavaScript("window.desktop.window('back')");
    await until('back to local settings',async()=>(await info()).current==='plugins');
    await check('back does not append a duplicate history destination',async()=>(await info()).current==='plugins');
    await win.webContents.executeJavaScript("window.desktop.navigateWorkspace('/workspace/')");
    await until('workspace restored',async()=>(await info()).loading.phase==='idle');
    pageFailed=true;
    await business.webContents.loadURL(origin+'/projects/998/');
    await until('error message',async()=>(await info()).loading.phase==='error');
    await check('HTTP failure provides retry instead of showing a broken document',()=>!business.getVisible()&&win.webContents.executeJavaScript("!document.querySelector('#loading-actions').hidden && document.querySelector('#loading-message').textContent.includes('500')"));
    pageFailed=false;await win.webContents.executeJavaScript('window.desktop.retryLoading()');
    await until('retry completed',async()=>(await info()).loading.phase==='idle');
    await check('retry restores the requested page',()=>business.getVisible());
    await win.webContents.executeJavaScript('window.desktop.logout()');
    await until('logout ready',async()=>{const value=await info();return !value.authenticated&&value.loading.phase==='idle';});
    await check('logout leaves a complete login screen without account remnants',()=>!account.getVisible()&&!business.getVisible()&&win.webContents.executeJavaScript("!document.querySelector('#login-page').hidden && document.querySelector('#interface-loading').hidden"));
    const releaseLogin=hold('/startup-delay.css');
    const login=win.webContents.executeJavaScript("window.desktop.login({username:'Debug',password:'fixture-only'})");
    await until('login transition',async()=>{const value=await info();return value.authenticated&&value.loading.phase==='loading';});
    await until('login local shell',async()=>!(await info()).loading.full);
    await check('login permits prepared local UI while content waits',()=>account.getVisible()&&!business.getVisible());
    releaseLogin();await login;await until('login finished',async()=>(await info()).loading.phase==='idle');
    await win.webContents.executeJavaScript('window.desktop.logout()');
    await until('second logout',async()=>(await info()).loading.phase==='idle');
    serviceFailed=true;
    await win.webContents.executeJavaScript('window.desktop.saveConnection({mode:"remote",url:'+JSON.stringify(origin)+'})');
    await until('connection failure',async()=>(await info()).loading.phase==='error');
    await check('connection failure offers retry and connection settings',()=>win.webContents.executeJavaScript("!document.querySelector('#loading-actions').hidden && !document.querySelector('#loading-connection').hidden"));
    serviceFailed=false;authenticated=false;
    await win.webContents.executeJavaScript('window.desktop.retryLoading()');
    await until('connection recovered',async()=>(await info()).loading.phase==='idle');
    await check('connection retry recovers to login',()=>win.webContents.executeJavaScript("!document.querySelector('#login-page').hidden && document.querySelector('#interface-loading').hidden"));
    console.log('ALL_LOADING_CHECKS_PASSED');server.close();app.exit(0);
  }catch(error){console.error(error);if(win){console.error(JSON.stringify(await info()));for(const view of win.contentView.children)console.error(view.webContents.getURL());}server.close();app.exit(1);}
});
