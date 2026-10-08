/* Bundled local history: account-separated durable storage, never cache API keys. */
(async function () {
  'use strict';
  if(window.zhiyuLocalChatReady)return;
  window.zhiyuLocalChatReady=true;
  const account = document.documentElement.dataset.account;
  if (!/^[1-9]\d*$/.test(account || '')) return;
  const offline = document.documentElement.dataset.localHistory === 'true';
  let db;
  try {
    db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('zhiyu-local-chat', 1);
      request.onupgradeneeded = () => {
        const rows = request.result.createObjectStore('messages', {keyPath:['account','channel','id']});
        rows.createIndex('channel', ['account','channel']); rows.createIndex('account', 'account');
        const chats = request.result.createObjectStore('chats', {keyPath:['account','channel']}); chats.createIndex('account','account');
      };
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
  } catch (_) { return; }
  const node = (tag, text, cls) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; };
  const url = value => { try { const u = new URL(value, location.href); return u.origin === location.origin && /^https?:$/.test(u.protocol) ? u.href : ''; } catch (_) { return ''; } };
  const commit = (stores, action) => new Promise((resolve, reject) => {
    const transaction = db.transaction(stores,'readwrite');
    transaction.oncomplete = resolve; transaction.onerror = () => reject(transaction.error); transaction.onabort = () => reject(transaction.error);
    try { action(transaction); } catch (error) { transaction.abort(); reject(error); }
  });
  const recent = (channel, limit=Infinity) => new Promise((resolve, reject) => {
    const rows = []; const request = db.transaction('messages').objectStore('messages').index('channel').openCursor(IDBKeyRange.only([account,channel]), 'prev');
    request.onsuccess = () => { const cursor = request.result; if (cursor && rows.length < limit) { rows.push(cursor.value); cursor.continue(); } else resolve(rows.reverse()); };
    request.onerror = () => reject(request.error);
  });
  async function clearChannel(channel) {
    await commit(['messages','chats'], tx => {
      const request = tx.objectStore('messages').index('channel').openCursor(IDBKeyRange.only([account,channel]));
      request.onsuccess = () => { const cursor = request.result; if (cursor) { cursor.delete(); cursor.continue(); } };
      const chatRequest=tx.objectStore('chats').get([account,channel]);
      chatRequest.onsuccess=()=>{
        const chat=chatRequest.result;if(chat)tx.objectStore('chats').put({...chat,hidden:true,clearedThrough:chat.latestId||chat.clearedThrough||0});
      };
    });
  }
  const chats = () => new Promise((resolve, reject) => {
    const request = db.transaction('chats').objectStore('chats').index('account').getAll(account);
    request.onsuccess = () => resolve(request.result.sort((a,b)=>b.updated-a.updated)); request.onerror = () => reject(request.error);
  });
  async function backup() {
    const rows=await new Promise((resolve,reject)=>{const r=db.transaction('messages').objectStore('messages').index('account').getAll(account);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
    const value=JSON.stringify({protocol:1,account,createdAt:new Date().toISOString(),origin:location.origin,chats:await chats(),messages:rows});
    if(new Blob([value]).size>20*1024*1024)throw Error('备份超过 20 MB，请先清理不需要的记录。');
    return value;
  }
  window.zhiyuPrepareChatBackup=async()=>{
    window.zhiyuChatBackup={ready:false};
    try{window.zhiyuChatBackup={ready:true,text:await backup()};}
    catch(error){window.zhiyuChatBackup={ready:true,error:error.message||'无法读取本机记录。'};}
  };
  function paint(row) {
    const card = node('article', undefined, 'personal-message-row message-bubble-row' + (row.mine ? ' mine' : ''));
    card.dataset.localMessage = String(row.id);
    const bubble = node('div', undefined, 'message-bubble');
    const byline = node('div', undefined, 'message-byline'); byline.append(node('strong',row.author),node('small',row.at));
    bubble.append(byline,node('p',row.withdrawn ? '消息已撤回' : row.body));
    if (row.quote) bubble.append(node('blockquote',row.quote));
    if (!row.withdrawn && row.sticker && url(row.sticker.url)) { const image = node('img',undefined,'message-sticker'); image.src = url(row.sticker.url); image.alt = row.sticker.name; bubble.append(image); }
    if (!row.withdrawn) for (const file of row.files || []) { const a = node('a', file.name, 'message-file'); if (url(file.url)) { a.href = url(file.url); bubble.append(a); } }
    card.append(bubble); return card;
  }
  async function renderLocalHistory() {
    const main = document.querySelector('main'); if (!main) return;
    main.replaceChildren();
    const label = node('p','本机聊天记录','muted'); main.append(label);
    const note = node('p','记录保存在这台设备，退出登录不会删除；换机前请备份。','muted'); main.append(note);
    const list = node('section',undefined,'phone-quick-card'); main.append(list);
    const stored = (await chats()).filter(chat=>!chat.hidden);
    if (!stored.length) list.append(node('p','还没有保存到本机的聊天记录。','phone-empty'));
    for (const chat of stored) {
      const button = node('button',undefined,'phone-row'); button.type='button'; button.append(node('strong',chat.title),node('span','›','phone-chevron'));
      button.addEventListener('click',async () => {
        const records = await recent(chat.channel); main.replaceChildren();
        const back = node('button','返回本机记录列表','button'); back.type='button'; back.onclick=renderLocalHistory;
        main.append(back,node('h2',chat.title));
        const search=node('input');search.type='search';search.placeholder='查找聊天记录';search.setAttribute('aria-label','查找聊天记录');main.append(search);
        const history=node('section',undefined,'phone-local-log');
        const show=()=>{const term=search.value.trim().toLocaleLowerCase();history.replaceChildren();records.filter(row=>!term||[row.body,row.author,row.quote].some(v=>(v||'').toLocaleLowerCase().includes(term))).forEach(row=>history.append(paint(row)));};
        search.oninput=show;show();main.append(history);
        const actions=node('div',undefined,'phone-local-actions');
        const remove=node('button','删除这段本机记录','button'); remove.type='button';
        remove.onclick=async()=>{ if(confirm('删除这段本机聊天记录？请先备份需要保留的内容。')){await clearChannel(chat.channel);renderLocalHistory();} };
        actions.append(remove);main.append(actions);
      });
      list.append(button);
      if(new URLSearchParams(location.search).get('channel')===chat.channel)button.click();
    }
    const exportButton = node('button','备份本机记录','button'); exportButton.type='button';
    exportButton.onclick=async()=>{
      if(navigator.userAgent.includes('ZhiyuMobile/')){location.href='/__phone_backup__/';return;}
      try{const blob=new Blob([await backup()],{type:'application/json'});const link=node('a');link.href=URL.createObjectURL(blob);
        link.download='Zhiyu-chat-'+account+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),60000);
      }catch(error){alert(error.message||'备份失败，请重试。');}
    };
    main.append(exportButton);
    const restore = node('label','导入聊天备份','button'); const file = node('input'); file.type='file'; file.accept='application/json'; file.hidden=true;restore.append(file);
    file.onchange=async()=>{
      try{
        const selected=file.files[0];if(!selected||selected.size>20*1024*1024)throw Error('备份文件过大。');
        const value=JSON.parse(await selected.text());
        if(value.protocol!==1||value.account!==account||value.origin!==location.origin||!Array.isArray(value.messages)||!Array.isArray(value.chats))throw Error('只能导入当前账号和服务器的备份。');
        if(!confirm('导入备份到本机？相同消息会合并。'))return;
        await commit(['messages','chats'],tx=>{
          for(const row of value.messages){if(row.account!==account||!Number.isSafeInteger(row.id)||row.id<=0||!/^\/(?:messages\/(?:personal|groups)\/[1-9]\d*)\/$/.test(row.channel)||typeof row.body!=='string'||typeof row.author!=='string'||typeof row.at!=='string'||row.quote&&typeof row.quote!=='string'||!Array.isArray(row.files||[])||row.files?.some(file=>typeof file.name!=='string'||typeof file.url!=='string')||row.sticker&&(typeof row.sticker.name!=='string'||typeof row.sticker.url!=='string'))throw Error('备份记录无效。');tx.objectStore('messages').put(row);}
          for(const chat of value.chats){if(chat.account!==account||typeof chat.title!=='string'||!/^\/(?:messages\/(?:personal|groups)\/[1-9]\d*)\/$/.test(chat.channel)||!Number.isFinite(chat.updated)||chat.latestId&&!Number.isSafeInteger(chat.latestId)||chat.clearedThrough&&!Number.isSafeInteger(chat.clearedThrough))throw Error('备份记录无效。');tx.objectStore('chats').put(chat);}
        });renderLocalHistory();
      }catch(error){alert(error.message||'无法导入备份。');}
    };main.append(restore);
  }
  if (offline || location.pathname==='/me/' && new URLSearchParams(location.search).get('mobile')==='history') { await renderLocalHistory(); return; }
  if (location.pathname==='/account/') {
    const menu=document.querySelector('main');
    if(menu){const a=node('a',undefined,'phone-row');a.href='/me/?mobile=history';a.append(node('strong','本机聊天记录'),node('span','›','phone-chevron'));menu.append(a);}
  }
  const thread=document.querySelector('[data-personal-thread]'); if(!thread) return;
  const channel=location.pathname;
  const match=channel.match(/^\/messages\/(personal|groups)\/(\d+)\/$/);if(!match)return;
  const serverChannel=(match[1]==='personal'?'person:':'group:')+match[2];
  const history=thread.querySelector('[data-history]');if(!history)return;
  const details=thread.querySelector('[data-chat-details]');
  if(details){const local=node('a','本机聊天记录','phone-row');local.href='/me/?'+new URLSearchParams({mobile:'history',channel});details.append(local);}
  const title=thread.querySelector('.conversation-title')?.textContent.trim()||'聊天';
  const storedChat=await new Promise(resolve=>{const r=db.transaction('chats').objectStore('chats').get([account,channel]);r.onsuccess=()=>resolve(r.result);r.onerror=()=>resolve(null);});
  let locallyCleared=storedChat?.clearedThrough||0;
  history.querySelectorAll('[data-message-id]').forEach(card=>{if(Number(card.dataset.messageId)<=locallyCleared)card.remove();});
  const originalFetch=window.fetch.bind(window);let saving=false,pending=false;
  const purged=new Set(), acknowledged=new Set();
  const csrf=()=>thread.querySelector('[name=csrfmiddlewaretoken]')?.value;
  function snapshot(card) {
    const id=Number(card.dataset.messageId);if(!Number.isSafeInteger(id)||id<=locallyCleared||id<=0||card.querySelector('[data-gift-id]'))return null;
    const withdrawn=card.classList.contains('message-system-note');
    if(withdrawn&&!card.textContent.includes('撤回'))return null;
    return {account,channel,id,author:card.querySelector('.message-byline strong')?.textContent||'',at:card.querySelector('.message-byline small')?.textContent||'',mine:card.classList.contains('mine'),
      body:withdrawn?'消息已撤回':card.querySelector('[data-message-body]')?.innerText||'',withdrawn,quote:card.querySelector('blockquote')?.textContent||'',
      files:[...card.querySelectorAll('.message-file')].map(a=>({name:a.textContent,url:url(a.href)})),
      sticker:card.querySelector('.message-sticker')?{url:url(card.querySelector('.message-sticker').src),name:card.querySelector('.message-sticker').alt}:null};
  }
  async function acknowledge(ids) {
    const fresh=ids.filter(id=>!acknowledged.has(id));
    for(let i=0;i<fresh.length;i+=200){
      try {
        const batch=fresh.slice(i,i+200);const response=await originalFetch('/messages/local-records/ack/',{method:'POST',headers:{'X-CSRFToken':csrf(),'Content-Type':'application/json'},body:JSON.stringify({channel:serverChannel,ids:batch}),cache:'no-store'});
        if(response.ok){const data=await response.json();for(const id of data.received||[])acknowledged.add(id);}
      } catch (_) { /* Retry after subsequent durable saves; no acknowledgment on failure. */ }
    }
  }
  async function save() {
    if(saving){pending=true;return;}saving=true;
    try{
      const rows=[...history.querySelectorAll('[data-message-id]')].map(snapshot).filter(Boolean);
      await commit(['messages','chats'],tx=>{
        const store=tx.objectStore('messages');rows.forEach(row=>store.put(row));
        if(rows.length)tx.objectStore('chats').put({account,channel,title,updated:Date.now(),latestId:Math.max(...rows.map(row=>row.id)),clearedThrough:locallyCleared});
      });
      // Commit completion, not message display or read status, triggers receipt.
      await acknowledge(rows.map(row=>row.id));
    }catch(_){const status=thread.querySelector('[data-thread-status]');if(status)status.textContent='本机存储暂不可用，服务器记录仍保留。';}
    finally{saving=false;if(pending){pending=false;save();}}
  }
  async function validateStored(rows) {
    const kept=[];
    for(let i=0;i<rows.length;i+=200){
      const batch=rows.slice(i,i+200);
      try{
        const response=await originalFetch('/messages/local-records/state/?'+new URLSearchParams({channel:serverChannel,known:batch.map(row=>row.id).join(',')}),{cache:'no-store'});
        if(!response.ok)return [];const data=await response.json();const permitted=new Set([...(data.visible||[]),...(data.purged||[])]);
        const withdrawn=new Set(data.withdrawn||[]);
        (data.purged||[]).forEach(id=>purged.add(id));
        await commit(['messages'],tx=>{for(const row of batch){if(permitted.has(row.id)){const current=withdrawn.has(row.id)?{...row,body:'消息已撤回',withdrawn:true,quote:'',files:[],sticker:null}:row;kept.push(current);if(current!==row)tx.objectStore('messages').put(current);}else tx.objectStore('messages').delete([account,channel,row.id]);}});
      }catch(_){return [];}
    }return kept;
  }
  await save();
  const cached=await validateStored(await recent(channel,500));
  const existing=new Set([...history.querySelectorAll('[data-message-id]')].map(el=>Number(el.dataset.messageId)));
  for(const row of cached){if(!existing.has(row.id)){const card=paint(row);card.dataset.cachedId=String(row.id);history.prepend(card);}}
  // Sort cached and live rows without changing server cursors/action handlers.
  const cards=[...history.children].filter(el=>el.dataset.messageId||el.dataset.cachedId).sort((a,b)=>Number(a.dataset.messageId||a.dataset.cachedId)-Number(b.dataset.messageId||b.dataset.cachedId));
  cards.forEach(card=>history.append(card));history.scrollTop=history.scrollHeight;
  let timer;new MutationObserver(()=>{clearTimeout(timer);timer=setTimeout(save,400);}).observe(history,{childList:true,subtree:true,characterData:true});
  window.fetch=async function(input,init){
    const response=await originalFetch(input,init);const value=input instanceof Request?input.url:String(input);let destination;try{destination=new URL(value,location.href);}catch(_){return response;}
    if(destination.origin!==location.origin||!destination.pathname.startsWith(channel))return response;
    if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))return response;
    const data=await response.clone().json();const body=init?.body;const action=body?.get?.('action');
    if(action==='clear'){locallyCleared=Math.max(locallyCleared,...[...history.querySelectorAll('[data-message-id],[data-cached-id]')].map(el=>Number(el.dataset.messageId||el.dataset.cachedId)));await clearChannel(channel);}
    if(action==='delete'){const id=Number(destination.pathname.match(/\/(\d+)\/$/)?.[1]);if(Number.isSafeInteger(id))await commit(['messages'],tx=>tx.objectStore('messages').delete([account,channel,id]));}
    if(Array.isArray(data.messages))data.messages=data.messages.filter(row=>row.id>locallyCleared);
    for(const row of data.messages||[])history.querySelector('[data-cached-id="'+Number(row.id)+'"]')?.remove();
    if(Array.isArray(data.removed)&&data.removed.length){
      // A server-expired record remains in the local archive; hidden/deleted
      // records are removed from local storage instead of being resurrected.
      const records=await recent(channel);const kept=await validateStored(records.filter(row=>data.removed.includes(row.id)));const permitted=new Set(kept.map(row=>row.id));
      for(const id of data.removed)if(!permitted.has(id))history.querySelector('[data-cached-id="'+Number(id)+'"]')?.remove();
      data.removed=data.removed.filter(id=>!purged.has(id));
    }
    const headers=new Headers(response.headers);headers.delete('Content-Length');headers.delete('Content-Encoding');
    return new Response(JSON.stringify(data),{status:response.status,headers});
  };
  // Collect older available records in the background, without a manual sync
  // button. Uncollected records are never acknowledged or eligible for purge.
  const abort=new AbortController();window.addEventListener('pagehide',()=>abort.abort(),{once:true});
  async function collectEarlier() {
    let before=Math.min(...[...history.querySelectorAll('[data-message-id]')].map(el=>Number(el.dataset.messageId)));
    if(!Number.isFinite(before))return;
    for(let page=0;page<50&&!abort.signal.aborted;page++){
      try{
        const response=await originalFetch(channel+'history/?'+new URLSearchParams({before:String(before)}),{headers:{Accept:'application/json'},cache:'no-store',signal:abort.signal});
        if(!response.ok)return;const data=await response.json();if(!Array.isArray(data.messages))return;
        const rows=data.messages.filter(row=>Number.isSafeInteger(row.id)&&row.id>locallyCleared&&!row.gift).map(row=>({account,channel,id:row.id,author:row.author||'',at:row.at||'',mine:!!row.mine,body:row.withdrawn?'消息已撤回':row.body||'',withdrawn:!!row.withdrawn,quote:row.withdrawn?'':row.quote?.body||'',files:row.files||[],sticker:row.sticker||null}));
        if(abort.signal.aborted)return;
        await commit(['messages'],tx=>rows.filter(row=>row.id>locallyCleared).forEach(row=>tx.objectStore('messages').put(row)));
        await acknowledge(rows.map(row=>row.id));
        if(!Number.isSafeInteger(data.next_before)||data.next_before>=before)return;before=data.next_before;
      }catch(_){return;}
    }
  }
  collectEarlier();
})();
