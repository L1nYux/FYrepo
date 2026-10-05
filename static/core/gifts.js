(() => {
  function nonce(){if(crypto.randomUUID)return crypto.randomUUID();const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');return hex.slice(0,8)+'-'+hex.slice(8,12)+'-'+hex.slice(12,16)+'-'+hex.slice(16,20)+'-'+hex.slice(20);}
  function pointCard(gift){const button=document.createElement('button');button.type='button';button.className='point-gift-card '+gift.kind;button.dataset.giftId=gift.id;button.dataset.giftStatus=gift.status;button.dataset.giftDimmed=String(gift.dimmed);
    const icon=document.createElement('span');icon.className='point-gift-icon';icon.textContent=gift.kind==='transfer'?'⇄':'福';
    const info=document.createElement('span'),title=document.createElement('strong'),state=document.createElement('small');title.textContent=gift.kind==='transfer'?Number(gift.points).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点':gift.greeting;state.textContent=gift.kind==='transfer'?gift.state_label:gift.claimed_points!==null?'已领取 '+Number(gift.claimed_points).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点':gift.status;info.append(title,state);
    const footer=document.createElement('span');footer.className='point-gift-footer';footer.textContent=gift.title+' · '+(gift.mode==='random'?'拼手气':'额外点数');button.append(icon,info,footer);return button;
  }
  window.workbenchPointCard=pointCard;
  document.querySelectorAll('[data-messages]').forEach(root=>{
    const send=root.querySelector('[data-gift-send-dialog]'),detail=root.querySelector('[data-gift-detail-dialog]');if(!send||!detail)return;
    const form=send.querySelector('form'),sendError=send.querySelector('[data-gift-send-error]'),detailError=detail.querySelector('[data-gift-detail-error]');
    let busy=false,id=null,selected=null,sendPayload=null,requestId=null;
    const csrf=()=>root.querySelector('[name=csrfmiddlewaretoken]').value;
    async function request(url,body){const response=await fetch(url,{method:body?'POST':'GET',headers:body?{'X-CSRFToken':csrf()}:undefined,body:body?new URLSearchParams(body):undefined,cache:'no-store'});if(!response.headers.get('content-type')?.includes('application/json'))throw Error('登录已失效，请重新登录。');const data=await response.json();if(!response.ok)throw Error(data.error||'操作未完成。');return data;}
    function paint(gift){selected=gift;detail.querySelector('h2').textContent=gift.title;const body=detail.querySelector('[data-gift-detail]');body.replaceChildren();
      for(const text of [gift.greeting,'总计 '+Number(gift.points).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点',gift.claimed_points!==null?(gift.kind==='transfer'?'你已收款 ':'你已领取 ')+Number(gift.claimed_points).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点':gift.status,'已领 '+gift.claimed_count+' / '+gift.count+' 份',Number(gift.refunded_points)>0?'已退回 '+Number(gift.refunded_points).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点':'24 小时未领取的部分自动退回']){const p=document.createElement('p');p.textContent=text;body.append(p);}
      for(const receipt of gift.receipts||[]){const p=document.createElement('p');p.className='gift-receipt';p.textContent=receipt.username+' · '+Number(receipt.points).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点';body.append(p);}
      const claim=detail.querySelector('[data-gift-claim]');claim.hidden=!gift.can_claim;claim.textContent=gift.kind==='transfer'?'确认收款':'领取红包';detail.querySelector('[data-gift-refund]').hidden=!gift.can_refund;
      root.querySelectorAll('[data-gift-id="'+gift.id+'"]').forEach(card=>card.replaceWith(pointCard(gift)));
    }
    async function open(giftId){if(busy)return;busy=true;id=giftId;detailError.textContent='';detail.querySelector('[data-gift-detail]').textContent='正在读取…';detail.querySelectorAll('[data-gift-claim],[data-gift-refund]').forEach(button=>button.hidden=true);detail.showModal();try{paint(await request('/messages/points/'+id+'/'));}catch(error){detailError.textContent=error.message;}finally{busy=false;}}
    root.addEventListener('click',event=>{const card=event.target.closest('[data-gift-id]');if(card)open(card.dataset.giftId);});
    root.querySelectorAll('[data-gift-close]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
    root.querySelectorAll('[data-gift-open]').forEach(button=>button.addEventListener('click',async()=>{
      if(busy)return;root.querySelector('[data-composer-plus]').open=false;sendError.textContent='';send.showModal();busy=true;
      try{const data=await request('/messages/points/');send.querySelector('[data-gift-available]').textContent=Number(data.available_points).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点';const history=send.querySelector('[data-gift-wallet-history]');history.replaceChildren();data.gifts.forEach(gift=>history.append(pointCard(gift)));}
      catch(error){sendError.textContent=error.message;}finally{busy=false;}
    }));
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(busy)return;const payload=Object.fromEntries(new FormData(form));
      if(root.dataset.channel.startsWith('dm:')){payload.mode='equal';payload.count='1';}
      payload.channel=root.dataset.channel;payload.confirm='yes';const signature=JSON.stringify(payload);
      if(!confirm('向当前聊天发送 '+payload.points+' 点'+(payload.kind==='transfer'?'转账':'红包')+'？将从你的额外点数中扣除。'))return;
      if(signature!==sendPayload){sendPayload=signature;requestId=nonce();}payload.request_id=requestId;
      busy=true;const button=form.querySelector('button[type=submit]');button.disabled=true;sendError.textContent='';
      try{const result=await request('/messages/points/send/',payload);root.dispatchEvent(new CustomEvent('point-gift-sent',{detail:result.message}));send.close();form.reset();sendPayload=null;requestId=null;}
      catch(error){sendError.textContent=error instanceof TypeError?'连接中断，请查看聊天记录后重试；重试同一份积分不会重复扣除。':error.message;}finally{busy=false;button.disabled=false;}
    });
    for(const [selector,refund] of [['[data-gift-claim]',false],['[data-gift-refund]',true]])detail.querySelector(selector).addEventListener('click',async event=>{
      if(busy||!id)return;if(refund&&!confirm('退回尚未领取的转账？点数将回到你的额外额度。'))return;
      busy=true;event.target.disabled=true;detailError.textContent='';try{paint(await request('/messages/points/'+id+(refund?'/':'/claim/'),{confirm:'yes',...(refund?{action:'refund'}:{})}));root.dispatchEvent(new CustomEvent('point-gift-updated'));}
      catch(error){detailError.textContent=error.message;}finally{busy=false;event.target.disabled=false;}
    });
  });
})();
