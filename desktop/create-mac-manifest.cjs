const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {version}=require('./package.json');
const files={};
for(const arch of ['arm64','x64']){
  const name=`ResearchWorkbench-${version}-mac-${arch}.dmg`,file=path.join(__dirname,'dist',name);
  const bytes=fs.readFileSync(file);files[arch]={name,size:bytes.length,sha512:crypto.createHash('sha512').update(bytes).digest('base64')};
}
fs.writeFileSync(path.join(__dirname,'dist/free-mac-update.json'),JSON.stringify({version,files},null,2)+'\n');
