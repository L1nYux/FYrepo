const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const {PageCache,readable}=require('../page-cache.cjs');
test('presence heartbeats retain pages; actual writes notify retained views',async t=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'zhiyu-cache-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));let calls=0,mutations=[];
 const cache=new PageCache(root,()=>({authenticated:true,account:'one',origin:'https://example.test'}),async()=>{calls++;return new Response('<html data-account="1"><body>cached</body></html>',{headers:{'content-type':'text/html'}});},()=>true,p=>mutations.push(p));
 const page=new Request('https://example.test/messages/social/');await cache.handle(page);
 await cache.handle(new Request('https://example.test/messages/unread/',{method:'POST'}));await cache.handle(page);assert.equal(calls,2);assert.deepEqual(mutations,[]);
 await cache.handle(new Request('https://example.test/messages/personal/2/',{method:'POST'}));assert.deepEqual(mutations,['/messages/personal/2/']);await cache.handle(page);assert.equal(calls,4);
});
test('cached pages open without another request, offline uses same route, accounts remain isolated',async t=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'zhiyu-cache-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));
  let account='one',online=true,calls=0;
  const cache=new PageCache(root,()=>({authenticated:true,account,origin:'https://example.test'}),async req=>{calls++;return new Response('<html data-account="1"><body>项目任务</body></html>',{headers:{'content-type':'text/html','set-cookie':'secret'}});},()=>online);
  const req=()=>new Request('https://example.test/projects/3/');
  await cache.handle(req());assert.equal(calls,1);const response=await cache.handle(req());assert.equal(calls,1);assert.equal(response.headers.get('set-cookie'),null);
  online=false;assert.match(await (await cache.handle(req())).text(),/离线/);assert.equal(calls,1);
  account='two';await cache.handle(req());assert.equal(calls,2);
  account='one';await cache.handle(new Request('https://example.test/tasks/3/',{method:'POST',body:'write'}));await cache.handle(req());assert.equal(calls,4);
});
test('mutations, credentials and paid APIs never use page cache',()=>{
  for(const p of ['/login/','/api-pool/','/api/pool/v1/chat/completions','/assistant/jobs/3/','/projects/3/archive/','/documents/3/versions/'])assert.equal(readable(new URL('https://example.test'+p)),false,p);
});
test('an authorization denial cannot fall back to cached private content',async t=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'zhiyu-cache-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));let denied=false;
  const cache=new PageCache(root,()=>({authenticated:true,account:'one',origin:'https://example.test'}),async()=>denied?new Response('Denied',{status:403}):new Response('<html data-account="1"><body>Private</body></html>',{headers:{'content-type':'text/html'}}));
  const req=()=>new Request('https://example.test/projects/3/');await cache.handle(req());denied=true;cache.force();assert.equal((await cache.handle(req())).status,403);assert.equal(await cache.read(cache.identity(),req().url),null);
});
test('cache preserves redirects so the native navigation can validate their target',async t=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'zhiyu-cache-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));
  const cache=new PageCache(root,()=>({authenticated:true,account:'one',origin:'https://example.test'}),async(req,options)=>{
    assert.equal(options.bypassCustomProtocolHandlers,true);
    return new Response(null,{status:302,headers:{location:'https://example.test/workspace/'}});
  });
  for(const request of [new Request('https://example.test/projects/3/'),new Request('https://example.test/manage/contact/',{method:'POST',body:'save'})]){
    const response=await cache.handle(request);assert.equal(response.status,302);assert.equal(response.headers.get('location'),'https://example.test/workspace/');
  }
});
