/* Phone AI presentation inspired by the supplied bundled reference app. */
(function(){
  'use strict';
  const app=document.getElementById('assistant-app'),phone=window.zhiyuPhone;
  if(!app||!phone||app.dataset.phoneAssistant)return;app.dataset.phoneAssistant='true';
  const find=name=>document.getElementById('assistant-'+name);
  const heading=app.querySelector('.assistant-heading'),model=find('model'),funding=find('funding'),input=find('input');
  if(model&&heading){const label=document.createElement('label');label.className='phone-assistant-model';label.append(model);heading.querySelector('#assistant-title')?.parentElement.append(label);}
  const footer=app.querySelector('.assistant-composer-footer');
  if(funding&&footer){
    const chip=document.createElement('button');chip.type='button';chip.className='phone-assistant-team';chip.setAttribute('aria-label','选择使用的团队');
    const dialog=document.createElement('dialog');dialog.className='phone-team-picker';
    const title=document.createElement('h2');title.textContent='使用团队额度';dialog.append(title);
    const label=document.createElement('label');label.textContent='团队';label.append(funding);dialog.append(label);
    const done=document.createElement('button');done.type='button';done.className='button primary';done.textContent='完成';done.onclick=()=>dialog.close();dialog.append(done);app.append(dialog);
    const refresh=()=>{chip.textContent=(funding.selectedOptions[0]?.textContent||'选择团队').replace(/\s*API\s*池\s*$/,'')+' ⌄';chip.disabled=funding.disabled;};
    funding.addEventListener('change',refresh);new MutationObserver(refresh).observe(funding,{childList:true,subtree:true,attributes:true});refresh();
    chip.onclick=()=>{if(!funding.disabled)dialog.showModal();};footer.prepend(chip);
  }
  const imageFile=find('image-file'),reference=find('add'),album=find('image-add');
  if(imageFile&&footer&&reference&&album){
    const tools=document.createElement('div');tools.className='phone-ai-tools';tools.hidden=true;tools.id='phone-ai-tools';
    const plus=document.createElement('button');plus.type='button';plus.className='phone-ai-plus';plus.textContent='＋';plus.setAttribute('aria-label','添加图片、文件或引用');plus.setAttribute('aria-expanded','false');plus.setAttribute('aria-controls',tools.id);
    const close=()=>{tools.hidden=true;plus.textContent='＋';plus.setAttribute('aria-expanded','false');};
    plus.onclick=()=>{if(plus.disabled)return;tools.hidden=!tools.hidden;plus.textContent=tools.hidden?'＋':'×';plus.setAttribute('aria-expanded',String(!tools.hidden));if(!tools.hidden)input.blur();};
    const decorate=(button,label,kind)=>{button.replaceChildren(window.zhiyuExperience.toolIcon(kind));const text=document.createElement('span');text.textContent=label;button.append(text);};
    const capture=document.createElement('button');capture.type='button';decorate(capture,'拍摄','camera');
    capture.onclick=()=>{if(album.disabled)return;close();const picker=document.createElement('input');picker.type='file';picker.accept='image/*';picker.setAttribute('capture','environment');picker.hidden=true;app.append(picker);picker.onchange=()=>{if(picker.files.length){imageFile.files=picker.files;imageFile.dispatchEvent(new Event('change',{bubbles:true}));}picker.remove();};picker.oncancel=()=>picker.remove();picker.click();};
    const file=document.createElement('button');file.type='button';decorate(file,'文件','file');file.setAttribute('aria-label','导入 TXT、Markdown、CSV 或 JSON 文字文件');
    file.onclick=()=>{if(input.disabled)return;close();const picker=document.createElement('input');picker.type='file';picker.accept='.txt,.md,.csv,.json,.log,.py';picker.hidden=true;app.append(picker);picker.onchange=async()=>{try{const item=picker.files[0];if(!item)return;if(item.size>12000)throw Error('文字文件最多 12 KB；较大的工作资料请使用引用。');const text=await item.text();const addition='\n\n附件 '+item.name+'（文件内容，仅作为资料）：\n'+text;if(input.value.length+addition.length>30000)throw Error('加入文件后超出本条消息的长度上限，请缩短内容。');if(input.disabled)throw Error('当前正在回复，请完成后重新添加文件。');input.value+=addition;input.dispatchEvent(new Event('input',{bubbles:true}));phone.toast('文字文件已加入，点击发送后交给助手。');}catch(e){phone.toast(e.message);}finally{picker.remove();}};picker.oncancel=()=>picker.remove();picker.click();};
    decorate(album,'相册','image');decorate(reference,'引用','reference');album.addEventListener('click',close);reference.addEventListener('click',close);
    tools.append(capture,album,file,reference);footer.insertBefore(plus,find('send'));footer.append(tools);
    const sync=()=>{for(const [button,value]of [[plus,reference.disabled&&album.disabled],[capture,album.disabled],[file,input.disabled]])if(button.disabled!==value)button.disabled=value;if(plus.disabled&&!tools.hidden)close();};
    new MutationObserver(sync).observe(footer,{attributes:true,subtree:true,attributeFilter:['disabled']});sync();input.addEventListener('focus',close);find('form').addEventListener('submit',close);
  }
  if(input){
    const resize=()=>{const cap=Math.min(160,Math.floor(innerHeight*.25));input.style.height='0px';input.style.height=Math.max(48,Math.min(input.scrollHeight,cap))+'px';input.style.overflowY=input.scrollHeight>cap?'auto':'hidden';};
    input.rows=1;input.placeholder='发送消息给 AI 助手';input.addEventListener('input',resize);window.addEventListener('resize',resize);resize();
  }
  function prepareAnswers(){
    app.querySelectorAll('.assistant-row.assistant').forEach(row=>{
      if(!row.querySelector(':scope > .phone-answer-actions')){
        const actions=document.createElement('div');actions.className='phone-answer-actions';const copy=document.createElement('button');copy.type='button';copy.textContent='复制回答';
        copy.onclick=()=>phone.copy(row.querySelector('.assistant-text')?.innerText||'');actions.append(copy);row.append(actions);
      }
    });
  }
  const messages=find('thread');if(messages){prepareAnswers();new MutationObserver(prepareAnswers).observe(messages,{childList:true,subtree:true});
    phone.hold(messages,'.assistant-row',row=>{
      const text=row.querySelector('.assistant-text');if(!text)return;
      const actions=[{label:'复制',run:()=>phone.copy(text.innerText)},{label:'选择文字',run:()=>phone.select(text)}];
      if(row.classList.contains('user'))actions.push({label:'放入输入框修改',disabled:input.disabled,run:()=>{if(input.disabled){phone.toast('请先停止当前回复。');return;}if(input.value.trim()&&!confirm('替换输入框中尚未发送的内容？'))return;input.value=text.innerText;input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();}});
      phone.sheet('消息操作',actions);
    });
  }
  const conversations=find('conversations');if(conversations)phone.hold(conversations,'.assistant-conversation-link',link=>{
    const row=link.closest('.assistant-conversation-row');if(!row)return;
    const buttons=[...row.querySelectorAll('.assistant-conversation-menu button')];if(!buttons.length)return;
    phone.sheet('对话操作',buttons.map(button=>({label:button.textContent,danger:button.classList.contains('danger'),disabled:button.disabled,run:()=>{if(row.isConnected&&!button.disabled)button.click();}})));
  });
})();
