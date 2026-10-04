// Reveal a prepared interface; document load events alone are not readiness.
class PresentationGate {
  constructor(changed, reveal, {slowAfter=3000, timeout=30000}={}) {
    this.changed=changed;this.reveal=reveal;this.slowAfter=slowAfter;this.timeout=timeout;
    this.generation=0;this.phase='idle';this.full=true;this.message='';
    this.readySurfaces=new Set();this.required=null;
  }
  snapshot(){return {generation:this.generation,phase:this.phase,full:this.full,message:this.message};}
  get pending(){return this.phase==='loading';}
  clear(){clearTimeout(this.slowTimer);clearTimeout(this.timeoutTimer);}
  begin(full, message='正在准备工作台…') {
    this.clear();this.generation++;this.phase='loading';this.full=full;this.message=message;
    this.readySurfaces.clear();this.required=null;this.changed();
    const generation=this.generation;
    this.slowTimer=setTimeout(()=>{if(this.pending&&generation===this.generation){this.message=this.full?'正在连接团队服务器…':'页面加载较慢，正在等待服务器…';this.changed();}},this.slowAfter);
    this.timeoutTimer=setTimeout(()=>{if(generation===this.generation)this.fail('加载超时，请检查网络后重试。');},this.timeout);
    return this.generation;
  }
  expect(surfaces){this.required=new Set(surfaces);this.check();}
  ready(surface,generation) {
    if(generation!==this.generation||!this.pending&&!(this.phase==='error'&&['chrome','account'].includes(surface)))return false;
    this.readySurfaces.add(surface);this.check();return true;
  }
  check(){
    if(!this.pending||!this.required||[...this.required].some(name=>!this.readySurfaces.has(name)))return;
    this.clear();this.phase='idle';this.message='';this.changed();this.reveal();
  }
  fail(message){this.clear();this.phase='error';this.message=message;this.changed();}
  dismiss(){this.clear();this.generation++;this.phase='idle';this.message='';this.changed();}
}
module.exports={PresentationGate};
