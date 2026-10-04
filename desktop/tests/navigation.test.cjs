const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveSettingsPage, workspacePath, workspaceMenu } = require('../navigation.cjs');
const routes = {account:'/account/',security:'/account/?tab=security',profile:'/account/public/',apimanage:'/api-pool/manage/'};
const pages = new Set(Object.keys(routes));

for (const [path, expected] of [
  ['/account/','account'], ['/account/?tab=security','security'],
  ['/account/?tab=security&extra=1','security'], ['/account/?tab=other','account'],
  ['/account/public/','profile'], ['/api-pool/manage/','apimanage'], ['/workspace/',undefined],
  ['/account/forgot/','security'], ['/account/forgot-code/new-password/','security'],
]) {
  test('settings route '+path, () => assert.equal(resolveSettingsPage(new URL(path,'http://localhost'),routes,pages),expected));
}

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
