const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{EventEmitter}=require('node:events');
const {FileDownloads}=require('../file-downloads.cjs');
test('default download folder, progress, reuse, cancellation and account isolation',t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'zhiyu-download-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const session=new EventEmitter(),events=[],opened=[];let account='one';const url='https://example.test/messages/files/1/';
 const contents={id:1,getURL:()=> 'https://example.test/files/upload/1/',send:(_,value)=>events.push(value),downloadURL:()=>{},isDestroyed:()=>false};
 const manager=new FileDownloads(session,root,()=>({authenticated:true,account,origin:'https://example.test'}),value=>opened.push(value));
 const item=()=>Object.assign(new EventEmitter(),{getURLChain:()=>[url],getURL:()=>url,getFilename:()=> '文件.docx',setSavePath(value){this.path=value;},getReceivedBytes:()=>50,getTotalBytes:()=>100,cancel(){this.cancelled=true;this.emit('done',{},'cancelled');},getState:()=> 'progressing'});
 manager.start(contents,url,true);const first=item();session.emit('will-download',{},first,contents);assert.equal(path.dirname(first.path),root);first.emit('updated');assert.equal(events.at(-1).percent,50);fs.writeFileSync(first.path,'complete');first.emit('done',{},'completed');assert.equal(opened.length,1);
 manager.start(contents,url);assert.equal(events.at(-1).state,'completed');
 account='two';assert.throws(()=>manager.action(contents,events.at(-1).id,'open'));manager.start(contents,url,true);const second=item();session.emit('will-download',{},second,contents);assert.notEqual(second.path,first.path);
 account='three';fs.writeFileSync(second.path,'complete');second.emit('done',{},'completed');assert.equal(opened.length,1,'no delayed open under another account');
 const third=item();session.emit('will-download',{},third,{...contents,getURL:()=> 'https://foreign.test/'});assert.equal(third.cancelled,true);
 assert.throws(()=>manager.start(contents,'https://foreign.test/file'));manager.close();
});
