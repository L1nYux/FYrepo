const {test}=require('node:test'),assert=require('node:assert/strict');
const {PresentationGate}=require('../loading.cjs');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
test('all renderers must be prepared before startup reveal',()=>{
  let reveals=0;const gate=new PresentationGate(()=>{},()=>reveals++);
  const generation=gate.begin(true);gate.expect(['chrome','account','business']);
  gate.ready('account',generation);gate.ready('chrome',generation);
  assert.equal(reveals,0);assert.equal(gate.phase,'loading');
  gate.ready('business',generation);assert.equal(reveals,1);assert.equal(gate.phase,'idle');
  gate.ready('business',generation);assert.equal(reveals,1);
});
test('unknown authentication target cannot reveal an account prematurely',()=>{
  let reveals=0;const gate=new PresentationGate(()=>{},()=>reveals++);
  const generation=gate.begin(true);gate.ready('chrome',generation);
  assert.equal(reveals,0);gate.expect(['chrome']);assert.equal(reveals,1);
});
test('late readiness from an earlier page cannot complete the new one',()=>{
  let reveals=0;const gate=new PresentationGate(()=>{},()=>reveals++);
  const old=gate.begin(true);gate.expect(['business']);
  const current=gate.begin(false);gate.expect(['business']);
  assert.equal(gate.ready('business',old),false);assert.equal(reveals,0);
  gate.ready('business',current);assert.equal(reveals,1);assert.equal(gate.snapshot().full,false);
});
test('slow connection has an explanation and finite timeout',async()=>{
  const gate=new PresentationGate(()=>{},()=>assert.fail('cannot reveal a timed-out page'),{slowAfter:5,timeout:25});
  gate.begin(true);gate.expect(['business']);await wait(12);
  assert.match(gate.message,/连接团队服务器/);await wait(30);
  assert.equal(gate.phase,'error');assert.match(gate.message,/超时/);
});
test('failure keeps content hidden until an explicit retry',()=>{
  let reveals=0;const gate=new PresentationGate(()=>{},()=>reveals++);
  const old=gate.begin(false);gate.expect(['business']);gate.fail('HTTP 500');
  gate.ready('business',old);assert.equal(reveals,0);assert.equal(gate.phase,'error');
  const next=gate.begin(false);gate.expect(['business']);gate.ready('business',next);assert.equal(reveals,1);
});
test('dismiss invalidates all outstanding readiness messages',()=>{
  let reveals=0;const gate=new PresentationGate(()=>{},()=>reveals++);
  const old=gate.begin(true);gate.expect(['business']);gate.dismiss();
  gate.ready('business',old);assert.equal(reveals,0);assert.equal(gate.phase,'idle');
});

test('ready local shell changes slow status to content loading',async()=>{
  const gate=new PresentationGate(()=>{},()=>{}, {slowAfter:5,timeout:1000});
  gate.begin(true);gate.expect(['chrome','account','business']);gate.full=false;
  await wait(12);assert.match(gate.message,/页面加载较慢/);gate.dismiss();
});
test('remote failure still accepts native readiness without exposing failed content',()=>{
  let reveals=0;const gate=new PresentationGate(()=>{},()=>reveals++);
  const generation=gate.begin(true);gate.expect(['chrome','account','business']);gate.fail('HTTP 500');
  assert.equal(gate.ready('chrome',generation),true);assert.equal(gate.ready('account',generation),true);
  assert.equal(gate.ready('business',generation),false);assert.equal(reveals,0);assert.equal(gate.phase,'error');
});
