// Match more specific settings routes before their query-free parent route.
function resolveSettingsPage(location, routes, settingsPages) {
  if(location.pathname.startsWith('/account/forgot-code/') || location.pathname==='/account/forgot/')return 'security';
  if (settingsPages.has('recycle') && location.pathname.startsWith(routes.recycle)) return 'recycle';
  return Object.entries(routes)
    .filter(([name]) => settingsPages.has(name))
    .map(([name, route]) => [name, new URL(route, 'http://local.invalid')])
    .filter(([, route]) => route.pathname === location.pathname)
    .sort((a, b) => b[1].searchParams.size - a[1].searchParams.size)
    .find(([, route]) => [...route.searchParams].every(([key, value]) => location.searchParams.get(key) === value))?.[0];
}
function workspacePath(value) {
  if(typeof value!=='string'||!/^\/(?:workspace|projects|tasks|competitions|experiments|finance)\/(?:\d+\/)?(?:\?[^#]*)?$/.test(value))throw Error('导航地址无效。');
  return value;
}
function workspaceMenu(value) {
  if(!value||!Array.isArray(value.projects)||JSON.stringify(value).length>512000)return null;
  let remaining=1500;
  const link=(item,kind)=>item&&typeof item.title==='string'&&typeof item.path==='string'&&new RegExp('^/'+kind+'/[0-9]+/$').test(item.path)?{title:item.title.slice(0,200),path:item.path}:null;
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
  return {projects,loaded:true};
}
module.exports = { resolveSettingsPage, workspacePath, workspaceMenu };
