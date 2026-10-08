const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function fixture(){
  class Node {
    constructor(){this.value='';this.textContent='';this.children=[];this.hidden=false;}
    addEventListener(){} setAttribute(){} removeAttribute(){}
    replaceChildren(...items){this.children=items;} append(...items){this.children.push(...items);}
    querySelector(){return new Node();} querySelectorAll(){return [];}
  }
  const nodes=new Map(),pending=[];
  const node=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
  const request=kind=>new Promise((resolve,reject)=>pending.push({kind,resolve,reject}));
  const api={repoStatus:()=>request('status'),repoFiles:()=>request('files'),repoList:()=>request('list'),onRepositorySaved(){},onRepositoryDiscard(){}};
  const context={window:{desktop:api},document:{getElementById:node,createElement:()=>new Node(),querySelectorAll:()=>[],addEventListener(){}},setTimeout,clearTimeout};
  vm.runInNewContext(fs.readFileSync(require.resolve('../ui/repository.js'),'utf8'),context);
  const complete=(offset,name)=>{
    pending[offset].resolve({ok:true,data:{name,context:name,files:[],empty:true}});
    pending[offset+1].resolve({ok:true,data:{context:name,files:[]}});
    pending[offset+2].resolve({ok:true,data:{items:[],selected:''}});
  };
  return {workbench:context.window.repositoryWorkbench,pending,node,complete};
}

test('logout discards a late repository response',async()=>{
  const f=fixture(),old=f.workbench.activate();
  f.workbench.reset();f.complete(0,'old-private-repository');await old;
  assert.notEqual(f.node('repo-name').textContent,'old-private-repository');
  assert.equal(f.node('repo-file-tree').children.length,0);
});

test('a new account starts a fresh repository load while the old request waits',async()=>{
  const f=fixture(),old=f.workbench.activate();
  f.workbench.reset();const fresh=f.workbench.activate();
  assert.equal(f.pending.length,6);
  f.complete(0,'old-private-repository');await old;
  const duplicate=f.workbench.activate();assert.equal(f.pending.length,6);
  f.complete(3,'current-repository');await fresh;await duplicate;
  assert.equal(f.node('repo-name').textContent,'current-repository');
});

test('a stale repository error cannot overwrite the new account status',async()=>{
  const f=fixture(),old=f.workbench.activate();
  f.workbench.reset();const fresh=f.workbench.activate();
  f.complete(3,'current-repository');await fresh;
  const text=f.node('repo-status').textContent;
  f.pending[0].reject(Error('old account request failed'));
  await old;
  assert.equal(f.node('repo-status').textContent,text);
});
