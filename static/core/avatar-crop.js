(() => {
  document.querySelectorAll('[data-avatar-editor]').forEach(editor => {
    const input=editor.querySelector('[data-avatar-file]'), preview=editor.querySelector('[data-avatar-preview]'), hint=editor.querySelector('[data-avatar-hint]');
    const form=input.form, submit=form.querySelector('button[type=submit]');
    const dialog=document.createElement('dialog');dialog.className='avatar-crop-dialog';
    dialog.innerHTML='<h2>调整头像</h2><p>拖动图片选择位置，滚动或双指缩放。</p><div class="avatar-crop-surface"><canvas width="512" height="512" aria-label="拖动调整头像"></canvas><div class="avatar-crop-mask"></div></div><label>缩放<input type="range" min="1" max="4" step="0.01" value="1"></label><div class="btn-row"><button type="button" data-rotate>旋转 90°</button><button type="button" data-cancel>取消</button><button type="button" data-apply class="button primary">使用头像</button></div><p role="status" data-error></p>';
    editor.append(dialog);
    const canvas=dialog.querySelector('canvas'), ctx=canvas.getContext('2d'), zoom=dialog.querySelector('input'), apply=dialog.querySelector('[data-apply]');
    const error=dialog.querySelector('[data-error]'), points=new Map();
    let image, source, angle=0, offsetX=0, offsetY=0, saved, accepting=false, sequence=0;
    const dimensions=()=>angle%180?{w:image.height,h:image.width}:{w:image.width,h:image.height};
    function draw(){if(!image)return;const d=dimensions(),s=Math.max(512/d.w,512/d.h)*Number(zoom.value);offsetX=Math.max(-(d.w*s-512)/2,Math.min((d.w*s-512)/2,offsetX));offsetY=Math.max(-(d.h*s-512)/2,Math.min((d.h*s-512)/2,offsetY));ctx.clearRect(0,0,512,512);ctx.save();ctx.translate(256+offsetX,256+offsetY);ctx.rotate(angle*Math.PI/180);ctx.scale(s,s);ctx.drawImage(image,-image.width/2,-image.height/2);ctx.restore();}
    function setFiles(file){const transfer=new DataTransfer();if(file)transfer.items.add(file);input.files=transfer.files;}
    function release(){if(source){URL.revokeObjectURL(source);source=null;}points.clear();}
    input.addEventListener('change',()=>{const file=input.files[0];if(!file)return;release();sequence++;accepting=false;submit.disabled=true;error.textContent='';
      if(file.size>5*1024*1024||!['image/png','image/jpeg','image/webp'].includes(file.type)){hint.textContent='请选择不超过 5 MB 的 PNG、JPG 或 WebP 图片。';setFiles(saved);submit.disabled=!saved;return;}
      const version=sequence;source=URL.createObjectURL(file);image=new Image();image.onload=()=>{if(version!==sequence)return;if(image.width*image.height>16000000){hint.textContent='图片尺寸过大。';release();setFiles(saved);submit.disabled=!saved;return;}angle=0;offsetX=offsetY=0;zoom.value='1';draw();dialog.showModal();};image.onerror=()=>{hint.textContent='无法读取图片。';release();setFiles(saved);submit.disabled=!saved;};image.src=source;
    });
    zoom.addEventListener('input',draw);dialog.querySelector('[data-rotate]').addEventListener('click',()=>{angle=(angle+90)%360;offsetX=offsetY=0;draw();});
    canvas.addEventListener('pointerdown',event=>{canvas.setPointerCapture(event.pointerId);points.set(event.pointerId,{x:event.clientX,y:event.clientY});});
    canvas.addEventListener('pointermove',event=>{if(!points.has(event.pointerId))return;const old=[...points.values()],before=points.get(event.pointerId),factor=512/canvas.getBoundingClientRect().width;points.set(event.pointerId,{x:event.clientX,y:event.clientY});const now=[...points.values()];if(old.length===2){const distance=p=>Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y);zoom.value=String(Math.max(1,Math.min(4,Number(zoom.value)*distance(now)/Math.max(1,distance(old)))));}offsetX+=(event.clientX-before.x)*factor/points.size;offsetY+=(event.clientY-before.y)*factor/points.size;draw();});
    ['pointerup','pointercancel','lostpointercapture'].forEach(type=>canvas.addEventListener(type,event=>points.delete(event.pointerId)));
    canvas.addEventListener('wheel',event=>{event.preventDefault();zoom.value=String(Math.max(1,Math.min(4,Number(zoom.value)*(event.deltaY>0?.93:1.07))));draw();},{passive:false});
    dialog.querySelector('[data-cancel]').addEventListener('click',()=>dialog.close());
    apply.addEventListener('click',()=>{const version=sequence;apply.disabled=true;canvas.toBlob(blob=>{apply.disabled=false;if(version!==sequence||!dialog.open)return;if(!blob){error.textContent='裁剪失败，请重试。';return;}saved=new File([blob],'avatar.webp',{type:'image/webp'});setFiles(saved);if(preview.src.startsWith('blob:'))URL.revokeObjectURL(preview.src);preview.src=URL.createObjectURL(saved);preview.hidden=false;hint.textContent='已完成裁剪，保存后更新头像。';accepting=true;dialog.close();},'image/webp',.9);});
    dialog.addEventListener('close',()=>{sequence++;release();if(!accepting)setFiles(saved);submit.disabled=!saved;});
    form.addEventListener('submit',event=>{if(dialog.open||!input.files.length){event.preventDefault();return;}submit.disabled=true;submit.textContent='上传中…';});
    window.addEventListener('pagehide',()=>{release();if(preview.src.startsWith('blob:'))URL.revokeObjectURL(preview.src);});
  });
})();
