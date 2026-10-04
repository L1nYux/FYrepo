(() => {
  const form=document.getElementById('pool-connect-form');if(!form)return;
  const connections=JSON.parse(document.getElementById('pool-connections').textContent);
  const $=id=>document.getElementById('pool-'+id),csrf=form.querySelector('[name=csrfmiddlewaretoken]').value;
  let ticket='',rows=[],pending=false;
  async function request(url,data){
    const response=await fetch(url,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify(data)});
    if(response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw Error('登录已失效，请重新登录。');
    const value=await response.json();if(!response.ok)throw Error(value.error||'请求未完成。');return value;
  }
  function busy(value){pending=value;form.querySelectorAll('input,select,button').forEach(n=>n.disabled=value);$('select-form').querySelectorAll('input,select,button').forEach(n=>n.disabled=value||n.dataset.unsupported==='true');$('new').disabled=value;if($('existing'))$('existing').disabled=value;}
  function invalidate(){ticket='';rows=[];$('selection').hidden=true;$('catalog').replaceChildren();$('status').textContent='';}
  for(const name of ['api_key','name','base_url','protocol'])form.elements.namedItem(name).addEventListener('input',invalidate);
  $('url').addEventListener('input',()=>{form.elements.namedItem('id').value='';form.elements.namedItem('name').value='';form.elements.namedItem('protocol').value='';});
  function chooseConnection(id){
    if(pending)return;const value=connections.find(p=>String(p.id)===String(id));form.reset();invalidate();
    if(!value){form.elements.namedItem('id').value='';$('key').placeholder='粘贴 API Key';$('url').focus();return;}
    form.elements.namedItem('id').value=value.id;
    for(const name of ['name','base_url','protocol'])form.elements.namedItem(name).value=value[name];
    $('key').placeholder='已保存，留空保留';
    $('status').textContent='已加载保存的连接；点击读取模型才会访问厂商。';
  }
  $('existing')?.addEventListener('change',()=>chooseConnection($('existing').value));
  $('new').addEventListener('click',()=>{if(pending)return;if($('existing'))$('existing').value='';chooseConnection('');});
  function exchange(){
    const need=rows.some(row=>$('catalog').querySelector('input[value="'+CSS.escape(row.id)+'"]')?.checked&&!row.has_price&&row.price?.currency==='USD'&&!row.price.cny_exchange_rate);
    $('exchange').hidden=!need;$('exchange-rate').required=need;
  }
  function selectionCount(){
    const items=[...$('catalog').querySelectorAll('.pool-discovered-model')],visible=items.filter(n=>!n.hidden);
    const checks=visible.map(n=>n.querySelector('input')).filter(n=>n.dataset.unsupported!=='true');
    const selected=items.filter(n=>n.querySelector('input').checked).length;
    $('all').checked=checks.length>0&&checks.every(n=>n.checked);$('all').indeterminate=checks.some(n=>n.checked)&&!$('all').checked;
    $('all').disabled=pending||!checks.length;
    $('catalog-count').textContent='显示 '+visible.length+' / '+items.length+' 个 · 已选 '+selected+' 个';
    $('catalog-empty').hidden=visible.length>0;
  }
  function filter(){
    const query=$('search').value.trim().toLowerCase(),vendor=$('vendor').value,use=$('use').value,selectedOnly=$('selected-only').checked;
    $('catalog').querySelectorAll('.pool-discovered-model').forEach(n=>{
      n.hidden=!n.dataset.search.includes(query)||(vendor&&n.dataset.vendor!==vendor)||(use==='assistant'?n.dataset.supported!=='true':use&&n.dataset.use!==use)||(selectedOnly&&!n.querySelector('input').checked);
    });
    $('catalog').querySelectorAll('.pool-model-group').forEach(n=>n.hidden=![...n.querySelectorAll('.pool-discovered-model')].some(row=>!row.hidden));
    selectionCount();exchange();
  }
  $('search').addEventListener('input',filter);
  for(const id of ['vendor','use','selected-only'])$(id).addEventListener('change',filter);
  $('all').addEventListener('change',()=>{const checked=$('all').checked;$('catalog').querySelectorAll('.pool-discovered-model').forEach(n=>{const input=n.querySelector('input');if(!n.hidden&&input.dataset.unsupported!=='true')input.checked=checked;});filter();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(pending)return;invalidate();busy(true);$('status').textContent='正在连接厂商并读取模型…';
    const body=Object.fromEntries(new FormData(form));
    // Disabled form fields are excluded by FormData, so read their values explicitly.
    for(const name of ['id','api_key','name','base_url','protocol'])body[name]=form.elements.namedItem(name).value;
    try{const value=await request(form.dataset.discover,body);ticket=value.ticket;rows=value.models;
      $('key').value='';form.elements.namedItem('id').value=value.provider;$('key').placeholder='留空使用已有 Key';
      $('channel').textContent='调用渠道：'+(value.channel||form.elements.namedItem('name').value||new URL(body.base_url).hostname)+'。价格和可用额度以该渠道账户为准。';
      const option=(value,label)=>{const n=document.createElement('option');n.value=value;n.textContent=label;return n;};
      const vendors=[...new Set(rows.map(row=>row.vendor||'其他 / 未标明'))].sort((a,b)=>a.localeCompare(b,'zh-CN'));
      $('vendor').replaceChildren(option('','全部厂商'),...vendors.map(v=>option(v,v)));
      const uses=new Map(rows.map(row=>[row.use||'chat',row.use_label||'文本对话']));
      $('use').replaceChildren(option('assistant','助手可用'),option('','全部用途'),...Array.from(uses,([id,label])=>option(id,label)));
      const groups=new Map();
      for(const vendor of vendors){const group=document.createElement('section');group.className='pool-model-group';const heading=document.createElement('h3');heading.textContent=vendor;group.append(heading);groups.set(vendor,group);$('catalog').append(group);}
      for(const row of [...rows].sort((a,b)=>Number(Boolean(b.selected))-Number(Boolean(a.selected))||a.id.localeCompare(b.id))){
        const supported=row.assistant_supported!==false,vendor=row.vendor||'其他 / 未标明';
        const label=document.createElement('label');label.className='pool-discovered-model';label.dataset.search=(row.label+' '+row.id+' '+vendor).toLowerCase();
        Object.assign(label.dataset,{vendor,use:row.use||'chat',supported:String(supported)});
        const check=document.createElement('input');check.type='checkbox';check.value=row.id;check.checked=supported&&Boolean(row.selected);check.disabled=!supported;check.dataset.unsupported=String(!supported);check.addEventListener('change',filter);
        const text=document.createElement('span'),strong=document.createElement('strong'),small=document.createElement('small');
        strong.textContent=row.label;small.textContent=row.id+' · '+(row.use_label||'文本对话')+' · '+(!supported?(row.unavailable_reason||'当前助手暂不支持'):row.price?'价格已读取':row.has_price?'价格已保存':'待补价格');
        if(row.price)small.title='输入 '+row.price.input_rate+' / 输出 '+row.price.output_rate+' '+row.price.currency+' / 百万 token';
        text.append(strong,small);label.append(check,text);groups.get(vendor).append(label);
      }
      $('selection').hidden=false;$('enable').hidden=false;$('search').value='';$('selected-only').checked=false;$('use').value='assistant';filter();
      $('status').textContent='已读取 '+rows.length+' 个模型，默认显示助手可用的模型，勾选后保存。'+(value.price_note||'')+(value.truncated?'列表达到读取上限。':'');
    }catch(error){$('status').textContent=error.message;}
    finally{body.api_key='';$('key').value='';busy(false);if(ticket)selectionCount();}
  });
  $('select-form').addEventListener('submit',async event=>{
    event.preventDefault();if(pending||!ticket)return;
    const selected=[...$('catalog').querySelectorAll('input:checked')].map(n=>n.value);if(!selected.length){$('status').textContent='请至少勾选一个模型。';return;}
    busy(true);$('status').textContent='正在保存所选模型…';
    try{const value=await request(form.dataset.enable,{ticket,models:selected,exchange_rate:$('exchange-rate').value});
      if(value.missing_prices.length){
        location.href='?prices=1#pool-saved-models';
      }else{location.href=form.dataset.finish;}
    }catch(error){$('status').textContent=error.message;}
    finally{busy(false);selectionCount();}
  });
  const saved=document.getElementById('pool-saved-models');
  if(location.hash==='#pool-model-management')document.getElementById('pool-model-management').open=true;
  function filterPrices(){
    if(!$('price-search'))return;
    const query=$('price-search').value.trim().toLowerCase(),provider=$('price-provider').value,state=$('price-state').value;
    const items=[...saved.querySelectorAll('.pool-saved-model')];
    items.forEach(n=>n.hidden=!n.dataset.search.toLowerCase().includes(query)||(provider&&n.dataset.provider!==provider)||(state&&n.dataset.priceState!==state));
    $('price-empty').hidden=items.some(n=>!n.hidden);
  }
  $('price-search')?.addEventListener('input',filterPrices);
  for(const id of ['price-provider','price-state'])$(id)?.addEventListener('change',filterPrices);
  $('management-search')?.addEventListener('input',()=>{
    const query=$('management-search').value.trim().toLowerCase(),root=document.getElementById('pool-model-management');
    root.querySelectorAll('[data-management-model]').forEach(n=>n.hidden=!n.dataset.search.toLowerCase().includes(query));
    root.querySelectorAll('[data-management-group]').forEach(n=>n.hidden=Boolean(query)&&![...n.querySelectorAll('[data-management-model]')].some(row=>!row.hidden));
    $('management-empty').hidden=[...root.querySelectorAll('[data-management-group]')].some(n=>!n.hidden);
  });
  async function savePrice(priceForm,automatic=false){
    const status=priceForm.querySelector('[data-price-status]');
    const body={...Object.fromEntries(new FormData(priceForm)),id:priceForm.dataset.model,action:automatic?'automatic':'manual'};
    const buttons=[...priceForm.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);status.textContent=automatic?'正在读取公开价格…':'正在保存…';
    try{
      const value=await request(saved.dataset.priceUrl,body);
      for(const name of ['input_rate','output_rate','currency'])priceForm.elements.namedItem(name).value=value[name];
      priceForm.closest('.pool-saved-model').querySelector('[data-price-summary]').textContent='输入 '+Number(value.input_rate)+' / 输出 '+Number(value.output_rate)+' '+value.currency+' / 百万 token';
      status.textContent='已保存 · '+value.source;
      priceForm.closest('.pool-saved-model').dataset.priceState='saved';filterPrices();
    }catch(error){status.textContent=error.message;}
    finally{buttons.forEach(b=>b.disabled=false);}
  }
  saved?.querySelectorAll('.pool-simple-price').forEach(priceForm=>{
    priceForm.addEventListener('submit',event=>{event.preventDefault();savePrice(priceForm);});
    priceForm.querySelector('[data-auto-price]').addEventListener('click',()=>savePrice(priceForm,true));
  });
  if(connections.length&&!location.search){if($('existing'))$('existing').value=connections[0].id;chooseConnection(connections[0].id);}
})();
