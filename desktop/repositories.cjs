const fs=require('node:fs'),path=require('node:path');
class Repositories {
  constructor(file){this.file=file;this.items=[];this.selected=null;try{const value=JSON.parse(fs.readFileSync(file,'utf8'));const rows=value.items|| (value.path?[{path:value.path}]:[]);for(const row of rows){if(typeof row.path==='string'&&fs.existsSync(row.path))this.add(row.path,Boolean(row.plain),false);}this.selected=this.items.find(row=>row.path===(value.selected||value.path))?.path||this.items[0]?.path||null;}catch(_) {}}
  save(){fs.mkdirSync(path.dirname(this.file),{recursive:true});const temporary=this.file+'.tmp';fs.writeFileSync(temporary,JSON.stringify({items:this.items,selected:this.selected},null,2));fs.renameSync(temporary,this.file);}
  add(directory,plain=false,persist=true){const real=fs.realpathSync(directory);if(!fs.statSync(real).isDirectory())throw Error('请选择文件夹。');let row=this.items.find(item=>process.platform==='win32'?item.path.toLowerCase()===real.toLowerCase():item.path===real);if(!row){row={path:real,plain};this.items.push(row);}else row.plain=plain;this.selected=row.path;if(persist)this.save();return row;}
  select(directory){const row=this.items.find(item=>item.path===directory);if(!row)throw Error('仓库未打开。');if(!fs.existsSync(row.path))throw Error('目录已移动或删除，请重新打开。');this.selected=row.path;this.save();return row;}
  remove(directory){if(!this.items.some(item=>item.path===directory))throw Error('仓库未打开。');this.items=this.items.filter(item=>item.path!==directory);if(this.selected===directory)this.selected=this.items[0]?.path||null;this.save();}
  current(){return this.items.find(item=>item.path===this.selected)||null;}
  list(){return {items:this.items.map(row=>({...row,name:path.basename(row.path)})),selected:this.selected};}
}
function deletionTarget(directory,protectedPaths){const target=fs.realpathSync(directory);if(path.dirname(target)===target)throw Error('不能删除磁盘根目录。');for(const protectedPath of protectedPaths){const value=path.resolve(protectedPath),relative=path.relative(target,value);if(!relative||relative==='.'||(!relative.startsWith('..'+path.sep)&&relative!=='..'&&!path.isAbsolute(relative)))throw Error('不能删除应用、个人主目录或配置所在目录。');}return target;}
module.exports={Repositories,deletionTarget};
