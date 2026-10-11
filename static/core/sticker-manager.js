(() => {
  'use strict';
  const root=document.querySelector('[data-sticker-manager]');if(!root)return;
  const grid=root.querySelector('[data-sticker-grid]'),input=root.querySelector('[data-sticker-upload]'),status=root.querySelector('[data-sticker-status]'),title=root.querySelector('[data-sticker-title]'),manage=root.querySelector('[data-sticker-manage]'),footer=root.querySelector('footer');
  let editing=new URLSearchParams(location.search).get('manage')==='1',values=[],selection=new Set(),busy=false;
  const request=body=>window.zhiyuExperience.json('/messages/stickers/',body);
  async function load(){values=(await request()).stickers;selection.clear();paint();}
  function paint(){
    const revision=JSON.stringify(values.map(s=>[s.id,s.url,s.name]));
    if(grid.dataset.revision!==revision){
      grid.replaceChildren();const plus=document.createElement('button');plus.type='button';plus.textContent='＋';plus.className='sticker-add';plus.setAttribute('aria-label','从相册添加表情');plus.onclick=()=>input.click();grid.append(plus);
      for(const sticker of values){
        const button=document.createElement('button'),image=document.createElement('img'),circle=document.createElement('span');button.type='button';button.dataset.stickerId=sticker.id;image.src=sticker.url;image.alt=sticker.name;image.loading='lazy';circle.className='sticker-check';button.append(image,circle);
        button.onclick=()=>{if(busy)return;if(editing){selection.has(sticker.id)?selection.delete(sticker.id):selection.add(sticker.id);paint();}else window.zhiyuChatUI.previewSticker(sticker);};
        grid.append(button);
      }
      grid.dataset.revision=revision;
    }
    grid.querySelector('.sticker-add').disabled=editing||busy;
    for(const button of grid.querySelectorAll('[data-sticker-id]')){
      const id=Number(button.dataset.stickerId),selected=selection.has(id),circle=button.querySelector('.sticker-check');
      button.disabled=busy;button.setAttribute('aria-pressed',String(selected));circle.hidden=!editing;circle.textContent=selected?[...selection].indexOf(id)+1:'';
    }
    title.textContent=editing?'已选择'+selection.size+'个表情':'添加的单个表情('+values.length+')';manage.textContent=editing?'取消':'整理';manage.disabled=busy;footer.hidden=!editing;
    footer.querySelector('[data-sticker-delete]').textContent='删除 ('+selection.size+')';footer.querySelectorAll('button').forEach(b=>b.disabled=!selection.size||busy);root.classList.toggle('editing',editing);
  }
  async function operate(action,ids){
    if(busy)return;busy=true;paint();status.textContent='';
    try{const body=new URLSearchParams({action});ids.forEach(id=>body.append('ids',id));await request(body);await load();status.textContent=action==='move'?'已移到前面':'已删除';}
    catch(error){status.textContent=error.message;}
    finally{busy=false;paint();}
  }
  manage.onclick=()=>{if(busy)return;editing=!editing;selection.clear();paint();};
  footer.querySelector('[data-sticker-move]').onclick=()=>operate('move',[...selection]);footer.querySelector('[data-sticker-delete]').onclick=()=>operate('bulk-remove',[...selection]);
  window.zhiyuExperience.hold(grid,'[data-sticker-id]',button=>{
    if(editing||busy)return;const sticker=values.find(item=>String(item.id)===button.dataset.stickerId);if(!sticker)return;
    window.zhiyuChatUI.stickerActions(button,sticker,[{label:'移到前面',run:()=>operate('move',[sticker.id])},{label:'删除',danger:true,run:()=>operate('bulk-remove',[sticker.id])}]);
  });
  input.onchange=async()=>{
    const files=[...input.files];input.value='';if(!files.length||busy)return;busy=true;paint();let count=0,result;
    try{for(const file of files){status.textContent='正在添加 '+(count+1)+'/'+files.length;if(file.size>5*1024*1024)throw Error('每张表情不能超过 5 MB');const body=new FormData();body.set('file',file);await request(body);count++;}result='已添加 '+count+' 个表情';}
    catch(error){result='已添加 '+count+' 个，'+error.message;}
    finally{try{await load();}catch(error){result+='；'+error.message;}busy=false;paint();status.textContent=result;}
  };
  status.textContent='正在读取…';load().then(()=>status.textContent='').catch(error=>{status.textContent=error.message;});
})();
