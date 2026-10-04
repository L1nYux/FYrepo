const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../../static/aihub/assistant.js'),'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness(fetch, savedJob = null) {
  class Element {
    constructor() {this.value='';this.disabled=false;this.hidden=false;this.children=[];this.events={};this.textContent='';}
    addEventListener(name,callback) {this.events[name]=callback;}
    append(...children) {this.children.push(...children);}
    replaceChildren(...children) {this.children=children;}
    querySelectorAll() {return [];}
    querySelector() {return new Element();}
    setAttribute() {} focus() {} scrollIntoView() {} remove() {} close() {} showModal() {}
  }
  const elements = new Map();
  const get = name => {if(!elements.has(name))elements.set(name,new Element());return elements.get(name);};
  const app = new Element();app.dataset={user:'1',catalog:'/catalog',start:'/start',jobBase:'/jobs/',references:'/references'};
  app.querySelector=()=>({value:'fake-csrf'});
  const stored = new Map(savedJob ? [['workbench-agent-job:1',savedJob]] : []);
  const storage = {getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value),removeItem:key=>stored.delete(key)};
  const timers = [];
  vm.runInNewContext(source,{
    document:{querySelector:()=>app,getElementById:id=>get(id.replace('assistant-','')),createElement:()=>new Element()},
    fetch,localStorage:storage,sessionStorage:storage,
    setTimeout:(callback,delay)=>{timers.push({callback,delay});return timers.length;},clearTimeout:()=>{},console,
  });
  return {get,stored,timers};
}
function response(data, status=200) {
  return {ok:status<400,status,redirected:false,headers:{get:()=> 'application/json'},json:async()=>data};
}
function catalog() {
  return response({models:[{id:1,configured:true,provider:'Test',label:'Test',supports_tools:true}],budget:{member_week:{limit:null,remaining_points:null},extra:{remaining_points:0}}});
}

test('pending assistant start cannot be submitted twice and failure keeps input', async () => {
  let starts=0, rejectStart;
  const ui=harness(async url=>{
    if(url==='/catalog')return catalog();
    if(url==='/start'){starts++;return new Promise((_,reject)=>{rejectStart=reject;});}
    throw Error('unexpected request');
  });
  await tick();
  ui.get('input').value='hello';
  const first=ui.get('form').events.submit({preventDefault(){}});
  await ui.get('form').events.submit({preventDefault(){}});
  assert.equal(starts,1);
  assert.equal(ui.get('send').disabled,true);
  rejectStart(Error('simulated offline'));
  await first;
  assert.equal(ui.get('input').value,'hello');
  assert.equal(ui.get('send').disabled,false);
  assert.match(ui.get('model').title,/基础额度不限/);
});

test('expired assistant job stops retrying and clears the saved job', async () => {
  const ui=harness(async url=>url==='/catalog'?catalog():response({error:'missing'},404),'expired-job');
  await tick();await tick();
  assert.equal(ui.stored.has('workbench-agent-job:1'),false);
  assert.equal(ui.get('send').disabled,false);
  assert.equal(ui.timers.length,0);
  assert.match(ui.get('status').textContent,/任务已不可用/);
});
