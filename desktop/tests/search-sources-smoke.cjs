const {app,BrowserWindow}=require('electron');require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch'),fixtures=path.join(scratch,'render-pages');
const sources=[{kind:'web',url:'https://one.example/page',id:'https://one.example/page',title:'官方来源',snippet:'真实来源摘要',citation:1,read:true},{kind:'web',url:'https://two.example/page',id:'https://two.example/page',title:'相关报道',snippet:'搜索摘要',citation:2,read:false}];
let win,server,native=false;const errors=[];const delay=ms=>new Promise(r=>setTimeout(r,ms));
const js=code=>win.webContents.executeJavaScript(code);
async function until(label,code){const stop=Date.now()+15000;while(Date.now()<stop){if(await js(code))return;await delay(50);}throw Error('Timed out '+label);}
async function check(label,code){assert.equal(await js(code),true,label);console.log('PASS:',label);}
app.disableHardwareAcceleration();app.whenReady().then(async()=>{
 server=http.createServer((req,res)=>{
  const u=new URL(req.url,'http://localhost'),json=value=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify(value));};
  if(u.pathname==='/api-pool/catalog/')return json({models:[{id:1,configured:true,provider:'Test',label:'Test'}],budget:{member_week:{limit:20},extra:{remaining_points:0}}});
  if(u.pathname==='/assistant/conversations/')return json({conversations:[],history_days:0});
  if(u.pathname==='/assistant/start/'){let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>json({job:body.includes('测试工具失败')?'source-fail':'source-job',conversation:1,title:'来源测试'}));return;}
  if(u.pathname==='/assistant/jobs/source-fail/')return json({state:'error',request:{text:'测试工具失败'},result:{error:'搜索服务未返回可用结果，请重试。',sources:[],elapsed_seconds:1,activity:[{tool:'search_web',label:'搜索互联网',status:'error',error:'搜索服务不可用',count:0,pages:[]}]}});
  if(u.pathname.startsWith('/assistant/jobs/'))return json({state:'done',result:{text:'结论有实际来源。[1] 未提供的编号保留文字：[99]',reasoning:'厂商返回的简短思考',sources,activity:[{tool:'search_web',label:'搜索互联网',query:'测试关键词',count:2,pages:sources},{tool:'read_web',label:'读取网页正文',count:1,pages:[sources[0]]}],elapsed_seconds:2,calls:2,tokens:50,cost_cny:'0'}});
  if(u.pathname==='/assistant/web-preview/')return json({source:sources[0],content:'公开网页正文',truncated:false});
  if(u.pathname==='/messages/unread/')return json({total:0});
  let file=u.pathname.startsWith('/static/')?path.resolve(root,u.pathname.slice(1)):path.join(fixtures,u.pathname==='/announcements/'?'release-announcement.html':'assistant.html');
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');
  let data=fs.readFileSync(file);if(file.endsWith('.html')){
    const mock='<script>window.updateOpens=0;window.workbenchUpdates={status:async()=>({ok:true,data:{version:"0.2.11",state:"available",nextVersion:"0.2.12",size_bytes:10485760}}),open:async()=>{window.updateOpens++;return {ok:true}},onState:f=>window.updateStateCallback=f};'+(native?'window.browserOpens=[];window.workbenchBrowser={open:async url=>{window.browserOpens.push(url);return {ok:true}},onState:f=>window.browserStateCallback=f};':'')+'</script>';
    data=Buffer.from(data.toString('utf8').replace('<head>','<head>'+mock));
  }res.end(data);
 });await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 win=new BrowserWindow({show:false,width:1280,height:820,webPreferences:{offscreen:true,sandbox:true,nodeIntegration:false,contextIsolation:true}});win.webContents.on('console-message',(_e,_level,message)=>{if(String(message).includes('Uncaught'))errors.push(message);});
 await win.loadURL(origin+'/announcements/');await until('release actions', 'window.updateStateCallback!==undefined');
 await js('document.querySelector("[data-release-update]").click()');
 await check('announcement invokes the shared updater','window.updateOpens===1');
 await js('document.querySelector("[data-release-feature]").click()');
 await check('new feature requires update without changing location','window.updateOpens===2 && location.pathname==="/announcements/" && document.querySelector(".release-status").textContent.includes("先更新")');
 await js('window.updateStateCallback({version:"0.2.11",state:"downloading",percent:42,size_bytes:10485760,message:"下载中"})');
 await check('announcement shares live progress','document.querySelector("[data-release-progress]").value===42 && document.querySelector(".release-status").textContent.includes("42%")');
 await win.loadURL(origin+'/assistant/');await until('model ready','!document.querySelector("#assistant-send").disabled');
 await js('document.querySelector("#assistant-input").value="测试搜索";document.querySelector("#assistant-form").requestSubmit()');
 await until('answer','Boolean(document.querySelector(".assistant-web-sources"))');
 await check('source and read totals are separate','document.querySelector(".assistant-process summary").textContent.includes("2 个网页 · 浏览 1 个页面")');
 await check('citations only link known sources','document.querySelectorAll(".source-citation").length===1 && document.querySelector(".assistant-row.assistant .assistant-text").textContent.includes("[99]")');
 await js('document.querySelector(".source-citation").click()');
 await check('inline citation opens and highlights matching source','!document.querySelector(".source-results-panel").hidden && document.querySelector(".source-result.highlight").dataset.citation==="1"');
 await check('panel has two metadata-rich sources','document.querySelectorAll(".source-result").length===2 && document.querySelector(".source-results-list").textContent.includes("已阅读正文") && document.querySelector(".source-results-list").textContent.includes("搜索摘要")');
 await js('document.querySelector(".source-result a").click()');await until('web body','document.querySelector(".web-source-content")?.textContent.includes("公开网页正文")');
 await js('document.querySelector(".web-source-panel [data-expand]").click()');
 await check('web reader expands while preserving its source and content','document.querySelector(".web-source-panel").classList.contains("is-expanded") && document.querySelector(".web-source-panel").getBoundingClientRect().width>1000 && document.querySelector(".web-source-content").textContent.includes("公开网页正文") && document.querySelector(".web-source-panel [data-external]").target==="_blank"');
 await js('document.querySelector(".web-source-panel [data-expand]").click()');
 await js('document.querySelector(".web-source-panel [data-close]").click()');
 await check('web reader returns to sources without replacing chat','!document.querySelector(".source-results-panel").hidden && document.querySelector(".assistant-row.assistant .assistant-text").textContent.includes("结论")');
 await delay(350);fs.writeFileSync(path.join(scratch,'search-sources-desktop.png'),(await win.webContents.capturePage()).toPNG());
 win.setContentSize(390,780);await delay(80);await check('mobile source drawer fills screen without horizontal overflow','document.documentElement.scrollWidth<=innerWidth && document.querySelector(".source-results-panel").getBoundingClientRect().width===innerWidth');
 await delay(350);fs.writeFileSync(path.join(scratch,'search-sources-phone.png'),(await win.webContents.capturePage()).toPNG());
 await js('document.querySelector(".source-results-panel header button").click()');await check('closing returns focus to the citation','document.querySelector(".source-results-panel").hidden && document.activeElement.classList.contains("source-citation")');
 native=true;win.setContentSize(1280,820);await win.loadURL(origin+'/assistant/');await until('native model ready','!document.querySelector("#assistant-send").disabled');
 await js('document.querySelector("#assistant-input").value="原生浏览器";document.querySelector("#assistant-form").requestSubmit()');await until('native sources','Boolean(document.querySelector(".assistant-web-sources"))');
 await js('document.querySelector(".assistant-web-sources").click();document.querySelector(".source-result a").click()');
 await check('native source link opens isolated browser and hides the list','window.browserOpens[0]==="https://one.example/page" && document.querySelector(".source-results-panel").hidden');
 await js('window.browserStateCallback({visible:false})');
 await check('native return restores source list','!document.querySelector(".source-results-panel").hidden && document.querySelectorAll(".source-result").length===2');
 await js('document.querySelector(".source-results-panel header button").click();document.querySelector("#assistant-new").click();document.querySelector("#assistant-input").value="测试工具失败";document.querySelector("#assistant-form").requestSubmit()');
 await until('tool failure retry','Boolean(document.querySelector("[data-assistant-retry]"))');
 await check('tool failure appears beside the message with explicit retry','document.querySelector("#assistant-thread").textContent.includes("搜索服务未返回可用结果") && document.querySelector(".assistant-process summary").textContent.includes("未完成") && !document.querySelector("#assistant-thread").textContent.includes("我来帮你搜索")');
 await js('window.workbenchSources.process(document.querySelector(".assistant-process"),{activity:[{tool:"read_attachment",label:"读取附件正文",status:"success",count:1,pages:[]}],sources:[]})');
 await check('non-web tools use material units rather than fake webpage counts','document.querySelector(".assistant-process summary").textContent.includes("资料读取") && document.querySelector(".source-process-body").textContent.includes("1 份附件")');
 assert.deepEqual(errors,[]);console.log('ALL_SEARCH_SOURCES_CHECKS_PASSED');win.destroy();server.close();app.exit(0);
}).catch(e=>{console.error(e);win?.destroy();server?.close();app.exit(1);});
