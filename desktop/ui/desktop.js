const $ = selector => document.querySelector(selector);
const api = window.desktop;
let active = 'workspace', info, config, toastTimer;
let signedIn = false, loginMode = 'login', loginPending = false;
let loginBackendReady = false, recoveryPending = false;
const businessPages = ['workspace', 'messages', 'ai', 'usage', 'account', 'security', 'apimanage', 'profile', 'members', 'invites', 'contact', 'recycle'];
const settingsPages = ['plugins', ...businessPages.filter(name => !['workspace', 'messages', 'ai', 'usage'].includes(name))];
let settingsSection = 'capabilities';
const settingsSections = {
  appearance: ['外观', '主题与壁纸只保存在本机。'],
  capabilities: ['能力模块', '按需要启用本地能力。'],
  connection: ['服务器连接', '应用自动连接团队服务器，无需选择运行模式。'],
  'local-environment': ['关于与更新', '查看版本、连接状态和应用更新。']
};
function renderSettingsNavigation() {
  document.querySelectorAll('.settings-link').forEach(button => {
    const selected = button.dataset.page ? button.dataset.page === active : active === 'plugins' && button.dataset.settingsSection === settingsSection;
    button.classList.toggle('selected', selected);
    if (selected) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
  $('#settings-heading').textContent = settingsSections[settingsSection][0];
  $('#settings-description').textContent = settingsSections[settingsSection][1];
  document.querySelectorAll('.settings-card').forEach(card => card.hidden = card.id !== settingsSection);
  $('#settings-save').hidden = settingsSection === 'local-environment' || settingsSection === 'appearance' || settingsSection === 'connection';
  $('.settings-main').hidden = active !== 'plugins';
}
async function call(promise) { const result = await promise; if (!result.ok) throw Error(result.error); return result.data; }
function toast(text) { $('#toast').textContent = text; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 5000); }
function guard(callback) { return async event => { try { await callback(event); } catch (error) { toast(error.message); } }; }
function displayMessageState(state) {
  $('#close-settings').disabled = !state.backAvailable;
  const badge = $('#desktop-unread');
  badge.hidden = !state.unreadTotal;
  badge.textContent = state.unreadTotal > 99 ? '99+' : state.unreadTotal || '';
}
function updateLoginForm() {
  const setup=loginMode === 'setup', register=loginMode === 'register';
  $('#login-heading').textContent=setup ? '设置本地登录密码' : register ? '加入科研团队' : '登录科研工作台';
  $('#login-description').textContent=setup ? '为现有本地预览账户设置密码，原有项目和记录会保留。' : register ? '使用管理员发放的邀请码注册。' : '使用团队账户继续。';
  $('#login-password').autocomplete=register || setup ? 'new-password' : 'current-password';
  $('#login-confirm-field').hidden=!(setup || register); $('#login-password-confirm').required=setup || register;
  $('#login-email-field').hidden=!register; $('#login-email').required=register;
  $('#login-invite-field').hidden=!register; $('#login-invite').required=register;
  $('#login-username').readOnly=setup;
  $('#login-submit').textContent=loginPending ? '正在处理…' : setup ? '设置密码并进入' : register ? '注册并进入' : '登录';
  $('#login-switch-hint').textContent=register ? '已有账户？' : '还没有账户？';
  $('#login-switch').textContent=register ? '登录' : '邀请码注册';
  $('.login-switch').hidden=setup;
  $('#login-recovery').hidden=setup || register;
  $('#login-forgot-password').disabled=loginPending || recoveryPending || !loginBackendReady;
}
let loadingDelay;
function displayLoading(state) {
  clearTimeout(loadingDelay);
  const busy=Boolean(state.pageLoading || state.backend==='connecting' || state.backend==='starting');
  document.body.classList.toggle('desktop-busy',busy);
  document.body.classList.toggle('connection-busy',!state.authenticated && busy);
  if(!busy||state.loading?.phase!=='idle'){$('#desktop-loading').hidden=true;return;}
  loadingDelay=setTimeout(()=>{$('#desktop-loading').hidden=false;},300);
}
function displayAuthentication(state) {
  displayLoading(state);
  window.updateInterfaceLoading(state);
  $('#settings-email-dot').hidden=!state.authenticated || !state.needsEmailBinding;
  loginBackendReady=state.backend === 'ready';
  const authenticated=Boolean(state.authenticated);
  if (!authenticated && signedIn) {
    window.repositoryWorkbench.reset();
    document.querySelectorAll('.repository-dialog[open]').forEach(dialog => dialog.close());
    $('#login-password').value=''; $('#login-password-confirm').value=''; $('#login-invite').value=''; $('#login-error').textContent='';
    loginMode='login';
  }
  signedIn=authenticated; document.body.classList.toggle('signed-out',!authenticated); $('.app-navigation').hidden=!authenticated;
  if (!authenticated) {
    if (state.requiresSetup) { loginMode='setup'; $('#login-username').value=state.setupUsername || 'local-admin'; }
    else if (loginMode === 'setup') loginMode='login';
    updateLoginForm();
    $('#login-submit').disabled=loginPending || state.backend !== 'ready';
    if(state.backend==='ready')$('#login-error').textContent='';
    $('#login-service-status').textContent=state.backend === 'ready' ? (state.mode === 'remote' ? '团队服务器 · '+(state.serverUrl||'') : '本地预览 · 数据保存在这台电脑') : state.backend === 'disconnected' ? '先连接团队服务器，再使用原有账户登录。' : state.backend === 'error' ? '连接未完成，可以检查网址并重新连接。' : '正在连接工作台…';
    $('#login-connection').hidden=state.backend!=='disconnected' && state.backend!=='error';
    $('#login-connection').open=!$('#login-connection').hidden;
    if(state.backend==='connecting'&&state.connectionAttempt>1)$('#login-service-status').textContent='正在重试团队连接（'+state.connectionAttempt+'/3）…';
  }
}
$('#login-switch').addEventListener('click',() => {
  if (loginPending || loginMode === 'setup') return;
  loginMode=loginMode === 'register' ? 'login' : 'register'; $('#login-error').textContent='';
  $('#login-recovery-message').textContent='';
  $('#login-password').value=''; $('#login-password-confirm').value=''; $('#login-invite').value=''; updateLoginForm();
});
$('#login-forgot-password').addEventListener('click',async () => {
  if (loginPending || recoveryPending || !loginBackendReady || loginMode !== 'login') return;
  recoveryPending=true; $('#login-error').textContent=''; updateLoginForm();
  try {
    await call(api.forgotPassword());
    $('#login-recovery-message').textContent='找回页面已在浏览器打开。设置新密码后回到这里登录；未绑定邮箱的账户请联系管理员重置。';
  } catch (error) { $('#login-error').textContent=error.message; }
  finally { recoveryPending=false; updateLoginForm(); }
});
$('#login-form').addEventListener('submit',async event => {
  event.preventDefault(); if (loginPending) return;
  loginPending=true; $('#login-submit').disabled=true; $('#login-switch').disabled=true; $('#login-error').textContent=''; updateLoginForm();
  const data={username:$('#login-username').value.trim(),password:$('#login-password').value,remember:$('#login-remember').checked?'1':'0'};
  if (loginMode !== 'login') data.passwordConfirm=$('#login-password-confirm').value;
  if (loginMode === 'register') {data.inviteCode=$('#login-invite').value.trim(); data.email=$('#login-email').value.trim();}
  try {
    await call(loginMode === 'setup' ? api.setupAccount(data) : loginMode === 'register' ? api.register(data) : api.login(data));
    $('#login-password').value=''; $('#login-password-confirm').value=''; $('#login-invite').value='';
  } catch (error) { $('#login-error').textContent=error.message; }
  finally { loginPending=false; $('#login-submit').disabled=!loginBackendReady; $('#login-switch').disabled=false; updateLoginForm(); }
});
function displayPage(name) {
  active = name;
  const pageName = settingsPages.includes(name) ? 'plugins' : businessPages.includes(name) ? 'workspace' : name;
  document.querySelectorAll('.page').forEach(page => page.hidden = page.id !== pageName + '-page');
  document.querySelectorAll('.app-tabs [data-page]').forEach(button => {
    if (button.dataset.page === name) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  renderSettingsNavigation();
}
async function navigate(name) {
  const wasSettings = settingsPages.includes(active);
  const actual = await call(api.navigate(name)); displayPage(actual);
  if (actual === 'git') await loadRepo();
  if (actual === 'plugins' && !wasSettings) await loadSettings();
}
api.onState(state => {
  displayAuthentication(state);
  displayMessageState(state);
  displayCapabilities(state);
  const changed = active !== state.current;
  const enteringSettings = !settingsPages.includes(active) && settingsPages.includes(state.current);
  displayPage(state.current);
  if (changed && state.current === 'git') loadRepo().catch(error => toast(error.message));
  if (enteringSettings) loadSettings().catch(error => toast(error.message));
  $('#admin-settings').hidden = !state.isAdmin;
  $('#api-settings').hidden = !state.canManageApi;
  $('#local-user').textContent = state.username || '未登录';
  $('#connection-label').textContent = state.backend === 'ready' ? (state.mode==='remote'?'团队服务器':'本地预览') : state.backend === 'error' ? '连接未完成' : '正在连接';
  $('#environment-mode').textContent=state.mode==='remote'?'团队服务器':'本地预览';
  $('#environment-server').textContent=state.mode==='remote'?(state.serverUrl||'尚未设置'):'独立本地数据';
  $('#status-dot').className = 'status-dot ' + state.backend;
  $('#details-button').hidden = !state.taskDetail;
  if (state.error) { $('#startup-message').textContent = state.error; if (!signedIn) $('#login-error').textContent=state.error; else toast(state.error); }
});
document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', guard(() => navigate(button.dataset.page))));
document.querySelectorAll('[data-window]').forEach(button => button.addEventListener('click', guard(() => call(api.window(button.dataset.window)))));
async function loadRepo() { await window.repositoryWorkbench.activate(); }
function displayCapabilities(value) {
  if (typeof value.gitEnabled === 'boolean') $('.app-tabs [data-page=git]').hidden = !value.gitEnabled;
  if (typeof value.aiEnabled === 'boolean') $('.app-tabs [data-page=ai]').hidden = !value.aiEnabled;
}
function showConfig(value) {
  if(value.appearance){window.applyWorkbenchAppearance(value.appearance);showAppearance(value.appearance);}
  config = value;
  displayCapabilities(value);
  window.repositoryWorkbench.configure(value);
  $('#git-enabled').checked = value.gitEnabled; $('#github-enabled').checked = value.githubEnabled; $('#ai-enabled').checked = value.aiEnabled;
}
async function loadSettings() { showConfig(await call(api.settings()));showAppearance(await call(api.appearance()));showConnection(await call(api.connection()));showUpdates(await call(api.updates())); }
function showAppearance(value){
  $('#appearance-mode').value=value.mode;
  $('#appearance-opacity').value=value.opacity;$('#appearance-opacity-value').textContent=value.opacity+'%';
  $('#appearance-blur').value=value.blur;$('#appearance-blur-value').textContent=value.blur+'px';
  $('#wallpaper-status').textContent=value.hasWallpaper?'已保存到本机':'未设置壁纸';
  $('#wallpaper-preview').hidden=!value.wallpaper;$('#wallpaper-preview').src=value.wallpaper||'';$('#wallpaper-clear').disabled=!value.hasWallpaper;
}
let appearanceTimer,appearanceSaving=false,appearanceAgain=false,appearanceRevision=0;
async function saveAppearance(){
  if(appearanceSaving){appearanceAgain=true;return;}appearanceSaving=true;
  const revision=appearanceRevision;
  try{const value=await call(api.saveAppearance({mode:$('#appearance-mode').value,opacity:Number($('#appearance-opacity').value),blur:Number($('#appearance-blur').value)}));if(revision===appearanceRevision)showAppearance(value);}
  catch(error){toast(error.message);}finally{appearanceSaving=false;if(appearanceAgain){appearanceAgain=false;saveAppearance();}}
}
$('#appearance-mode').addEventListener('change',()=>{appearanceRevision++;saveAppearance();});
for(const name of ['opacity','blur'])$('#appearance-'+name).addEventListener('input',()=>{
  appearanceRevision++;
  $('#appearance-'+name+'-value').textContent=$('#appearance-'+name).value+(name==='opacity'?'%':'px');clearTimeout(appearanceTimer);appearanceTimer=setTimeout(saveAppearance,180);
});
$('#wallpaper-choose').addEventListener('click',guard(async()=>showAppearance(await call(api.chooseWallpaper()))));
$('#wallpaper-clear').addEventListener('click',guard(async()=>showAppearance(await call(api.clearWallpaper()))));
$('#appearance-reset').addEventListener('click',guard(async()=>showAppearance(await call(api.resetAppearance()))));
async function saveSettings() {
  const result=await call(api.saveSettings({gitEnabled:$('#git-enabled').checked,githubEnabled:$('#github-enabled').checked,aiEnabled:$('#ai-enabled').checked}));
  showConfig(result); $('#save-status').textContent = '设置已保存到本机。'; return result;
}
$('#settings-form').addEventListener('submit', guard(async event => { event.preventDefault(); await saveSettings(); toast('设置已保存'); }));
document.querySelectorAll('[data-settings-section]').forEach(button => button.addEventListener('click', guard(async () => {
  settingsSection = button.dataset.settingsSection;
  await navigate('plugins');
})));
function showConnection(value) {
  if(!value)return;
  $('#server-url').value=value.url||'';$('#login-server-url').value=value.url||'';
}
async function connectFrom(prefix){
  const loggedOut=prefix==='login';
  const url=$(loggedOut?'#login-server-url':'#server-url').value.trim();
  const button=$(loggedOut?'#login-connect':'#connect-server'), message=$(loggedOut?'#login-connection-status':'#connection-result');
  button.disabled=true;message.textContent='正在连接…';
  try{const value=await call(api.saveConnection({mode:'remote',url}));showConnection(value);message.textContent=value.cancelled?'已取消':'连接设置已保存。';}
  finally{button.disabled=false;}
}
$('#login-connection-form').addEventListener('submit',guard(async event=>{event.preventDefault();await connectFrom('login');}));
$('#connect-server').addEventListener('click',guard(()=>connectFrom('settings')));
function showUpdates(value){
  if(!value)return;$('#update-status').textContent=value.message;
  $('#update-download').hidden=value.state!=='available';
  $('#update-install').hidden=value.state!=='downloaded';
  $('#update-install').textContent=value.mode==='manual-mac'?'打开安装包':'安装并重启';
  $('#update-check').disabled=['disabled','checking','downloading','downloaded'].includes(value.state);
}
api.onUpdates(value=>{showUpdates(value);if(value.state==='downloaded')toast(value.message+'：点击头像旁的更新按钮');});
$('#update-check').addEventListener('click',guard(async()=>showUpdates(await call(api.checkUpdates()))));
$('#update-download').addEventListener('click',guard(()=>call(api.downloadUpdate())));
$('#update-install').addEventListener('click',guard(()=>call(api.installUpdate())));
$('#update-releases').addEventListener('click',guard(()=>call(api.openExternal('https://github.com/L1nYux/FYrepo/releases'))));

(async () => {
  try {
    info = await call(api.info()); showConnection(info.connection);showUpdates(info.updates);showConfig(info); displayAuthentication(info); displayPage(info.current); displayMessageState(info);
    $('#admin-settings').hidden = !info.isAdmin;
    $('#api-settings').hidden = !info.canManageApi;
    $('#local-user').textContent = info.username || '正在准备'; $('#app-version').textContent = info.version; $('#local-data-path').textContent = info.dataPath;
    await window.prepareInterfaceLoading(info);
  } catch (error) { $('#startup-message').textContent=error.message;window.updateInterfaceLoading({loading:{phase:'error',full:true,message:error.message}}); }
})();

window.desktop.onBrowser(value=>{const header=document.getElementById("browser-header");header.hidden=!value.visible;if(value.width)header.style.width=value.width+"px";document.getElementById("browser-title").textContent=value.error|| (value.loading?"正在读取网页…":value.title||value.url);header.querySelector("[data-browser-action=back]").disabled=!value.canBack;});document.querySelectorAll("[data-browser-action]").forEach(button=>button.addEventListener("click",()=>window.desktop.browserAction(button.dataset.browserAction)));
