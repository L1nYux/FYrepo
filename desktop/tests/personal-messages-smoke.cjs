const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch'),fixtures=path.join(scratch,'render-pages');
app.setPath('userData',path.join(scratch,'personal-messages-ui-'+Date.now()));app.disableHardwareAcceleration();
let win,server,selected='v3-personal.html',message,failNext=false,postedFile=false,muted=false,checks=0;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const js=code=>win.webContents.executeJavaScript(code);
async function check(label,code){const deadline=Date.now()+10000;while(Date.now()<deadline){if(await js(code)){console.log('PASS:',label);checks++;return;}await delay(40);}throw Error('Timed out: '+label);}
app.whenReady().then(async()=>{
  for(const name of ['v3-personal.html','v3-friend-group.html'])assert.ok(fs.existsSync(path.join(fixtures,name)),name+' Django fixture');
  server=http.createServer((req,res)=>{
    const url=new URL(req.url,'http://localhost'),parts=[];req.on('data',chunk=>parts.push(chunk));
    req.on('end',()=>{
      const json=(value,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(value));};
      if(url.pathname.startsWith('/static/')){
        const file=path.resolve(root,url.pathname.slice(1));if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
        res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/javascript');res.end(fs.readFileSync(file));return;
      }
      if(url.pathname.endsWith('/unread/'))return json({total:0,channels:{},presence:{},muted_channels:[],hidden_channels:[]});
      if(url.pathname.includes('/history/'))return json({messages:[{id:99,author:'我',at:'10-06 12:00',body:'历史中的消息',files:[]}],next_before:null});
      if(url.pathname.includes('/settings/')){muted=new URLSearchParams(Buffer.concat(parts).toString()).get('action')==='mute';return json({muted});}
      if(url.pathname.includes('/action/')){
        const body=Buffer.concat(parts).toString();
        if(body.includes('draft'))return json({draft:{id:99,body:'重新编辑的消息',attachments:['pasted.png']}});
        if(body.includes('withdraw'))message.withdrawn=true;
        return json({ok:true});
      }
      if(req.headers.accept==='application/json'){
        if(req.method==='POST'){
          if(failNext){failNext=false;return json({error:'本次发送失败，请重试'},500);}
          postedFile=Buffer.concat(parts).toString().includes('pasted.png');
          message={id:99,author:'我',author_id:1,mine:true,body:'粘贴图片后的消息',at:'10-06 12:00',action_url:'/messages/personal/2/action/99/',files:[]};
          return json({ok:true});
        }
        return json({messages:message?[message]:[],removed:[]});
      }
      res.setHeader('Content-Type','text/html;charset=utf-8');res.end(fs.readFileSync(path.join(fixtures,selected)));
    });
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
  win=new BrowserWindow({show:false,width:1200,height:850,useContentSize:true,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,offscreen:true}});
  await win.loadURL(origin+'/messages/personal/2/');
  await check('personal composer has tools left and send at bottom right',"(()=>{const form=document.querySelector('[data-thread-form]'),tools=form.querySelector('.composer-tools').getBoundingClientRect(),send=form.querySelector('[data-thread-send]').getBoundingClientRect();return send.left>tools.right&&send.right>form.getBoundingClientRect().right-40})()");
  await js("(()=>{const input=document.querySelector('[data-thread-form] textarea'),data=new DataTransfer();data.items.add(new File(['image'],'pasted.png',{type:'image/png'}));input.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));input.value='图片消息';input.dispatchEvent(new Event('input'));})()");
  await check('clipboard image becomes a retained composer attachment',"document.querySelector('[data-thread-files]').files.length===1&&document.querySelector('[data-thread-file-names]').textContent.includes('pasted.png')");
  failNext=true;await js("document.querySelector('[data-thread-form]').requestSubmit()");
  await check('failed send retains typed text and the pasted file',"document.querySelector('[data-thread-status]').textContent.includes('发送失败')&&document.querySelector('[data-thread-form] textarea').value==='图片消息'&&document.querySelector('[data-thread-files]').files.length===1");
  const reloaded=new Promise(resolve=>win.webContents.once('did-finish-load',resolve));win.reload();await reloaded;
  await check('draft text survives page refresh',"document.querySelector('[data-thread-form] textarea').value==='图片消息'");
  await js("(()=>{const data=new DataTransfer();data.items.add(new File(['image'],'pasted.png',{type:'image/png'}));document.querySelector('[data-thread-files]').files=data.files;document.querySelector('[data-thread-form]').requestSubmit()})()");
  await check('sent message is visible with its avatar outside the bubble',"(()=>{const row=document.querySelector('[data-message-id=\"99\"]');return row&&parseFloat(getComputedStyle(row).opacity)===1&&row.querySelector('.conversation-avatar').parentElement===row&&row.querySelector('.message-bubble').textContent.includes('粘贴图片后的消息')})()");assert.equal(postedFile,true);
  await js("document.querySelector('[data-message-id=\"99\"] [data-message-actions]').click();document.querySelector('[data-thread-quote-action]').click()");
  await check('quote action fills the composer without changing navigation',"document.querySelector('[name=quoted_message]').value==='99'&&!document.querySelector('[data-thread-quote]').hidden");
  await js("document.querySelector('[data-message-id=\"99\"] [data-message-actions]').click();document.querySelector('[data-thread-withdraw-action]').click()");
  await check('withdraw is a centered notice with reedit',"document.querySelector('[data-message-id=\"99\"].message-system-note [data-thread-reedit]')!==null");
  await js("document.querySelector('[data-thread-reedit]').click()");
  await check('reedit restores text and original attachment intent',"document.querySelector('[data-thread-form] textarea').value==='重新编辑的消息'&&document.querySelector('[name=resend_message]').value==='99'&&document.querySelector('[data-thread-draft]').textContent.includes('pasted.png')");
  await js("document.querySelector('[data-thread-history-open]').click()");
  await check('history opens as a dialog and displays searched records',"document.querySelector('[data-thread-history-dialog]').open&&document.querySelector('[data-thread-history-results]').textContent.includes('历史中的消息')");
  await js("document.querySelector('[data-thread-history-close]').click();document.querySelector('[data-thread-setting=\"mute\"]').click()");
  await check('mute updates the conversation control',"document.querySelector('[data-thread-setting=\"unmute\"]')!==null");
  await js("window.confirm=()=>true;document.querySelector('[data-thread-setting=\"clear\"]').click()");
  await check('clearing removes only displayed conversation records',"document.querySelector('[data-history]').children.length===0");
  selected='v3-friend-group.html';await win.loadURL(origin+'/messages/groups/1/');
  await js("document.querySelector('[data-chat-details-toggle]').click()");
  await check('friend group shows independent group details and member management',"!document.querySelector('[data-chat-details]').hidden&&document.querySelector('[data-chat-details]').textContent.includes('群公告')&&document.querySelector('[data-chat-details] [name=nickname]')!==null");
  await js("document.querySelector('[data-chat-details-close]').click();document.documentElement.dataset.theme='light'");
  await check('group details close restores the chat width',"document.querySelector('[data-chat-details]').hidden");
  await delay(150);
  fs.writeFileSync(path.join(scratch,'v3-friend-group-light.png'),(await win.webContents.capturePage()).toPNG());
  await js("document.documentElement.dataset.theme='dark'");
  await delay(150);
  fs.writeFileSync(path.join(scratch,'v3-friend-group-dark.png'),(await win.webContents.capturePage()).toPNG());
  console.log('ALL_PERSONAL_MESSAGE_UI_CHECKS_PASSED',checks);win.destroy();server.close();app.exit(0);
}).catch(error=>{console.error(error.stack);if(win&&!win.isDestroyed())win.destroy();server?.close();app.exit(1);});
