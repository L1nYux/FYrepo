(() => {
  const app=document.querySelector('#assistant-app'); if(!app)return;
  const $=id=>document.getElementById('assistant-'+id), csrf=app.querySelector('[name=csrfmiddlewaretoken]').value;
  let models=[],history=[],context=null,job=null,pollTimer=null,searchTimer=null,searchEpoch=0,starting=false;
  let conversation=null,conversations=[],opening=false,viewEpoch=0,listEpoch=0,renameId=null,listTimer=null;
  const drafts=new Map(),lastKey='workbench-agent-conversation:'+app.dataset.user;
  const jobKey='workbench-agent-job:'+app.dataset.user, modelKey='workbench-agent-model:'+app.dataset.user;
  async function request(url,body){
    const r=await fetch(url,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',
      headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRFToken':csrf},body:body===undefined?undefined:JSON.stringify(body)});
    if(r.redirected||!r.headers.get('content-type')?.includes('application/json')){const error=Error(r.status===404?'对话已不存在。':'登录已失效，请重新登录。');error.status=r.redirected?401:r.status;throw error;}
    const data=await r.json();if(!r.ok){const error=Error(data.error||'请求未完成。');error.status=r.status;throw error;}return data;
  }
  function status(text){$('status').textContent=text;}
  function busy(value){
    if(!value)$('stop').disabled=false;
    $('send').disabled=value||opening||!models.some(m=>m.configured);$('stop').hidden=!value;$('new').disabled=starting||opening;
    $('model').disabled=value||opening;$('input').disabled=value||opening;$('add').disabled=value||opening;
    if(app.dataset.conversations)renderConversations();
  }
  function rememberConversation(){try{localStorage.setItem(lastKey,conversation===null?'new':String(conversation));}catch(_){} }
  function renderConversations(){
    const list=$('conversations');list.replaceChildren();
    for(const item of conversations){
      const row=document.createElement('div');row.className='assistant-conversation-row'+(item.id===conversation?' selected':'');
      const link=document.createElement('button');link.type='button';link.className='assistant-conversation-link';link.textContent=(item.running?'● ':'')+item.title;link.title=item.title+(item.running?' · 正在回复':'');link.disabled=starting||opening;
      if(item.id===conversation)link.setAttribute('aria-current','page');
      link.addEventListener('click',()=>openConversation(item.id));
      const menu=document.createElement('details');menu.className='assistant-conversation-menu';
      const trigger=document.createElement('summary');trigger.textContent='⋯';trigger.setAttribute('aria-label',item.title+'的操作');
      const actions=document.createElement('div');
      for(const [action,label] of [['rename','重命名'],['delete','删除']]){
        const button=document.createElement('button');button.type='button';button.textContent=label;button.disabled=starting||opening;
        if(action==='delete')button.className='danger';
        button.addEventListener('click',()=>{menu.open=false;if(action==='rename'){renameId=item.id;$('rename-title').value=item.title;$('rename-error').textContent='';$('rename-dialog').showModal();$('rename-title').focus();}else deleteConversation(item);});
        actions.append(button);
      }
      menu.append(trigger,actions);row.append(link,menu);list.append(row);
    }
    if(!conversations.length){const empty=document.createElement('p');empty.className='muted';empty.textContent=$('conversation-search').value?'没有匹配的对话':'你的对话会保存在这里';list.append(empty);}
  }
  async function refreshConversations(){
    if(!app.dataset.conversations)return;
    const epoch=++listEpoch,data=await request(app.dataset.conversations+'?q='+encodeURIComponent($('conversation-search').value));
    if(epoch!==listEpoch)return;conversations=data.conversations;renderConversations();
  }
  function resetThread(){history=[];$('thread').querySelectorAll('.assistant-row').forEach(n=>n.remove());$('empty').hidden=false;showContext(null,'');}
  function newConversation(){
    if(starting||opening)return;
    drafts.set(conversation??'new',$('input').value);viewEpoch++;clearTimeout(pollTimer);job=null;conversation=null;
    sessionStorage.removeItem(jobKey);resetThread();$('input').value=drafts.get('new')||'';
    if(app.dataset.conversations){$('title').textContent='新对话';rememberConversation();}
    busy(false);status('调用计入你的团队 API 池用量');
  }
  async function openConversation(id){
    if(starting||opening||id===conversation)return;
    drafts.set(conversation??'new',$('input').value);const epoch=++viewEpoch;clearTimeout(pollTimer);job=null;opening=true;busy(false);
    try{
      const data=await request(app.dataset.conversationBase+id+'/');if(epoch!==viewEpoch)return;
      conversation=data.id;resetThread();$('title').textContent=data.title;$('input').value=drafts.get(conversation)||'';rememberConversation();
      for(const row of data.messages){message(row.role,row.text,row.result,false);history.push({role:row.role,content:row.text});}
      $('thread').scrollTop=$('thread').scrollHeight;job=data.active_job;status(job?'正在恢复当前对话…':'调用计入你的团队 API 池用量');
      if(job){sessionStorage.setItem(jobKey,job);poll();}else sessionStorage.removeItem(jobKey);
      if(window.matchMedia('(max-width:700px)').matches)setSidebar(false);
    }catch(error){status(error.message);}
    finally{if(epoch===viewEpoch){opening=false;busy(Boolean(job));}}
  }
  async function deleteConversation(item){
    if(!confirm('删除“'+item.title+'”？对话内容会被删除，已发生的用量记录保留。'))return;
    try{await request(app.dataset.conversationBase+item.id+'/',{action:'delete'});drafts.delete(item.id);if(conversation===item.id)newConversation();await refreshConversations();}
    catch(error){status(error.message);}
  }
  function setSidebar(open){app.classList.toggle('sidebar-collapsed',!open);$('sidebar-toggle').setAttribute('aria-expanded',String(open));}
  if(app.dataset.conversations){
    setSidebar(!window.matchMedia('(max-width:700px)').matches);
    $('sidebar-toggle').addEventListener('click',()=>setSidebar(app.classList.contains('sidebar-collapsed')));
    $('sidebar-close').addEventListener('click',()=>setSidebar(false));
    $('conversation-search').addEventListener('input',()=>{clearTimeout(listTimer);listTimer=setTimeout(()=>refreshConversations().catch(error=>status(error.message)),200);});
    $('rename-close').addEventListener('click',()=>$('rename-dialog').close());
    $('rename-form').addEventListener('submit',async event=>{
      event.preventDefault();const id=renameId,title=$('rename-title').value.trim();
      try{const data=await request(app.dataset.conversationBase+id+'/',{action:'rename',title});if(conversation===id)$('title').textContent=data.title;$('rename-dialog').close();await refreshConversations();}
      catch(error){$('rename-error').textContent=error.message;}
    });
  }
  async function load(preferred){
    const data=await request(app.dataset.catalog);models=data.models;
    let saved=preferred||data.budget.preferred_model;try{saved=saved||localStorage.getItem(modelKey);}catch(_){}
    const usable=models.filter(m=>m.configured),selected=usable.find(m=>String(m.id)===String(saved))||usable[0];
    $('model').replaceChildren();const groups=new Map();
    for(const model of usable){
      let group=groups.get(model.provider_id);if(!group){group=document.createElement('optgroup');group.label=model.provider;$('model').append(group);groups.set(model.provider_id,group);}
      const option=document.createElement('option');option.value=model.id;option.textContent=model.label+(model.supports_tools?'':' · 资料摘要模式');group.append(option);
    }
    if(selected)$('model').value=selected.id;
    else{const option=document.createElement('option');option.value='';option.textContent='暂无可用模型';$('model').append(option);status('API 池尚无可用模型，请管理员连接厂商并配置价格。');}
    $('model').title=data.budget.member.remaining===null?'本月未设上限 · 已用 ¥ '+data.budget.member.spent:'本月剩余额度 ¥ '+data.budget.member.remaining;
    busy(Boolean(job)||starting);
  }
  $('model').addEventListener('change',()=>{try{localStorage.setItem(modelKey,$('model').value);}catch(_){}
    request('/api-pool/preferences/',{model:Number($('model').value)}).catch(()=>status('模型已切换，暂未保存为下次默认。'));
  });
  function showContext(value,title){context=value;$('context').hidden=!value;$('context').querySelector('span').textContent=value?title:'';}
  if(app.dataset.contextKind&&/^\d+$/.test(app.dataset.contextId))showContext({kind:app.dataset.contextKind,id:Number(app.dataset.contextId)},'当前资料 · '+app.dataset.contextKind+' #'+app.dataset.contextId);
  $('clear-context').addEventListener('click',()=>showContext(null,''));
  function message(role,text,result,scroll=true){
    $('empty').hidden=true;const article=document.createElement('article');article.className='assistant-row '+role;
    const name=document.createElement('strong');name.textContent=role==='user'?'你':result?.provider?'AI 助手 · '+result.provider+' / '+result.model:'AI 助手';
    const body=document.createElement('div');body.className='assistant-text';body.textContent=text;article.append(name,body);
    if(result?.sources?.length){const list=document.createElement('div');list.className='assistant-sources';for(const s of result.sources){
      if(typeof s.url!=='string'||!s.url.startsWith('/')||s.url.startsWith('//'))continue;
      const a=document.createElement('a');a.href=s.url;a.textContent=s.label+' · '+s.title;list.append(a);
    }article.append(list);}
    if(result?.activity?.length){const detail=document.createElement('details');detail.className='assistant-activity';const title=document.createElement('summary');title.textContent='读取过程 · '+result.activity.length+' 步';detail.append(title);for(const step of result.activity){const p=document.createElement('p');p.textContent=step.label;detail.append(p);}article.append(detail);}
    $('thread').append(article);if(scroll)article.scrollIntoView({behavior:'smooth',block:'end'});
  }
  async function poll(){
    const activeJob=job,epoch=viewEpoch;if(!activeJob)return;
    try{const data=await request(app.dataset.jobBase+activeJob+'/');if(epoch!==viewEpoch||job!==activeJob)return;
      if(data.state==='running'){status(data.activity?.at(-1)?.label||'正在思考与查找资料…');pollTimer=setTimeout(poll,900);return;}
      const result=data.result; job=null;sessionStorage.removeItem(jobKey);busy(false);
      refreshConversations().catch(()=>{});
      if(result.error){message('assistant',result.error,result);status('本轮未完成，已发生的调用在 API 池查看。');return;}
      message('assistant',result.text,result);if(data.state==='done')history.push({role:'assistant',content:result.text});
      status((data.state==='cancelled'?'已停止 · ':'')+'本轮 '+result.calls+' 次调用 · '+result.tokens+' tokens · 约 ¥ '+result.cost_cny+(result.pending_cost?'，部分费用待核对':'')+(result.warning?' · '+result.warning:''));
      load().catch(()=>{});
    }catch(error){
      if(epoch!==viewEpoch||job!==activeJob)return;
      if([401,403,404].includes(error.status)){job=null;sessionStorage.removeItem(jobKey);busy(false);status('对话任务已不可用，请重新开始；已发生的用量记录保留。');return;}
      status(error.message+' 可稍后重新打开助手恢复。');pollTimer=setTimeout(poll,5000);
    }
  }
  $('form').addEventListener('submit',async event=>{
    event.preventDefault();if(job||starting||opening)return;const text=$('input').value.trim();if(!text)return;
    history=history.slice(-20);
    starting=true;history.push({role:'user',content:text});busy(true);status('正在启动…');
    try{const data=await request(app.dataset.start,{model:Number($('model').value),messages:app.dataset.conversations?[{role:'user',content:text}]:history,context,conversation});
      if(data.conversation){conversation=data.conversation;$('title').textContent=data.title;rememberConversation();drafts.delete('new');drafts.delete(conversation);refreshConversations().catch(()=>{});}
      job=data.job;sessionStorage.setItem(jobKey,job);message('user',text);$('input').value='';poll();
    }catch(error){history.pop();status(error.message);}
    finally{starting=false;busy(Boolean(job));}
  });
  $('stop').addEventListener('click',async()=>{if(!job)return;try{await request(app.dataset.jobBase+job+'/',{});status('正在停止；已发送的模型请求会先完成用量结算。');$('stop').disabled=true;}catch(error){status(error.message);}});
  $('new').addEventListener('click',newConversation);
  $('input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('form').requestSubmit();}});
  app.querySelectorAll('[data-assistant-prompt]').forEach(b=>b.addEventListener('click',()=>{$('input').value=b.dataset.assistantPrompt;$('input').focus();}));
  async function search(){const epoch=++searchEpoch;const results=$('reference-results');results.textContent='正在搜索…';
    try{const url=app.dataset.references+'?kind='+encodeURIComponent($('reference-kind').value)+'&q='+encodeURIComponent($('reference-query').value);const data=await request(url);if(epoch!==searchEpoch)return;results.replaceChildren();
      for(const row of data.results){const s=row.source,b=document.createElement('button');b.type='button';b.className='assistant-reference-item';b.textContent=s.label+' · '+s.title;b.addEventListener('click',()=>{showContext({kind:s.kind,id:s.id},s.label+' · '+s.title);$('reference-dialog').close();});results.append(b);}
      if(!data.results.length)results.textContent='没有匹配的资料。';
    }catch(error){results.textContent=error.message;}}
  $('add').addEventListener('click',()=>{$('reference-dialog').showModal();search();});$('reference-close').addEventListener('click',()=>$('reference-dialog').close());
  $('reference-kind').addEventListener('change',search);$('reference-query').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(search,250);});
  async function init(){
    await load();
    if(app.dataset.conversations){
      await refreshConversations();
      if(context)return;
      let saved;try{saved=localStorage.getItem(lastKey);}catch(_){}
      const previous=conversations.find(row=>String(row.id)===saved);
      if(previous)await openConversation(previous.id);
      else if(saved!=='new'&&conversations.length)await openConversation(conversations[0].id);
    }else{const saved=sessionStorage.getItem(jobKey);if(saved){job=saved;busy(true);poll();}}
  }
  init().catch(error=>status(error.message));
})();
