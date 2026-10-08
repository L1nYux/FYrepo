const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const yaml=require('js-yaml');
const {validateManifest}=require('./free-mac-update.cjs');
const {validateInfo}=require('./release-details.cjs');
function verifyReleaseAssets(directory,version,platform='all'){
  if(!['windows','macos','all'].includes(platform))throw Error('Invalid platform');
  const checked=new Set();
  function file(name,expected){
    if(typeof name!=='string'||path.basename(name)!==name)throw Error('Invalid asset name');
    const bytes=fs.readFileSync(path.join(directory,name));
    if(bytes.length<1024)throw Error('Empty installer: '+name);
    if(expected&&(expected.size!==bytes.length||expected.sha512!==crypto.createHash('sha512').update(bytes).digest('base64')))throw Error('Checksum mismatch: '+name);
    checked.add(name);return bytes;
  }
  function manifest(name,required){
    const data=yaml.load(fs.readFileSync(path.join(directory,name),'utf8'));
    if(data?.version!==version||!Array.isArray(data.files))throw Error('Invalid update manifest: '+name);
    for(const name of required){const row=data.files.find(row=>row.url===name);if(!row)throw Error('Missing manifest asset: '+name);file(name,row);}
    // Check every referenced file, including the top-level legacy updater path.
    for(const row of data.files)file(row.url,row);
    if(!data.files.some(row=>row.url===data.path&&row.sha512===data.sha512))throw Error('Invalid legacy updater path');
    checked.add(name);
  }
  if(platform!=='macos'){
    const name=`ResearchWorkbench-${version}-win-x64.exe`;
    manifest('latest.yml',[name]);file(name+'.blockmap');
  }
  if(platform!=='windows'){
    const zips=['arm64','x64'].map(arch=>`ResearchWorkbench-${version}-mac-${arch}.zip`);
    manifest('latest-mac.yml',zips);
    const data=JSON.parse(fs.readFileSync(path.join(directory,'free-mac-update.json'),'utf8'));
    validateInfo(data.release,version);
    for(const arch of ['arm64','x64']){
      const row=validateManifest(data,version,arch);file(row.name,row);file(row.name+'.blockmap');
      file(`ResearchWorkbench-${version}-mac-${arch}.zip.blockmap`);
    }
    checked.add('free-mac-update.json');
  }
  if(platform==='all'){
    const info=validateInfo(JSON.parse(fs.readFileSync(path.join(directory,'release-info.json'),'utf8')),version);
    if(!info)throw Error('Missing release details');checked.add('release-info.json');
  }
  return [...checked];
}
if(require.main===module){const [directory,version,platform]=process.argv.slice(2);console.log('Verified release assets:',verifyReleaseAssets(directory,version,platform).join(', '));}
module.exports={verifyReleaseAssets};
