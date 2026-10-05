const {app,BrowserWindow}=require('electron');
require('./runtime.cjs').installRuntime(app);
const assert=require('node:assert/strict');
const {PublicBrowser,address}=require('../public-browser.cjs');
app.disableHardwareAcceleration();
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.whenReady().then(async()=>{
  const win=new BrowserWindow({show:false,width:1000,height:700,webPreferences:{sandbox:true}});
  let last;const browser=new PublicBrowser(win,value=>last=value);
  browser.view.setBounds({x:560,y:140,width:440,height:560});
  // Generated public-page responses avoid a dependency on live websites in CI.
  browser.view.webContents.session.protocol.handle('https',request=>new Response('<title>Public source</title><h1>Readable public page</h1><a href="https://example.org/next">Next</a>',{headers:{'Content-Type':'text/html'}}));
  await browser.open('https://example.org/');
  assert.equal(last.visible,true);assert.equal(last.title,'Public source');
  console.log('PASS: public source opens in a separate browser view');
  const isolated=await browser.view.webContents.executeJavaScript("typeof require==='undefined' && typeof desktop==='undefined' && typeof workbenchBrowser==='undefined'");
  assert.equal(isolated,true);assert.equal(browser.view.webContents.getLastWebPreferences().sandbox,true);
  console.log('PASS: public page has no Node or workspace APIs');
  await browser.open('https://example.org/next');browser.action('back');await wait(100);
  assert.equal(browser.view.webContents.getURL(),'https://example.org/');
  console.log('PASS: back restores the previous source');
  browser.action('reload');await wait(150);assert.equal(browser.view.webContents.getURL(),'https://example.org/');assert.equal(browser.view.webContents.isDestroyed(),false);
  browser.action('close');assert.equal(last.visible,false);assert.equal(last.loading,false);
  console.log('PASS: refresh and close remain usable');
  for(const url of ['http://127.0.0.1/','http://localhost/','http://server.local/','http://198.18.0.1/'])assert.throws(()=>address(url));
  console.log('PASS: local files, privileged schemes and internal addresses are blocked');
  win.destroy();app.exit(0);
}).catch(error=>{console.error(error.stack);app.exit(1);});
