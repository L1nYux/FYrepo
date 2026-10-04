const api = window.desktop;
const menu = document.querySelector('#account-menu');
let readyGeneration=-1;
api.onAppearance(value=>{document.documentElement.dataset.theme=value.theme;});
function update(value) {
  document.documentElement.dataset.chatMode=String(value.current==='messages');
  document.querySelector('#email-dot').hidden=!value.authenticated || !value.needsEmailBinding;
  if (value.authenticated === false) { menu.open=false; document.querySelector('#username').textContent='未登录'; document.querySelector('#menu-username').textContent='未登录'; document.querySelector('#avatar').textContent='研'; }
  if (value.username) {
    document.querySelector('#username').textContent = value.username;
    document.querySelector('#menu-username').textContent = value.username;
    document.querySelector('#avatar').textContent = Array.from(value.username)[0].toUpperCase();
    if(typeof value.avatar==='string'&&/^data:image\/webp;base64,[A-Za-z0-9+/=]+$/.test(value.avatar)){
      const image=document.createElement('img');image.src=value.avatar;image.alt='';
      image.addEventListener('error',()=>image.remove(),{once:true});document.querySelector('#avatar').append(image);
    }
  }
  menu.open = Boolean(value.accountMenuOpen);
  if(value.loading&&value.loading.phase!=='idle'&&readyGeneration!==value.loading.generation){
    readyGeneration=value.loading.generation;const generation=readyGeneration;
    document.fonts.ready.then(()=>{document.documentElement.getBoundingClientRect();api.accountReady(generation);});
  }
}
menu.addEventListener('toggle', () => api.accountMenu(menu.open));
let usageBusy=false;
async function loadUsage(){
  if(usageBusy||!menu.open)return;usageBusy=true;
  const owner=document.querySelector('#username').textContent;
  try{const result=await api.usage();if(!result.ok)throw Error(result.error);
    if(owner!==document.querySelector('#username').textContent)return;
    const budget=result.data.budget;
    for(const [period,window,reset] of [['week',budget.member_week,budget.next_week_at],['month',budget.member,budget.next_month_at]]){
      const row=document.querySelector('[data-period="'+period+'"]'); if(period==='month'){row.hidden=true;continue;}
      row.querySelector('span').textContent=window.limit===null?'未设上限':Math.round(window.remaining_percent)+'% 剩余';
      const progress=row.querySelector('progress');progress.hidden=window.limit===null;progress.value=window.used_percent;
      row.querySelector('small').textContent=(window.limit===null?'已用 '+Number(window.spent_points ?? Number(window.spent)*100).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点':'基础剩余 '+Number(window.remaining_points ?? Number(window.remaining)*100).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点')+' · '+new Date(reset).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})+' 恢复'+(period==='week'?' · 额外 '+Number(budget.extra?.remaining_points||0).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点':'');
    }
  }catch(error){document.querySelectorAll('.usage-window small').forEach(n=>n.textContent='用量暂不可用');}
  finally{usageBusy=false;}
}
menu.addEventListener('toggle',()=>{if(menu.open)loadUsage();});
document.querySelector('#usage-details').addEventListener('click',async()=>{menu.open=false;await api.accountMenu(false);await api.usageOpen();});
document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', async () => {
  menu.open = false;
  await api.accountMenu(false);
  await api.navigate(button.dataset.page);
}));
document.querySelector('#quit').addEventListener('click', () => api.window('close'));
document.querySelector('#logout').addEventListener('click',async event => {
  event.target.disabled=true; document.querySelector('#account-error').hidden=true;
  try {
    const result=await api.logout();
    if (!result.ok) { document.querySelector('#account-error').textContent=result.error; document.querySelector('#account-error').hidden=false; }
    else if (!result.data?.cancelled) menu.open=false;
  } finally { event.target.disabled=false; }
});
document.addEventListener('keydown', event => { if (event.key === 'Escape') menu.open = false; });
document.addEventListener('click', event => { if (!menu.contains(event.target)&&!event.target.closest('#avatar-update')) menu.open = false; });
api.onState(update);
api.info().then(result => { if (result.ok){update(result.data);renderUpdates(result.data.updates);if(result.data.appearance)document.documentElement.dataset.theme=result.data.appearance.theme;} });

let updateState={state:'disabled',message:'正在准备更新功能…'};
function renderUpdates(value){
  if(!value)return;updateState=value;
  const ready=value.state==='downloaded';
  const button=document.querySelector('#avatar-update');
  button.disabled=value.state==='disabled';button.dataset.state=value.state;
  button.title=value.message;button.setAttribute('aria-label',ready?(value.mode==='manual-mac'?'打开更新安装包':'安装更新并重启'):value.state==='error'?'重试应用更新':value.message);
  document.querySelector('#update-dot').hidden=!['available','downloaded'].includes(value.state);
  document.querySelector('#avatar-update-status').textContent=value.message;
  const progress=document.querySelector('#avatar-update-progress');progress.hidden=value.state!=='downloading';progress.value=value.percent||0;
  const install=document.querySelector('#avatar-update-install');install.hidden=!ready;install.textContent=value.mode==='manual-mac'?'打开安装包':'安装并重启';
}
async function updateAction(install=false){
  menu.open=true;await api.accountMenu(true);document.querySelector('#update-panel').hidden=false;
  try{const result=await (install||updateState.state==='downloaded'?api.installUpdate():api.checkUpdates());
    if(!result.ok)throw Error(result.error);if(result.data?.state)renderUpdates(result.data);
  }catch(error){document.querySelector('#avatar-update-status').textContent=error.message;}
}
document.querySelector('#avatar-update').addEventListener('click',()=>updateAction());
document.querySelector('#avatar-update-install').addEventListener('click',()=>updateAction(true));
api.onUpdates?.(renderUpdates);
