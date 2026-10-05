const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch'),fixtures=path.join(scratch,'render-pages');
app.setPath('userData',path.join(scratch,'members-ui-'+Date.now()));app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
let server,win,checks=0;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms)),js=code=>win.webContents.executeJavaScript(code);
async function until(label,code){const deadline=Date.now()+10000;while(Date.now()<deadline){if(await js(code))return;await delay(40);}throw Error('Timed out: '+label);}
async function check(label,code){await until(label,code);checks++;console.log('PASS:',label);}
async function capture(name){await delay(100);fs.writeFileSync(path.join(scratch,name+'.png'),(await win.webContents.capturePage()).toPNG());}
app.whenReady().then(async()=>{
  const pages={'/workspace/':'navigation-announcements.html','/manage/members/':'member-directory.html','/member-delete/':'member-delete.html','/member-reset/':'member-reset.html','/member-temporary/':'member-temporary.html','/account/set-password/':'member-required-password.html'};
  for(const file of Object.values(pages))assert.ok(fs.existsSync(path.join(fixtures,file)),'Django fixture missing: '+file);
  server=http.createServer((req,res)=>{
    const url=new URL(req.url,'http://localhost');req.resume();
    const json=value=>{res.setHeader('content-type','application/json');res.end(JSON.stringify(value));};
    if(/^\/members\/\d+\/card\/$/.test(url.pathname)){json({id:2,username:'directory-member',display_name:'公开昵称',name:'实验成员',initial:'实',role:'开发者',active:true,research_area:'机器学习',bio:'公开简介',projects:[{name:'资料库项目',url:'/projects/1/'}],manage_url:'/manage/members/?q=directory-member',chat_url:'/messages/to/2/',avatar_url:''});return;}
    if(url.pathname==='/messages/unread/'){json({total:0,presence:{},channels:{},muted_channels:[],hidden_channels:[]});return;}
    const file=url.pathname.startsWith('/static/')?path.join(root,url.pathname.slice(1)):path.join(fixtures,pages[url.pathname]||'member-directory.html');
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('content-type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');res.end(fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
  win=new BrowserWindow({show:false,width:1100,height:850,useContentSize:true,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
  await win.loadURL(origin+'/workspace/');await js("document.documentElement.dataset.theme='light'");
  await check('expanded web navigation is compact and labels readable',"(()=>{const bar=document.querySelector('.shell-sidebar'),item=document.querySelector('.shell-nav-item');return Math.round(bar.getBoundingClientRect().width)===232&&parseFloat(getComputedStyle(item).fontSize)>=14&&document.querySelector('[data-sidebar-collapse]').getAttribute('aria-expanded')==='true'})()");
  const before=await js("document.querySelector('.shell-main').getBoundingClientRect().width");
  await check('announcement cards have 20px breathing room and 24px padding',"(()=>{const cards=document.querySelectorAll('.announcement-card');return cards.length>=2&&Math.round(cards[1].getBoundingClientRect().top-cards[0].getBoundingClientRect().bottom)===20&&getComputedStyle(cards[0]).padding==='24px'&&getComputedStyle(cards[0]).boxShadow==='none'})()");
  await capture('workspace-expanded-light');await js("document.querySelector('[data-sidebar-collapse]').click()");
  await check('collapsed navigation shows centered icons and tooltips',"(()=>{const bar=document.querySelector('.shell-sidebar'),item=document.querySelector('.shell-nav-item'),icon=item.querySelector('.nav-glyph');return Math.round(bar.getBoundingClientRect().width)===68&&getComputedStyle(item.querySelector('.nav-label')).display==='none'&&getComputedStyle(document.querySelector('.sidebar-projects')).display==='none'&&item.title==='公告栏'&&Math.abs(icon.getBoundingClientRect().left+icon.getBoundingClientRect().width/2-bar.getBoundingClientRect().width/2)<2})()");
  assert.ok(await js("document.querySelector('.shell-main').getBoundingClientRect().width")>before+150,'main grows when sidebar collapses');checks++;console.log('PASS: main content gains the released width');
  await capture('workspace-collapsed-light');const reloaded=new Promise(resolve=>win.webContents.once('did-finish-load',resolve));win.reload();await reloaded;
  await check('sidebar remembers collapsed state after reload',"document.documentElement.dataset.sidebarCollapsed==='true'&&document.querySelector('[data-sidebar-collapse]').getAttribute('aria-expanded')==='false'");
  await win.loadURL(origin+'/manage/members/');
  await check('directory presents searchable member cards and admin actions',"Boolean(document.querySelector('.member-search input[type=search]'))&&document.querySelectorAll('.member-directory-card').length>=3&&document.body.textContent.includes('重置密码')");
  await js("document.querySelector('.member-name[data-member-id=\"2\"]').click()");
  await check('profile card is styled outside the chat page',"(()=>{const card=document.querySelector('.member-card-dialog');return card.open&&card.textContent.includes('公开简介')&&card.querySelector('.member-card-header .user-avatar').getBoundingClientRect().width===64&&parseFloat(getComputedStyle(card).borderRadius)>=12&&card.querySelector('.member-card-footer a').getAttribute('href')==='/messages/to/2/'})()");
  await js("document.documentElement.dataset.theme='light'");await capture('member-card-light');
  await js("document.documentElement.dataset.theme='dark'");
  await check('profile card follows dark theme',"getComputedStyle(document.querySelector('.member-card-dialog')).backgroundColor==='rgb(40, 40, 40)'");await capture('member-card-dark');
  await js("document.querySelector('.member-card-close').click()");
  await check('profile close button dismisses dialog',"!document.querySelector('.member-card-dialog').open");
  await win.loadURL(origin+'/member-delete/');
  await check('delete confirmation shows responsibility handoff and exact-name field',"Boolean(document.querySelector('#member-successor[required]'))&&Boolean(document.querySelector('#confirm-username[required]'))&&document.body.textContent.includes('接任任务')");
  await win.loadURL(origin+'/member-temporary/');
  await check('temporary password is readonly and can be copied',"document.querySelector('#temporary-password').readOnly&&Boolean(document.querySelector('[data-copy-temporary]'))&&document.body.textContent.includes('24 小时')");
  await win.loadURL(origin+'/account/set-password/');
  await check('mandatory password change form uses two new-password fields',"Boolean(document.querySelector('[name=new_password1]'))&&Boolean(document.querySelector('[name=new_password2]'))");
  win.setContentSize(390,760);await win.loadURL(origin+'/manage/members/');
  await check('phone directory stays within viewport',"document.documentElement.scrollWidth<=window.innerWidth");
  console.log('ALL_MEMBER_UI_CHECKS_PASSED',checks);win.destroy();server.close();app.exit(0);
}).catch(error=>{console.error(error);if(win&&!win.isDestroyed())win.destroy();if(server)server.close();app.exit(1);});
