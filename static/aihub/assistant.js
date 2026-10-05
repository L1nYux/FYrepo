(() => {
  const app=document.querySelector('#assistant-app'); if(!app)return;
  const $=id=>document.getElementById('assistant-'+id), csrf=app.querySelector('[name=csrfmiddlewaretoken]').value;
  let models=[],history=[],context=null,job=null,pollTimer=null,searchTimer=null,searchEpoch=0,starting=false;
  let conversation=null,conversations=[],opening=false,viewEpoch=0,listEpoch=0,renameId=null,listTimer=null;
  let activeAttempt=null;
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
    $('thread').querySelectorAll('[data-assistant-retry]').forEach(button=>button.disabled=value||opening||starting);
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
    if($('history-days'))$('history-days').value=String(data.history_days||0);
  }
  function resetThread(){history=[];$('thread').querySelectorAll('.assistant-row').forEach(n=>n.remove());$('empty').hidden=false;showContext(null,'');}
  function newConversation(){
    if(starting||opening)return;
    drafts.set(conversation??'new',$('input').value);viewEpoch++;clearTimeout(pollTimer);job=null;activeAttempt=null;conversation=null;
    sessionStorage.removeItem(jobKey);resetThread();$('input').value=drafts.get('new')||'';
    if(app.dataset.conversations){$('title').textContent='新对话';rememberConversation();}
    busy(false);status('调用计入你的团队 API 池用量');
  }
  async function openConversation(id){
    if(starting||opening||id===conversation)return;
    drafts.set(conversation??'new',$('input').value);const epoch=++viewEpoch;clearTimeout(pollTimer);job=null;activeAttempt=null;opening=true;busy(false);
    try{
      const data=await request(app.dataset.conversationBase+id+'/');if(epoch!==viewEpoch)return;
      conversation=data.id;resetThread();$('title').textContent=data.title;$('input').value=drafts.get(conversation)||'';rememberConversation();
      for(const row of data.messages){
        const article=message(row.role,row.text,row.result,false);if(row.role==='user'&&row.context)referenceLabel(article,row.context);
        if(row.retry){const attempt=makeAttempt(row.retry.text,row.retry.context);attempt.retryJob=row.retry.job;attempt.accepted=true;attempt.row=article;failed(attempt,row.text);}
        if(!row.result?.error)history.push({role:row.role,content:row.text});
      }
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
    $('history-days').addEventListener('change',async()=>{
      if(starting||opening){status('请等待当前操作完成。');return;}
      const days=Number($('history-days').value);
      if(days && !confirm('自动删除超过 '+days+' 天未使用的对话？正在执行的对话和用量账目保留。')){await refreshConversations();return;}
      try{await request(app.dataset.conversations,{action:'retention',days});if(!job)newConversation();await refreshConversations();status('历史保留设置已保存。');}
      catch(error){status(error.message);}
    });
    $('history-clear').addEventListener('click',async()=>{
      if(starting||opening||job){status('请先停止当前对话，完成后再清空。');return;}
      if(!confirm('清空你的全部 AI 对话？不能恢复，已发生的用量账目保留。'))return;
      try{await request(app.dataset.conversations,{action:'clear'});$('input').value='';newConversation();drafts.clear();await refreshConversations();status('对话已清空，用量账目保留。');}
      catch(error){status(error.message);}
    });
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
      const option=document.createElement('option');option.value=model.id;option.textContent=model.label;group.append(option);
    }
    if(selected)$('model').value=selected.id;
    else{const option=document.createElement('option');option.value='';option.textContent='暂无可用模型';$('model').append(option);status('API 池尚无可用模型，请管理员连接厂商并配置价格。');}
    $('model').title=(data.budget.member_week.limit===null?'本周基础额度不限':'本周基础剩余 '+Number(data.budget.member_week.remaining_points).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点')+' · 额外可用 '+Number(data.budget.extra?.remaining_points||0).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点';
    busy(Boolean(job)||starting);
  }
  $('model').addEventListener('change',()=>{try{localStorage.setItem(modelKey,$('model').value);}catch(_){}
    request('/api-pool/preferences/',{model:Number($('model').value)}).catch(()=>status('模型已切换，暂未保存为下次默认。'));
  });
  function showContext(value,title){context=value;$('context').hidden=!value;$('context').querySelector('span').textContent=value?title:'';}
  const referenceNames={project:'项目',task:'任务',experiment:'实验',announcement:'公告',message:'消息',entry:'账目',claim:'报销'};
  if(app.dataset.contextKind&&/^\d+$/.test(app.dataset.contextId))showContext({kind:app.dataset.contextKind,id:Number(app.dataset.contextId)},'当前资料 · '+(referenceNames[app.dataset.contextKind]||'资料')+' #'+app.dataset.contextId);
  $('clear-context').addEventListener('click',()=>showContext(null,''));
  function message(role,text,result,scroll=true,existing=null){
    $('empty').hidden=true;const article=existing||document.createElement('article');if(existing)article.replaceChildren();article.className='assistant-row '+role;
    const name=document.createElement('strong');name.textContent=role==='user'?'你':result?.provider?'AI 助手 · '+result.provider+' / '+result.model:'AI 助手';
    const body=document.createElement('div');body.className='assistant-text';if(role==='assistant'&&window.workbenchMarkdown)window.workbenchMarkdown(body,text,result||{});else body.textContent=text;article.append(name,body);
    if(result?.reasoning){const detail=document.createElement('details');detail.className='assistant-thinking';const summary=document.createElement('summary');summary.textContent='思考过程';const content=document.createElement('div');content.className='assistant-thinking-text';content.textContent=result.reasoning;detail.append(summary,content);article.insertBefore(detail,body);}
    if(result?.sources?.length){const list=document.createElement('details');list.className='assistant-sources';const label=document.createElement('summary');label.textContent='参考资料 · '+result.sources.length;list.append(label);for(const s of result.sources){
      if(typeof s.url!=='string'||!(s.url.startsWith('/')&&!s.url.startsWith('//')||/^https?:\/\//.test(s.url)))continue;
      const a=document.createElement('a');a.href=s.url;if(s.kind==='web'){a.dataset.webSource='';a.target='_blank';a.rel='noopener noreferrer';}a.textContent=s.label+' · '+s.title;list.append(a);
    }article.append(list);}
    if(result?.activity?.length){const detail=document.createElement('details');detail.className='assistant-activity';const title=document.createElement('summary');title.textContent='读取过程 · '+result.activity.length+' 步';detail.append(title);for(const step of result.activity){const p=document.createElement('p');p.textContent=step.label;detail.append(p);}article.append(detail);}
    if(!existing)$('thread').append(article);if(scroll)article.scrollIntoView({behavior:'smooth',block:'end'});return article;
  }
  function nonce(){
    if(crypto.randomUUID)return crypto.randomUUID();
    const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
    const hex=Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');return hex.slice(0,8)+'-'+hex.slice(8,12)+'-'+hex.slice(12,16)+'-'+hex.slice(16,20)+'-'+hex.slice(20);
  }
  function referenceLabel(row,value,title){if(!value)return;const label=document.createElement('small');label.className='assistant-reference-label';label.textContent='引用：'+(title||(referenceNames[value.kind]||'资料')+' #'+value.id);row.append(label);}
  function makeAttempt(text,value){return {text,context:value?{...value}:null,model:Number($('model').value),conversation,requestId:nonce(),messages:[...history.slice(-20),{role:'user',content:text}],accepted:false,epoch:viewEpoch};}
  function pending(attempt,value={},activity=[]){
    if(!attempt.pendingRow){attempt.pendingRow=message('assistant','');attempt.pendingRow.classList.add('assistant-pending');
      const state=document.createElement('div');state.className='assistant-wait';state.setAttribute('role','status');state.innerHTML='<span class="assistant-wait-dot" aria-hidden="true"></span><span data-wait-label></span><small data-wait-time></small>';
      const details=document.createElement('details');details.className='assistant-thinking';details.hidden=true;
      const summary=document.createElement('summary');summary.textContent='思考过程';const content=document.createElement('div');content.className='assistant-thinking-text';details.append(summary,content);
      attempt.pendingRow.insertBefore(details,attempt.pendingRow.querySelector('.assistant-text'));attempt.pendingRow.append(state);attempt.startedAt=Date.now();
    }
    const row=attempt.pendingRow,stick=$('thread').scrollHeight-$('thread').scrollTop-$('thread').clientHeight<120;
    const body=row.querySelector('.assistant-text');if(window.workbenchMarkdown)window.workbenchMarkdown(body,value.text||'');else body.textContent=value.text||'';
    row.querySelector('.assistant-thinking').hidden=!value.reasoning;
    row.querySelector('.assistant-thinking-text').textContent=value.reasoning||'';
    row.querySelector('[data-wait-label]').textContent=['searching','reading'].includes(value.stage)?(activity.at(-1)?.label||'正在读取资料…'):value.text?'正在回复…':'正在思考…';
    row.querySelector('[data-wait-time]').textContent=Math.floor((Date.now()-attempt.startedAt)/1000)+' 秒';
    if(stick)$('thread').scrollTop=$('thread').scrollHeight;
  }
  function clearPending(attempt){attempt?.pendingRow?.remove();if(attempt)attempt.pendingRow=null;}
  function failed(attempt,text,resumeJob=null){
    clearPending(attempt);
    attempt.control?.remove();const box=document.createElement('div');box.className='assistant-send-status';box.setAttribute('role','status');
    const hint=document.createElement('span');hint.textContent=text;const button=document.createElement('button');button.type='button';button.className='button assistant-retry';button.setAttribute('data-assistant-retry','');button.textContent='重试';
    button.addEventListener('click',()=>{
      if(job||starting||opening||attempt.epoch!==viewEpoch)return;
      if(resumeJob){attempt.control.remove();attempt.control=null;activeAttempt=attempt;job=resumeJob;busy(true);status('正在恢复本轮回复…');poll();return;}
      if(attempt.retryJob)attempt.requestId=nonce();startAttempt(attempt);
    });
    box.append(hint,button);attempt.row.append(box);attempt.control=box;busy(Boolean(job)||starting);
  }
  async function startAttempt(attempt){
    if(job||starting||opening||attempt.epoch!==viewEpoch)return;
    starting=true;activeAttempt=attempt;attempt.control?.remove();attempt.control=null;pending(attempt);busy(true);status('正在启动…');
    try{
      const data=await request(app.dataset.start,{model:attempt.model,messages:app.dataset.conversations?[{role:'user',content:attempt.text}]:attempt.messages,context:attempt.context,conversation:attempt.conversation,request_id:attempt.requestId,retry_job:attempt.retryJob||undefined});
      if(attempt.epoch!==viewEpoch)return;
      if(!attempt.accepted){history.push({role:'user',content:attempt.text});attempt.accepted=true;}
      if(data.conversation){conversation=data.conversation;attempt.conversation=conversation;$('title').textContent=data.title;rememberConversation();refreshConversations().catch(()=>{});}
      job=data.job;sessionStorage.setItem(jobKey,job);poll();
    }catch(error){if(attempt.epoch===viewEpoch){failed(attempt,error.message);status('消息未完成，可在消息旁重试。');}}
    finally{if(attempt.epoch===viewEpoch){starting=false;busy(Boolean(job));}}
  }
  async function poll(){
    const activeJob=job,epoch=viewEpoch;if(!activeJob)return;
    try{const data=await request(app.dataset.jobBase+activeJob+'/');if(epoch!==viewEpoch||job!==activeJob)return;
      if(!activeAttempt&&data.request){activeAttempt=makeAttempt(data.request.text,data.request.context);activeAttempt.accepted=true;activeAttempt.restored=true;}
      if(data.state==='running'){if(activeAttempt)pending(activeAttempt,data.result?.progress||{},data.activity||[]);status(data.result?.progress?.text?'正在回复…':'正在思考…');pollTimer=setTimeout(poll,700);return;}
      const result=data.result; job=null;sessionStorage.removeItem(jobKey);busy(false);clearPending(activeAttempt);
      refreshConversations().catch(()=>{});
      if(result.error){const attempt=activeAttempt||makeAttempt(data.request?.text||history.at(-1)?.content||'',data.request?.context);attempt.row=message('assistant','本轮未完成',result,true,attempt.retryJob&&!attempt.restored?attempt.row:null);attempt.retryJob=activeJob;attempt.accepted=true;failed(attempt,result.error);activeAttempt=null;status('本轮未完成，可在消息旁重试；已发生的调用在 API 池查看。');return;}
      message('assistant',result.text,result,true,activeAttempt?.retryJob&&!activeAttempt.restored?activeAttempt.row:null);activeAttempt=null;if(data.state==='done')history.push({role:'assistant',content:result.text});
      status((data.state==='cancelled'?'已停止 · ':'')+'本轮 '+result.calls+' 次调用 · '+result.tokens+' tokens · '+(Number(result.cost_cny||0)*100).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点（约 ¥ '+result.cost_cny+'）'+(result.pending_cost?'，部分费用待核对':'')+(result.warning?' · '+result.warning:''));
      load().catch(()=>{});
    }catch(error){
      if(epoch!==viewEpoch||job!==activeJob)return;
      if([401,403,404].includes(error.status)){clearPending(activeAttempt);job=null;sessionStorage.removeItem(jobKey);busy(false);status('对话任务已不可用，请重新开始；已发生的用量记录保留。');return;}
      const attempt=activeAttempt||makeAttempt('',null);attempt.row=attempt.row||message('assistant','回复连接中断');job=null;failed(attempt,error.message,activeJob);busy(false);status('连接中断，点击消息旁的重试恢复本轮回复。');
    }
  }
  $('form').addEventListener('submit',async event=>{
    event.preventDefault();if(job||starting||opening)return;const text=$('input').value.trim();if(!text)return;
    const attempt=makeAttempt(text,context);attempt.row=message('user',text);referenceLabel(attempt.row,context,$('context').querySelector('span').textContent);
    $('input').value='';showContext(null,'');drafts.delete(conversation??'new');await startAttempt(attempt);
  });
  $('stop').addEventListener('click',async()=>{if(!job)return;try{await request(app.dataset.jobBase+job+'/',{});status('正在停止；已发送的模型请求会先完成用量结算。');$('stop').disabled=true;}catch(error){status(error.message);}});
  $('new').addEventListener('click',newConversation);
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
