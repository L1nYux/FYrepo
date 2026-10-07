const test=require('node:test'),assert=require('node:assert/strict');
const {fetchAvatar}=require('../avatar.cjs');
const url='/accounts/1/avatar/'+ 'a'.repeat(32)+'/';
test('avatar fetch uses the authenticated session and stays on the server',async()=>{
 let target,options;const bytes=Buffer.from('RIFF1234WEBPtest');
 const value=await fetchAvatar({fetch:async(u,o)=>{target=u;options=o;return new Response(bytes,{headers:{'content-type':'image/webp'}});}},'https://team.example',url);
 assert.equal(target,'https://team.example'+url);assert.equal(options.credentials,'include');assert.equal(options.redirect,'error');assert.equal(value,'data:image/webp;base64,'+bytes.toString('base64'));
});
test('arbitrary avatar paths cannot fetch other resources',async()=>{
 for(const value of ['https://evil.example/a','//evil.example/a','/api/key/','/accounts/1/avatar/a/?x=1','/accounts/1/avatar/../../secret/'])
 assert.equal(await fetchAvatar({fetch:()=>{throw Error('must not call');}},'https://team.example',value),'');
});
test('avatar payload must be a small WebP image',async()=>{
 for(const response of [new Response('html',{headers:{'content-type':'text/html'}}),new Response('not webp',{headers:{'content-type':'image/webp'}}),new Response(Buffer.alloc(512*1024+1),{headers:{'content-type':'image/webp'}}),new Response('missing',{status:404})])
 assert.equal(await fetchAvatar({fetch:async()=>response},'https://team.example',url),'');
});
