const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {AccountSnapshot}=require('../account-snapshot.cjs');
test('offline account keeps navigation context, omits secrets and is cleared by logout',t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'zhiyu-account-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));const cache=new AccountSnapshot(root);
 cache.save('https://one.test',{authenticated:true,username:'one',teamId:2,spaces:[{id:2,name:'团队'}],csrfToken:'secret',password:'secret'});
 assert.equal(cache.read('https://one.test').teamId,2);assert.equal(cache.read('https://two.test'),null);assert.equal(cache.read('https://one.test').csrfToken,undefined);assert.doesNotMatch(fs.readFileSync(cache.file('https://one.test'),'utf8'),/secret/);
 cache.remove('https://one.test');assert.equal(cache.read('https://one.test'),null);
});
