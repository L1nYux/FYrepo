// Real renderer checks against isolated HTML and mock catalogs; no real keys.
const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch');
app.setPath('userData',path.join(scratch,'model-picker-client'));app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
const models=[
  {id:'qwen-missing',vendor:'千问',use:'chat',use_label:'文本对话',assistant_supported:true},
  {id:'qwen-priced',vendor:'千问',use:'chat',use_label:'文本对话',assistant_supported:true,selected:true,has_price:true},
  {id:'glm-5.3-flash',vendor:'智谱',use:'vision',use_label:'多模态对话',assistant_supported:true,selected:true},
  {id:'qwen-image-2.1-pro',vendor:'千问',use:'image',use_label:'图片生成',assistant_supported:false},
  {id:'qwen-tts',vendor:'千问',use:'audio',use_label:'语音 / 实时音频',assistant_supported:false},
  {id:'wan-2.2',vendor:'通义万相',use:'video',use_label:'视频生成',assistant_supported:false},
  {id:'text-embedding-v4',vendor:'其他 / 未标明',use:'embedding',use_label:'向量 / 排序',assistant_supported:false},
  ...Array.from({length:216},(_,i)=>({id:'qwen-test-'+i,vendor:'千问',use:'chat',use_label:'文本对话',assistant_supported:true}))
].map(row=>({label:row.id,...row}));
let win,server,selected;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(label,expression){const end=Date.now()+10000;while(Date.now()<end){if(await win.webContents.executeJavaScript(expression))return;await delay(50);}throw Error('Timed out: '+label);}
async function check(label,expression){assert.equal(await win.webContents.executeJavaScript(expression),true,label);console.log('PASS:',label);}
const change=(id,value)=>`{const n=document.getElementById(${JSON.stringify(id)});n.value=${JSON.stringify(value)};n.dispatchEvent(new Event('change',{bubbles:true}));}`;
app.whenReady().then(async()=>{
  server=http.createServer(async(req,res)=>{
    const url=new URL(req.url,'http://localhost');const json=(data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
    if(url.pathname==='/api-pool/discover/'){req.resume();json({provider:1,ticket:'fake-proposal',channel:'阿里云百炼',models});return;}
    if(url.pathname==='/api-pool/enable-models/'){
      let body='';for await(const chunk of req)body+=chunk;selected=JSON.parse(body).models;
      json({error:'模拟保存失败，检查原勾选是否保留'},400);return;
    }
    if(url.pathname==='/api-pool/model-price/') {req.resume();json({saved:true,input_rate:'1',output_rate:'2',currency:'CNY',source:'管理员登记'});return;}
    if(url.pathname==='/messages/unread/'){json({total:0});return;}
    const file=url.pathname.startsWith('/static/')?path.join(root,url.pathname.slice(1)):path.join(scratch,'render-pages/model-picker.html');
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');res.end(fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  win=new BrowserWindow({show:false,width:1100,height:800,useContentSize:true,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
  const errors=[];win.webContents.on('console-message',(_event,level,message)=>{if(level===3)errors.push(message);});
  await win.loadURL('http://127.0.0.1:'+server.address().port+'/api-pool/manage/');
  await until('management initialized',"document.querySelector('#pool-status').textContent.includes('已加载')");
  await win.webContents.executeJavaScript("const url=document.querySelector('#pool-url');url.value='https://dashscope.aliyuncs.com/compatible-mode/v1';url.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#pool-connect-form').requestSubmit()");
  await until('catalog ready',"!document.querySelector('#pool-selection').hidden && !document.querySelector('#pool-enable').disabled");
  await check('223 catalog defaults to conversations only',"document.querySelectorAll('.pool-discovered-model').length===223 && [...document.querySelectorAll('.pool-discovered-model')].filter(n=>!n.hidden).length===219 && document.querySelector('input[value=\"qwen-image-2.1-pro\"]').closest('label').hidden");
  await check('channel and vendor groups are explicit',"document.querySelector('#pool-channel').textContent.includes('阿里云百炼') && [...document.querySelectorAll('.pool-model-group h3')].some(n=>n.textContent==='智谱')");
  await check('existing selected models retained without selecting new ones',"document.querySelectorAll('#pool-catalog input:checked').length===2 && !document.querySelector('input[value=\"qwen-missing\"]').checked");
  await win.webContents.executeJavaScript(change('pool-vendor','智谱')+"document.querySelector('#pool-all').click()");
  await check('select all is limited to visible rows',"document.querySelector('input[value=\"qwen-priced\"]').checked && !document.querySelector('input[value=\"glm-5.3-flash\"]').checked && !document.querySelector('input[value=\"qwen-missing\"]').checked");
  await win.webContents.executeJavaScript("document.querySelector('#pool-all').click();"+change('pool-vendor','')+change('pool-use','image'));
  await check('unsupported image is visible by category but cannot enable',"!document.querySelector('input[value=\"qwen-image-2.1-pro\"]').closest('label').hidden && document.querySelector('input[value=\"qwen-image-2.1-pro\"]').disabled && document.querySelector('#pool-all').disabled");
  await win.webContents.executeJavaScript(change('pool-use','assistant')+"document.querySelector('input[value=\"qwen-missing\"]').click();document.querySelector('#pool-selected-only').click()");
  await check('only selected retains choices across filters',"[...document.querySelectorAll('.pool-discovered-model')].filter(n=>!n.hidden).length===3 && document.querySelector('#pool-catalog-count').textContent.includes('已选 3')");
  await win.webContents.executeJavaScript(change('pool-vendor','智谱')+"document.querySelector('#pool-select-form').requestSubmit()");
  await until('save response',"document.querySelector('#pool-status').textContent.includes('模拟保存失败')");
  assert.deepEqual(selected.sort(),['glm-5.3-flash','qwen-missing','qwen-priced']);console.log('PASS: save includes selected rows hidden by filters');
  await check('unsupported model remains disabled after request ends',"document.querySelector('input[value=\"qwen-image-2.1-pro\"]').disabled && document.querySelectorAll('#pool-catalog input:checked').length===3");
  await check('prices contain only active models with missing first',"document.querySelectorAll('.pool-saved-model').length===2 && document.querySelector('.pool-saved-model').dataset.priceState==='missing' && !document.querySelector('#pool-saved-models').textContent.includes('qwen-paused') && document.querySelector('#pool-model-management').textContent.includes('qwen-paused')");
  await win.webContents.executeJavaScript("document.querySelector('#pool-saved-models').open=true;"+change('pool-price-state','missing'));
  await check('price status filter hides priced models',"[...document.querySelectorAll('.pool-saved-model')].filter(n=>!n.hidden).length===1");
  await win.webContents.executeJavaScript("document.querySelector('.pool-simple-price [name=input_rate]').value='1';document.querySelector('.pool-simple-price [name=output_rate]').value='2';document.querySelector('.pool-simple-price').requestSubmit()");
  await until('price saved',"document.querySelector('.pool-saved-model').dataset.priceState==='saved'");
  await check('saving a price updates missing filter immediately',"document.querySelector('#pool-price-empty').hidden===false && [...document.querySelectorAll('.pool-saved-model')].every(n=>n.hidden)");
  await win.webContents.executeJavaScript(change('pool-price-state','')+"const s=document.querySelector('#pool-price-search');s.value='qwen-priced';s.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#pool-model-management').open=true;const m=document.querySelector('#pool-management-search');m.value='qwen-paused';m.dispatchEvent(new Event('input',{bubbles:true}));");
  await check('price and separate management search are scoped',"[...document.querySelectorAll('.pool-saved-model')].filter(n=>!n.hidden).length===1 && [...document.querySelectorAll('[data-management-model]')].filter(n=>!n.hidden).length===1");
  win.setContentSize(390,760);await delay(100);
  await check('phone layout fits and filters have touch height',"document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('.pool-catalog-filters select')].every(n=>n.getBoundingClientRect().height>=44)");
  // Hidden test windows don't paint transitions reliably; check the settled layout.
  await win.webContents.insertCSS('.shell-sidebar{transition:none!important}');
  await win.webContents.executeJavaScript("document.querySelector('#pool-vendor').scrollIntoView({block:'center',behavior:'instant'})");
  await delay(100);
  await check('phone vendor filter is not covered by the sidebar',"(()=>{const n=document.querySelector('#pool-vendor'),r=n.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===n})()");
  fs.writeFileSync(path.join(scratch,'model-picker-phone.png'),(await win.webContents.capturePage()).toPNG());
  assert.deepEqual(errors,[]);console.log('PASS: no renderer script errors');
  console.log('ALL_MODEL_PICKER_CHECKS_PASSED');win.destroy();server.close();app.exit(0);
}).catch(error=>{console.error(error);win?.destroy();server?.close();app.exit(1);});
