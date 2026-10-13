const test=require('node:test'),assert=require('node:assert/strict');
const plugins=require('../client-plugins.cjs'),{pluginPagePath}=require('../navigation.cjs');
test('all local capability switches share the catalog and retain their settings',()=>{
 const values=plugins.snapshot({gitEnabled:false,githubEnabled:true,aiEnabled:false});
 assert.deepEqual(values.map(row=>[row.id,row.enabled]),[['desktop-repository',false],['desktop-sync',true],['desktop-assistant',false]]);
 assert.ok(values.every(row=>row.scope==='device'&&row.available&&row.runtime==='desktop'&&!('setting' in row)));
 assert.deepEqual(plugins.change('desktop-sync',false),{githubEnabled:false});
 assert.deepEqual(plugins.change('desktop-repository',true),{gitEnabled:true});
 assert.equal(plugins.action('desktop-repository'),'git');assert.equal(plugins.action('desktop-assistant'),'ai');
});
test('unknown plugin identifiers and non-boolean settings cannot alter native capabilities',()=>{
 for(const id of ['tasks','../main.cjs','constructor','unknown','gitEnabled'])assert.throws(()=>plugins.change(id,true));
 for(const value of [null,0,1,'false',{},[]])assert.throws(()=>plugins.change('desktop-sync',value));
});
test('native plugin bridge only trusts the current authenticated top-level marketplace page',()=>{
 const frame={url:'https://team.example/plugins/desktop-sync/'},contents={mainFrame:frame};
 const event={sender:contents,senderFrame:frame};
 assert.equal(plugins.trustedSender(event,contents,'https://team.example',true,pluginPagePath),true);
 assert.equal(plugins.trustedSender(event,contents,'https://team.example',false,pluginPagePath),false);
 assert.equal(plugins.trustedSender({...event,senderFrame:{...frame}},contents,'https://team.example',true,pluginPagePath),false);
 assert.equal(plugins.trustedSender({...event,sender:{}},contents,'https://team.example',true,pluginPagePath),false);
 for(const url of ['https://other.example/plugins/','https://team.example/workspace/','https://team.example/plugins/tasks/setting/','file:///plugins/','https://team.example/plugins/?redirect=https://other.example']){
  frame.url=url;assert.equal(plugins.trustedSender(event,contents,'https://team.example',true,pluginPagePath),false);
 }
});
