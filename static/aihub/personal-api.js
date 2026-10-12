(() => {
  const panel=document.getElementById('my-api-key');if(!panel)return;
  const model=document.getElementById('personal-api-model'),url=document.getElementById('personal-api-url');
  const example=document.getElementById('personal-api-example'),hint=document.getElementById('personal-api-example-hint');
  const experiment=document.getElementById('personal-api-experiment');
  const project=document.getElementById('personal-api-project');
  const streaming=document.getElementById('personal-api-stream');
  const status=panel.querySelector('[data-api-copy-status]');let language='sdk';
  const shellQuote=value=>"'"+value.replace(/'/g,"'\"'\"'")+"'";
  function render(){
    const available=Boolean(model.value);
    if(!model.options.length){const empty=document.createElement('option');empty.value='';empty.textContent='暂无可用模型';model.append(empty);}
    const associated=Boolean(experiment.value);
    panel.querySelector('.personal-api-example').hidden=!available;
    panel.querySelector('[data-api-copy="personal-api-model"]').disabled=!available;
    model.disabled=!available;
    panel.querySelector('[data-api-copy="personal-api-experiment"]').disabled=!associated;
    document.getElementById('personal-api-experiment-id').textContent=associated?'experiment_id: '+experiment.value:
      '可不关联实验，调用归属当前团队。';
    document.getElementById('personal-api-model-id').textContent=available?model.value:'暂无可用模型，请联系管理员启用模型并配置价格。';
    if(!available){example.textContent='';return;}
    const body={model:model.value,messages:[{role:'user',content:'请用一句话介绍你自己。'}],max_tokens:Math.min(1024,Number(model.selectedOptions[0]?.dataset.limit)||1024),stream:streaming.checked};
    if(body.stream)body.stream_options={include_usage:true};
    if(associated)body.experiment_id=Number(experiment.value);
    if(project.value)body.project_id=Number(project.value);
    if(language==='sdk'){
      hint.textContent='先安装：pip install openai。示例不自动重试；中断后先查询调用账单。';
      const args=Object.entries(body).filter(([key])=>!['project_id','experiment_id'].includes(key));
      const extra=Object.fromEntries(Object.entries(body).filter(([key])=>['project_id','experiment_id'].includes(key)));
      example.textContent=['import getpass','import json','from openai import OpenAI','',
        'client = OpenAI(base_url='+JSON.stringify(url.value)+',',
        '                api_key=getpass.getpass("我的 API Key: "), max_retries=0, timeout=1800)',
        'payload = json.loads('+JSON.stringify(JSON.stringify(Object.fromEntries(args)))+')',
        ...(Object.keys(extra).length?['payload["extra_body"] = json.loads('+JSON.stringify(JSON.stringify(extra))+')']:[]),
        'response = client.chat.completions.create(**payload)',
        ...(body.stream?['for chunk in response:','    if chunk.choices:','        print(chunk.choices[0].delta.content or "", end="", flush=True)','print()']:['print(response.choices[0].message.content)'])].join('\n');
    }else if(language==='python'){
      hint.textContent='Python 示例不需要安装额外依赖，运行后输入你保存的 API Key。';
      example.textContent=[
        'import getpass','import json','import urllib.request','',
        'api_key = getpass.getpass("我的 API Key: ")',
        'payload = json.loads('+JSON.stringify(JSON.stringify(body))+')',
        'request = urllib.request.Request(',
        '    '+JSON.stringify(url.value+'/chat/completions')+',',
        '    data=json.dumps(payload).encode("utf-8"),',
        '    headers={"Authorization": "Bearer " + api_key,',
        '             "Content-Type": "application/json"},',
        '    method="POST",',')',
        'with urllib.request.urlopen(request, timeout=1800) as response:',
        ...(body.stream?['    for line in response:','        text = line.decode("utf-8").strip()','        if not text.startswith("data: "): continue','        if text[6:] == "[DONE]": break','        chunk = json.loads(text[6:])','        if "error" in chunk: raise RuntimeError(chunk["error"])','        if chunk.get("choices"):','            print(chunk["choices"][0]["delta"].get("content", ""), end="", flush=True)','print()']:['    result = json.load(response)','print(result["choices"][0]["message"]["content"])']),
      ].join('\n');
    }else{
      hint.textContent='适用于 bash / zsh。将 YOUR_API_KEY 替换为你保存的 Key；不要把含 Key 的命令分享给他人。';
      example.textContent=['curl '+(body.stream?'-N ':'')+shellQuote(url.value+'/chat/completions')+' \\',
        '  -H "Authorization: Bearer YOUR_API_KEY" \\',
        '  -H "Content-Type: application/json" \\',
        '  --data-raw '+shellQuote(JSON.stringify(body))].join('\n');
    }
  }
  model.addEventListener('change',render);
  streaming.addEventListener('change',render);
  function filterExperiments(){
    for(const option of experiment.options)option.hidden=Boolean(option.value&&project.value&&option.dataset.project!==project.value);
    if(experiment.selectedOptions[0]?.hidden)experiment.value='';
    render();
  }
  project.addEventListener('change',filterExperiments);
  experiment.addEventListener('change',()=>{
    const id=experiment.selectedOptions[0]?.dataset.project;
    if(id&&[...project.options].some(option=>option.value===id))project.value=id;
    filterExperiments();
  });
  panel.querySelectorAll('[data-api-language]').forEach(button=>button.addEventListener('click',()=>{
    language=button.dataset.apiLanguage;
    panel.querySelectorAll('[data-api-language]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
    render();
  }));
  function selectForCopy(target,value){
    const previous=document.activeElement,selection=window.getSelection();
    const ranges=selection?[...Array(selection.rangeCount)].map((_,i)=>selection.getRangeAt(i).cloneRange()):[];
    const temporary=document.createElement('textarea');temporary.value=value;
    temporary.setAttribute('readonly','');temporary.style.cssText='position:fixed;top:0;left:0;opacity:0;pointer-events:none';
    panel.append(temporary);temporary.focus({preventScroll:true});temporary.select();
    let copied=false;try{copied=document.execCommand('copy');}catch(_){}finally{temporary.remove();previous?.focus({preventScroll:true});}
    if(selection){selection.removeAllRanges();for(const range of ranges)selection.addRange(range);}
    if(!copied){
      target.focus({preventScroll:true});
      if(typeof target.select==='function')target.select();
      else if(selection){const range=document.createRange();range.selectNodeContents(target);selection.removeAllRanges();selection.addRange(range);}
    }
    return copied;
  }
  panel.querySelectorAll('[data-api-copy]').forEach(button=>button.addEventListener('click',async()=>{
    if(button.disabled)return;
    const target=document.getElementById(button.dataset.apiCopy),value=target.value??target.textContent;
    if(!value)return;
    button.disabled=true;let copied=false;
    try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(value);copied=true;}}catch(_){}
    if(!copied)copied=selectForCopy(target,value);
    status.textContent=copied?button.textContent.replace(/^复制/,'已复制')+'。':'自动复制未成功，请长按或选中内容手动复制。';
    button.disabled=false;
  }));
  document.querySelector('[data-open-api-key]')?.addEventListener('click',()=>{panel.open=true;});
  panel.querySelector('.personal-api-create').addEventListener('submit',event=>{
    const button=document.getElementById('personal-api-generate');if(button.disabled){event.preventDefault();return;}button.disabled=true;button.textContent='正在生成…';
  });
  filterExperiments();
})();
