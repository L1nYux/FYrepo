const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch');
app.setPath('userData',path.join(scratch,'teams-ui-'+Date.now()));app.disableHardwareAcceleration();
app.on('window-all-closed',()=>{});
let server,win;
app.whenReady().then(async()=>{
  const fixture=path.join(scratch,'render-pages/teams.html');assert.ok(fs.existsSync(fixture),'Generate current Django team fixture first');
  server=http.createServer((request,response)=>{
    const url=new URL(request.url,'http://localhost');request.resume();
    if(url.pathname.startsWith('/static/')){
      const file=path.resolve(root,url.pathname.slice(1));
      if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){response.writeHead(404);response.end();return;}
      response.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'application/octet-stream');response.end(fs.readFileSync(file));return;
    }
    response.setHeader('Content-Type','text/html;charset=utf-8');response.end(fs.readFileSync(fixture));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  win=new BrowserWindow({show:false,width:1100,height:800,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
  const url='http://127.0.0.1:'+server.address().port+'/teams/';await win.loadURL(url);
  const result=await win.webContents.executeJavaScript(`(()=>{
    const forms=[...document.querySelectorAll('form')];
    return {title:document.querySelector('h1')?.textContent,
      create:forms.some(f=>f.action.endsWith('/teams/create/')&&f.querySelector('[name=name][required]')),
      join:forms.some(f=>f.action.endsWith('/teams/join/')&&f.querySelector('[name=code][required]')),
      teamNavigation:!!document.querySelector('a[href^="/projects/?ownership="]')&&!!document.querySelector('a[href^="/messages/teams/?team="]'),
      csrf:forms.every(f=>f.querySelector('[name=csrfmiddlewaretoken]')),
      privateAdmin:!!document.querySelector('a[href="/platform/"]')};})()`);
  assert.equal(result.title,'我的团队');assert.equal(result.create,true);assert.equal(result.join,true);
  assert.equal(result.teamNavigation,true);assert.equal(result.csrf,true);assert.equal(result.privateAdmin,false);
  win.setContentSize(390,760);await win.loadURL(url);
  assert.ok(await win.webContents.executeJavaScript('document.documentElement.scrollWidth<=window.innerWidth'),'mobile layout stays inside viewport');
  fs.writeFileSync(path.join(scratch,'teams-ui.png'),(await win.webContents.capturePage()).toPNG());
  console.log('ALL_TEAM_UI_CHECKS_PASSED 7');win.destroy();server.close();app.exit(0);
}).catch(error=>{console.error(error);if(win&&!win.isDestroyed())win.destroy();server?.close();app.exit(1);});
