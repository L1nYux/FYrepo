const fs = require('node:fs');
const path = require('node:path');
const { nativeImage } = require('electron');

class Appearance {
  constructor(root) { this.root=root; this.file=path.join(root,'appearance.json'); this.image=path.join(root,'wallpaper-image'); this.wallpaper=''; }
  options() {
    let saved={};try{saved=JSON.parse(fs.readFileSync(this.file,'utf8'));}catch(_){}
    const number=(value,fallback,max)=>Number.isFinite(Number(value))?Math.max(0,Math.min(max,Number(value))):fallback;
    return {mode:['dark','light','system'].includes(saved.mode)?saved.mode:'dark',opacity:number(saved.opacity,18,60),blur:number(saved.blur,4,24)};
  }
  save(value) {
    if(!value||!['dark','light','system'].includes(value.mode))throw Error('请选择有效主题。');
    if(!Number.isFinite(Number(value.opacity))||!Number.isFinite(Number(value.blur)))throw Error('壁纸参数无效。');
    fs.writeFileSync(this.file,JSON.stringify({mode:value.mode,opacity:Math.max(0,Math.min(60,Number(value.opacity))),blur:Math.max(0,Math.min(24,Number(value.blur)))},null,2));
  }
  mime(bytes) {
    if(bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))return 'image/png';
    if(bytes[0]===255&&bytes[1]===216&&bytes[2]===255)return 'image/jpeg';
    if(bytes.toString('ascii',0,4)==='RIFF'&&bytes.toString('ascii',8,12)==='WEBP')return 'image/webp';
    throw Error('请选择 PNG、JPG 或 WebP 图片。');
  }
  upload(file) {
    const stat=fs.statSync(file);if(!stat.isFile()||stat.size>10*1024*1024)throw Error('壁纸需要小于 10 MB。');
    const bytes=fs.readFileSync(file),mime=this.mime(bytes),image=nativeImage.createFromBuffer(bytes);
    const size=image.getSize();if(image.isEmpty()||size.width*size.height>40000000)throw Error('图片无法读取或尺寸过大。');
    fs.writeFileSync(this.image,bytes);this.wallpaper='data:'+mime+';base64,'+bytes.toString('base64');
  }
  clear() { if(fs.existsSync(this.image))fs.unlinkSync(this.image);this.wallpaper=''; }
  snapshot(systemDark) {
    const options=this.options();
    if(!this.wallpaper&&fs.existsSync(this.image)){
      try{if(fs.statSync(this.image).size<=10*1024*1024){const bytes=fs.readFileSync(this.image);this.wallpaper='data:'+this.mime(bytes)+';base64,'+bytes.toString('base64');}}catch(_){}
    }
    return {...options,theme:options.mode==='system'?(systemDark?'dark':'light'):options.mode,wallpaper:this.wallpaper,hasWallpaper:Boolean(this.wallpaper)};
  }
}
module.exports={Appearance};
