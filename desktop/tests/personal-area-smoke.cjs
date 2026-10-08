// Exercise actual native shell markup, styles and sandboxed preload with fixture IPC.
const {app,BrowserWindow,ipcMain}=require('electron');
require('./runtime.cjs').installRuntime(app);
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),scratch=path.join(root,'.test-scratch');
app.setPath('userData',path.join(scratch,'personal-shell-client'));app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
let win;const errors=[],requests=[];
const state={authenticated:true,backend:'ready',current:'workspace',mode:'remote',serverUrl:'http://localhost',username:'fixture',accountId:'fixture',isAdmin:false,canManageApi:false,gitEnabled:true,githubEnabled:true,aiEnabled:true,connection:{url:'http://localhost'},updates:{state:'disabled',message:'Fixture'},appearance:{theme:'light',mode:'light',wallpaper:'',opacity:18,blur:4},version:'0.4.0',dataPath:'fixture',loading:{phase:'idle',generation:1},workspacePath:'/projects/1/',mePath:'/me/',workspaceNavigation:{loaded:true,spaces:[{id:'1',name:'个人'},{id:'2',name:'合作团队'}],projects:[{title:'法学论文大模型测评能力与边界研究项目',owner:'合作团队',space:'2',path:'/projects/1/',tasks:[{title:'实验设计与记录',path:'/tasks/1/',children:[]}]}],competitions:[{title:'2026年科研创新比赛',owner:'合作团队',space:'2',path:'/competitions/1/'}],experiments:[{title:'中文法学推理实验',owner:'个人',space:'1',path:'/experiments/1/'}]}};
const emit=()=>win.webContents.send('desktop:state',state);
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const js=code=>win.webContents.executeJavaScript(code);
async function until(label,code){for(let n=0;n<60;n++){if(await js(code)){console.log('PASS:',label);return;}await pause(50);}throw Error(label);}
async function screenshot(name,rect){await js('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');await pause(130);fs.writeFileSync(path.join(scratch,name+'.png'),(await win.webContents.capturePage(rect)).toPNG());}
app.whenReady().then(async()=>{
 for(const channel of ['desktop:info','settings:get','appearance:get','connection:get','updates:status','desktop:presentation-ready'])ipcMain.handle(channel,()=>({ok:true,data:channel==='appearance:get'?state.appearance:channel==='connection:get'?state.connection:channel==='updates:status'?state.updates:state}));
 ipcMain.handle('desktop:navigate',(_event,name)=>{state.current=name;emit();return {ok:true,data:name};});
 ipcMain.handle('desktop:workspace-navigate',(_event,destination)=>{requests.push(destination);state.current=destination.startsWith('/me/')?'me':'workspace';if(state.current==='me')state.mePath=destination;else state.workspacePath=destination;emit();return {ok:true,data:state.current};});
 ipcMain.handle('desktop:workspace-branch',()=>({ok:true,data:{project:{tasks:state.workspaceNavigation.projects[0].tasks},truncated:false}}));
 win=new BrowserWindow({show:false,width:1380,height:880,webPreferences:{preload:path.join(root,'desktop/preload.cjs'),sandbox:true,contextIsolation:true,backgroundThrottling:false}});
 win.webContents.on('console-message',(_event,detail)=>{if(detail.level==='error')errors.push(detail.message);});
 await win.loadFile(path.join(root,'desktop/ui/index.html'));await pause(200);emit();
 await js("document.querySelectorAll('.workspace-resource-section').forEach(el=>el.open=true)");
 await until('native resource titles use readable text styles',"[...document.querySelectorAll('.workspace-item-title')].filter(el=>el.getBoundingClientRect().width>0).every(el=>parseFloat(getComputedStyle(el).fontSize)===13&&el.getBoundingClientRect().width>100)&&document.querySelectorAll('.workspace-item-title').length>=3");
 assert.equal(await js("document.querySelector('[data-workspace-path=\"/projects/\"]').classList.contains('selected')"),false,'resource category does not duplicate selected project highlight');
 await screenshot('v4-native-navigation',{x:0,y:84,width:232,height:650});
 await js("document.querySelector('.app-tabs [data-page=me]').click()");
 await until('me has its own native sidebar',"!document.querySelector('#me-page').hidden&&document.querySelector('#workspace-page').hidden&&document.querySelector('.app-tabs [data-page=me]').getAttribute('aria-current')==='page'");
 await js("document.querySelector('[data-me-path=\"/me/talent/\"]').click()");
 await until('talent profile stays selected inside me',"document.querySelector('[data-me-path=\"/me/talent/\"]').getAttribute('aria-current')==='page'");
 assert.equal(requests.at(-1),'/me/talent/');
 await screenshot('v4-native-me',{x:0,y:84,width:248,height:650});
 await js("document.querySelector('.app-tabs [data-page=workspace]').click();document.querySelector('[data-workspace-path=\"/finance/teams/\"]').click()");
 await pause(120);assert.equal(requests.at(-1),'/finance/teams/');
 const fatal=errors.filter(value=>/Uncaught|SyntaxError|ReferenceError|TypeError/.test(value));assert.deepEqual(fatal,[]);
 console.log('PASS: native personal navigation and resource branches');app.exit(0);
}).catch(error=>{console.error(error);app.exit(1);});
