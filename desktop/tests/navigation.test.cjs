const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveSettingsPage, resolveBusinessPage, workspacePath, workspaceMenu, publicPagePath, conversationPath, messagePagePath, teamIndependentPath, discoveryPagePath, personalPagePath } = require('../navigation.cjs');
const routes = {account:'/account/',security:'/account/?tab=security',profile:'/account/public/',apimanage:'/api-pool/manage/',members:'/manage/members/'};
const pages = new Set(Object.keys(routes));

test('sampling navigation accepts bounded workspace paths and rejects foreign URLs',()=>{
  for(const value of ['/sampling/','/sampling/new/','/sampling/42/','/sampling/?ownership=7','/sampling/?ownership=all'])
    assert.equal(workspacePath(value),value);
  for(const value of ['//other/sampling/','/sampling/../platform/','/sampling/?ownership='+ '9'.repeat(100),'/sampling/?redirect=https://other'])
    assert.throws(()=>workspacePath(value));
});

test('account usage enters the team API page with a bounded team',()=>{
  const {personalUsagePath}=require('../navigation.cjs');
  for(const id of [null,undefined,0,'0','-1','9'.repeat(100),'1&tab=connections'])assert.equal(personalUsagePath(id),'/api-pool/');
  assert.equal(personalUsagePath('42'),'/api-pool/?ownership=42');
  assert.equal(resolveBusinessPage(new URL(personalUsagePath('42'),'http://localhost'),routes,pages),'usage');
});
test('one exported resolver classifies personal, discovery, messages and settings pages',()=>{
  const {resolveBusinessPage}=require('../navigation.cjs');
  for(const [path,page] of [['/me/api/?tab=connections','me'],['/discover/profile/','discovery'],['/messages/social/?tab=friends','messages'],['/account/?tab=security','security'],['/account/public/','profile'],['/assistant/','ai'],['/documents/3/','workspace']])assert.equal(resolveBusinessPage(new URL(path,'http://localhost'),routes,pages),page);
});

test('personal area remembers safe pages and excludes destructive actions',()=>{
  for(const path of ['/me/','/me/ledger/?page=2','/me/ledger/new/','/me/ledger/12/edit/','/me/usage/','/me/connections/']){
    assert.equal(personalPagePath(path),true,path);assert.equal(workspacePath(path),path);
  }
  for(const path of ['/me/ledger/12/archive/','/me/ledger/?ownership=1','/me/ledger/?page=0','/me/../me/','/me/#test','/me/ledger/0/edit/','https://example.com/me/','//example.com/me/','/me/\\ledger/',null])assert.equal(personalPagePath(path),false,path);
  assert.equal(workspacePath('/finance/teams/'),'/finance/teams/');
});

test('discovery retains listings, application forms and private offer pages',()=>{
  for(const path of ['/discover/?q=research','/discover/talents/?page=2','/discover/talents/12/','/discover/profile/','/discover/applications/','/discover/offers/?view=sent','/discover/offers/12/','/team-square/12/','/team-square/apply/12/']){
    assert.equal(discoveryPagePath(path),true,path);assert.equal(workspacePath(path),path);assert.equal(conversationPath(path),false);
  }
  for(const path of ['/discover/offers/12/respond/','/discover/?next=/account/','/discover/?page=0','/discover/talents/0/','https://example.com/discover/','//example.com/discover/'])assert.equal(discoveryPagePath(path),false,path);
});
test('team settings and platform areas keep contextual navigation',()=>{
  assert.equal(messagePagePath('/messages/teams/?team=12&tab=settings'),false);
  assert.equal(workspacePath('/messages/teams/?team=12&tab=settings'),'/messages/teams/?team=12&tab=settings');
  assert.equal(resolveBusinessPage(new URL('/messages/teams/?team=12&tab=settings','http://localhost'),routes,pages),'workspace');
  assert.equal(messagePagePath('/messages/teams/?team=12&tab=unknown'),false);
  const adminPages=new Set(['platform','platformaccounts','platformaudit']);
  for(const [path,name] of [['/platform/','platform'],['/platform/accounts/12/','platformaccounts'],['/platform/audit/','platformaudit']])assert.equal(resolveSettingsPage(new URL(path,'http://localhost'),{},adminPages),name);
});

test('personal community destinations remain usable without team membership',()=>{
  for(const value of ['/team-square/','/team-square/12/','/team-square/apply/12/','/team-square/resume/','/team-square/applications/?page=2','/messages/social/','/messages/personal/12/'])assert.equal(teamIndependentPath(value),true,value);
  for(const value of ['/projects/1/','/messages/','/messages/groups/1/','/team-square/applications/1/','https://example.com/team-square/','//example.com/team-square/','/team-square/../manage/','/team-square/%2fmanage/',null])assert.equal(teamIndependentPath(value),false,value);
});

test('only conversations can become the messages tab destination',()=>{
  for(const path of ['/messages/','/messages/?room=public','/messages/to/12/'])assert.equal(conversationPath(path),true,path);
  for(const path of ['/messages/references/announcement/1/','/messages/points/','/messages/to/12/poll/','/messages/?room=invalid','https://example.com/messages/','/messages/?next=/account/'])assert.equal(conversationPath(path),false,path);
});
test('contacts and group settings remain in messages without replacing the conversation',()=>{
  for(const path of ['/messages/social/','/messages/social/?tab=friends','/messages/social/?tab=requests&q=alice','/messages/groups/2/manage/','/messages/notices/']){
    assert.equal(messagePagePath(path),true,path);assert.equal(conversationPath(path),false,path);
  }
  for(const path of ['/messages/social/?tab=invalid','/messages/social/?next=/account/','/messages/groups/2/delete/','https://example.com/messages/social/','//example.com/messages/social/'])assert.equal(messagePagePath(path),false,path);
});

for (const [path, expected] of [
  ['/account/','account'], ['/account/?tab=security','security'],
  ['/account/?tab=security&extra=1','security'], ['/account/?tab=other','account'],
  ['/account/public/','profile'], ['/api-pool/manage/','apimanage'], ['/workspace/',undefined],
  ['/account/set-password/','security'], ['/members/2/delete/',undefined], ['/members/2/reset-password/',undefined],
  ['/account/forgot/','security'], ['/account/forgot-code/new-password/','security'],
]) {
  test('settings route '+path, () => assert.equal(resolveSettingsPage(new URL(path,'http://localhost'),routes,pages),expected));
}
test('public visitor routes are separate from internal profile and management',()=>{
  for(const path of ['/','/public/members/','/contact/','/about/','/showcase/','/download/'])assert.equal(publicPagePath(path),true);
  for(const path of ['/account/public/','/manage/contact/','/workspace/','/account/forgot/'])assert.equal(publicPagePath(path),false);
});

test('native navigation accepts business destinations and rejects action routes',()=>{
  assert.equal(personalPagePath('/me/talent/'),true);
  assert.equal(resolveBusinessPage(new URL('/me/talent/','http://localhost'),routes,pages),'me');
  for(const path of ['/workspace/','/projects/12/','/tasks/3/','/finance/?type=expense','/teams/','/manage/members/','/manage/recruitment/','/updates/'])assert.equal(workspacePath(path),path);
  for(const path of ['https://example.com/','//example.com/','/projects/1/delete/','/tasks/new/','/manage/members/2/delete/',null])assert.throws(()=>workspacePath(path));
});
test('native menu uses bounded plain text and validated project/task paths',()=>{
  const menu=workspaceMenu({projects:[{title:'<img onerror=alert(1)>',path:'/projects/1/',tasks:[{title:'x'.repeat(250),path:'/tasks/2/',open:true,children:[{title:'valid',path:'/tasks/3/'},{title:'unsafe',path:'https://example.com/'}]}]},{title:'unsafe',path:'/projects/1/delete/'},{title:'object',path:{toString:()=>'/projects/4/'}}]});
  assert.equal(menu.loaded,true);assert.equal(menu.projects.length,1);
  assert.equal(menu.projects[0].title,'<img onerror=alert(1)>');
  assert.equal(menu.projects[0].tasks[0].title.length,200);
  assert.deepEqual(menu.projects[0].tasks[0].children,[{title:'valid',path:'/tasks/3/'}]);
  assert.equal(workspaceMenu({projects:[{title:'x'.repeat(512001),path:'/projects/1/'}]}),null);
});
