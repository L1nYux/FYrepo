const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto'),yaml=require('js-yaml');
const {verifyReleaseAssets}=require('../verify-release-assets.cjs');
function fixture(t){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'release-assets-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const version='0.4.4',bytes=Buffer.alloc(2048,3),files={};
 function asset(name){fs.writeFileSync(path.join(dir,name),bytes);fs.writeFileSync(path.join(dir,name+'.blockmap'),bytes);return {url:name,size:bytes.length,sha512:crypto.createHash('sha512').update(bytes).digest('base64')};}
 function manifest(name,rows){fs.writeFileSync(path.join(dir,name),yaml.dump({version,files:rows,path:rows[0].url,sha512:rows[0].sha512}));}
 manifest('latest.yml',[asset(`ResearchWorkbench-${version}-win-x64.exe`)]);
 const zips=[];for(const arch of ['arm64','x64']){zips.push(asset(`ResearchWorkbench-${version}-mac-${arch}.zip`));const row=asset(`ResearchWorkbench-${version}-mac-${arch}.dmg`);files[arch]={name:row.url,size:row.size,sha512:row.sha512};}
 manifest('latest-mac.yml',zips);
 const release={version,features:[],fixes:[]};fs.writeFileSync(path.join(dir,'release-info.json'),JSON.stringify(release));fs.writeFileSync(path.join(dir,'free-mac-update.json'),JSON.stringify({version,files,release}));
 return {dir,version};
}
test('both Windows and Mac architectures require all update assets',t=>{const {dir,version}=fixture(t);assert.equal(verifyReleaseAssets(dir,version).length,14);fs.rmSync(path.join(dir,`ResearchWorkbench-${version}-mac-x64.zip`));assert.throws(()=>verifyReleaseAssets(dir,version));});
test('a wrong version or changed installer blocks preparation',t=>{const {dir,version}=fixture(t);assert.throws(()=>verifyReleaseAssets(dir,'0.4.3'));fs.writeFileSync(path.join(dir,`ResearchWorkbench-${version}-win-x64.exe`),Buffer.alloc(2048,4));assert.throws(()=>verifyReleaseAssets(dir,version),/Checksum mismatch/);});
test('an incomplete Mac manifest cannot pass using only Windows assets',t=>{const {dir,version}=fixture(t);const file=path.join(dir,'latest-mac.yml'),data=yaml.load(fs.readFileSync(file,'utf8'));data.files=data.files.slice(0,1);fs.writeFileSync(file,yaml.dump(data));assert.throws(()=>verifyReleaseAssets(dir,version),/Missing manifest asset/);});
