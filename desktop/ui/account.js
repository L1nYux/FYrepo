const api = window.desktop;
const menu = document.querySelector('#account-menu');
api.onAppearance(value=>{document.documentElement.dataset.theme=value.theme;});
function update(value) {
  if (value.authenticated === false) { menu.open=false; document.querySelector('#username').textContent='未登录'; document.querySelector('#menu-username').textContent='未登录'; document.querySelector('#avatar').textContent='研'; }
  if (value.username) {
    document.querySelector('#username').textContent = value.username;
    document.querySelector('#menu-username').textContent = value.username;
    document.querySelector('#avatar').textContent = Array.from(value.username)[0].toUpperCase();
  }
  menu.open = Boolean(value.accountMenuOpen);
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
      row.querySelector('small').textContent=(window.limit===null?'已用 '+Number(window.spent_points ?? Number(window.spent)*100).toFixed(2)+' 点':'基础剩余 '+Number(window.remaining_points ?? Number(window.remaining)*100).toFixed(2)+' 点')+' · '+new Date(reset).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})+' 恢复'+(period==='week'?' · 额外 '+Number(budget.extra?.remaining_points||0).toFixed(2)+' 点':'');
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
document.addEventListener('click', event => { if (!menu.contains(event.target)) menu.open = false; });
api.onState(update);
api.info().then(result => { if (result.ok){update(result.data);if(result.data.appearance)document.documentElement.dataset.theme=result.data.appearance.theme;} });
