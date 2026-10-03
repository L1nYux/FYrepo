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
  function busy(value){pending=value;form.querySelectorAll('input,select,button').forEach(n=>n.disabled=value);$('enable').disabled=value;$('new').disabled=value;if($('existing'))$('existing').disabled=value;}
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
  function filter(){const query=$('search').value.trim().toLowerCase();$('catalog').querySelectorAll('.pool-discovered-model').forEach(n=>n.hidden=!n.dataset.search.includes(query));}
  $('search').addEventListener('input',filter);
  $('all').addEventListener('change',()=>{$('catalog').querySelectorAll('input[type=checkbox]').forEach(n=>{if(!n.closest('label').hidden)n.checked=$('all').checked;});exchange();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(pending)return;invalidate();busy(true);$('status').textContent='正在连接厂商并读取模型…';
    const body=Object.fromEntries(new FormData(form));
    // Disabled form fields are excluded by FormData, so read their values explicitly.
    for(const name of ['id','api_key','name','base_url','protocol'])body[name]=form.elements.namedItem(name).value;
    try{const value=await request(form.dataset.discover,body);ticket=value.ticket;rows=value.models;
      $('key').value='';form.elements.namedItem('id').value=value.provider;$('key').placeholder='留空使用已有 Key';
      const preferred=rows.find(r=>r.selected)||rows.find(r=>r.has_price||r.price);
      for(const row of rows){
        const label=document.createElement('label');label.className='pool-discovered-model';label.dataset.search=(row.label+' '+row.id).toLowerCase();
        const check=document.createElement('input');check.type='checkbox';check.value=row.id;check.checked=row.selected||row===preferred;check.addEventListener('change',exchange);
        const text=document.createElement('span'),strong=document.createElement('strong'),small=document.createElement('small');
        strong.textContent=row.label;small.textContent=row.id+' · '+(row.price?'价格已读取':row.has_price?'价格已保存':'待补价格');
        if(row.price)small.title='输入 '+row.price.input_rate+' / 输出 '+row.price.output_rate+' '+row.price.currency+' / 百万 token';
        text.append(strong,small);label.append(check,text);$('catalog').append(label);
      }
      $('selection').hidden=false;$('enable').hidden=false;$('search').value='';$('all').checked=false;exchange();
      $('status').textContent='已读取 '+rows.length+' 个模型，勾选后保存。'+(value.price_note||'')+(value.truncated?'列表达到读取上限。':'');
    }catch(error){$('status').textContent=error.message;}
    finally{body.api_key='';$('key').value='';busy(false);}
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
    finally{busy(false);}
  });
  const saved=document.getElementById('pool-saved-models');
  async function savePrice(priceForm,automatic=false){
    const status=priceForm.querySelector('[data-price-status]');
    const body={...Object.fromEntries(new FormData(priceForm)),id:priceForm.dataset.model,action:automatic?'automatic':'manual'};
    const buttons=[...priceForm.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);status.textContent=automatic?'正在读取公开价格…':'正在保存…';
    try{
      const value=await request(saved.dataset.priceUrl,body);
      for(const name of ['input_rate','output_rate','currency'])priceForm.elements.namedItem(name).value=value[name];
      priceForm.closest('.pool-saved-model').querySelector('[data-price-summary]').textContent='输入 '+Number(value.input_rate)+' / 输出 '+Number(value.output_rate)+' '+value.currency+' / 百万 token';
      status.textContent='已保存 · '+value.source;
    }catch(error){status.textContent=error.message;}
    finally{buttons.forEach(b=>b.disabled=false);}
  }
  saved?.querySelectorAll('.pool-simple-price').forEach(priceForm=>{
    priceForm.addEventListener('submit',event=>{event.preventDefault();savePrice(priceForm);});
    priceForm.querySelector('[data-auto-price]').addEventListener('click',()=>savePrice(priceForm,true));
  });
  if(connections.length&&!location.search){if($('existing'))$('existing').value=connections[0].id;chooseConnection(connections[0].id);}
})();
