// Run with Electron; exercise real sandboxed renderers against test-only pages.
const {app,BrowserWindow,ipcMain}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
const fixtures=path.join(root,'.test-scratch/render-pages');
app.setPath('userData',path.join(root,'.test-scratch/electron-renderer'));
app.disableHardwareAcceleration();
app.on('window-all-closed',()=>{});
let server,win,theme='light',posts=0;
const css=fs.readFileSync(path.join(root,'desktop/business.css'),'utf8');
const appearance=()=>({theme,wallpaper:'',opacity:18,blur:4});
const delay=()=>new Promise(resolve=>setTimeout(resolve,150));
async function result(label,expression){let value=false;for(let attempt=0;attempt<40;attempt++){await delay();value=await win.webContents.executeJavaScript(expression);if(value)break;}assert.equal(value,true,label);console.log('PASS:',label);}
app.whenReady().then(async()=>{
  for(const [name,contract] of [['profile.html','settings-content'],['recovery.html','verify-code'],['delete.html','data-confirm-delete']]) {
    const file=path.join(fixtures,name);assert.equal(fs.existsSync(file),true,'Run Django with WORKBENCH_CAPTURE_UI before UI checks: '+name);
    assert.ok(fs.readFileSync(file,'utf8').includes(contract),'Current fixture contract missing: '+name+' / '+contract);
  }
  server=http.createServer((req,res)=>{
    const location=new URL(req.url,'http://localhost');
    if(req.method==='POST'){
      // Background unread POSTs are not deletion submissions.
      if(location.pathname==='/delete')posts++;
      req.resume();
      if(location.pathname==='/save'){res.writeHead(302,{Location:'/profile-after-save'});res.end();return;}
      res.end('<p>Deleted</p>');return;
    }
    let file;
    if(location.pathname.startsWith('/static/'))file=path.join(root,location.pathname.slice(1));
    else file=path.join(fixtures,location.pathname.startsWith('/delete')?'delete.html':location.pathname.startsWith('/recovery')?'recovery.html':'profile.html');
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html; charset=utf-8');res.end(fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  ipcMain.handle('desktop:business-presentation',event=>{assert.equal(event.senderFrame,event.sender.mainFrame);return {css,settings:true,appearance:appearance(),generation:1};});
  win=new BrowserWindow({show:false,width:1100,height:800,webPreferences:{preload:path.join(root,'desktop/business-preload.cjs'),sandbox:true,contextIsolation:true}});
  let preloadError;
  win.webContents.on('preload-error',(_e,_file,error)=>{preloadError=error;});
  await win.loadURL(origin+'/profile');
  await result('profile uses full available width',"document.querySelector('.settings-content').getBoundingClientRect().width>600");
  await result('duplicate navigation is hidden',"getComputedStyle(document.querySelector('.global-topbar')).display==='none' && getComputedStyle(document.querySelector('.shell-sidebar')).display==='none'");
  await result('embedded theme matches desktop',"document.documentElement.dataset.theme==='light'");
  await win.loadURL(origin+'/save',{postData:[{type:'rawData',bytes:Buffer.from('action=profile')}],extraHeaders:'Content-Type: application/x-www-form-urlencoded'});
  await result('POST redirect preserves desktop layout and theme',"document.documentElement.dataset.theme==='light' && getComputedStyle(document.querySelector('.global-topbar')).display==='none' && document.querySelector('.settings-content').getBoundingClientRect().width>600");
  theme='dark';win.webContents.send('desktop:business-presentation',{css,settings:true,appearance:appearance(),generation:1});
  await result('theme changes apply immediately',"document.documentElement.dataset.theme==='dark'");
  assert.equal(preloadError,undefined,'sandboxed preload loaded');
  await win.loadURL(origin+'/recovery');
  await result('recovery page follows desktop dark theme',"document.documentElement.dataset.theme==='dark' && getComputedStyle(document.querySelector('input:not([type=hidden])')).color==='rgb(237, 237, 237)'");
  win.destroy();
  win=new BrowserWindow({show:false,width:390,height:760,useContentSize:true,webPreferences:{sandbox:true,contextIsolation:true}});
  await win.loadURL(origin+'/recovery');
  await result('390px phone has no horizontal overflow',"document.documentElement.scrollWidth<=window.innerWidth");
  await result('phone inputs are readable and buttons touch sized',"parseFloat(getComputedStyle(document.querySelector('input:not([type=hidden])')).fontSize)>=16 && document.querySelector('button').getBoundingClientRect().height>=44");
  win.setContentSize(360,500);
  await result('360px phone remains within viewport',"document.documentElement.scrollWidth<=window.innerWidth");
  await win.webContents.executeJavaScript("document.querySelector('.verify-code button[type=submit],.verify-code button:not([type])').scrollIntoView({block:'end'})");
  await result('submit can scroll above phone keyboard',"document.querySelector('.verify-code button[type=submit],.verify-code button:not([type])').getBoundingClientRect().bottom<=window.innerHeight+1");
  win.setContentSize(800,760);await win.loadURL(origin+'/delete');
  const before=posts;
  await win.webContents.executeJavaScript("document.querySelector('button[value=delete]').click()");
  await result('permanent deletion opens modal and defaults to cancel',"document.querySelector('.delete-confirm-dialog').open && document.activeElement.textContent==='取消'");
  await win.webContents.executeJavaScript("document.querySelector('.delete-confirm-dialog button').click()");
  await result('cancel closes the dialog',"!document.querySelector('.delete-confirm-dialog')");
  await win.webContents.executeJavaScript("fetch('/messages/unread/',{method:'POST'}).then(response=>response.text())");
  assert.equal(posts,before,'cancel does not submit');console.log('PASS: cancel never submits deletion');
  await win.webContents.executeJavaScript("document.querySelector('button[value=delete]').click()");
  await win.webContents.executeJavaScript("document.querySelector('.delete-confirm-dialog .danger').click()");
  for(let attempt=0;attempt<40&&posts<before+1;attempt++)await delay();
  assert.equal(posts,before+1,'confirmation submits once');console.log('PASS: confirmation submits deletion exactly once');
  win.destroy();
  let info={authenticated:false,backend:'ready',current:'login',requiresSetup:false,mode:'remote',
    connection:{url:origin},updates:{state:'disabled',message:'Debug'},gitEnabled:true,githubEnabled:true,aiEnabled:true,
    username:'',version:require('../package.json').version,dataPath:'test-only',appearance:{...appearance(),mode:'dark',hasWallpaper:false},needsEmailBinding:false};
  ipcMain.handle('desktop:info',()=>({ok:true,data:info}));
  ipcMain.handle('desktop:account-menu',()=>({ok:true,data:null}));
  win=new BrowserWindow({show:false,width:1100,height:800,webPreferences:{preload:path.join(root,'desktop/preload.cjs'),sandbox:true,contextIsolation:true}});
  await win.loadFile(path.join(root,'desktop/ui/index.html'));
  await result('desktop login label includes workbench ID and email',"document.querySelector('#login-username').labels[0].textContent.includes('工作台号或邮箱')");
  win.destroy();info={...info,authenticated:true,username:'dev',needsEmailBinding:true,accountMenuOpen:false};
  win=new BrowserWindow({show:false,width:248,height:70,webPreferences:{preload:path.join(root,'desktop/preload.cjs'),sandbox:true,contextIsolation:true}});
  await win.loadFile(path.join(root,'desktop/ui/account.html'));
  await result('missing email shows red dot',"document.querySelector('#email-dot').hidden===false");
  win.webContents.send('desktop:state',{...info,needsEmailBinding:false});
  await result('binding email clears red dot',"document.querySelector('#email-dot').hidden===true");
  win.destroy();server.close();console.log('ALL_PRESENTATION_CHECKS_PASSED');app.exit(0);
}).catch(error=>{console.error(error);if(win&&!win.isDestroyed())win.destroy();if(server)server.close();app.exit(1);});
