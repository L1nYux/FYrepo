const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {Connection,DEFAULT_SERVER_URL,confirmConnection}=require('../connection.cjs');
function fixture(t,saved){
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'workbench-connection-'));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  if(saved)fs.writeFileSync(path.join(directory,'server-connection.json'),JSON.stringify({mode:'remote',url:saved}));
  return new Connection(directory);
}
test('fresh client defaults to HTTPS',t=>{
  const connection=fixture(t);assert.equal(new URL(DEFAULT_SERVER_URL).protocol,'https:');
  assert.equal(connection.snapshot().url,DEFAULT_SERVER_URL);
});
test('saved HTTP requires confirmation before the first connection, even at the same address',async t=>{
  const connection=fixture(t,'http://team.example.com');let prompts=0,requests=0;
  if(await confirmConnection(connection,connection.value.url,async()=>{prompts++;return false;}))requests++;
  assert.equal(prompts,1);assert.equal(requests,0);
  assert.equal(connection.needsHttpConfirmation(),true);
});
test('temporary HTTP permission is never persisted and restart requires confirmation',async t=>{
  const connection=fixture(t,'http://team.example.com');let prompts=0;
  const allow=async()=>{prompts++;return true;};
  assert.equal(await confirmConnection(connection,connection.value.url,allow),true);
  connection.save(connection.snapshot());
  assert.equal(await confirmConnection(connection,connection.value.url,allow),true);
  assert.equal(prompts,1);
  assert.equal(new Connection(path.dirname(connection.file)).needsHttpConfirmation(),true);
  assert.deepEqual(JSON.parse(fs.readFileSync(connection.file)),connection.snapshot());
});
test('cancelled HTTP change preserves HTTPS configuration',async t=>{
  const connection=fixture(t);const before=connection.snapshot();
  assert.equal(await confirmConnection(connection,'http://team.example.com',async()=>false),false);
  assert.throws(()=>connection.save({mode:'remote',url:'http://team.example.com'}),/明确确认/);
  assert.deepEqual(connection.snapshot(),before);
});
test('approval for one origin does not authorize another origin or port',async t=>{
  const connection=fixture(t);await confirmConnection(connection,'http://team.example.com',async()=>true);
  assert.equal(connection.needsHttpConfirmation('http://other.example.com'),true);
  assert.equal(connection.needsHttpConfirmation('http://team.example.com:8080'),true);
});
test('HTTPS and exact loopback addresses do not require HTTP confirmation',async t=>{
  const connection=fixture(t);const fail=()=>{throw Error('unexpected prompt');};
  for(const url of ['https://team.example.com','http://localhost:8000','http://127.0.0.1:8000','http://[::1]:8000'])
    assert.equal(await confirmConnection(connection,url,fail),true);
  assert.equal(connection.needsHttpConfirmation('http://localhost.example.com'),true);
  assert.equal(connection.needsHttpConfirmation('http://127.example.com'),true);
});
