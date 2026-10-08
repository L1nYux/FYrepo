// Match more specific settings routes before their query-free parent route.
function resolveSettingsPage(location, routes, settingsPages) {
  if(settingsPages.has('platformaudit') && location.pathname==='/platform/audit/')return 'platformaudit';
  if(settingsPages.has('platformaccounts') && location.pathname.startsWith('/platform/accounts/'))return 'platformaccounts';
  if(settingsPages.has('platform') && location.pathname.startsWith('/platform/'))return 'platform';
  if(location.pathname === '/account/close/')return 'security';
  if(location.pathname === '/account/set-password/')return 'security';
  if(location.pathname.startsWith('/account/forgot-code/') || location.pathname.startsWith('/account/reset/') || location.pathname.startsWith('/account/forgot/'))return 'security';
  if (settingsPages.has('recycle') && location.pathname.startsWith(routes.recycle)) return 'recycle';
  return Object.entries(routes)
    .filter(([name]) => settingsPages.has(name))
    .map(([name, route]) => [name, new URL(route, 'http://local.invalid')])
    .filter(([, route]) => route.pathname === location.pathname)
    .sort((a, b) => b[1].searchParams.size - a[1].searchParams.size)
    .find(([, route]) => [...route.searchParams].every(([key, value]) => location.searchParams.get(key) === value))?.[0];
}
function publicPagePath(pathname){return /^\/(?:$|public\/|contact\/|showcase\/|about\/|download\/)/.test(pathname);}
function resolveBusinessPage(location, routes, settingsPages) {
  const path=location.pathname+location.search;
  return resolveSettingsPage(location,routes,settingsPages) ||
    (personalPagePath(path)?'me':discoveryPagePath(path)?'discovery':
    messagePagePath(path)?'messages':location.pathname==='/assistant/'?'ai':
    location.pathname==='/api-pool/manage/'?'apimanage':location.pathname==='/api-pool/'?(location.searchParams.get('scope')==='team'?'apimanage':'usage'):'workspace');
}
function personalUsagePath(spaceId){
  const identifier=String(spaceId??'');
  return '/api-pool/'+(/^[1-9][0-9]{0,17}$/.test(identifier)?'?ownership='+identifier:'');
}
function workspacePath(value) {
  if(teamManagementPath(value))return value;
  if(typeof value==='string' && /^\/sampling\/(?:new\/|[1-9][0-9]{0,17}\/)?(?:\?ownership=(?:all|[1-9][0-9]{0,17}))?$/.test(value))return value;
  if(documentPagePath(value))return value;
  if(discoveryPagePath(value)||personalPagePath(value)||value==='/finance/teams/')return value;
  if(typeof value!=='string'||!/^\/(?:manage\/(?:members\/|invites\/|contact\/|recruitment\/(?:applications\/)?|)?|(?:workspace|projects|tasks|competitions|experiments|finance|teams|team-square|updates|platform)\/(?:\d+\/)?(?:\?[^#]*)?)$/.test(value))throw Error('导航地址无效。');
  return value;
}
function workspaceMenu(value) {
  if(!value||!Array.isArray(value.projects)||JSON.stringify(value).length>512000)return null;
  let remaining=1500;
  const link=(item,kind)=>{
    if(!item||typeof item.title!=='string'||typeof item.path!=='string'||!new RegExp('^/'+kind+'/[0-9]+/$').test(item.path))return null;
    const entry={title:item.title.slice(0,200),path:item.path};
    if(typeof item.owner==='string'&&item.owner)entry.owner=item.owner.slice(0,100);
    if(/^[0-9]{1,18}$/.test(item.space))entry.space=item.space;
    return entry;
  };
  const projects=[];
  for(const item of value.projects.slice(0,200)){
    const project=link(item,'projects');if(!project||remaining--<=0)continue;
    project.tasks=[];
    for(const task of (Array.isArray(item.tasks)?item.tasks:[]).slice(0,100)){
      const mother=link(task,'tasks');if(!mother||remaining--<=0)continue;
      mother.open=Boolean(task.open);mother.children=[];
      for(const child of (Array.isArray(task.children)?task.children:[]).slice(0,200)){
        const entry=link(child,'tasks');if(entry && remaining-- > 0)mother.children.push(entry);
      }
      project.tasks.push(mother);
    }
    projects.push(project);
  }
  const entries=kind=>(Array.isArray(value[kind])?value[kind]:[]).slice(0,100).map(item=>link(item,kind)).filter(Boolean);
  const spaces=(Array.isArray(value.spaces)?value.spaces:[]).slice(0,200).filter(item=>item&&/^[0-9]{1,18}$/.test(item.id)&&typeof item.name==='string').map(item=>({id:item.id,name:item.name.slice(0,100)}));
  return {projects,competitions:entries('competitions'),experiments:entries('experiments'),spaces,loaded:true};
}
// Reference/detail/action pages must never replace the remembered conversation.
function conversationPath(value) {
  try { const url=new URL(value,'http://local.invalid');
    return url.origin==='http://local.invalid' && /^\/messages\/(?:to\/[1-9][0-9]*\/|personal\/[1-9][0-9]*\/|groups\/[1-9][0-9]*\/)?$/.test(url.pathname)
      && [...url.searchParams].every(([key,v])=>key==='room'&&['public','developers'].includes(v)||key==='space'&&/^[1-9][0-9]{0,17}$/.test(v));
  } catch (_) { return false; }
}
function messagePagePath(value) {
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\'))return false;
  try {const url=new URL(value,'http://local.invalid');
    if(url.origin!=='http://local.invalid')return false;
    if(conversationPath(value))return true;
    if(/^\/messages\/groups\/[1-9][0-9]*\/$/.test(url.pathname))return [...url.searchParams].every(([key,v])=>key==='details'&&v==='1');
    if(url.pathname==='/teams/')return false;
    if(url.pathname==='/messages/notices/')return [...url.searchParams].every(([key,v])=>key==='page'&&/^[1-9][0-9]{0,8}$/.test(v));
    if(url.pathname==='/messages/social/')return [...url.searchParams].every(([key,v])=>key==='tab'&&['chats','friends','requests','groups','team'].includes(v)||key==='q'&&v.length<=150);
    if(teamManagementPath(value))return false;
    return /^\/messages\/groups\/[1-9][0-9]*\/manage\/$/.test(url.pathname)&&!url.search;
  }catch(_){return false;}
}
function teamIndependentPath(value) {
  if(teamManagementPath(value))return true;
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\'))return false;
  try {
    const url=new URL(value,'http://local.invalid');
    return url.origin==='http://local.invalid' && /^\/(?:updates\/(?:[1-9][0-9]*\/)?|teams\/|platform\/|team-square\/(?:[1-9][0-9]*\/|apply\/[1-9][0-9]*\/|resume\/|applications\/)?|messages\/(?:social\/|personal\/[1-9][0-9]*\/))$/.test(url.pathname);
  } catch (_) { return false; }
}
module.exports = { resolveSettingsPage, resolveBusinessPage, personalUsagePath, workspacePath, workspaceMenu, publicPagePath, conversationPath, messagePagePath, teamIndependentPath };

function discoveryPagePath(value){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\'))return false;
  try{const url=new URL(value,'http://local.invalid');return url.origin==='http://local.invalid' && (/^\/discover\/(?:talents\/(?:[1-9][0-9]*\/)?|profile\/|applications\/|offers\/(?:[1-9][0-9]*\/)?)?$/.test(url.pathname)||/^\/team-square\/(?:[1-9][0-9]*\/|apply\/[1-9][0-9]*\/|resume\/|applications\/)?$/.test(url.pathname)) && [...url.searchParams].every(([k,v])=>k==='q'&&v.length<=150||k==='page'&&/^[1-9][0-9]{0,8}$/.test(v)||k==='view'&&v==='sent');}catch(_){return false;}
}
module.exports.discoveryPagePath=discoveryPagePath;
function personalPagePath(value){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\'))return false;
  try{const url=new URL(value,'http://local.invalid');return url.origin==='http://local.invalid' && !url.hash && url.pathname===value.split('?')[0] && /^\/me\/(?:talent\/|api\/|usage\/|connections\/|ledger\/(?:new\/|[1-9][0-9]*\/edit\/)?)?$/.test(url.pathname) && [...url.searchParams].every(([k,v])=>k==='page'&&/^[1-9][0-9]{0,8}$/.test(v)||k==='tab'&&['usage','connections'].includes(v)||k==='funding'&&/^[1-9][0-9]{0,17}$/.test(v)||['model','provider'].includes(k)&&(v===''||/^[1-9][0-9]{0,17}$/.test(v))||k==='month'&&(v===''||/^\d{4}-\d{2}$/.test(v))||k==='prices'&&v==='1'||k==='scope'&&v==='mine');}catch(_){return false;}
}
module.exports.personalPagePath=personalPagePath;
function documentPagePath(value){
 if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\'))return false;
 try{const url=new URL(value,'http://local.invalid');return url.origin==='http://local.invalid'&&!url.hash&&/^\/documents\/(?:new\/|[1-9][0-9]*\/(?:plan\/)?)?$/.test(url.pathname)&&[...url.searchParams].every(([k,v])=>k==='ownership'&&v==='all'||['project','task','competition','experiment','draft','version','ownership'].includes(k)&&/^[1-9][0-9]{0,17}$/.test(v)||k==='q'&&v.length<=150||k==='page'&&/^[1-9][0-9]{0,8}$/.test(v)||k==='purpose'&&['','plan','notes','result'].includes(v)||k==='view'&&v==='trash'||k==='kind'&&['online','docx','xlsx','pdf'].includes(v));}catch(_){return false;}
}
module.exports.documentPagePath=documentPagePath;

function teamManagementPath(value){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\'))return false;
  try{const url=new URL(value,'http://local.invalid');
    return url.origin==='http://local.invalid'&&!url.hash&&/^\/messages\/teams\/(?:members\/(?:[1-9][0-9]*\/remove\/)?|invites\/|review\/|recruitment\/|permissions\/[1-9][0-9]*\/|rename\/|transfer\/|leave\/|disband\/)?$/.test(url.pathname)&&[...url.searchParams].every(([key,v])=>['team','space'].includes(key)&&/^[1-9][0-9]{0,17}$/.test(v)||['page','members_page','applications_page','invites_page'].includes(key)&&/^[1-9][0-9]{0,8}$/.test(v)||key==='q'&&v.length<=160||key==='tab'&&v==='settings');
  }catch(_){return false;}
}
