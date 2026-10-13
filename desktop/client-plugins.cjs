const fs=require('node:fs'),path=require('node:path');
function catalogPath(directory,resources){
 const candidates=[resources&&path.join(resources,'client-plugins.json'),path.join(directory,'client-plugins.json'),path.join(directory,'../static/core/client-plugins.json')].filter(Boolean);
 const file=candidates.find(candidate=>fs.existsSync(candidate));
 if(!file)throw Error('Built-in client plugin catalog is missing.');
 return file;
}
const file=catalogPath(__dirname,process.resourcesPath);
const definitions=JSON.parse(fs.readFileSync(file,'utf8'));
const settings=new Set(['gitEnabled','githubEnabled','aiEnabled']),ids=new Set();
for(const row of definitions){
  if(!row||!/^desktop-[a-z-]+$/.test(row.id)||ids.has(row.id)||!settings.delete(row.setting)||!['git','ai'].includes(row.action))throw Error('Invalid built-in client plugin catalog.');
  ids.add(row.id);Object.freeze(row);
}
if(settings.size)throw Error('Incomplete built-in client plugin catalog.');
function snapshot(value){return definitions.map(({setting,action,...row})=>({...row,runtime:'desktop',scope:'device',enabled:value[setting]!==false,available:true,writes:false}));}
function change(identifier,enabled){
  const plugin=definitions.find(row=>row.id===identifier);
  if(!plugin||typeof enabled!=='boolean')throw Error('插件选项无效。');
  return {[plugin.setting]:enabled};
}
function action(identifier){const plugin=definitions.find(row=>row.id===identifier);if(!plugin)throw Error('插件不存在。');return plugin.action;}
function trustedSender(event,contents,origin,authenticated,pathname){
  try{return authenticated&&event.sender===contents&&event.senderFrame===contents.mainFrame&&new URL(event.senderFrame.url).origin===origin&&pathname(new URL(event.senderFrame.url).pathname+new URL(event.senderFrame.url).search);}
  catch(_){return false;}
}
module.exports={snapshot,change,action,trustedSender,catalogPath};
