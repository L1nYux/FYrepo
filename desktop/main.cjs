const { app, BrowserWindow, WebContentsView, ipcMain, dialog, shell, Menu, nativeTheme } = require('electron');

const { spawn } = require('node:child_process');
const { Repository, DOCUMENTS } = require('./repository.cjs');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const crypto = require('node:crypto');
const { Appearance } = require('./appearance.cjs');
const {resolveSettingsPage,workspacePath:validateWorkspacePath,workspaceMenu,publicPagePath,conversationPath} = require('./navigation.cjs');
const {Connection} = require('./connection.cjs');
const {Updates} = require('./updates.cjs');
const {PresentationGate} = require('./loading.cjs');

const APP_ROOT = path.resolve(__dirname, '..');
// An explicit source-only development command; never a member-facing mode.
const LOCAL_PREVIEW = !app.isPackaged && process.argv.includes('--local-preview');
const STATE = path.resolve(process.env.WORKBENCH_DESKTOP_STATE || (LOCAL_PREVIEW ? path.join(__dirname, '.local') : path.join(app.getPath('appData'), 'ResearchWorkbench')));
try {
  fs.mkdirSync(STATE, {recursive:true});
  if (!app.isPackaged && !LOCAL_PREVIEW && !process.env.WORKBENCH_DESKTOP_STATE) {
    const previous = path.join(path.resolve(APP_ROOT, '../..'), 'work', 'desktop-preview');
    // Copy only client preferences, never a development database or provider keys.
    for (const name of ['appearance.json','wallpaper-image','connections.json','repository.json','server-connection.json']) {
      const from=path.join(previous,name), to=path.join(STATE,name);
      if (fs.existsSync(from) && !fs.existsSync(to)) fs.copyFileSync(from,to,fs.constants.COPYFILE_EXCL);
    }
  }
  app.setPath('userData', path.join(STATE, 'client'));
} catch (error) {
  dialog.showErrorBox('无法打开工作台配置目录', '请检查目录是否可写：'+STATE+'\n'+String(error.message));
  app.exit(1);
  return;
}
const connection = new Connection(STATE);
if (LOCAL_PREVIEW) connection.value = {mode:'local', url:''};
let connectionEpoch = 0, csrfToken = '', connectionBusy = false;
let updates;
app.setName('科研工作台');
if (process.platform === 'win32') app.setAppUserModelId('org.fyrepo.researchworkbench');
let window, content, accountView, editView, editTarget, editAllowed, backend, origin, username = '', current = 'login', repository = null;
let publicBrowser;
let accountAvatar='', avatarSource='', avatarEpoch=0;
const {fetchAvatar}=require('./avatar.cjs');
function updateAvatar(value){
  const url=value.avatarUrl||'', source=origin+url;
  if(source===avatarSource)return;
  avatarSource=source;accountAvatar='';const generation=++avatarEpoch;
  if(!url){state();return;}
  fetchAvatar(content.webContents.session,origin,url).then(image=>{
    if(generation!==avatarEpoch||!authenticated)return;
    accountAvatar=image;state();
  }).catch(()=>{if(generation===avatarEpoch)avatarSource='';});
}
let authenticated = false, requiresSetup = false, setupUsername = '', authBusy = false, authEpoch = 0, needsEmailBinding = false;
let mustChangePassword=false;
let quitting = false, backendState = 'starting', accountMenuOpen = false, isAdmin = false, canManageApi = false;
let workspacePath = '/workspace/', messagesPath = '/messages/';
let preparedBusinessPath='/workspace/';
let businessVisible = false, unreadTotal = 0, unreadTimer, unreadBusy = false, restoringHistory = false;
const navigationHistory = [];
const UI_URL = pathToFileURL(path.join(__dirname, 'ui/index.html')).href;
const EDIT_URL = pathToFileURL(path.join(__dirname, 'ui/edit-menu.html')).href;
const appearance = new Appearance(STATE);
const ACCOUNT_URL = pathToFileURL(path.join(__dirname, 'ui/account.html')).href;
const BUSINESS_CSS = fs.readFileSync(path.join(__dirname, 'business.css'), 'utf8');
const TOKEN = crypto.randomBytes(32).toString('hex');
const SETTINGS_FILE = path.join(STATE, 'connections.json');
const defaults = { gitEnabled: true, githubEnabled: true, aiEnabled: true, workspaceCollapsed:false };
let workspaceCollapsed=Boolean(settings().workspaceCollapsed), workspaceWidth=workspaceCollapsed?68:232, workspaceResizeTimer;
const REPOSITORY_FILE = path.join(STATE, 'repository.json');
const {Repositories,deletionTarget}=require('./repositories.cjs');
const repositories=new Repositories(REPOSITORY_FILE);
repository=repositories.selected;
const localRepository = new Repository(repository, () => settings().gitEnabled);
localRepository.plain=Boolean(repositories.current()?.plain);
function applyRepository(){repository=repositories.selected;localRepository.directory=repository;localRepository.plain=Boolean(repositories.current()?.plain);}
let repositoryDraft = null, confirmingClose = false;

function closeEditMenu() { if(editView)editView.setVisible(false);editTarget=null;editAllowed=null; }
function installEditMenu(contents) {
  contents.on('context-menu',async (_event,params)=>{
    if(!editView||!window||window.isDestroyed())return;
    if(contents===content.webContents){
      const messageMenuOpen=await contents.executeJavaScript("Boolean(document.querySelector('[data-message-menu]:not([hidden])'))").catch(()=>false);
      if(messageMenuOpen||contents.isDestroyed()||!window||window.isDestroyed())return;
    }
    editTarget=contents;const flags=params.editFlags;
    editAllowed={cut:params.isEditable&&flags.canCut,copy:flags.canCopy,paste:params.isEditable&&flags.canPaste,selectAll:flags.canSelectAll};
    const offset=contents===content.webContents?content.getBounds():contents===accountView.webContents?accountView.getBounds():{x:0,y:0};
    const [width,height]=window.getContentSize();
    editView.setBounds({x:Math.max(0,Math.min(width-148,offset.x+params.x)),y:Math.max(0,Math.min(height-136,offset.y+params.y)),width:148,height:136});
    editView.webContents.send('desktop:edit-menu',{allowed:editAllowed,theme:appearance.snapshot(nativeTheme.shouldUseDarkColors).theme});
    editView.setVisible(true);editView.webContents.focus();
  });
}
function applyEmbeddedAppearance() {
  if(!origin||!content||content.webContents.isDestroyed()||!content.webContents.getURL().startsWith(origin+'/'))return Promise.resolve();
  content.webContents.send('desktop:business-presentation', businessPresentation(content.webContents.getURL()));
  return Promise.resolve();
}
function businessPresentation(url) {
  if(!origin || new URL(url).origin!==origin)return null;
  const location=new URL(url);
  return {css:BUSINESS_CSS,settings:Boolean(resolveSettingsPage(location,routes,settingsPages)),
    appearance:appearance.snapshot(nativeTheme.shouldUseDarkColors),generation:presentation.generation};
}
async function syncAppearance() {
  const mode=appearance.options().mode;if(nativeTheme.themeSource!==mode)nativeTheme.themeSource=mode;
  const value=appearance.snapshot(nativeTheme.shouldUseDarkColors);
  if(window&&!window.isDestroyed()) {window.setBackgroundColor(value.theme==='dark'?'#202020':'#f7f7f7');window.webContents.send('desktop:appearance',value);}
  if(accountView&&!accountView.webContents.isDestroyed())accountView.webContents.send('desktop:appearance',{theme:value.theme});
  await applyEmbeddedAppearance();return value;
}
function settings() {
  try { return { ...defaults, ...JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8')) }; }
  catch { return { ...defaults }; }
}
function publicSettings() { const value=settings(); return {gitEnabled:value.gitEnabled,githubEnabled:value.githubEnabled,aiEnabled:value.aiEnabled,needsEmailBinding,workspaceCollapsed,mustChangePassword}; }

let pageLoading=false, shellReady=false, retryPath=null, restoredGeneration=null, workspaceNavigation={projects:[],loaded:false};
const presentation = new PresentationGate(()=>state(),()=>{
  shellReady=authenticated;
  if(content)content.setVisible(Boolean(authenticated&&businessVisible));
  if(accountView)accountView.setVisible(authenticated);
  if(authenticated&&businessVisible&&!accountMenuOpen&&window?.isFocused())content.webContents.focus();
  updateBusinessActivity();
});
function revealLocalShell(){
  if(!authenticated||!presentation.readySurfaces.has('chrome')||!presentation.readySurfaces.has('account'))return;
  shellReady=true;presentation.full=false;accountView.setVisible(true);state();
}
function beginPresentation(full, message) {
  closeEditMenu();closeAccountMenu();
  if(content)content.setVisible(false);
  if(accountView&&full)accountView.setVisible(false);
  presentation.begin(full,message);
}
function loadingLeft(){return current==='workspace'?(workspaceCollapsed?68:232):settingsPages.has(current)?248:0;}
async function retryPresentation(){
  if(presentation.pending)return;
  if(backendState!=='ready'||!origin){await startConnection();return;}
  if(!authenticated){await showLogin();return;}
  await navigate(current,retryPath);
}
function state(extra = {}) {
  const value = { loading:presentation.snapshot(),loadingLeft:loadingLeft(),workspaceNavigation,workspacePath,pageLoading, mode:connection.value.mode, serverUrl:connection.value.url, current, backend: backendState, username, isAdmin, canManageApi, authenticated, requiresSetup, setupUsername, accountMenuOpen, unreadTotal, gitEnabled:settings().gitEnabled, aiEnabled:settings().aiEnabled, backAvailable: settingsPages.has(current) ? authenticated && Boolean(origin) : navigationHistory.length > 1,
    taskDetail: Boolean(origin && current === 'workspace' && content && content.webContents.getURL().startsWith(origin + '/tasks/') && /^\/tasks\/\d+\/$/.test(new URL(content.webContents.getURL()).pathname)), ...extra };
  value.needsEmailBinding=needsEmailBinding;
  value.workspaceCollapsed=workspaceCollapsed;
  value.mustChangePassword=mustChangePassword;
  value.avatar=accountAvatar;
  if (window && !window.isDestroyed()) window.webContents.send('desktop:state', value);
  if (accountView && !accountView.webContents.isDestroyed()) accountView.webContents.send('desktop:state', value);
}
function trusted(event) {
  const host = window && event.sender === window.webContents && event.senderFrame.url === UI_URL;
  const account = accountView && event.sender === accountView.webContents && event.senderFrame.url === ACCOUNT_URL;
  if (!host && !account) throw Error('无权调用桌面功能。');
}
let repositoryChangeBusy=false;
function handle(name, callback) {
  ipcMain.handle(name, async (event, ...args) => {
    trusted(event);
    let repositoryChangeAcquired=false;
    try {
      if(name.startsWith("repo:") && repositoryChangeBusy)throw Error("仓库正在切换，请稍后。 ");
      if(["repo:select","repo:choose","repo:new-file","repo:remove"].includes(name)){repositoryChangeBusy=true;repositoryChangeAcquired=true;}
      if (!authenticated && !['desktop:info','desktop:window','desktop:external','auth:status','auth:login','auth:register','auth:setup','auth:forgot-password','connection:get','connection:save','updates:status','updates:check','updates:download','updates:install','desktop:presentation-ready','desktop:loading-retry','desktop:loading-dismiss'].includes(name)) throw Error('请先登录工作台。');
      if(mustChangePassword && (name.startsWith('repo:') || name.startsWith('settings:') || name==='desktop:workspace-navigate'))throw Error('请先设置新密码。');
      return { ok: true, data: await callback(...args) };
    }
    catch (error) { return { ok: false, error: String(error.message).slice(0, 600) }; }
    finally {if(repositoryChangeAcquired)repositoryChangeBusy=false;}
  });
}
function bounds() {
  if (!content || !window || window.isDestroyed()) return;
  const [width, height] = window.getContentSize();
  const left=current==='workspace'?Math.round(workspaceWidth):loadingLeft();
  const browserWidth=publicBrowser?.visible&&authenticated&&businessVisible?Math.min(440,Math.floor((width-left)*.45)):0;
  content.setBounds({ x: left, y: 84, width: Math.max(0,width - left-browserWidth), height: Math.max(0, height - 84) });
  if(publicBrowser){publicBrowser.view.setBounds({x:width-browserWidth,y:140,width:Math.max(1,browserWidth),height:Math.max(1,height-140)});publicBrowser.view.setVisible(Boolean(browserWidth));window.webContents.send('desktop:browser',{...publicBrowser.snapshot(),visible:Boolean(browserWidth),width:browserWidth});}
  if (accountView) {
    const compact=current==='workspace'&&workspaceCollapsed&&!accountMenuOpen;
    const accountHeight = accountMenuOpen ? 440 : compact?116:68;
    const accountWidth=current==='workspace'?(accountMenuOpen?232:Math.round(workspaceWidth)):248;
    accountView.setBounds({ x: 0, y: Math.max(84, height - accountHeight), width: accountWidth, height: Math.min(accountHeight, height - 84) });
  }
}
function closeAccountMenu() {
  if (!accountMenuOpen) return;
  accountMenuOpen = false; bounds(); state();
}
function visible(show) {
  if (!content) return;
  businessVisible = Boolean(show);
  content.setVisible(Boolean(show&&presentation.phase==='idle'));
  if (show) bounds();
  updateBusinessActivity();
}
function updateBusinessActivity() {
  if (!content || content.webContents.isDestroyed() || !origin) return;
  const active = Boolean(authenticated && businessVisible && presentation.phase==='idle' && window && window.isFocused() && !window.isMinimized());
  content.webContents.executeJavaScript(`window.workbenchActive = ${active}; document.dispatchEvent(new Event('workbench-visibility'));`).catch(() => {});
}
function rememberNavigation(area, pagePath = null) {
  const entry = {area, path: pagePath};
  const last = navigationHistory.at(-1);
  if (!last || last.area !== area || last.path !== pagePath) navigationHistory.push(entry);
  if (navigationHistory.length > 100) navigationHistory.shift();
}
async function goBack() {
  if (current === 'git' && localRepository.busy) throw Error('仓库正在同步，请等待完成后切换页面。');
  if (current === 'git' && !await leaveRepositoryEditor()) return;
  if (settingsPages.has(current)) {
    while (navigationHistory.length && settingsPages.has(navigationHistory.at(-1).area)) navigationHistory.pop();
    await navigate('workspace', '/workspace/');
    return;
  }
  if (navigationHistory.length < 2) return;
  navigationHistory.pop();
  const previous = navigationHistory.at(-1);
  restoringHistory = true;
  try { await navigate(previous.area, previous.path); }
  finally { restoringHistory = false; state(); }
}
async function refreshMessageState() {
  if (!authenticated || authBusy || !origin || !content || content.webContents.isDestroyed() || unreadBusy || quitting) return;
  unreadBusy = true;
  const epoch=authEpoch;
  try {
    const session = content.webContents.session;
    const cookies = await session.cookies.get({url: origin, name:'csrftoken'});
    const heartbeat = window && window.isFocused() && !window.isMinimized() && cookies.length;
    const response = await session.fetch(origin + '/messages/unread/', {
      method: heartbeat ? 'POST' : 'GET',
      headers: heartbeat ? {'X-CSRFToken':cookies[0].value,Origin:origin,Referer:origin+'/'} : {},
      credentials:'include', cache:'no-store', signal:AbortSignal.timeout(5000)
    });
    if (!authenticated || authBusy || epoch !== authEpoch) return;
    if (response.status === 401 || response.redirected && new URL(response.url).pathname === '/login/') { await restoreAuthentication(); return; }
    if (response.ok && response.headers.get('content-type')?.includes('application/json')) {
      const data = await response.json();
      await content.webContents.executeJavaScript('window.dispatchEvent(new CustomEvent("workbench:presence",{detail:'+JSON.stringify(data)+'}));').catch(()=>{});
      unreadTotal = Number(data.total) || 0; state();
    }
  } catch (_) { /* Reconnect on the next tick without creating activity logs. */ }
  finally { unreadBusy = false; }
}
const routes = { ai:'/assistant/', usage:'/api-pool/', apimanage:'/api-pool/manage/', workspace: '/workspace/', messages: '/messages/', account: '/account/',
  security: '/account/?tab=security', profile: '/account/public/',
  members: '/manage/members/', invites: '/manage/invites/', contact: '/manage/contact/', recycle: '/recycle-bin/' };
const settingsPages = new Set(['plugins', 'account', 'security', 'apimanage', 'profile', 'members', 'invites', 'contact', 'recycle']);
async function leaveRepositoryEditor() {
  if (!repositoryDraft) return true;
  const choice = await dialog.showMessageBox(window, {type:'question', title:'文件尚未保存', message:'保存这个文件的修改吗？', detail:repositoryDraft.file,
    buttons:['保存','不保存','取消'], defaultId:0, cancelId:2});
  if (choice.response === 2) return false;
  if (choice.response === 0) {
    const saved = await localRepository.save(repositoryDraft);
    window.webContents.send('repo:saved',saved);
  } else window.webContents.send('repo:discard');
  repositoryDraft=null;
  return true;
}
async function navigate(name, explicitPath = null) {
  if (!authenticated) throw Error('请先登录工作台。');
  if(mustChangePassword && name!=='security')throw Error('请先设置新密码。');
  if (current === 'git' && localRepository.busy && name !== 'git') throw Error('仓库正在同步，请等待完成后切换页面。');
  if (![...Object.keys(routes), 'git', 'ai', 'plugins'].includes(name)) throw Error('页面不存在。');
  const config = settings();
  if (name === 'apimanage' && !canManageApi) throw Error('公共 API 池仅限负责人管理。');
  if (name === 'git' && !config.gitEnabled) throw Error('请在左下角设置的能力模块中启用本地 Git。');
  if (name === 'ai' && !config.aiEnabled) throw Error('请在左下角设置的能力模块中启用 AI 助手。');
  if (current === 'git' && name !== 'git' && !await leaveRepositoryEditor()) return current;
  current = name;
  const target = explicitPath || (name === 'workspace' ? workspacePath : name === 'messages' ? messagesPath : routes[name]);
  if(name==='workspace'&&target)workspacePath=target;
  if(target&&origin){retryPath=target;beginPresentation(!shellReady);restoredGeneration=restoringHistory?presentation.generation:null;presentation.expect(['chrome','account','business']);}
  else {content.webContents.stop();presentation.dismiss();accountView.setVisible(authenticated);}
  closeAccountMenu();
  visible(Boolean(routes[name] && origin));
  state();
  if (target && origin) {
    const generation=presentation.generation;
    // Business preparation is acknowledged by its preload. Do not keep local
    // navigation or login locked while optional remote assets finish downloading.
    content.webContents.loadURL(origin+target).catch(error=>{
      if(generation!==presentation.generation||error.code==='ERR_ABORTED'||error.errno===-3)return;
      presentation.fail('页面加载失败，请重试。');
    });
  } else if (!routes[name]) {
    if (!restoringHistory) rememberNavigation(name);
    state();
  }
  return name;
}
function repoStatus() { return repository?localRepository.status():Promise.resolve({empty:true,context:null,name:'尚未打开仓库',branch:'打开仓库或新建文件',files:[],conflicts:0,detached:true}); }
function repoDiff(file) { return localRepository.diff(file); }
async function authRequest(action, data) {
  if (!origin || backendState !== 'ready') throw Error('工作台尚未连接，请先连接服务器或等待本地服务就绪。');
  const remote = connection.value.mode === 'remote';
  if (remote && action === 'setup') throw Error('服务器账户由管理员管理，不能在客户端初始化。');
  if (remote && data !== undefined && !csrfToken) await authRequest('status');
  const response = await content.webContents.session.fetch(origin + (remote ? '/desktop/api/' : '/_desktop/auth/') + action + '/', {
    method:data === undefined ? 'GET' : 'POST', credentials:'include', cache:'no-store', redirect:'error',
    headers:{'Content-Type':'application/json',...(remote ? (data === undefined ? {} : {'X-CSRFToken':csrfToken,Origin:origin,Referer:origin+'/'}) : {'X-Desktop-Token':TOKEN})},
    body:data === undefined ? undefined : JSON.stringify(data), signal:AbortSignal.timeout(15000)
  });
  if (!response.headers.get('content-type')?.includes('application/json')) throw Error('登录服务暂时不可用，请稍后重试。');
  const result=await response.json();
  if (!response.ok) throw Error(result.error || '登录未完成，请稍后重试。');
  if (remote) { if (result.protocol !== 1 || typeof result.csrfToken !== 'string') throw Error('服务器需要升级到支持桌面连接的版本。'); csrfToken=result.csrfToken; }
  return result;
}
async function showLogin(value = {}) {
  shellReady=false;workspaceNavigation={projects:[],loaded:false};beginPresentation(true,'正在准备登录…');
  needsEmailBinding=false;
  accountAvatar='';avatarSource='';avatarEpoch++;
  authenticated=false; username=''; isAdmin=false; canManageApi=false; current='login'; authEpoch++;
  requiresSetup=Boolean(value.requiresSetup); setupUsername=value.setupUsername || '';
  accountMenuOpen=false; unreadTotal=0; clearInterval(unreadTimer); unreadTimer=null;
  mustChangePassword=false;navigationHistory.length=0;workspacePath='/workspace/';messagesPath='/messages/';preparedBusinessPath='/workspace/';
  accountView.setVisible(false);visible(false);presentation.expect(['chrome']);state();
  if (content.webContents.getURL() !== 'about:blank') await content.webContents.loadURL('about:blank');
}
async function enterWorkspace(value) {
  if (!value.authenticated) { await showLogin(value); return; }
  if(username!==value.username)workspaceNavigation={projects:[],loaded:false};
  needsEmailBinding=value.hasEmail === false;
  mustChangePassword=Boolean(value.mustChangePassword);
  authenticated=true; requiresSetup=false; setupUsername=''; username=value.username; isAdmin=Boolean(value.isAdmin); canManageApi=Boolean(value.canManageApi); authEpoch++;
  updateAvatar(value);
  state();
  await navigate(mustChangePassword?'security':'workspace',mustChangePassword?'/account/set-password/':'/workspace/');
}
async function restoreAuthentication() {
  if (authBusy) return;
  const epoch=authEpoch, value=await authRequest('status');
  if (authBusy || epoch !== authEpoch) return;
  if (!value.authenticated) { if (authenticated || current !== 'login') await showLogin(value); else { requiresSetup=Boolean(value.requiresSetup); setupUsername=value.setupUsername || ''; state(); } }
  else if (!authenticated || value.username !== username) await enterWorkspace(value);
  else { isAdmin=Boolean(value.isAdmin); canManageApi=Boolean(value.canManageApi);needsEmailBinding=value.hasEmail===false;mustChangePassword=Boolean(value.mustChangePassword);updateAvatar(value);state(); }
  return value;
}
async function authenticate(action, data) {
  if (authBusy || connectionBusy) throw Error('正在处理登录或连接，请稍后。');
  if (authenticated) throw Error('当前已登录，请先退出当前账户。');
  if (!data || typeof data !== 'object') throw Error('请填写登录信息。');
  authBusy=true;
  try { const value=await authRequest(action,data); await content.webContents.session.cookies.flushStore(); await enterWorkspace(value); return value; }
  finally { authBusy=false; }
}
async function signOut() {
  publicBrowser?.action('close');
  if (authBusy) throw Error('账户操作正在进行，请稍后。');
  if (localRepository.busy || repositoryChangeBusy) throw Error('仓库操作尚未完成，请稍后退出登录。');
  authBusy=true;
  try {
    if (!await leaveRepositoryEditor()) return {cancelled:true};
    const value=await authRequest('logout',{}); await content.webContents.session.cookies.flushStore(); await showLogin(value); return value;
  } finally { authBusy=false; }
}
function completeBusinessPage(url){
      if (!origin || !url.startsWith(origin + '/')) return;
      closeEditMenu();
      content.webContents.executeJavaScript('window.workbenchDesktop=true;').catch(()=>{});
      applyEmbeddedAppearance();
      authRequest('status').then(value=>{if(authenticated && value.username===username){needsEmailBinding=value.hasEmail===false;mustChangePassword=Boolean(value.mustChangePassword);updateAvatar(value);state();}}).catch(()=>{});
      const location = new URL(url);
      if (location.pathname === '/login/' || location.pathname === '/register/' || location.pathname === '/') { restoreAuthentication().catch(() => state({error:'登录状态无法读取，请重新打开应用。'})); return; }
      if (!authenticated) { visible(false); return; }
      const pagePath = location.pathname + location.search;
      preparedBusinessPath=pagePath;
      if (location.pathname.startsWith('/_desktop/')) return;
      const setting = resolveSettingsPage(location, routes, settingsPages);
      if (setting) current = setting;
      else if (location.pathname === '/api-pool/' && location.searchParams.get('scope') === 'team' && canManageApi) { current='apimanage'; }
      else if (location.pathname === '/api-pool/') { current='usage'; }
      else if (location.pathname === '/assistant/') { current='ai'; }
      else if (conversationPath(pagePath)) { current = 'messages'; messagesPath = pagePath; }
      else if (location.pathname.startsWith('/messages/references/')) { /* Keep the originating tab and conversation destination. */ }
      else { current = 'workspace'; workspacePath = pagePath; }
      if (restoredGeneration!==presentation.generation) rememberNavigation(current, pagePath);
      updateBusinessActivity();
      refreshMessageState();
      if (!unreadTimer) unreadTimer = setInterval(refreshMessageState, 10000);
      bounds(); state();
}
function restoreInternalPage(){
  if(!authenticated||!businessVisible||!origin)return;
  const location=new URL(preparedBusinessPath,origin);
  const page=resolveSettingsPage(location,routes,settingsPages)||
    (location.pathname.startsWith('/messages/')?'messages':location.pathname==='/assistant/'?'ai':location.pathname==='/api-pool/'?'usage':'workspace');
  navigate(page,preparedBusinessPath).catch(error=>state({error:error.message}));
}
function registerIPC() {
  handle('desktop:presentation-ready',(generation)=>{presentation.ready('chrome',generation);revealLocalShell();});
  // A separate account renderer must finish applying its own data and theme.
  ipcMain.handle('desktop:account-ready',(event,generation)=>{
    if(!accountView||event.sender!==accountView.webContents||event.senderFrame.url!==ACCOUNT_URL)return;
    presentation.ready('account',generation);revealLocalShell();
  });
  ipcMain.on('desktop:business-ready',(event,value)=>{
    const generation=value?.generation;
    if(!content||event.sender!==content.webContents||event.senderFrame!==content.webContents.mainFrame)return;
    const url=event.senderFrame.url;
    if(!origin||new URL(url).origin!==origin||!authenticated||publicPagePath(new URL(url).pathname)||/^\/(login|register)\/$/.test(new URL(url).pathname))return;
    if(generation!==presentation.generation||!presentation.pending)return;
    const menu=workspaceMenu(value.sidebar);if(menu)workspaceNavigation=menu;
    completeBusinessPage(url);
    presentation.ready('business',generation);state();
  });
  handle('desktop:loading-retry',retryPresentation);
  handle('desktop:loading-dismiss',async()=>{await showLogin();});
  ipcMain.handle('desktop:business-presentation', event => {
    if(!content || event.sender!==content.webContents || event.senderFrame!==content.webContents.mainFrame)return null;
    return businessPresentation(event.senderFrame.url);
  });
  ipcMain.handle('desktop:edit-action',(event,action)=>{
    if(!editView||event.sender!==editView.webContents||event.senderFrame?.url!==EDIT_URL)return;
    const target=editTarget,allowed=editAllowed;closeEditMenu();
    if(!target||target.isDestroyed())return;
    target.focus();if(action==='close')return;
    if(['cut','copy','paste','selectAll'].includes(action)&&allowed?.[action])target[action]();
  });
  handle('appearance:get',()=>appearance.snapshot(nativeTheme.shouldUseDarkColors));
  handle('appearance:save',async value=>{appearance.save(value);return syncAppearance();});
  handle('appearance:wallpaper',async()=>{
    const value=await dialog.showOpenDialog(window,{title:'选择本地壁纸',properties:['openFile'],filters:[{name:'图片',extensions:['png','jpg','jpeg','webp']}]});
    if(!value.canceled)appearance.upload(value.filePaths[0]);return syncAppearance();
  });
  handle('appearance:clear',async()=>{appearance.clear();return syncAppearance();});
  handle('appearance:reset',async()=>{appearance.clear();appearance.save({mode:'dark',opacity:18,blur:4});return syncAppearance();});
  handle('desktop:info', () => ({ avatar:accountAvatar,needsEmailBinding,mode: connection.value.mode, serverUrl:connection.value.url, connection:connection.snapshot(), updates:updates.snapshot(), backend: backendState, username, isAdmin, canManageApi, authenticated, requiresSetup, setupUsername, current, accountMenuOpen, unreadTotal, backAvailable: settingsPages.has(current) ? authenticated && Boolean(origin) : navigationHistory.length > 1, version: app.getVersion(), dataPath: STATE, appearance:appearance.snapshot(nativeTheme.shouldUseDarkColors),loading:presentation.snapshot(),loadingLeft:loadingLeft(),workspaceNavigation,workspacePath, ...publicSettings() }));
  handle('connection:get',()=>connection.snapshot());
  handle('connection:save',saveConnection);
  const showUpdateInfo=()=>{if(publicBrowser?.visible)publicBrowser.action('close');accountMenuOpen=true;accountView.setVisible(true);bounds();state();accountView.webContents.send('desktop:update-open');return updates.snapshot();};
  const businessTrusted=event=>authenticated&&event.sender===content.webContents&&event.senderFrame===content.webContents.mainFrame&&new URL(event.senderFrame.url).origin===origin;
  ipcMain.handle('desktop:update-open',event=>{if(!businessTrusted(event))throw Error('无权打开更新页面。');return {ok:true,data:showUpdateInfo()};});
  ipcMain.handle('desktop:update-state',event=>{if(!businessTrusted(event))throw Error('无权查看更新状态。');return {ok:true,data:updates.snapshot()};});
  handle('updates:show',showUpdateInfo);
  handle('updates:feature',async index=>{const release=updates.snapshot().release;const {newer}=require('./free-mac-update.cjs');if(!Number.isInteger(index)||!release?.features?.[index]||newer(release.version,app.getVersion()))throw Error('请先完成更新后使用此功能。');const target=release.features[index].path;const {PATHS}=require('./release-details.cjs');if(!PATHS.has(target))throw Error('功能入口无效。');const name=Object.keys(routes).find(k=>routes[k]===target)||'workspace';await navigate(name,name==='workspace'?target:undefined);return {opened:true};});
  handle('updates:status',()=>updates.snapshot());
  handle('updates:check',()=>updates.check());
  handle('updates:download',()=>updates.download());
  handle('updates:install',async()=>{
    if(localRepository.busy||authBusy)throw Error('请等待当前操作结束后再安装更新。');
    if(!await leaveRepositoryEditor())return {cancelled:true};
    const manual=updates.snapshot().mode==='manual-mac';
    const answer=await dialog.showMessageBox(window,{type:'question',message:manual?'打开已下载的 Mac 安装包？':'安装更新并重新启动科研工作台？',detail:manual?'保存当前内容后，退出科研工作台，将安装包中的应用拖入 Applications 覆盖旧版本，再重新打开。':'请先提交或保存网页中正在填写的内容。服务器数据不会被覆盖。',buttons:[manual?'打开安装包':'安装并重启','取消'],defaultId:1,cancelId:1});
    if(answer.response!==0)return {cancelled:true};
    await updates.install();return {installing:true};
  });
  handle('auth:status', async()=>backendState==='ready'?restoreAuthentication():{authenticated:false,requiresSetup:false});
  handle('auth:login', value => authenticate('login',value));
  handle('auth:register', value => authenticate('register',value));
  handle('auth:setup', value => authenticate('setup',value));
  handle('auth:forgot-password', async () => {
    if (!origin || backendState !== 'ready') throw Error('请先连接团队服务器，再找回密码。');
    if (requiresSetup) throw Error('请先为本地预览账户设置密码。');
    await shell.openExternal(new URL('/account/forgot/', origin).href);
    return {opened:true};
  });
  handle('auth:logout', signOut);
  handle('desktop:navigate', name => navigate(name));
  handle('desktop:workspace-collapse', (value,reduced=false) => {
    if(typeof value!=='boolean'||typeof reduced!=='boolean')throw Error('侧边栏状态无效。');
    fs.writeFileSync(SETTINGS_FILE,JSON.stringify({...settings(),workspaceCollapsed:value},null,2));
    workspaceCollapsed=value;closeAccountMenu();clearInterval(workspaceResizeTimer);
    const start=workspaceWidth, target=value?68:232, began=Date.now();
    if(reduced){workspaceWidth=target;bounds();}
    else workspaceResizeTimer=setInterval(()=>{
      const progress=Math.min(1,(Date.now()-began)/240);
      workspaceWidth=start+(target-start)*progress;bounds();
      if(progress===1){clearInterval(workspaceResizeTimer);workspaceResizeTimer=null;}
    },16);
    state();return {collapsed:value};
  });
  handle('desktop:workspace-navigate',value=>navigate('workspace',validateWorkspacePath(value)));
  handle('desktop:account-menu', open => { accountMenuOpen = Boolean(open); bounds(); state(); });
  handle('desktop:account', () => navigate('account'));
  handle('desktop:usage-open', () => navigate('usage'));
  handle('desktop:usage', async () => {
    const response=await content.webContents.session.fetch(origin+'/api-pool/usage/',{credentials:'include',cache:'no-store',headers:{Accept:'application/json'}});
    if (!response.ok || response.redirected) throw Error('登录状态已过期，请重新登录。');
    return response.json();
  });
  handle('desktop:window', action => {
    if (action === 'minimize') window.minimize();
    else if (action === 'maximize') window.isMaximized() ? window.unmaximize() : window.maximize();
    else if (action === 'close') window.close();
    else if (action === 'back') return goBack();
    else if (action === 'reload') { if (content) content.webContents.reload(); }
    else if (action === 'details' && content) content.webContents.executeJavaScript("document.querySelector('[data-details-toggle]')?.click()");
  });
  handle('repo:status', repoStatus);
  handle('repo:diff', repoDiff);
  handle('repo:files', () => repository?localRepository.files():{context:null,files:[]});
  handle('repo:read', file => localRepository.read(file));
  handle('repo:save', async value => { const saved = await localRepository.save(value); repositoryDraft=null; return saved; });
  handle('repo:create', (file, context) => localRepository.create(file,context));
  handle('repo:search', (query, context) => localRepository.search(query,context));
  handle('repo:history', () => localRepository.history());
  handle('repo:leave', leaveRepositoryEditor);
  handle('repo:draft', value => {
    if (!value) { repositoryDraft=null; return; }
    localRepository.requireContext(value.context);
    localRepository.resolve(value.file);
    if (typeof value.text !== 'string' || value.text.length > 2*1024*1024) throw Error('文件内容超过编辑限制。');
    repositoryDraft=value;
  });
  handle('repo:perform', async (action,value) => {
    if (repositoryDraft) throw Error('请先保存当前文件，再同步仓库。');
    if (action !== 'commit' && !settings().githubEnabled) throw Error('请先在能力模块中启用远程仓库同步。');
    return localRepository.perform(action,value);
  });
  handle('repo:list',()=>repositories.list());
  handle('repo:select',async directory=>{if(localRepository.busy)throw Error('仓库正在同步。');if(!await leaveRepositoryEditor())return null;repositories.select(directory);applyRepository();return repoStatus();});
  handle('repo:choose', async (initialize=false) => {
    if (localRepository.busy) throw Error('仓库正在同步，请等待完成后切换。');
    if (!await leaveRepositoryEditor()) return null;
    const picked=await dialog.showOpenDialog(window,{title:initialize?'新建本地仓库：选择或创建文件夹':'打开仓库或文件夹',properties:['openDirectory','createDirectory']});
    if(picked.canceled)return null;
    const candidate=new Repository(picked.filePaths[0],()=>settings().gitEnabled);
    let directory=picked.filePaths[0],plain=false;
    if(initialize)await candidate.git(['init']);
    try{directory=(await candidate.git(['rev-parse','--show-toplevel'])).trim();}catch(error){if(initialize)throw error;plain=true;}
    repositories.add(directory,plain);applyRepository();return repoStatus();
  });
  handle('repo:new-file',async()=>{
    if(localRepository.busy)throw Error('仓库正在同步。');if(!await leaveRepositoryEditor())return null;
    const picked=await dialog.showSaveDialog(window,{title:'选择新文件保存位置',defaultPath:path.join(app.getPath('documents'),'未命名.md')});if(picked.canceled)return null;
    const directory=path.dirname(picked.filePath);const candidate=new Repository(directory,()=>settings().gitEnabled);
    let root=directory,plain=false;try{root=(await candidate.git(['rev-parse','--show-toplevel'])).trim();}catch(_){plain=true;}
    candidate.directory=root;candidate.plain=plain;
    const result=candidate.create(path.relative(root,picked.filePath).replaceAll('\\','/'),candidate.context());
    repositories.add(root,plain);applyRepository();return result;
  });
  handle('repo:remove',async(directory,physical=false)=>{
    if(localRepository.busy)throw Error('仓库正在同步。');if(!repositories.items.some(row=>row.path===directory))throw Error('仓库未打开。');if(!await leaveRepositoryEditor())return null;
    if(physical){const target=deletionTarget(directory,[app.getPath('home'),app.getPath('documents'),STATE,app.getAppPath()]);
      const response=await dialog.showMessageBox(window,{type:'warning',title:'删除本地仓库',message:'将整个本地目录移入回收站？',detail:target+'\n包括未提交文件；远程仓库仍保留。',buttons:['取消','移入回收站'],defaultId:0,cancelId:0,noLink:true});
      if(response.response!==1)return null;await shell.trashItem(target);
    }
    repositories.remove(directory);applyRepository();return repositories.list();
  });
  handle('repo:open', async file => {
    let target=localRepository.root();
    if (file) {
      if (!DOCUMENTS.has(path.extname(file).toLowerCase())) throw Error('文本和源码可以在工作区编辑；其他文件请在文件管理器中选择打开方式。');
      target=localRepository.resolve(file);
    }
    const error=await shell.openPath(target); if (error) throw Error('没有找到适合的本机软件，请通过文件管理器打开。');
  });
  handle('desktop:browser-action',action=>{if(action==='external'&&publicBrowser?.visible)return shell.openExternal(publicBrowser.view.webContents.getURL());publicBrowser?.action(action);bounds();});
  ipcMain.handle('desktop:browser-open',async(event,url)=>{if(!authenticated||event.sender!==content.webContents||event.senderFrame!==content.webContents.mainFrame||new URL(event.senderFrame.url).origin!==origin)throw Error('无权打开网页。');if(!publicBrowser){const {PublicBrowser}=require('./public-browser.cjs');publicBrowser=new PublicBrowser(window,value=>{window.webContents.send('desktop:browser',value);content.webContents.send('desktop:browser-state',value);bounds();});}await publicBrowser.open(url);bounds();return {ok:true};});
  handle('desktop:external', async value => {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) throw Error('仅支持网页链接。');
    await shell.openExternal(url.href);
  });
  handle('settings:get', publicSettings);
  handle('settings:save', value => {
    const old = settings();
    const next = { ...old, gitEnabled:Boolean(value.gitEnabled), githubEnabled:Boolean(value.githubEnabled), aiEnabled:Boolean(value.aiEnabled) };
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(next, null, 2));
    for (let index=navigationHistory.length-1; index>=0; index--) {
      if ((!next.gitEnabled && navigationHistory[index].area === 'git') || (!next.aiEnabled && navigationHistory[index].area === 'ai')) navigationHistory.splice(index,1);
    }
    state();
    return publicSettings();
  });

}
async function startConnection() {
  const epoch=++connectionEpoch;csrfToken='';origin=null;shellReady=false;beginPresentation(true,'正在准备工作台…');
  if(LOCAL_PREVIEW && connection.value.mode==='local'){backendState='starting';state();startBackend();return;}
  if(!connection.value.url){backendState='disconnected';await showLogin();state();return;}
  backendState='connecting';state();
  const target=connection.value.url;
  try {
    let response;
    for(let attempt=0;attempt<3;attempt++){
      if(epoch!==connectionEpoch)return;
      state({connectionAttempt:attempt+1});
      try {
        response=await content.webContents.session.fetch(target+'/desktop/api/status/',{credentials:'include',redirect:'error',cache:'no-store',signal:AbortSignal.timeout(8000)});
        if(![502,503,504].includes(response.status)||attempt===2)break;
      }catch(error){
        if(attempt===2||/CERT|SSL/.test(String(error.code||error.message)))throw error;
      }
      await new Promise(resolve=>setTimeout(resolve,750*(attempt+1)));
    }
    if(epoch!==connectionEpoch)return;
    if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw Error('服务器接口返回 HTTP '+response.status+'，请检查服务器桌面接口和反向代理配置。');
    const value=await response.json();
    if(value.protocol!==1||typeof value.csrfToken!=='string')throw Error('服务器版本与此客户端不兼容。');
    origin=target;csrfToken=value.csrfToken;backendState='ready';await enterWorkspace(value);state();
  }catch(error){
    if(epoch!==connectionEpoch)return;
    backendState='error';origin=null;await showLogin();
    const detail=String(error.code||error.cause?.code||error.message||'未知网络错误').slice(0,240);
    let message=error.message.startsWith('服务器')?error.message:
      error.name==='TimeoutError'||error.name==='AbortError'?'连接超时，请检查服务器与网络。':
      /PROXY|TUNNEL/.test(detail)?'代理连接失败，请检查系统代理设置。':
      /CERT|SSL/.test(detail)?'服务器证书校验失败，请检查证书。':
      '无法连接团队服务器：'+detail;
    presentation.fail(message);state({error:message});
  }
}
async function saveConnection(value) {
  if(connectionBusy||authBusy||localRepository.busy)throw Error('当前操作正在进行，请稍后切换连接。');
  connectionBusy=true;
  try {
    // Validate before logging out or changing the active service.
    const {serverOrigin}=require('./connection.cjs');
    if(value?.mode!=='remote')throw Error('工作台使用团队服务器。');
    serverOrigin(value.url);
    if(value.mode==='remote'&&new URL(value.url).protocol==='http:'&&serverOrigin(value.url)!==connection.value.url){
      const answer=await dialog.showMessageBox(window,{type:'warning',message:'此地址使用 HTTP，账户与内容将未经加密传输。',detail:'建议服务器启用 HTTPS。仅在你确认当前连接环境可信时继续。',buttons:['取消','继续使用 HTTP'],defaultId:0,cancelId:0});
      if(answer.response!==1)return {cancelled:true,...connection.snapshot()};
    }
    if(authenticated){const result=await signOut();if(result.cancelled)return {cancelled:true,...connection.snapshot()};}
    connection.save(value);++connectionEpoch;
    if(backend){const previous=backend;backend=null;previous.kill();}
    await showLogin();await startConnection();return connection.snapshot();
  }finally{connectionBusy=false;}
}
function startBackend() {
  const epoch=connectionEpoch;
  const candidates = [process.env.WORKBENCH_PYTHON, path.join(APP_ROOT, '../venv/Scripts/python.exe'), path.join(APP_ROOT, '.venv/Scripts/python.exe'), path.join(APP_ROOT,'../venv/bin/python'), path.join(APP_ROOT,'.venv/bin/python')].filter(Boolean);
  const python = candidates.find(value => fs.existsSync(value)) || (process.platform==='win32'?'python':'python3');
  backend = spawn(python, ['-u', path.join(__dirname, 'server.py')], {
    cwd: APP_ROOT, windowsHide: true, env: { ...process.env, WORKBENCH_DESKTOP_STATE: STATE,
      WORKBENCH_DESKTOP_BOOT_TOKEN: TOKEN,
      WORKBENCH_DESKTOP_SOURCE_DATA: process.env.WORKBENCH_DESKTOP_SOURCE_DATA || path.join(APP_ROOT, '../merged-preview') }
  });
  let pending = '';
  backend.stdout.on('data', chunk => {
    pending += chunk.toString();
    const lines = pending.split('\n'); pending = lines.pop();
    for (const line of lines) {
      let value; try { value = JSON.parse(line); } catch { continue; }
      if (!value.desktop_ready || epoch!==connectionEpoch) continue;
      origin = 'http://127.0.0.1:' + value.port; backendState = 'ready';
      console.info('Local workbench ready: ' + origin);
      restoreAuthentication().catch(() => state({ error:'登录服务未连接，请关闭并重新打开应用。' }));
      state();
    }
  });
  backend.stderr.on('data', chunk => {
    const log = path.join(STATE, 'startup.log'); fs.appendFileSync(log, chunk);
  });
  backend.on('error', () => { if(epoch!==connectionEpoch)return; backendState = 'error'; state({ error: '未找到 Python，请设置 WORKBENCH_PYTHON 后重新启动。' }); });
  backend.on('exit', code => { if (!quitting && epoch===connectionEpoch) { backendState = 'error'; visible(false); state({ error: '本地服务已停止，请重新启动应用。诊断信息在本地数据目录。' }); } });
}
const lock = app.requestSingleInstanceLock();
if (!lock) app.quit();
else {
  app.on('second-instance', () => {
    if (window && !window.isDestroyed()) {
      if (window.isMinimized()) window.restore();
      window.show(); window.focus();
    }
  });
  app.whenReady().then(async () => {
    Menu.setApplicationMenu(process.platform==='darwin'?Menu.buildFromTemplate([{role:'appMenu'},{role:'editMenu'},{role:'viewMenu'},{role:'windowMenu'}]):null);
    updates=new Updates(app,value=>{for(const view of [window,accountView,content])if(view&&!view.isDestroyed?.()&&!view.webContents.isDestroyed())view.webContents.send('desktop:updates',value);});
    registerIPC();
    window = new BrowserWindow({ width: 1380, height: 900, minWidth: 980, minHeight: 650,
      show:false,frame: false,title:'科研工作台',backgroundColor:appearance.snapshot(nativeTheme.shouldUseDarkColors).theme==='dark'?'#202020':'#f7f7f7',
      icon: path.join(__dirname, 'assets', process.platform==='win32'?'team-logo-rounded.ico':'team-logo.png'),
      webPreferences: { preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true,backgroundThrottling:false } });
    content = new WebContentsView({ webPreferences: { preload:path.join(__dirname,'business-preload.cjs'), nodeIntegration: false, contextIsolation: true, sandbox: true, partition:'persist:local-workbench',backgroundThrottling:false } });
    // Cover both permission requests and synchronous checks, including local chrome.
    for (const session of new Set([content.webContents.session, window.webContents.session])) {
      session.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
      session.setPermissionCheckHandler(()=>false);
      session.setDevicePermissionHandler(()=>false);
    }
    content.setBackgroundColor('#202020'); window.contentView.addChildView(content); visible(false);
    accountView = new WebContentsView({ webPreferences: { preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true,backgroundThrottling:false } });
    accountView.setBackgroundColor('#00000000'); window.contentView.addChildView(accountView); bounds();
    accountView.setVisible(false);
    editView = new WebContentsView({webPreferences:{preload:path.join(__dirname,'edit-menu-preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true}});
    editView.setBackgroundColor('#00000000');window.contentView.addChildView(editView);editView.setVisible(false);
    editView.webContents.setWindowOpenHandler(()=>({action:'deny'}));
    editView.webContents.on('will-navigate',(event,url)=>{if(url!==EDIT_URL)event.preventDefault();});
    await editView.webContents.loadURL(EDIT_URL);
    [window.webContents, content.webContents, accountView.webContents].forEach(installEditMenu);
    accountView.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    accountView.webContents.on('will-navigate', (event, url) => { if (url !== ACCOUNT_URL) event.preventDefault(); });
    content.webContents.on('focus', () => { closeAccountMenu(); closeEditMenu(); });
    window.webContents.on('focus', () => { closeAccountMenu(); closeEditMenu(); });
    accountView.webContents.on('focus',closeEditMenu);
    window.on('blur',closeEditMenu);
    content.webContents.setWindowOpenHandler(({ url }) => { if (/^https?:\/\//.test(url)) shell.openExternal(url); return { action: 'deny' }; });
    content.webContents.on('will-navigate', (event, url) => {
      if (origin && new URL(url).origin !== origin) { event.preventDefault(); if (/^https?:\/\//.test(url)) shell.openExternal(url); }
      else if (origin && authenticated && publicPagePath(new URL(url).pathname)) { event.preventDefault();state({error:'请通过“预览公开页面”打开对外展示。'}); }
      else if (origin) {
        if (/^\/recycle-bin\/(project|task)\/\d+\/delete\/$/.test(new URL(url).pathname)) {
          workspacePath='/workspace/';
          for (let index=navigationHistory.length-1; index>=0; index--) {
            if (/^\/(projects|tasks)\//.test(navigationHistory[index].path || '')) navigationHistory.splice(index,1);
          }
        }
        const archived = new URL(url).pathname.match(/^\/(tasks|projects)\/(\d+)\/archive\/$/);
        if (archived) {
          const prefix = '/' + archived[1] + '/' + archived[2] + '/';
          for (let index = navigationHistory.length - 1; index >= 0; index--) {
            if (navigationHistory[index].path?.startsWith(prefix)) navigationHistory.splice(index, 1);
          }
        }
      }
    });
    content.webContents.on('will-redirect', (event, url) => {
      if(origin && new URL(url).origin!==origin){event.preventDefault();return;}
      if(origin && authenticated && publicPagePath(new URL(url).pathname)){
        event.preventDefault();setImmediate(restoreInternalPage);
      }
    });
    content.webContents.on('did-start-navigation',(_event,url,_inPlace,isMainFrame)=>{
      if(!isMainFrame||_inPlace||!origin||new URL(url).origin!==origin||!authenticated)return;
      retryPath=new URL(url).pathname+new URL(url).search;
      if(!presentation.pending){beginPresentation(!shellReady);presentation.expect(['chrome','account','business']);}
      else presentation.readySurfaces.delete('business');
      pageLoading=true;state();
    });
    content.webContents.on('did-navigate',(_event,url,status)=>{
      if(!origin||new URL(url).origin!==origin)return;
      if(authenticated&&publicPagePath(new URL(url).pathname)){content.setVisible(false);setImmediate(restoreInternalPage);return;}
      if(status>=400)presentation.fail('服务器返回 HTTP '+status+'，请稍后重试。');
    });
    content.webContents.on('did-start-loading',()=>{pageLoading=true;state();});
    content.webContents.on('did-stop-loading',()=>{pageLoading=false;state();});
    content.webContents.on('did-fail-load',(_event,code,description,_url,isMainFrame)=>{
      if(!isMainFrame || code===-3)return;
      pageLoading=false;presentation.fail('页面加载失败，请重试（'+description+'）。');
    });
    content.webContents.on('did-finish-load',()=>{const url=content.webContents.getURL();if(origin&&url.startsWith(origin+'/')&&['/login/','/register/','/'].includes(new URL(url).pathname))completeBusinessPage(url);});
    window.on('resize',()=>{closeEditMenu();bounds();});
    window.on('close', event => {
      if (localRepository.busy) { event.preventDefault(); if (!confirmingClose) { confirmingClose=true; dialog.showMessageBox(window,{type:'info',message:'仓库正在同步，请等待完成后关闭。'}).finally(() => confirmingClose=false); } return; }
      if (!repositoryDraft) return;
      event.preventDefault();
      if (confirmingClose) return;
      confirmingClose=true;
      leaveRepositoryEditor().then(leave => { if (leave) window.close(); }).catch(error => dialog.showErrorBox('文件未保存',error.message)).finally(() => confirmingClose=false);
    });
    window.on('blur', () => { closeAccountMenu(); updateBusinessActivity(); });
    window.on('focus', () => { updateBusinessActivity(); refreshMessageState(); });
    window.on('minimize', updateBusinessActivity);
    window.on('restore', updateBusinessActivity);
    window.on('closed', () => { if (!content.webContents.isDestroyed()) content.webContents.close(); if (!accountView.webContents.isDestroyed()) accountView.webContents.close(); if (!editView.webContents.isDestroyed()) editView.webContents.close(); window = null; });
    beginPresentation(true,'正在准备工作台…');
    await window.loadURL(UI_URL);
    await accountView.webContents.loadURL(ACCOUNT_URL);
    await syncAppearance();
    nativeTheme.on('updated',()=>syncAppearance().catch(()=>{}));
    // Explicitly show the interactive window even when a background launcher used SW_HIDE.
    window.show(); window.focus();
    console.info('Desktop window ready.');
    await startConnection();
    updates.start();
  }).catch(error => {
    dialog.showErrorBox('桌面工作台启动失败', String(error.message));
    app.quit();
  });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', () => { quitting = true;presentation.clear(); updates?.stop(); clearInterval(unreadTimer); if (backend) backend.kill(); });
}
