// Exercise the real document template and locally hosted native emoji picker.
const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch');
app.setPath('userData',path.join(scratch,'unicode-emoji-client'));app.disableHardwareAcceleration();
let win,server;const errors=[],pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const js=code=>win.webContents.executeJavaScript(code);
app.whenReady().then(async()=>{
  server=http.createServer((req,res)=>{
    const url=new URL(req.url,'http://localhost');
    if(url.pathname==='/document'){
      res.setHeader('Content-Type','text/html; charset=utf-8');
      return res.end(fs.readFileSync(path.join(scratch,'render-pages/unicode-document.html')));
    }
    if(url.pathname.startsWith('/static/')){
      const file=path.resolve(root,url.pathname.slice(1));
      if(file.startsWith(path.join(root,'static')+path.sep)&&fs.existsSync(file)){
        const type={'.js':'text/javascript','.mjs':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png'};
        res.setHeader('Content-Type',type[path.extname(file)]||'application/octet-stream');return res.end(fs.readFileSync(file));
      }
    }
    res.writeHead(404);res.end();
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  win=new BrowserWindow({show:false,width:1300,height:900,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
  win.webContents.on('console-message',(_event,details)=>{if(/Uncaught|SyntaxError|ReferenceError|TypeError/.test(details.message))errors.push(details.message);});
  await win.loadURL('http://127.0.0.1:'+server.address().port+'/document');
  await js("document.querySelector('.comment-emoji-tools button').click()");
  for(let n=0;n<100;n++){
    if(await js("document.querySelector('em-emoji-picker')?.shadowRoot?.querySelectorAll('button').length>100"))break;
    await pause(50);
  }
  assert.equal(await js("document.querySelector('em-emoji-picker')?.shadowRoot?.querySelectorAll('button').length>100"),true);
  assert.equal(await js("document.querySelector('.expression-picker [data-tab=favorites]').hidden && document.querySelector('.expression-picker [data-upload]').hidden"),true);
  assert.equal(await js("document.querySelector('textarea[name=body]').required"),true);
  const catalog=JSON.parse(fs.readFileSync(path.join(root,'static/vendor/emoji-mart/data.json'),'utf8'));
  assert.equal(Object.keys(catalog.emojis).length,1870);
  assert.equal(Object.values(catalog.emojis).reduce((sum,item)=>sum+item.skins.length,0),3395);
  for(const native of ['😁','😂','😄','👿','😉','😊'])assert.ok(Object.values(catalog.emojis).some(item=>item.skins.some(skin=>skin.native===native)));
  const categories=await js("[...document.querySelector('em-emoji-picker').shadowRoot.querySelectorAll('.category[data-id]')].map(node=>node.dataset.id)");
  for(const category of catalog.categories)assert.ok(categories.includes(category.id),category.id+' is available in the panel');
  const locale=JSON.parse(fs.readFileSync(path.join(root,'static/vendor/emoji-mart/zh.json'),'utf8'));
  for(const category of catalog.categories){
    const label=locale.categories[category.id];
    assert.equal(await js(`(()=>{const buttons=[...document.querySelector('em-emoji-picker').shadowRoot.querySelectorAll('button')];const button=buttons.find(item=>item.getAttribute('aria-label')===${JSON.stringify(label)});if(!button)return false;button.click();return true;})()`),true);
    await js("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))");
    await pause(200);
    const position=await js(`(()=>{const shadow=document.querySelector('em-emoji-picker').shadowRoot;const node=shadow.querySelector('.category[data-id="${category.id}"]');return {category:node.getBoundingClientRect().top,picker:shadow.host.getBoundingClientRect().top,selected:shadow.querySelector('button[aria-selected=true]')?.getAttribute('aria-label')};})()`);
    assert.ok(position.category>=position.picker&&position.category<position.picker+150,JSON.stringify(position));
  }
  await js(`(()=>{const buttons=[...document.querySelector('em-emoji-picker').shadowRoot.querySelectorAll('button')];buttons.find(item=>item.getAttribute('aria-label')===${JSON.stringify(locale.categories.people)}).click();})()`);
  await pause(100);
  // The native glyph is the text inside an emoji button, not an uploaded image.
  const selected=await js(`(()=>{
    const picker=document.querySelector('em-emoji-picker');
    const buttons=[...picker.shadowRoot.querySelectorAll('button')];
    const button=buttons.find(item=>/^[\\u{1F300}-\\u{1FAFF}]/u.test(item.textContent.trim()));
    if(!button)throw Error('No native emoji button found');
    const native=button.textContent.trim();button.click();return {native,value:document.querySelector('textarea[name=body]').value};
  })()`);
  assert.equal(selected.value,selected.native);
  assert.equal(await js("document.querySelector('.expression-picker').hidden"),true);
  await js("document.querySelector('textarea[name=body]').value='😁😂😄👿😉😊 👍🏽 👩‍🔬 ❤️';document.querySelector('.comment-emoji-tools button').click()");
  for(let n=0;n<100;n++){
    if(await js("!document.querySelector('.expression-picker').hidden&&!document.querySelector('.expression-picker [role=status]').textContent&&document.querySelector('em-emoji-picker')?.shadowRoot?.querySelectorAll('button').length>100"))break;
    await pause(50);
  }
  assert.equal(await js("!document.querySelector('.expression-picker [role=status]').textContent && document.querySelector('em-emoji-picker')?.shadowRoot?.querySelectorAll('button').length>100"),true);
  console.log('PASS: all eight categories available; 1870 emoji entries / 3395 variants, including all six requested emoji');
  await js("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))");
  await pause(400);
  fs.writeFileSync(path.join(scratch,'unicode-document-picker.png'),(await win.webContents.capturePage()).toPNG());
  const rect=await js("(()=>{const r=document.querySelector('.expression-picker').getBoundingClientRect();return {x:Math.floor(r.x),y:Math.floor(r.y),width:Math.ceil(r.width),height:Math.ceil(r.height)};})()");
  fs.writeFileSync(path.join(scratch,'unicode-emoji-panel.png'),(await win.webContents.capturePage(rect)).toPNG());
  assert.deepEqual(errors,[]);
  console.log('PASS: document picker displays native emoji, inserts Unicode text, preserves required input and hides unsupported sticker controls');
  server.close();app.exit(0);
}).catch(error=>{console.error(error);server?.close();app.exit(1);});
