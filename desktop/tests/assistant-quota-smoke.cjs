const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch'),fixtures=path.join(scratch,'render-pages');
app.setPath('userData',path.join(scratch,'assistant-quota-client'));app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
let server,win;const starts=[];let quotaReads=0;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(label,expression){const deadline=Date.now()+10000;while(Date.now()<deadline){if(await win.webContents.executeJavaScript(expression))return;await delay(50);}throw Error('Timed out: '+label);}
async function check(label,expression){const value=await win.webContents.executeJavaScript(expression);if(!value)console.error(await win.webContents.executeJavaScript("JSON.stringify([...document.querySelectorAll('[data-assistant-retry]')].map(b=>({text:b.textContent,height:b.getBoundingClientRect().height,style:getComputedStyle(b).minHeight,body:document.body.className})))"));assert.equal(value,true,label);console.log('PASS:',label);}
app.whenReady().then(async()=>{
  server=http.createServer(async(req,res)=>{
    const url=new URL(req.url,'http://localhost');
    const json=(data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
    if(url.pathname==='/assistant/start/'){
      let text='';for await(const chunk of req)text+=chunk;starts.push(JSON.parse(text));
      if(starts.length===1){json({error:'模拟启动失败'},503);return;}
      json({job:'job-'+starts.length,conversation:1,title:'Debug'},202);return;
    }
    if(url.pathname.startsWith('/assistant/jobs/')){const failed=url.pathname.includes('job-2');json({state:failed?'error':'done',result:failed?{error:'模拟模型失败'}:{text:'完成',calls:1,tokens:2,cost_cny:0}});return;}
    if(url.pathname==='/assistant/conversations/'){json({conversations:[],history_days:0});return;}
    if(url.pathname==='/api-pool/catalog/'){json({models:[{id:1,configured:true,provider:'Test',label:'Test',supports_tools:true}],budget:{member_week:{limit:null},extra:{remaining_points:0}}});return;}
    if(url.pathname.endsWith('/quota/')){
      req.resume();quotaReads++;json({supported:true,kind:'plan',note:'M Plan 套餐额度',error:quotaReads>1?'厂商暂时无法读取，保留上次结果。':'',stale:quotaReads>1,value:{updated_at:'2026-10-04T02:00:00Z',windows:[{label:'5 小时窗口',remaining:75,total:100,remaining_percent:75,reset_at:'2026-10-04T07:00:00Z',unlimited:false}]}});return;
    }
    if(url.pathname==='/messages/unread/'){json({total:0});return;}
    const file=url.pathname.startsWith('/static/')?path.join(root,url.pathname.slice(1)):path.join(fixtures,url.pathname==='/assistant/'?'assistant.html':url.pathname==='/account/forgot/'?'recovery-bound.html':'pool-manage.html');
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');res.end(fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
  win=new BrowserWindow({show:false,width:1100,height:800,useContentSize:true,webPreferences:{sandbox:true,contextIsolation:true}});
  await win.loadURL(origin+'/assistant/');await until('models ready',"!document.querySelector('#assistant-send').disabled");
  await win.webContents.executeJavaScript("document.querySelector('#assistant-input').value='原问题';document.querySelector('#assistant-form').requestSubmit()");
  await until('failed bubble',"Boolean(document.querySelector('[data-assistant-retry]'))");
  await check('reference and text clear from composer but stay in sent bubble',"document.querySelector('#assistant-input').value==='' && document.querySelector('#assistant-context').hidden && document.querySelector('.assistant-row.user').textContent.includes('引用：')");
  await check('failed message has accessible touch-sized retry',"document.querySelector('[data-assistant-retry]').textContent==='重试' && document.querySelector('[data-assistant-retry]').getBoundingClientRect().height>=44");
  await win.webContents.executeJavaScript("document.querySelector('#assistant-input').value='下一条草稿';const b=document.querySelector('[data-assistant-retry]');b.click();b.click()");
  await until('failed model bubble',"document.querySelector('.assistant-row.assistant')?.textContent.includes('模拟模型失败') && !document.querySelector('[data-assistant-retry]').disabled");
  assert.equal(starts.length,2);assert.deepEqual(starts[0],starts[1]);console.log('PASS: double retry sends once and retains original reference');
  await win.webContents.executeJavaScript("document.querySelector('[data-assistant-retry]').click()");
  await until('retry complete',"document.querySelector('#assistant-status').textContent.includes('本轮 1 次调用')");
  assert.equal(starts.length,3);assert.equal(starts[2].retry_job,'job-2');assert.notEqual(starts[2].request_id,starts[0].request_id);
  await check('retry preserves the new composer draft',"document.querySelector('#assistant-input').value==='下一条草稿'");
  await win.webContents.executeJavaScript("document.querySelector('#assistant-form').requestSubmit()");await until('second message complete',"document.querySelectorAll('.assistant-row.user').length===2 && !document.querySelector('#assistant-send').disabled");
  assert.equal(starts[3].context,null);console.log('PASS: next message has no leftover reference');
  fs.writeFileSync(path.join(scratch,'assistant-retry.png'),(await win.webContents.capturePage()).toPNG());
  win.setContentSize(390,760);await delay(200);
  await check('AI assistant fits phone width',"document.documentElement.scrollWidth<=window.innerWidth");
  await win.loadURL(origin+'/api-pool/manage/');
  await check('quota controls fit phone and have touch-sized refresh',"document.documentElement.scrollWidth<=window.innerWidth && document.querySelector('[data-quota-refresh]').getBoundingClientRect().height>=44");
  await win.webContents.executeJavaScript("document.querySelector('[data-quota-refresh]').click()");await until('quota shown',"document.querySelector('[data-quota-value]').textContent.includes('75 / 100')");
  await check('vendor quota includes timestamp and reset time',"document.querySelector('[data-quota-value]').textContent.includes('更新于') && document.querySelector('[data-quota-value]').textContent.includes('重置')");
  await win.webContents.executeJavaScript("document.querySelector('[data-quota-refresh]').click()");await until('quota failure',"document.querySelector('[data-quota-status]').textContent.includes('保留上次结果')");
  await check('quota failure retains prior value and marks it stale',"document.querySelector('[data-quota-value]').textContent.includes('75 / 100') && document.querySelector('[data-quota-value]').textContent.includes('上次结果')");
  await win.webContents.executeJavaScript("document.querySelector('#vendor-quotas').scrollIntoView({block:'start'})");fs.writeFileSync(path.join(scratch,'vendor-quota-phone.png'),(await win.webContents.capturePage()).toPNG());
  win.setContentSize(360,600);await win.loadURL(origin+'/account/forgot/');
  await check('signed-in recovery fits phone and retains settings',"document.documentElement.scrollWidth<=window.innerWidth && Boolean(document.querySelector('.settings-content.recovery-content'))");
  let pageErrors=[];win.webContents.on('console-message',(_e,...args)=>{const detail=args[0];if(detail?.level==='error')pageErrors.push(detail.message);});
  await win.webContents.executeJavaScript("document.querySelector('form.send-code').addEventListener('submit',e=>e.preventDefault());document.querySelector('form.send-code').requestSubmit()");
  await check('recovery submit locks its implicit submit button without errors',"document.querySelector('form.send-code button').disabled && document.querySelector('form.send-code button').textContent.includes('正在发送')");assert.deepEqual(pageErrors,[]);
  console.log('ALL_ASSISTANT_QUOTA_CHECKS_PASSED');win.destroy();server.close();app.exit(0);
}).catch(error=>{console.error(error);if(win)win.destroy();server?.close();app.exit(1);});
