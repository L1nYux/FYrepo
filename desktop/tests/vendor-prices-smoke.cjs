// Isolated renderer checks with synthetic responses; no supplier keys or inference.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch');
app.setPath('userData',path.join(scratch,'vendor-prices-client'));app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
let win,server,failNext=false;const requests=[];
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(label,expression){const end=Date.now()+10000;while(Date.now()<end){if(await win.webContents.executeJavaScript(expression))return;await delay(30);}throw Error('Timed out: '+label);}
async function check(label,expression){assert.equal(await win.webContents.executeJavaScript(expression),true,label);console.log('PASS:',label);}
const row=model=>`document.querySelector('.pool-saved-model[data-search*="${model}"]')`;
app.whenReady().then(async()=>{
  server=http.createServer(async(req,res)=>{
    const url=new URL(req.url,'http://localhost'),json=(value,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(value));};
    if(url.pathname==='/api-pool/model-price/'){
      let text='';for await(const chunk of req)text+=chunk;const data=JSON.parse(text);requests.push(data);await delay(50);
      if(failNext){failNext=false;json({error:'自动读取暂时失败，已有价格已保留；请稍后重试。'},400);return;}
      json({saved:true,input_rate:data.action==='automatic'?'0.8':data.input_rate,output_rate:data.action==='automatic'?'2.8':data.output_rate,
        currency:data.currency||'CNY',source:data.action==='automatic'?'自动读取：官方按量价；阶梯按最高档保守估算':'管理员登记'});return;
    }
    if(url.pathname==='/messages/unread/'){json({total:0});return;}
    const file=url.pathname.startsWith('/static/')?path.join(root,url.pathname.slice(1)):path.join(scratch,'render-pages/vendor-prices.html');
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');res.end(fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  win=new BrowserWindow({show:false,width:1100,height:800,useContentSize:true,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
  const errors=[];win.webContents.on('console-message',(_event,level,message)=>{if(level===3)errors.push(message);});
  await win.loadURL('http://127.0.0.1:'+server.address().port+'/api-pool/manage/?prices=1');
  await check('all three official sources have usable buttons',`['glm-5.3-flash','MiniMax-M2.7','qwen3.8-flash'].every(id=>!document.querySelector('.pool-saved-model[data-search*="'+id+'"] [data-auto-price]').disabled)`);
  await check('unsupported source has an explanation and disabled button',`${row('custom-model')}.querySelector('[data-auto-price]').disabled && ${row('custom-model')}.textContent.includes('尚未接入可靠')`);
  await check('plan and conservative pricing are explicitly explained',"document.querySelector('#pool-saved-models').textContent.includes('M Plan') && document.querySelector('#pool-saved-models').textContent.includes('最高档')");
  await win.webContents.executeJavaScript(`const g=${row('glm-5.3-flash')};g.querySelector('[data-auto-price]').click();g.querySelector('[data-auto-price]').click()`);
  await until('automatic price saved',`${row('glm-5.3-flash')}.dataset.priceState==='saved'`);
  assert.equal(requests.length,1);assert.equal(requests[0].action,'automatic');console.log('PASS: repeated clicks make one price request');
  await check('automatic read fills units and source immediately',`${row('glm-5.3-flash')}.querySelector('[name=input_rate]').value==='0.8' && ${row('glm-5.3-flash')}.querySelector('[name=output_rate]').value==='2.8' && ${row('glm-5.3-flash')}.querySelector('[data-price-status]').textContent.includes('自动读取')`);
  await check('remaining missing count updates without reloading',"document.querySelector('#pool-missing-count').textContent.includes('3 个待补价格')");
  failNext=true;
  await win.webContents.executeJavaScript(`${row('glm-5.3-flash')}.querySelector('[data-auto-price]').click()`);
  await until('read failed',`${row('glm-5.3-flash')}.querySelector('[data-price-status]').textContent.includes('已有价格')`);
  await check('failure retains fields and allows manual retry',`${row('glm-5.3-flash')}.querySelector('[name=input_rate]').value==='0.8' && !${row('glm-5.3-flash')}.querySelector('[data-auto-price]').disabled`);
  await win.webContents.executeJavaScript(`${row('glm-5.3-flash')}.querySelector('[data-auto-price]').click()`);
  await until('manual retry succeeded',`${row('glm-5.3-flash')}.querySelector('[data-price-status]').textContent.startsWith('已保存')`);
  console.log('PASS: retry works after a failed price query');
  await win.webContents.executeJavaScript(`const c=${row('custom-model')};c.querySelector('[name=input_rate]').value='0';c.querySelector('[name=output_rate]').value='0';c.querySelector('form.pool-simple-price').requestSubmit()`);
  await until('custom price saved',`${row('custom-model')}.dataset.priceState==='saved'`);
  await check('manual zero price retained and unsupported auto stays disabled',`${row('custom-model')}.querySelector('[name=input_rate]').value==='0' && ${row('custom-model')}.querySelector('[data-auto-price]').disabled`);
  await win.webContents.executeJavaScript(`const p=${row('MiniMax-M2.7')};p.querySelector('[name=currency]').value='USD';p.querySelector('[data-auto-price]').click()`);
  await until('minimax price saved',`${row('MiniMax-M2.7')}.dataset.priceState==='saved'`);
  await check('currency and summary remain consistent',`${row('MiniMax-M2.7')}.querySelector('[name=currency]').value==='USD' && ${row('MiniMax-M2.7')}.querySelector('[data-price-summary]').textContent.includes('USD / 百万 token')`);
  await win.webContents.executeJavaScript("{const state=document.querySelector('#pool-price-state');state.value='missing';state.dispatchEvent(new Event('change',{bubbles:true}))}");
  await check('only unpriced enabled model remains in missing filter',"[...document.querySelectorAll('.pool-saved-model')].filter(n=>!n.hidden).length===1");
  await win.webContents.executeJavaScript(`${row('qwen3.8-flash')}.querySelector('[data-auto-price]').click()`);
  await until('qwen price saved',`${row('qwen3.8-flash')}.dataset.priceState==='saved'`);
  await check('final automatic save clears missing filter and badge',"document.querySelector('#pool-missing-count').textContent==='' && document.querySelector('#pool-price-empty').hidden===false");
  assert(requests.every(data=>!('api_key' in data)));console.log('PASS: price requests never contain provider keys');
  await win.webContents.executeJavaScript("{const state=document.querySelector('#pool-price-state');state.value='';state.dispatchEvent(new Event('change',{bubbles:true}))}");
  win.setContentSize(390,760);await delay(100);await win.webContents.insertCSS('.shell-sidebar{transition:none!important}');
  await win.webContents.executeJavaScript(`${row('glm-5.3-flash')}.querySelector('[data-auto-price]').scrollIntoView({behavior:'instant',block:'center'})`);
  await check('phone layout fits and auto price control is accessible',`document.documentElement.scrollWidth<=innerWidth && (()=>{const n=${row('glm-5.3-flash')}.querySelector('[data-auto-price]'),r=n.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===n})()`);
  assert.deepEqual(errors,[]);console.log('PASS: no renderer errors');console.log('ALL_VENDOR_PRICE_CHECKS_PASSED');win.destroy();server.close();app.exit(0);
}).catch(error=>{console.error(error);win?.destroy();server?.close();app.exit(1);});
