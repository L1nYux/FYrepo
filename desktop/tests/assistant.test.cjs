const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../static/aihub/assistant.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(fetch,savedJob=null,reference=false){
  class Element{
    constructor(){this.value='';this.disabled=false;this.hidden=false;this.children=[];this.events={};this.textContent='';this.attributes={};this.selectors={};this.classList={add(){}};}
    addEventListener(name,callback){this.events[name]=callback;}
    append(...children){for(const child of children){child.parent=this;this.children.push(child);}}
    insertBefore(child){this.append(child);}
    replaceChildren(...children){this.children=[];this.append(...children);}
    querySelectorAll(selector){return this.children.flatMap(child=>[...(selector==='[data-assistant-retry]'&&child.attributes[selector.slice(1,-1)]!==undefined?[child]:[]),...child.querySelectorAll(selector)]);}
    querySelector(selector){return this.selectors[selector]??=new Element();}
    setAttribute(k,v){this.attributes[k]=v;}focus(){}scrollIntoView(){}close(){}showModal(){}
    remove(){if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);}
  }
  const elements=new Map(),get=name=>{if(!elements.has(name))elements.set(name,new Element());return elements.get(name);};
  const app=new Element();app.dataset={user:'1',team:'1',catalog:'/catalog',start:'/start',jobBase:'/jobs/',references:'/references',...(reference?{contextKind:'task',contextId:'12'}:{})};app.querySelector=()=>({value:'fake-csrf'});
  const stored=new Map(savedJob?[['workbench-agent-job:1:1',savedJob]]:[]),storage={getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},timers=[];
  vm.runInNewContext(source,{window:{},document:{querySelector:()=>app,getElementById:id=>get(id.replace('assistant-','')),createElement:()=>new Element()},crypto:require('node:crypto').webcrypto,fetch,localStorage:storage,sessionStorage:storage,setTimeout:(callback,delay)=>{timers.push({callback,delay});return timers.length;},clearTimeout:()=>{},console});
  return {get,stored,timers,retry:()=>get('thread').querySelectorAll('[data-assistant-retry]').at(-1),submit:()=>get('form').events.submit({preventDefault(){}})};
}
function response(data,status=200){return {ok:status<400,status,redirected:false,headers:{get:()=> 'application/json'},json:async()=>data};}
function catalog(){return response({models:[{id:1,configured:true,provider:'Test',label:'Test',supports_tools:true}],budget:{member_week:{limit:null,remaining_points:null},extra:{remaining_points:0}}});}
test('pending start guarded; failed bubble retries original payload without clearing new draft',async()=>{
  let rejectStart;const bodies=[];
  const ui=harness(async(url,options)=>{if(url==='/catalog')return catalog();if(url==='/start'){bodies.push(JSON.parse(options.body));if(bodies.length===1)return new Promise((_,reject)=>rejectStart=reject);return response({job:'job-1'});}return response({state:'done',result:{text:'ok',calls:1,tokens:1,cost_cny:0}});},null,true);
  await tick();ui.get('model').value='1';ui.get('input').value='hello';const first=ui.submit();await ui.submit();assert.equal(bodies.length,1);assert.equal(ui.get('send').disabled,true);
  assert.equal(ui.get('input').value,'');assert.equal(ui.get('context').hidden,true);rejectStart(Error('offline'));await first;
  assert.equal(ui.get('send').disabled,false);assert.equal(ui.retry().textContent,'重试');
  ui.get('input').value='new draft';const retry=ui.retry();retry.events.click();retry.events.click();await tick();await tick();
  assert.equal(bodies.length,2);assert.deepEqual(bodies[0],bodies[1]);assert.deepEqual(bodies[1].context,{kind:'task',id:12});assert.equal(ui.get('input').value,'new draft');
  assert.equal(ui.get('thread').children.filter(row=>row.className==='assistant-row user').length,1);
});
test('successful send clears reference and next message carries none',async()=>{
  const bodies=[];const ui=harness(async(url,options)=>url==='/catalog'?catalog():url==='/start'?(bodies.push(JSON.parse(options.body)),response({job:'job-'+bodies.length})):response({state:'done',result:{text:'ok',calls:1,tokens:1,cost_cny:0}}),null,true);
  await tick();ui.get('input').value='first';await ui.submit();await tick();ui.get('input').value='second';await ui.submit();await tick();assert.deepEqual(bodies[0].context,{kind:'task',id:12});assert.equal(bodies[1].context,null);
});
test('model failure retries explicitly with failed job and fresh identifier',async()=>{
  const bodies=[];const ui=harness(async(url,options)=>url==='/catalog'?catalog():url==='/start'?(bodies.push(JSON.parse(options.body)),response({job:'job-'+bodies.length})):response({state:'error',result:{error:'upstream failed'}}),null,true);
  await tick();ui.get('input').value='original';await ui.submit();await tick();assert.equal(bodies.length,1);ui.retry().events.click();await tick();assert.equal(bodies.length,2);assert.equal(bodies[1].retry_job,'job-1');assert.notEqual(bodies[1].request_id,bodies[0].request_id);assert.deepEqual(bodies[1].context,bodies[0].context);
});
test('poll disconnect manual retry resumes same job without another start',async()=>{
  let starts=0,polls=0;const ui=harness(async url=>{if(url==='/catalog')return catalog();if(url==='/start'){starts++;return response({job:'same-job'});}polls++;if(polls===1)throw Error('offline');return response({state:'done',result:{text:'ok',calls:1,tokens:1,cost_cny:0}});});
  await tick();ui.get('input').value='hello';await ui.submit();await tick();assert.equal(ui.timers.length,0);assert.equal(ui.stored.get('workbench-agent-job:1:1'),'same-job');ui.retry().events.click();await tick();assert.equal(starts,1);assert.equal(polls,2);
});
test('expired assistant job clears saved task without automatic retry',async()=>{
  const ui=harness(async url=>url==='/catalog'?catalog():response({error:'missing'},404),'expired-job');await tick();await tick();assert.equal(ui.stored.has('workbench-agent-job:1:1'),false);assert.equal(ui.get('send').disabled,false);assert.equal(ui.timers.length,0);assert.match(ui.get('status').textContent,/任务已不可用/);
});
