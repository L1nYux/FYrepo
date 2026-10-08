const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch'),fixtures=path.join(scratch,'render-pages');
app.setPath('userData',path.join(scratch,'personal-api-client'));app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
let server,win;const errors=[];
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function check(label,expression){const value=await win.webContents.executeJavaScript(expression);if(!value)console.error(await win.webContents.executeJavaScript("JSON.stringify({width:innerWidth,scroll:document.documentElement.scrollWidth,buttons:[...document.querySelectorAll('[data-api-copy]')].map(b=>({id:b.dataset.apiCopy,height:b.getBoundingClientRect().height,min:getComputedStyle(b).minHeight})),overflow:[...document.querySelectorAll('body *')].filter(n=>n.getBoundingClientRect().right>innerWidth+1&&getComputedStyle(n).position!=='fixed').slice(0,16).map(n=>({tag:n.tagName,cls:n.className,width:n.getBoundingClientRect().width,right:n.getBoundingClientRect().right}))})"));assert.equal(value,true,label);console.log('PASS:',label);}
async function until(label,expression){const end=Date.now()+10000;while(Date.now()<end){if(await win.webContents.executeJavaScript(expression))return;await delay(50);}throw Error('Timed out: '+label);}
async function open(name){await win.loadURL('http://127.0.0.1:'+server.address().port+'/'+name);await until('API controls ready',"Boolean(document.querySelector('#personal-api-model-id')?.textContent)");}
app.whenReady().then(async()=>{
  server=http.createServer((req,res)=>{
    const url=new URL(req.url,'http://localhost');
    if(url.pathname==='/messages/unread/'){res.setHeader('Content-Type','application/json');res.end('{"total":0}');return;}
    const file=url.pathname.startsWith('/static/')?path.join(root,url.pathname.slice(1)):path.join(fixtures,path.basename(url.pathname));
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');res.end(fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  win=new BrowserWindow({show:false,width:1100,height:800,useContentSize:true,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
  win.webContents.on('console-message',(_event,level,message)=>{if(level===3)errors.push(message);});
  await open('personal-api.html');
  await check('member has a discoverable My API Key link',"document.querySelector('[data-open-api-key]').textContent==='我的 API Key'");
  await win.webContents.executeJavaScript("document.querySelector('[data-open-api-key]').click()");
  await check('entry opens its collapsed panel',"document.querySelector('#my-api-key').open");
  await check('URL and model ID copy buttons are available',"!document.querySelector('[data-api-copy=personal-api-url]').disabled && !document.querySelector('[data-api-copy=personal-api-model]').disabled");
  await check('returning visitor cannot copy an old full key',"!document.querySelector('#personal-api-secret') && !document.querySelector('[data-api-copy=personal-api-secret]')");
  await check('team calls have an example without requiring an experiment',"!document.querySelector('.personal-api-example').hidden && !document.querySelector('#personal-api-experiment').required && !document.querySelector('#personal-api-example').textContent.includes('experiment_id')");
  await win.webContents.executeJavaScript("const e=document.querySelector('#personal-api-experiment');e.value=e.options[1].value;e.dispatchEvent(new Event('change'))");
  await check('Python example uses the selected model and no-dependency input',"document.querySelector('#personal-api-example').textContent.includes(document.querySelector('#personal-api-model').value) && document.querySelector('#personal-api-example').textContent.includes('getpass.getpass') && document.querySelector('#personal-api-example').textContent.includes('stream')");
  fs.writeFileSync(path.join(scratch,'personal-api-python.py'),await win.webContents.executeJavaScript("document.querySelector('#personal-api-example').textContent"));
  await win.webContents.executeJavaScript("window.copied=[];Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>window.copied.push(text)}});document.querySelector('[data-api-copy=personal-api-url]').click()");
  await until('URL copied',"document.querySelector('[data-api-copy-status]').textContent==='已复制地址。'");
  await check('secure clipboard gets the exact URL',"window.copied[0]===document.querySelector('#personal-api-url').value");
  await win.webContents.executeJavaScript("document.querySelector('[data-api-copy=personal-api-model]').click()");
  await until('model copied',"window.copied.length===2");
  await check('model copy includes the provider alias',"window.copied[1]===document.querySelector('#personal-api-model').value && window.copied[1].endsWith('/test-model')");
  await win.webContents.executeJavaScript("document.querySelector('[data-api-language=curl]').click();document.querySelector('[data-api-copy=personal-api-example]').click()");
  await until('example copied',"window.copied.length===3");
  await check('curl example and copied code agree and disable streaming',"window.copied[2]===document.querySelector('#personal-api-example').textContent && window.copied[2].includes('YOUR_API_KEY') && window.copied[2].includes('\"stream\":false') && document.querySelector('[data-api-language=curl]').getAttribute('aria-pressed')==='true'");
  await win.webContents.executeJavaScript("const o=document.createElement('option');o.value='2/second-model';o.textContent='Second';document.querySelector('#personal-api-model').append(o);document.querySelector('#personal-api-model').value=o.value;document.querySelector('#personal-api-model').dispatchEvent(new Event('change'))");
  await check('generated requests contain the selected experiment ID',"document.querySelector('#personal-api-example').textContent.includes('\"experiment_id\":'+document.querySelector('#personal-api-experiment').value)");
  await check('changing model updates the example and visible ID',"document.querySelector('#personal-api-example').textContent.includes('2/second-model') && document.querySelector('#personal-api-model-id').textContent==='2/second-model'");
  await win.webContents.executeJavaScript("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('clipboard denied')}}});document.execCommand=command=>{window.fallbackCopy={command,value:document.activeElement.value};return true;};document.querySelector('[data-api-copy=personal-api-model]').click()");
  await until('fallback copy',"Boolean(window.fallbackCopy)");
  await check('HTTP or denied clipboard falls back to exact selected text',"window.fallbackCopy.command==='copy' && window.fallbackCopy.value==='2/second-model' && !document.querySelector('[data-api-copy=personal-api-model]').disabled");
  await win.webContents.executeJavaScript("document.execCommand=()=>false;document.querySelector('[data-api-copy=personal-api-url]').click()");
  await until('manual copy hint',"document.querySelector('[data-api-copy-status]').textContent.includes('手动复制')");
  await check('failed clipboard selects the URL for manual copying',"document.activeElement.id==='personal-api-url' && document.activeElement.selectionEnd===document.activeElement.value.length");
  await open('personal-api-fresh.html');
  await check('new full Key is shown in an opened panel',"document.querySelector('#my-api-key').open && document.querySelector('#personal-api-secret').value.startsWith('fy_')");
  await win.webContents.executeJavaScript("window.copied=[];Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>window.copied.push(text)}});document.querySelector('[data-api-copy=personal-api-secret]').click()");
  await until('key copied',"window.copied.length===1");
  await check('Key copy uses only the new member Key',"window.copied[0]===document.querySelector('#personal-api-secret').value && document.querySelector('[data-api-copy-status]').textContent==='已复制 Key。'");
  await check('full Key is absent from examples and persistent storage',"!document.querySelector('#personal-api-example').textContent.includes(document.querySelector('#personal-api-secret').value) && !JSON.stringify({...localStorage,...sessionStorage}).includes(document.querySelector('#personal-api-secret').value)");
  win.setContentSize(360,760);await delay(100);
  await check('phone layout fits and copy buttons have touch targets',"document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('[data-api-copy]')].every(b=>b.getBoundingClientRect().height>=44)");
  await win.webContents.executeJavaScript("document.querySelector('[data-api-copy=personal-api-secret]').scrollIntoView({block:'center',behavior:'instant'})");
  await check('phone copy Key button has no blocking overlay',"(()=>{const b=document.querySelector('[data-api-copy=personal-api-secret]'),r=b.getBoundingClientRect();return b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})()");
  await win.webContents.executeJavaScript("document.querySelector('.personal-api-create').addEventListener('submit',e=>e.preventDefault());document.querySelector('.personal-api-create').requestSubmit()");
  await check('generation locks against duplicate form submissions',"document.querySelector('#personal-api-generate').disabled && document.querySelector('#personal-api-generate').textContent==='正在生成…'");
  await open('personal-api-empty.html');await win.webContents.executeJavaScript("document.querySelector('#my-api-key').open=true");
  await check('no configured models has an explanation and no bogus example',"document.querySelector('#personal-api-model').disabled && document.querySelector('[data-api-copy=personal-api-model]').disabled && document.querySelector('.personal-api-example').hidden && document.querySelector('#personal-api-model-id').textContent.includes('暂无可用模型') && !document.querySelector('#personal-api-generate').disabled");
  await open('personal-api-escaped.html');await win.webContents.executeJavaScript("document.querySelector('#my-api-key').open=true");
  await win.webContents.executeJavaScript("const e=document.querySelector('#personal-api-experiment');e.value=e.options[1].value;e.dispatchEvent(new Event('change'))");
  fs.writeFileSync(path.join(scratch,'personal-api-escaped-python.py'),await win.webContents.executeJavaScript("document.querySelector('#personal-api-example').textContent"));
  await win.webContents.executeJavaScript("document.querySelector('[data-api-language=curl]').click()");
  await check('quoted model identifiers remain data and are shell quoted',"document.querySelector('#personal-api-model').value.includes('<script>') && document.querySelector('#personal-api-example').textContent.includes(\"'\\\"'\\\"'\")");
  await open('personal-api-desktop.html');await win.webContents.executeJavaScript("document.querySelector('[data-open-api-key]').click()");
  await check('desktop member screen exposes the same API Key tools',"document.querySelector('#my-api-key').open && document.querySelector('[data-api-copy=personal-api-url]') && document.documentElement.scrollWidth<=innerWidth");
  assert.deepEqual(errors,[]);console.log('PASS: no renderer script errors');
  console.log('ALL_PERSONAL_API_CHECKS_PASSED');win.destroy();server.close();app.exit(0);
}).catch(error=>{console.error(error);if(win)win.destroy();server?.close();app.exit(1);});
