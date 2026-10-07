import {build} from 'esbuild';
import {mkdir,copyFile,cp,readdir,readFile,writeFile} from 'node:fs/promises';
const root=new URL('../static/vendor/documents/',import.meta.url);
await mkdir(root,{recursive:true});
await build({entryPoints:['editor.js'],bundle:true,format:'esm',minify:true,sourcemap:false,outfile:new URL('editor.js',root).pathname.replace(/^\/([A-Za-z]:)/,'$1'),legalComments:'linked'});
await copyFile('node_modules/pdfjs-dist/build/pdf.worker.min.mjs',new URL('pdf.worker.mjs',root));
await cp('node_modules/pdfjs-dist/cmaps',new URL('cmaps',root),{recursive:true});
await cp('node_modules/pdfjs-dist/standard_fonts',new URL('standard_fonts',root),{recursive:true});
await cp('node_modules/pdfjs-dist/wasm',new URL('wasm',root),{recursive:true});
// Preserve third party attribution alongside the distributed browser bundle.
const packages=[];
for(const entry of await readdir('node_modules',{withFileTypes:true})){
 if(!entry.isDirectory()||entry.name.startsWith('.'))continue;
 if(entry.name.startsWith('@')){
  for(const child of await readdir('node_modules/'+entry.name,{withFileTypes:true}))if(child.isDirectory())packages.push('node_modules/'+entry.name+'/'+child.name);
 }else packages.push('node_modules/'+entry.name);
}
let notices='知域文档浏览器组件：第三方许可证\n\n';
for(const directory of packages.sort()){
 let metadata;try{metadata=JSON.parse(await readFile(directory+'/package.json','utf8'));}catch{continue;}
 notices+=`${metadata.name} ${metadata.version}\nLicense: ${typeof metadata.license==='string'?metadata.license:JSON.stringify(metadata.license||'See package license')}\n`;
 for(const name of await readdir(directory))if(/^(?:licen[sc]e|copying|notice)(?:\..*)?$/i.test(name)){
  try{notices+=await readFile(directory+'/'+name,'utf8')+'\n';}catch{}
 }
 notices+='\n------------------------------\n\n';
}
await writeFile(new URL('THIRD_PARTY_NOTICES.txt',root),notices);
