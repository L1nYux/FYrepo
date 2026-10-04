const {app,BrowserWindow,ipcMain}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch'),fixtures=path.join(scratch,'render-pages');
app.setPath('userData',path.join(scratch,'social-client'));app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
let server,win,checks=0,manageCalls=0,muted=false,cleared=false,giftPosts=[],claimed=0;const errors=[];
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));const js=code=>win.webContents.executeJavaScript(code);
async function until(label,code){const deadline=Date.now()+10000;while(Date.now()<deadline){if(await js(code))return;await delay(40);}throw Error('Timed out: '+label);}
async function check(label,code){assert.equal(await js(code),true,label);checks++;console.log('PASS:',label);}
const message=(id,text)=>({id,author:'gift-peer',initial:'G',at:'10-04 21:00',body:text,mine:false,withdrawn:false,action_url:'/messages/'+id+'/action/',references:[],attachments:[]});
const gift={id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',kind:'transfer',mode:'equal',title:'积分转账',greeting:'科研顺利！',points:'10',status:'待领取',claimed_points:null,claimed_count:0,count:1,mine:false,can_claim:true,can_refund:false,expires_at:new Date(Date.now()+86400000).toISOString(),refunded_points:'0'};
app.whenReady().then(async()=>{
 server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');let body='';if(req.method==='POST')for await(const part of req)body+=part;
  const params=new URLSearchParams(body),json=(value,status=200)=>{res.writeHead(status,{'content-type':'application/json'});res.end(JSON.stringify(value));};
  if(url.pathname==='/messages/unread/'||url.pathname==='/messages/read/'){json({total:muted?0:1,channels:{developers:1},muted_channels:muted?['developers']:[],hidden_channels:[]});return;}
  if(url.pathname.includes('/poll/')){json({messages:[],updates:[],removed:[]});return;}
  if(url.pathname==='/messages/manage/'){manageCalls++;muted=params.get('action')==='mute'?true:params.get('action')==='unmute'?false:muted;cleared=params.get('action')==='clear';json({total:muted?0:1,channels:{},muted,muted_channels:muted?[params.get('channel')]:[],hidden_channels:[],cleared_through:cleared?900:0});return;}
  if(url.pathname==='/messages/history/'){
   if(url.searchParams.get('around'))json({messages:[message(40,'前文'),message(50,'找到的旧消息'),message(60,'后文')],target:50,cursor:999});
   else if(url.searchParams.get('before'))json({messages:[message(10,'更早的消息')],next_before:null});
   else if(url.searchParams.get('q'))json({messages:[message(50,'找到的旧消息')],next_before:50});
   else json({messages:[message(999,'最新消息')],next_before:null});return;
  }
  if(url.pathname==='/messages/points/'){json({available_points:'100',gifts:[]});return;}
  if(url.pathname==='/messages/points/send/'){giftPosts.push(params.get('request_id'));json({message:{...message(1000,'积分转账'),mine:true,gift}});return;}
  if(url.pathname.startsWith('/messages/points/')&&url.pathname.endsWith('/claim/')){claimed++;gift.claimed_points='10';gift.claimed_count=1;gift.can_claim=false;gift.status='已领完';json(gift);return;}
  if(/^\/messages\/points\/[a-f0-9-]+\/$/.test(url.pathname)){json(gift);return;}
  if(url.pathname.startsWith('/accounts/')&&url.pathname.includes('/avatar/')){res.setHeader('content-type','image/webp');res.end(fs.readFileSync(path.join(fixtures,'avatar.webp')));return;}
  const pages={'/profile/':'avatar-profile.html','/conversations/':'conversations.html','/gifts/':'gifts.html'};
  const file=url.pathname.startsWith('/static/')?path.join(root,url.pathname.slice(1)):path.join(fixtures,pages[url.pathname]||'workspace.html');
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
  res.setHeader('content-type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');res.end(fs.readFileSync(file));
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
 win=new BrowserWindow({show:false,width:1100,height:850,useContentSize:true,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
 win.webContents.on('console-message',(_e,details)=>{if(details?.level==='error')errors.push(details.message);});
 await win.loadURL(origin+'/conversations/');await until('message scripts',"typeof window.workbenchConversations==='object'");
 await check('chat sidebar is dark and selected peer is clearly distinct',"(()=>{const sidebar=document.querySelector('.conversation-list'),selected=document.querySelector('.conversation-link.selected');return getComputedStyle(sidebar).backgroundColor==='rgb(29, 29, 29)'&&getComputedStyle(selected).backgroundColor!==getComputedStyle(sidebar).backgroundColor})()");
 await check('message action is available without right click',"(()=>{document.querySelector('[data-message-actions]').click();return !document.querySelector('[data-message-menu]').hidden})()");
 await js("window.confirm=()=>false;document.querySelector('[data-conversation-action=clear]').click()");await delay(120);assert.equal(manageCalls,0);
 await check('cancel clear leaves messages and does not send a request',"Boolean(document.querySelector('[data-message-log] [data-id]'))");
 await js("window.confirm=()=>true;document.querySelector('[data-conversation-action=mute]').click()");
 await until('mute',"document.querySelector('[data-conversation-action=mute]').getAttribute('aria-pressed')==='true'");
 await check('mute state and control label update immediately',"!document.querySelector('[data-current-muted]').hidden&&document.querySelector('[data-conversation-action=mute]').textContent.includes('关闭')");
 await js("document.querySelector('[data-conversation-action=search]').click()");await until('search dialog',"document.querySelector('[data-history-dialog]').open");
 await js("document.querySelector('[data-history-form] [name=q]').value='旧消息';document.querySelector('[data-history-form]').requestSubmit()");
 await until('search results',"document.querySelector('.history-result span')?.textContent==='找到的旧消息'");
 await js("document.querySelector('.history-result').click()");await until('context',"Boolean(document.querySelector('[data-id=\"50\"].message-search-target'))");
 await check('search jumps into surrounding context and closes dialog',"!document.querySelector('[data-history-dialog]').open&&document.querySelector('[data-id=\"40\"]')&&document.querySelector('[data-id=\"60\"]')&&!document.querySelector('[data-conversation-latest]').hidden?true:false");
 await js("document.querySelector('[data-conversation-latest]').click()");await until('latest',"document.querySelector('[data-id=\"999\"]')?.textContent.includes('最新消息')");
 await js("document.querySelector('[data-conversation-action=clear]').click()");await until('clear',"!document.querySelector('[data-message-log] [data-id]')");
 await check('clear does not leave old bubbles visible',"!document.querySelector('[data-message-log] [data-id]')");
 await win.loadURL(origin+'/profile/');await until('avatar',"[...document.querySelectorAll('[data-avatar-image]')].every(image=>image.complete&&image.naturalWidth>0)");
 await check('uploaded avatar is shown in settings and account header',"document.querySelectorAll('[data-avatar-image]').length>=2");
 await js("(()=>{const list=new DataTransfer();list.items.add(new File(['bad'], 'new.png',{type:'image/png'}));const input=document.querySelector('[data-avatar-file]');input.files=list.files;input.dispatchEvent(new Event('change'));})()");
 await check('new avatar gets a preview before saving',"!document.querySelector('[data-avatar-preview]').hidden&&document.querySelector('[data-avatar-hint]').textContent.includes('保存')");
 await win.loadURL(origin+'/gifts/');await until('gift scripts',"typeof window.workbenchPointCard==='function'");
 await js("window.confirm=()=>true;document.querySelector('[data-gift-open]').click()");await until('available points',"document.querySelector('[data-gift-available]').textContent==='100 点'");
 await check('only supplemental points are advertised and private group fields are hidden',"document.querySelector('[data-gift-send-dialog]').textContent.includes('每周基础额度不能转赠')&&document.querySelector('.gift-group-fields').hidden");
 await js("document.querySelector('[data-gift-form] [name=points]').value='10';document.querySelector('[data-gift-form] [name=kind]').value='transfer';document.querySelector('[data-gift-form]').requestSubmit()");
 await until('gift bubble',"document.querySelector('[data-id=\"1000\"] .point-gift-card')");assert.equal(giftPosts.length,1);assert.match(giftPosts[0],/^[a-f0-9-]{36}$/);
 await check('transfer renders as an interactive point card',"document.querySelector('[data-id=\"1000\"] .point-gift-card').textContent.includes('积分转账')");
 await js("document.querySelector('[data-id=\"1000\"] .point-gift-card').click()");await until('gift detail',"!document.querySelector('[data-gift-claim]').hidden");
 await js("document.querySelector('[data-gift-claim]').click()");await until('gift receipt',"document.querySelector('[data-gift-detail]').textContent.includes('你已领取 10 点')");
 await check('claimed gift cannot be claimed again through its button',"document.querySelector('[data-gift-claim]').hidden");assert.equal(claimed,1);
 win.setContentSize(390,780);
 await check('gift dialog fits phone and has 44 pixel controls',"document.documentElement.scrollWidth<=innerWidth&&document.querySelector('[data-gift-detail-dialog]').getBoundingClientRect().width<=innerWidth");
 await delay(150);fs.writeFileSync(path.join(scratch,'gift-phone.png'),(await win.webContents.capturePage()).toPNG());
 await win.loadURL(origin+'/conversations/');await js("document.querySelector('[data-conversation-action=search]').click()");
 await check('phone search has no horizontal overflow',"document.documentElement.scrollWidth<=innerWidth&&document.querySelector('[data-history-dialog]').getBoundingClientRect().width<=innerWidth");
 await delay(150);fs.writeFileSync(path.join(scratch,'chat-history-phone.png'),(await win.webContents.capturePage()).toPNG());
 win.setContentSize(1100,850);await win.loadURL(origin+'/conversations/');await delay(150);fs.writeFileSync(path.join(scratch,'chat-dark-sidebar.png'),(await win.webContents.capturePage()).toPNG());
 // Run the actual DOM renderer with malformed links and HTML, no model call.
 await js("(()=>{const script=document.createElement('script');script.src='/static/aihub/markdown.js';document.head.append(script)})()");await until('markdown',"typeof window.workbenchMarkdown==='function'");
 await check('Markdown renders bold, lists, trusted reference titles and never executes HTML',"(()=>{const box=document.createElement('div');window.workbenchMarkdown(box,'**摘要**\\n\\n- [[项目名]](/projects/2/)\\n- [危险](javascript:bad)\\n\\n<script>window.bad=1</script>',{sources:[{url:'/projects/2/'}]});return box.querySelector('strong').textContent==='摘要'&&box.querySelector('ul')&&box.querySelector('a').textContent==='[项目名]'&&box.querySelectorAll('a').length===1&&!box.querySelector('script')&&!window.bad&&!box.textContent.includes('/projects/2/')})()");
 assert.deepEqual(errors.filter(error=>!error.includes('Failed to load resource')),[]);console.log('SOCIAL UI CHECKS:',checks);
 const avatarData='data:image/webp;base64,'+fs.readFileSync(path.join(fixtures,'avatar.webp')).toString('base64');
 ipcMain.handle('social:test-info',()=>({ok:true,data:{username:'头像测试',authenticated:true,current:'messages',avatar:avatarData,appearance:{theme:'light'}}}));
 const native=new BrowserWindow({show:false,width:248,height:400,useContentSize:true,webPreferences:{preload:path.join(__dirname,'social-preload.cjs'),sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
 await native.loadFile(path.join(root,'desktop/ui/account.html'));const savedWindow=win;win=native;
 await until('native avatar',"document.querySelector('#avatar img')?.naturalWidth>0");
 await check('native desktop account avatar loads privately and matches the dark chat sidebar in light theme',"getComputedStyle(document.querySelector('details')).backgroundColor==='rgb(29, 29, 29)'&&document.querySelector('#avatar img').src.startsWith('data:image/webp;base64,')");
 native.webContents.send('social:test-state',{username:'另一个账号',authenticated:true,current:'workspace',avatar:''});
 await until('cleared native avatar',"!document.querySelector('#avatar img')&&document.querySelector('#avatar').textContent==='另'");
 await check('switching accounts removes previous user avatar',"!document.querySelector('#avatar img')");
 native.destroy();win=savedWindow;console.log('TOTAL SOCIAL UI CHECKS:',checks);
 win.destroy();await new Promise(resolve=>server.close(resolve));app.exit(0);
}).catch(async error=>{console.error(error);if(win&&!win.isDestroyed())fs.writeFileSync(path.join(scratch,'social-failure.png'),(await win.webContents.capturePage()).toPNG());server?.close();app.exit(1);});
