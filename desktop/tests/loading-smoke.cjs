// Run the real main process and all three sandboxed renderers against a local fixture server.
const {app,BrowserWindow,shell,dialog}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch');
const state=path.join(scratch,'loading-client-'+Date.now());
fs.mkdirSync(state,{recursive:true});process.env.WORKBENCH_DESKTOP_STATE=state;
app.disableHardwareAcceleration();
// Keep debug windows hidden; production main code and IPC remain unchanged.
app.on('browser-window-created',(_event,window)=>{window.show=()=>{};window.focus=()=>{};});
let win,server,authenticated=true,needsTeam=false,mustChangePassword=false,serviceFailed=false,pageFailed=false,blocked=new Map(),legacyTeam=false,spaceSupport=false;
const external=[];shell.openExternal=async url=>{external.push(url);};let legacyPosts=0;
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(label,fn){const deadline=Date.now()+15000;while(Date.now()<deadline){if(await fn())return;await wait(50);}throw Error('Timed out: '+label);}
async function info(){const result=await win.webContents.executeJavaScript('window.desktop.info()');assert.equal(result.ok,true);return result.data;}
async function check(label,fn){assert.equal(await fn(),true,label);console.log('PASS:',label);}
function hold(name){let release;const ready=new Promise(resolve=>release=resolve);blocked.set(name,ready);return ()=>{blocked.delete(name);release();};}
const releaseStartup=hold('/startup-delay.css');
let fixtureUpdates,updateChecks=0,updateInstalls=0;
class FixtureUpdates{
 constructor(app,publish){fixtureUpdates=this;this.publish=publish;this.value={state:'idle',version:app.getVersion(),message:'检查应用更新'};}
 snapshot(){return {...this.value};}start(){}stop(){}
 set(value){this.value={...this.value,...value};this.publish(this.snapshot());}
 async check(){updateChecks++;this.set({state:'available',nextVersion:'0.3.0',size_bytes:12345678,release:{version:'0.3.0',features:[{title:'搜索来源',description:'新来源侧栏',path:'/assistant/'}],fixes:['修复展示']},message:'有新版本'});return this.snapshot();}
 async download(){this.set({state:'downloading',percent:45,message:'正在下载更新 45%'});await wait(150);this.set({state:'downloaded',nextVersion:'0.3.0',message:'更新已下载'});return this.snapshot();}
 async install(){updateInstalls++;}
}
require.cache[require.resolve('../updates.cjs')]={exports:{Updates:FixtureUpdates}};
const browserModule=require('../public-browser.cjs');
class FixtureBrowser extends browserModule.PublicBrowser {
  constructor(...args){super(...args);this.contents.session.protocol.handle('https',()=>new Response('<title>Fixture web source</title><h1>Public page</h1>',{headers:{'Content-Type':'text/html'}}));}
}
require.cache[require.resolve('../public-browser.cjs')].exports={...browserModule,PublicBrowser:FixtureBrowser};
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
    res.end(JSON.stringify({protocol:1,csrfToken:'fixture-only',authenticated,username:authenticated?'Debug':'',isAdmin:true,canManageApi:false,hasEmail:true,mustChangePassword,needsTeam,teamId:legacyTeam?7:null,teamName:legacyTeam?'Fixture team':'',...(spaceSupport?{teamId:null,spaceId:77,spaceKind:'personal',spaceName:'个人空间',spaces:[{id:'personal',name:'个人空间'},{id:'7',name:'Fixture team'}]}:{})}));return;
  }
  if(url.pathname==='/account/set-password/'&&req.method==='POST'){mustChangePassword=false;req.resume();res.writeHead(302,{Location:'/workspace/'});res.end();return;}
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
  const fixture=url.pathname==='/account/set-password/'?'member-required-password.html':url.pathname==='/manage/contact/'?'contact.html':url.pathname==='/account/forgot/'?'recovery-bound.html':/^\/messages\/(?:to\/\d+\/)?$/.test(url.pathname)?'conversations.html':url.pathname==='/messages/social/'?'community-social.html':url.pathname==='/assistant/'?'assistant.html':'workspace.html';
  let html=fs.readFileSync(path.join(scratch,'render-pages',fixture),'utf8');
  if(spaceSupport||legacyTeam){const spaces=spaceSupport?[{id:'77',name:'个人空间'},{id:'7',name:'Fixture team'}]:[{id:'7',name:'Fixture team'}];html=html.replace(/(<script[^>]+id="resource-space-options"[^>]*>)[\s\S]*?(<\/script>)/,'$1'+JSON.stringify(spaces)+'$2');}
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
    await check('content shows themed logo without hiding prepared chrome',()=>win.webContents.executeJavaScript("!document.querySelector('#interface-loading').hidden && !document.body.classList.contains('interface-starting') && document.documentElement.dataset.theme==='light' && document.querySelector('#interface-loading').style.left==='232px'"));
    await wait(3200);
    await check('slow content loading explains the wait',()=>win.webContents.executeJavaScript("document.querySelector('#loading-message').textContent.includes('页面加载较慢')"));
    await wait(250);
    fs.writeFileSync(path.join(scratch,'loading-logo-light.png'),(await win.webContents.capturePage()).toPNG());
    releaseStartup();
    await until('first complete reveal',async()=>(await info()).loading.phase==='idle');
    await check('prepared content joins the existing native shell',()=>business.getVisible()&&account.getVisible());
    await check('server project data populates the local sidebar',()=>win.webContents.executeJavaScript("document.querySelector('#workspace-projects').textContent.includes('蛋白结构预测')"));
    await win.webContents.executeJavaScript("document.querySelector('[data-workspace-path=\"/sampling/\"]').click()");
    await until('sampling entry joins workspace navigation',async()=>(await info()).current==='workspace'&&(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/sampling/'));
    await check('sampling has one selected native entry',()=>win.webContents.executeJavaScript("document.querySelector('[data-workspace-path=\"/sampling/\"]').getAttribute('aria-current')==='page'"));
    await win.webContents.executeJavaScript("window.desktop.usageOpen()");
    await until('account usage opens team API',async()=>{const value=await info();return value.current==='usage'&&value.loading.phase==='idle'&&business.webContents.getURL().includes('/api-pool/');});
    await check('account usage selects the AI area',()=>win.webContents.executeJavaScript("document.querySelectorAll('.app-tabs [aria-current=page]').length===1&&document.querySelector('.app-tabs [data-page=ai]').getAttribute('aria-current')==='page'&&document.querySelector('#workspace-sidebar').hidden"));
    await win.webContents.executeJavaScript("window.desktop.navigateWorkspace('/workspace/')");
    await until('workspace restored after usage',async()=>(await info()).current==='workspace'&&(await info()).loading.phase==='idle');
    await win.webContents.executeJavaScript("document.querySelector('#workspace-collapse').click()");
    await until('native sidebar collapsed',async()=>business.getBounds().x===68&&await win.webContents.executeJavaScript("Math.round(document.querySelector('#workspace-sidebar').getBoundingClientRect().width)===68"));
    await check('native content and account follow collapsed sidebar width',()=>business.getBounds().x===68&&account.getBounds().width===68&&account.getBounds().height===116);
    await check('collapsed preference is persisted',()=>JSON.parse(fs.readFileSync(path.join(state,'connections.json'),'utf8')).workspaceCollapsed===true);
    await check('collapsed native labels and project list are hidden',()=>win.webContents.executeJavaScript("getComputedStyle(document.querySelector('.workspace-nav-label')).display==='none'&&getComputedStyle(document.querySelector('#workspace-projects')).display==='none'&&document.querySelector('[data-workspace-path]').title==='概览'"));
    await account.webContents.executeJavaScript("document.querySelector('summary').click()");
    await until('collapsed account menu opens',async()=>(await info()).accountMenuOpen);
    await check('account menu stays readable from a collapsed sidebar',()=>account.getBounds().width===232);
    await account.webContents.executeJavaScript("document.querySelector('summary').click()");
    await win.webContents.executeJavaScript("document.querySelector('#workspace-collapse').click()");
    await until('native sidebar expanded',async()=>business.getBounds().x===232&&await win.webContents.executeJavaScript("Math.round(document.querySelector('#workspace-sidebar').getBoundingClientRect().width)===232"));
    await check('expanding restores content and account bounds',()=>account.getBounds().width===232&&account.getBounds().height===68);
    await win.webContents.executeJavaScript("window.desktop.navigate('contact')");
    await until('contact page ready',async()=>(await info()).loading.phase==='idle'&&(await info()).current==='workspace'&&business.webContents.getURL().endsWith('/manage/contact/'));
    const beforeSaveGeneration=(await info()).loading.generation;
    await business.webContents.executeJavaScript("document.querySelector('.form-card form').requestSubmit()");
    await until('legacy save restored',async()=>legacyPosts===1&&(await info()).loading.generation>beforeSaveGeneration&&(await info()).loading.phase==='idle'&&(await info()).current==='workspace'&&business.webContents.getURL().endsWith('/manage/contact/'));
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
    await win.webContents.executeJavaScript("window.desktop.navigate('messages')");
    await until('messages ready',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/messages/social/'));
    await check('native messages fill content height without top blank area',()=>business.webContents.executeJavaScript("document.querySelector('.messages-layout').getBoundingClientRect().top===0 && Math.abs(document.querySelector('.messages-layout').getBoundingClientRect().height-innerHeight)<2"));
    await check('native account footer matches the conversation rail',()=>account.webContents.executeJavaScript("getComputedStyle(document.querySelector('details')).backgroundColor==='rgb(29, 29, 29)'"));
    await business.webContents.loadURL(origin+'/messages/to/12/');await until('private conversation remembered',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/messages/to/12/'));
    await business.webContents.loadURL(origin+'/messages/social/?tab=friends');
    await until('contacts remain in messages',async()=>(await info()).loading.phase==='idle'&&(await info()).current==='messages');
    await win.webContents.executeJavaScript("window.desktop.navigate('messages')");
    await until('contacts do not replace conversation',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/messages/to/12/'));
    await win.webContents.executeJavaScript("window.desktop.navigate('ai')");await until('assistant ready',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/assistant/'));
    await business.webContents.executeJavaScript("document.querySelector('#assistant-input').value='preserved browser draft';window.workbenchBrowser.open('https://example.org/')");
    await until('browser opens inside originating section',()=>win.webContents.executeJavaScript("!document.querySelector('#browser-header').hidden"));
    await until('public source actually loads with localized application name',()=>win.webContents.executeJavaScript("document.querySelector('#browser-title').textContent==='Fixture web source'"));
    await win.webContents.executeJavaScript("window.desktop.browserAction('toggle-composer')");
    await until('AI composer hidden in browser mode',()=>business.webContents.executeJavaScript("getComputedStyle(document.querySelector('#assistant-form')).display==='none'"));
    await win.webContents.executeJavaScript("window.desktop.browserAction('close')");
    await until('closing browser restores composer',()=>business.webContents.executeJavaScript("getComputedStyle(document.querySelector('#assistant-form')).display!=='none'&&document.querySelector('#assistant-input').value==='preserved browser draft'"));
    await business.webContents.executeJavaScript("window.workbenchBrowser.open('https://example.org/')");
    await win.webContents.executeJavaScript("window.desktop.navigate('workspace')");
    await until('workbench tab returns home and removes browser',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/workspace/')&&await win.webContents.executeJavaScript("document.querySelector('#browser-header').hidden"));
    await check('browser cannot cover another top navigation section',()=>Promise.resolve(true));
    await win.webContents.executeJavaScript("window.desktop.navigate('ai')");await until('assistant returns after browser ownership',async()=>(await info()).loading.phase==='idle');
    await business.webContents.executeJavaScript("const source=document.createElement('a');source.href='/messages/references/announcement/1/';document.body.append(source);source.click()");
    await until('reference opened',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/messages/references/announcement/1/'));
    await win.webContents.executeJavaScript("window.desktop.navigate('messages')");
    await until('message tab restores chat not announcement',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/messages/to/12/'));
    await check('AI source navigation cannot replace the messages destination',()=>business.webContents.executeJavaScript("Boolean(document.querySelector('.conversation-main'))"));
    await account.webContents.executeJavaScript("document.querySelector('#avatar-update').click()");
    await until('update details before download',()=>win.webContents.executeJavaScript("document.querySelector('#application-update-dialog').open && !document.querySelector('[data-update-download]').hidden && document.querySelector('[data-update-size]').textContent.includes('MB') && document.querySelector('[data-update-features]').textContent.includes('搜索来源')"));
    await check('update modal is centered and hides native business views',()=>!business.getVisible()&&!account.getVisible()&&win.webContents.executeJavaScript("document.querySelector('#application-update-dialog').getBoundingClientRect().width>=600"));
    await check('update requires confirmation before downloading',()=>Promise.resolve(fixtureUpdates.snapshot().state==='available'));
    await win.webContents.executeJavaScript("document.querySelector('[data-update-download]').click()");
    await until('outer button progress visible',()=>account.webContents.executeJavaScript("!document.querySelector('#update-percent').hidden && document.querySelector('#update-percent').textContent==='45%'"));
    await until('update readiness rendered',()=>account.webContents.executeJavaScript("!document.querySelector('#update-dot').hidden && document.querySelector('#update-label').textContent==='安装'"));
    await check('avatar update entry shows download readiness without restarting',()=>account.webContents.executeJavaScript("!document.querySelector('#update-dot').hidden && document.querySelector('#update-label').textContent==='安装'"));
    await win.webContents.executeJavaScript("document.querySelector('[data-update-close]').click()");
    await until('closing update restores original page',()=>business.getVisible()&&account.getVisible());
    assert.equal(updateChecks,1);assert.equal(updateInstalls,0);
    const realDialog=dialog.showMessageBox;dialog.showMessageBox=async()=>({response:1});
    await account.webContents.executeJavaScript('window.desktop.installUpdate()');assert.equal(updateInstalls,0);
    dialog.showMessageBox=async()=>({response:0});
    await account.webContents.executeJavaScript('window.desktop.installUpdate()');assert.equal(updateInstalls,1);dialog.showMessageBox=realDialog;
    await check('cancelled update does not install and confirmed update invokes the installer',()=>Promise.resolve(updateInstalls===1));
    await check('update state reaches the main settings renderer too',()=>win.webContents.executeJavaScript("!document.querySelector('#update-install').hidden"));
    fixtureUpdates.set({state:'error',message:'更新失败，请重试'});
    await check('failed update keeps the avatar retry entry available',()=>account.webContents.executeJavaScript("!document.querySelector('#avatar-update').disabled && document.querySelector('#avatar-update').getAttribute('aria-label').includes('重试')"));
    // Repository actions use disposable fixture directories only.
    const repositoryFixture=fs.mkdtempSync(path.join(app.getPath('temp'),'workbench-repository-ui-'));const first=path.join(repositoryFixture,'files-a'),second=path.join(repositoryFixture,'files-b');fs.mkdirSync(first);fs.mkdirSync(second);
    const oldSave=dialog.showSaveDialog,oldOpen=dialog.showOpenDialog,oldTrash=shell.trashItem,oldConfirm=dialog.showMessageBox;
    dialog.showSaveDialog=async()=>({canceled:false,filePath:path.join(first,'draft.md')});
    const created=await win.webContents.executeJavaScript('window.desktop.repoNewFile()');assert.equal(created.ok,true);
    await check('a file can be created before choosing any repository',()=>Promise.resolve(fs.existsSync(path.join(first,'draft.md'))));
    dialog.showOpenDialog=async()=>({canceled:false,filePaths:[second]});
    const opened=await win.webContents.executeJavaScript('window.desktop.repoChoose()');assert.equal(opened.ok,true);
    let registry=await win.webContents.executeJavaScript('window.desktop.repoList()');assert.equal(registry.data.items.length,2);
    const switched=await win.webContents.executeJavaScript('window.desktop.repoSelect('+JSON.stringify(first)+')');assert.equal(switched.ok,true);
    await check('multiple folders can be opened and switched',()=>Promise.resolve(switched.data.path===fs.realpathSync(first)));
    const before=await win.webContents.executeJavaScript('window.desktop.repoRead("draft.md")');
    const draft={...before.data,text:'unsaved fixture draft'};
    await win.webContents.executeJavaScript('window.desktop.repoDraft('+JSON.stringify(draft)+')');
    dialog.showMessageBox=async()=>({response:2}); // Cancel the unsaved editor prompt.
    const cancelled=await win.webContents.executeJavaScript('window.desktop.repoSelect('+JSON.stringify(second)+')');
    assert.equal(cancelled.data,null);assert.equal((await win.webContents.executeJavaScript('window.desktop.repoStatus()')).data.path,fs.realpathSync(first));
    await check('cancel switching keeps the current draft and repository',()=>Promise.resolve(true));
    dialog.showMessageBox=async()=>({response:1}); // Discard fixture draft, then remove from list.
    await win.webContents.executeJavaScript('window.desktop.repoRemove('+JSON.stringify(second)+',false)');
    await check('closing a repository leaves its files on disk',()=>Promise.resolve(fs.existsSync(second)));
    let trashed='';shell.trashItem=async target=>{trashed=target;};
    await win.webContents.executeJavaScript('window.desktop.repoRemove('+JSON.stringify(first)+',true)');
    await check('confirmed deletion targets only the selected directory and uses trash',()=>Promise.resolve(trashed===fs.realpathSync(first)));
    const empty=await win.webContents.executeJavaScript('window.desktop.repoStatus()');assert.equal(empty.data.empty,true);
    dialog.showSaveDialog=oldSave;dialog.showOpenDialog=oldOpen;shell.trashItem=oldTrash;dialog.showMessageBox=oldConfirm;
    if(path.resolve(repositoryFixture).startsWith(path.resolve(app.getPath('temp'))+path.sep)&&path.basename(repositoryFixture).startsWith('workbench-repository-ui-'))fs.rmSync(repositoryFixture,{recursive:true,force:true});
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
    mustChangePassword=true;await win.webContents.executeJavaScript("window.desktop.login({username:'Debug',password:'fixture-only',remember:'1'})");
    await until('mandatory password page ready',async()=>(await info()).current==='security'&&(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/account/set-password/'));
    await check('temporary login cannot open local repositories',async()=>(await win.webContents.executeJavaScript("window.desktop.repoStatus()")).ok===false);
    await check('mandatory password change disables application tabs',()=>win.webContents.executeJavaScript("[...document.querySelectorAll('.app-tabs [data-page]')].every(button=>button.disabled)"));
    await business.webContents.executeJavaScript("document.querySelector('[name=new_password1]').value='different-Q5-pass';document.querySelector('[name=new_password2]').value='different-Q5-pass';document.querySelector('[name=new_password1]').closest('form').requestSubmit()");
    await until('mandatory change releases workspace',async()=>(await info()).current==='workspace'&&(await info()).loading.phase==='idle'&&!(await info()).mustChangePassword);
    await check('successful mandatory change reenables navigation',()=>win.webContents.executeJavaScript("[...document.querySelectorAll('.app-tabs [data-page]')].every(button=>!button.disabled)"));
    await win.webContents.executeJavaScript('window.desktop.logout()');
    await until('logout after mandatory change',async()=>(await info()).loading.phase==='idle');
    serviceFailed=true;
    await win.webContents.executeJavaScript('window.desktop.saveConnection({mode:"remote",url:'+JSON.stringify(origin)+'})');
    await until('connection failure',async()=>(await info()).loading.phase==='error');
    await check('connection failure offers retry and connection settings',()=>win.webContents.executeJavaScript("!document.querySelector('#loading-actions').hidden && !document.querySelector('#loading-connection').hidden"));
    serviceFailed=false;authenticated=false;
    await win.webContents.executeJavaScript('window.desktop.retryLoading()');
    await until('connection recovered',async()=>(await info()).loading.phase==='idle');
    await check('connection retry recovers to login',()=>win.webContents.executeJavaScript("!document.querySelector('#login-page').hidden && document.querySelector('#interface-loading').hidden"));
    needsTeam=true;
    await win.webContents.executeJavaScript("window.desktop.login({username:'Debug',password:'fixture-only'})");
    await until('teamless login',async()=>(await info()).loading.phase==='idle'&&(await info()).needsTeam);
    assert.equal((await win.webContents.executeJavaScript("window.desktop.navigateWorkspace('/team-square/')")).ok,true);
    await until('teamless square',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/team-square/'));
    assert.equal((await win.webContents.executeJavaScript("window.desktop.navigate('messages')")).ok,true);
    await until('teamless personal inbox',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/messages/social/'));
    await check('teamless members can open AI joining guidance while team projects stay blocked',async()=>
      (await win.webContents.executeJavaScript("window.desktop.navigate('ai')")).ok===true&&
      (await win.webContents.executeJavaScript("window.desktop.navigateWorkspace('/projects/1/')")).ok===false);
    needsTeam=false;legacyTeam=true;
    await win.webContents.executeJavaScript('window.desktop.logout()');
    await until('compatibility logout',async()=>!(await info()).authenticated&&(await info()).loading.phase==='idle');
    await win.webContents.executeJavaScript("window.desktop.login({username:'Debug',password:'fixture-only'})");
    await until('legacy team restored',async()=>(await info()).loading.phase==='idle'&&(await info()).teamId===7);
    await check('old server retains its current team without a false personal switch',()=>win.webContents.executeJavaScript("document.querySelector('#workspace-space-select').value==='all'&&!document.querySelector('#workspace-team-manage')&&!document.querySelector('#workspace-team-members')&&document.querySelector('#workspace-space-select').options.length===2"));
    spaceSupport=true;
    await win.webContents.executeJavaScript('window.desktop.logout()');
    await until('workspace protocol logout',async()=>!(await info()).authenticated&&(await info()).loading.phase==='idle');
    await win.webContents.executeJavaScript("window.desktop.login({username:'Debug',password:'fixture-only'})");
    await until('personal space restored',async()=>(await info()).loading.phase==='idle'&&(await info()).spaceId===77);
    await check('new server exposes personal and team ownership in one resource filter',()=>win.webContents.executeJavaScript("document.querySelector('#workspace-space-select').value==='all'&&!document.querySelector('#workspace-space-select').disabled&&document.querySelector('#workspace-space-select').options.length===3"));
    await win.webContents.executeJavaScript("window.desktop.navigateWorkspace('/sampling/')");
    await until('sampling under new ownership protocol',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/sampling/'));
    await win.webContents.executeJavaScript("const select=document.querySelector('#workspace-space-select');select.value='77';select.dispatchEvent(new Event('change'));");
    await until('sampling ownership filter updates server page',async()=>(await info()).loading.phase==='idle'&&business.webContents.getURL().endsWith('/sampling/?ownership=77'));
    await check('sampling preserves its native ownership filter',()=>win.webContents.executeJavaScript("document.querySelector('#workspace-space-select').value==='77'&&document.querySelector('[data-workspace-path=\"/sampling/\"]').getAttribute('aria-current')==='page'"));
    console.log('ALL_LOADING_CHECKS_PASSED');server.close();app.exit(0);
  }catch(error){console.error(error);if(win){console.error(JSON.stringify(await info()));for(const view of win.contentView.children)console.error(view.webContents.getURL());}server.close();app.exit(1);}
});
