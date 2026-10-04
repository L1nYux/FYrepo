const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveSettingsPage } = require('../navigation.cjs');
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
