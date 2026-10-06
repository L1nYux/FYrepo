const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveSettingsPage, workspacePath, workspaceMenu, publicPagePath, conversationPath, teamIndependentPath } = require('../navigation.cjs');
const routes = {account:'/account/',security:'/account/?tab=security',profile:'/account/public/',apimanage:'/api-pool/manage/',members:'/manage/members/'};
const pages = new Set(Object.keys(routes));

test('personal community destinations remain usable without team membership',()=>{
  for(const value of ['/team-square/','/team-square/12/','/team-square/apply/12/','/team-square/resume/','/team-square/applications/?page=2','/messages/social/','/messages/personal/12/'])assert.equal(teamIndependentPath(value),true,value);
  for(const value of ['/projects/1/','/messages/','/messages/groups/1/','/team-square/applications/1/','https://example.com/team-square/','//example.com/team-square/','/team-square/../manage/','/team-square/%2fmanage/',null])assert.equal(teamIndependentPath(value),false,value);
});

test('only conversations can become the messages tab destination',()=>{
  for(const path of ['/messages/','/messages/?room=public','/messages/to/12/'])assert.equal(conversationPath(path),true,path);
  for(const path of ['/messages/references/announcement/1/','/messages/points/','/messages/to/12/poll/','/messages/?room=invalid','https://example.com/messages/','/messages/?next=/account/'])assert.equal(conversationPath(path),false,path);
});

for (const [path, expected] of [
  ['/account/','account'], ['/account/?tab=security','security'],
  ['/account/?tab=security&extra=1','security'], ['/account/?tab=other','account'],
  ['/account/public/','profile'], ['/api-pool/manage/','apimanage'], ['/workspace/',undefined],
  ['/account/set-password/','security'], ['/members/2/delete/','members'], ['/members/2/reset-password/','members'],
  ['/account/forgot/','security'], ['/account/forgot-code/new-password/','security'],
]) {
  test('settings route '+path, () => assert.equal(resolveSettingsPage(new URL(path,'http://localhost'),routes,pages),expected));
}
test('public visitor routes are separate from internal profile and management',()=>{
  for(const path of ['/','/public/members/','/contact/','/about/','/showcase/','/download/'])assert.equal(publicPagePath(path),true);
  for(const path of ['/account/public/','/manage/contact/','/workspace/','/account/forgot/'])assert.equal(publicPagePath(path),false);
});

test('native navigation accepts business destinations and rejects action routes',()=>{
  for(const path of ['/workspace/','/projects/12/','/tasks/3/','/finance/?type=expense'])assert.equal(workspacePath(path),path);
  for(const path of ['https://example.com/','//example.com/','/projects/1/delete/','/tasks/new/','/manage/members/',null])assert.throws(()=>workspacePath(path));
});
test('native menu uses bounded plain text and validated project/task paths',()=>{
  const menu=workspaceMenu({projects:[{title:'<img onerror=alert(1)>',path:'/projects/1/',tasks:[{title:'x'.repeat(250),path:'/tasks/2/',open:true,children:[{title:'valid',path:'/tasks/3/'},{title:'unsafe',path:'https://example.com/'}]}]},{title:'unsafe',path:'/projects/1/delete/'},{title:'object',path:{toString:()=>'/projects/4/'}}]});
  assert.equal(menu.loaded,true);assert.equal(menu.projects.length,1);
  assert.equal(menu.projects[0].title,'<img onerror=alert(1)>');
  assert.equal(menu.projects[0].tasks[0].title.length,200);
  assert.deepEqual(menu.projects[0].tasks[0].children,[{title:'valid',path:'/tasks/3/'}]);
  assert.equal(workspaceMenu({projects:[{title:'x'.repeat(512001),path:'/projects/1/'}]}),null);
});
