const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

function fixture(){
  class Node{
    constructor(){this.textContent='';this.hidden=false;this.open=false;this.value=0;this.children=new Map();}
    addEventListener(){} setAttribute(){} append(){} contains(){return false;}
    querySelector(key){if(!this.children.has(key))this.children.set(key,new Node());return this.children.get(key);}
  }
  const nodes=new Map(),pending=[];
  const node=key=>{if(!nodes.has(key))nodes.set(key,new Node());return nodes.get(key);};
  let update;
  const desktop={onAppearance(){},onState(fn){update=fn;},info:()=>new Promise(()=>{}),onUpdates(){},
    usage:()=>new Promise(resolve=>pending.push(resolve))};
  const context={window:{desktop},document:{querySelector:node,querySelectorAll:selector=>selector==='.usage-window small'?['week','month'].map(p=>node('[data-period="'+p+'"]').querySelector('small')):[],createElement:()=>new Node(),documentElement:{dataset:{}},addEventListener(){}},localStorage:{getItem(){return '';}}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../ui/account.js'),'utf8'),context);
  const state=(name='first',server='https://one.example')=>update({authenticated:Boolean(name),username:name,accountId:name,teamId:1,spaceId:1,serverUrl:server,accountMenuOpen:Boolean(name)});
  const resolve=(index,remaining)=>pending[index]({ok:true,data:{budget:{member_week:{limit:100,remaining_percent:remaining,used_percent:100-remaining,remaining_points:remaining},member:{limit:100},next_week_at:'2026-10-12T00:00:00Z',next_month_at:'2026-11-01T00:00:00Z',extra:{}}}});
  return {state,node,pending,resolve,load:()=>context.loadUsage(),flush:()=>new Promise(resolve=>setImmediate(resolve))};
}

test('switching account clears the previous allowance preview immediately',async()=>{
  const f=fixture();f.state();const loading=f.load();f.resolve(0,77);await loading;
  const preview=f.node('[data-period="week"]').querySelector('span');assert.equal(preview.textContent,'77% 剩余');
  f.state('second');assert.notEqual(preview.textContent,'77% 剩余');
});

test('new account can load allowance while the old account request is pending',async()=>{
  const f=fixture();f.state();const old=f.load();
  f.state('second');const fresh=f.load();assert.equal(f.pending.length,2);
  f.resolve(0,77);await old;
  assert.notEqual(f.node('[data-period="week"]').querySelector('span').textContent,'77% 剩余');
  const duplicate=f.load();assert.equal(f.pending.length,2);
  f.resolve(1,22);await fresh;await duplicate;
  assert.equal(f.node('[data-period="week"]').querySelector('span').textContent,'22% 剩余');
});

test('logging out and back into the same account rejects the previous request',async()=>{
  const f=fixture();f.state();const old=f.load();f.state('');f.state();
  f.resolve(0,77);await old;
  assert.notEqual(f.node('[data-period="week"]').querySelector('span').textContent,'77% 剩余');
});

test('identical names and team IDs on a different server do not share usage responses',async()=>{
  const f=fixture();f.state();const old=f.load();f.state('first','https://two.example');
  f.resolve(0,77);await old;
  assert.notEqual(f.node('[data-period="week"]').querySelector('span').textContent,'77% 剩余');
});
