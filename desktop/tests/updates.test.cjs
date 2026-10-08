const test=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const {Updates}=require('../updates.cjs');
const {validateManifest,newer}=require('../free-mac-update.cjs');
const bytes=Buffer.alloc(4096,7),sha512=crypto.createHash('sha512').update(bytes).digest('base64');
function manifest(arch='arm64',version='0.2.9'){return {version,files:{[arch]:{name:`ResearchWorkbench-${version}-mac-${arch}.dmg`,size:bytes.length,sha512}}};}
const app={isPackaged:true,getVersion:()=> '0.2.8'};
test('version comparisons reject downgrades and malformed versions',()=>{
 assert.equal(newer('0.2.9','0.2.8'),true);for(const version of ['0.2.7','0.2.8','v0.2.9','0.2.9-beta','../0.2.9'])assert.equal(newer(version,'0.2.8'),false);
});
test('manifest binds the installer to architecture/version/name/size/hash',()=>{
 const valid=validateManifest(manifest(),'0.2.9','arm64');assert.match(valid.url,/\/v0.2.9\/ResearchWorkbench-0.2.9-mac-arm64.dmg$/);
 for(const change of [{name:'../evil.dmg'},{name:'other.exe'},{size:0},{size:600*1024*1024},{sha512:'wrong'}]){
   const data=manifest();Object.assign(data.files.arm64,change);assert.throws(()=>validateManifest(data,'0.2.9','arm64'));
 }
 assert.throws(()=>validateManifest(manifest(),'0.2.9','x64'));assert.throws(()=>validateManifest(manifest(),'0.3.0','arm64'));
});
test('Windows updater requires explicit download, tracks progress and installs only explicitly',async()=>{
 const updater=new EventEmitter();let checks=0,installed=0,downloads=0;
 updater.checkForUpdates=async()=>{checks++;updater.emit('checking-for-update');updater.emit('update-available',{version:'0.2.9',files:[{url:'installer.exe',size:12345}]});};
 updater.quitAndInstall=(silent,restart)=>{assert.equal(silent,true);assert.equal(restart,true);installed++;};
 updater.downloadUpdate=async()=>{downloads++;updater.emit('download-progress',{percent:43.4});};
 const events=[],updates=new Updates(app,value=>events.push(value),{platform:'win32',updater,fetch:async()=>Response.json({version:'0.2.9',features:[],fixes:[]})});
 assert.equal(updater.autoDownload,false);assert.equal(updater.autoInstallOnAppQuit,false);
 await assert.rejects(updates.install());await updates.check();assert.equal(updates.snapshot().state,'available');assert.equal(downloads,0);assert.equal(updates.snapshot().size_bytes,12345);await updates.download();assert.equal(downloads,1);assert.equal(updates.snapshot().percent,43);await updates.check();assert.equal(checks,1);
 updater.emit('update-downloaded',{version:'0.2.9'});assert.equal(installed,0);await updates.install();assert.equal(installed,1);
 updater.emit('error',Error('network'));assert.equal(updates.snapshot().state,'error');assert.ok(events.length>=4);
});
test('preview installs remain disabled',async()=>{const updates=new Updates({...app,isPackaged:false},()=>{});assert.equal((await updates.check()).state,'disabled');await assert.rejects(updates.install());});
test('unsigned Mac waits for download confirmation and verifies the DMG before opening',async t=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'workbench-update-'));t.after(()=>fs.rm(dir,{recursive:true,force:true}));let opened=[],requests=[],fail=false;
 const data=manifest();
 const fetch=async url=>{requests.push(url);if(url.endsWith('/latest'))return Response.json({tag_name:'v0.2.9',draft:false,prerelease:false,assets:[data.files.arm64]});if(url.endsWith('.json'))return Response.json(data);return new Response(fail?Buffer.alloc(4096,8):bytes);};
 const updates=new Updates({...app,getPath:()=>dir},()=>{},{platform:'darwin',signature:()=>({status:1}),fetch,arch:'arm64',shell:{openPath:async file=>{opened.push(file);return '';}}});
 assert.equal(updates.snapshot().mode,'manual-mac');await updates.check();assert.equal(updates.snapshot().state,'available');assert.ok(!requests.some(v=>v.endsWith('.dmg')));await updates.download();assert.equal(updates.snapshot().state,'downloaded');assert.equal(opened.length,0);
 assert.ok(requests.every(url=>url.startsWith('https://github.com/L1nYux/FYrepo/')||url.startsWith('https://api.github.com/repos/L1nYux/FYrepo/')));
 await updates.install();assert.equal(opened.length,1);assert.deepEqual(await fs.readFile(opened[0]),bytes);
 await fs.writeFile(opened[0],'tampered');await assert.rejects(updates.install());assert.equal(opened.length,1);assert.equal(updates.snapshot().state,'error');
 fail=true;await updates.check();await updates.download();assert.equal(updates.snapshot().state,'error');assert.ok(!(await fs.readdir(path.join(dir,'verified-updates'))).some(name=>name.endsWith('.part')));
 fail=false;await updates.check();await updates.download();assert.equal(updates.snapshot().state,'downloaded');
});
test('Mac without a release has friendly feedback and does not download',async()=>{
 const updates=new Updates(app,()=>{},{platform:'darwin',signature:()=>({status:1}),fetch:async()=>new Response('',{status:404}),shell:{}});
 await updates.check();assert.equal(updates.snapshot().state,'current');assert.equal(updates.snapshot().nextVersion,null);
});
test('network errors can be retried without permanently disabling updates',async()=>{
 let broken=true;const updates=new Updates(app,()=>{},{platform:'darwin',signature:()=>({status:1}),fetch:async()=>{if(broken)throw Error('offline');return new Response('',{status:404});},shell:{}});
 await updates.check();assert.equal(updates.snapshot().state,'error');broken=false;await updates.check();assert.equal(updates.snapshot().state,'current');
});


test('Windows distinguishes an ahead-of-channel install and cannot downgrade',async()=>{
 const updater=new EventEmitter();
 updater.checkForUpdates=async()=>updater.emit('update-not-available',{version:'0.3.1'});
 const updates=new Updates({...app,getVersion:()=> '0.4.4'},()=>{},{platform:'win32',updater});
 await updates.check();assert.equal(updates.snapshot().state,'current');assert.equal(updates.snapshot().nextVersion,null);
 assert.equal(updates.snapshot().channelVersion,'0.3.1');assert.match(updates.snapshot().message,/0\.4\.4/);assert.match(updates.snapshot().message,/0\.3\.1/);
 assert.equal(updater.allowDowngrade,false);assert.equal(updater.allowPrerelease,false);await assert.rejects(updates.download());
});
test('unsigned Mac distinguishes an ahead-of-channel install without fetching installers',async()=>{
 const requests=[];const updates=new Updates({...app,getVersion:()=> '0.4.4'},()=>{},{platform:'darwin',signature:()=>({status:1}),shell:{},fetch:async url=>{requests.push(url);return Response.json({tag_name:'v0.3.1',prerelease:false,draft:false});}});
 await updates.check();assert.equal(updates.snapshot().state,'current');assert.equal(updates.snapshot().nextVersion,null);assert.equal(updates.snapshot().channelVersion,'0.3.1');assert.match(updates.snapshot().message,/0\.4\.4/);assert.equal(requests.length,1);await assert.rejects(updates.download());
});
