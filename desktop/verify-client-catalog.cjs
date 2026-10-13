const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(process.argv[2]||'dist'),resources=[];
function walk(directory){
 for(const entry of fs.readdirSync(directory,{withFileTypes:true})){
  if(entry.isDirectory()&&!entry.isSymbolicLink())walk(path.join(directory,entry.name));
  else if(entry.isFile()&&entry.name==='app.asar')resources.push(directory);
 }
}
walk(root);assert.equal(resources.length,1,'Exactly one packaged desktop application is required');
const source=fs.readFileSync(path.join(__dirname,'../static/core/client-plugins.json'));
assert.ok(fs.readFileSync(path.join(resources[0],'client-plugins.json')).equals(source),'Packaged plugin catalog must match its source');
assert.equal(JSON.parse(source).length,3);
console.log('Verified all three built-in client plugins in the packaged resources.');
