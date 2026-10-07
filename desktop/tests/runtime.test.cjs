const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {installRuntime}=require('./runtime.cjs');
test('broken stdout and stderr exit the test once without an uncaught error',()=>{
 const stdout=new EventEmitter(),stderr=new EventEmitter(),codes=[];
 const dispose=installRuntime({exit:code=>codes.push(code)},{stdout,stderr});
 stdout.emit('error',Object.assign(new Error('broken pipe'),{code:'EPIPE'}));
 stderr.emit('error',Object.assign(new Error('broken pipe'),{code:'EPIPE'}));
 assert.deepEqual(codes,[1]);dispose();
 assert.equal(stdout.listenerCount('error'),0);assert.equal(stderr.listenerCount('error'),0);
});
test('a stuck UI test exits at its deadline',async()=>{
 const codes=[],dispose=installRuntime({exit:code=>codes.push(code)},
  {stdout:new EventEmitter(),stderr:new EventEmitter(),timeoutMs:10});
 await new Promise(resolve=>setTimeout(resolve,25));
 assert.deepEqual(codes,[1]);dispose();
});
