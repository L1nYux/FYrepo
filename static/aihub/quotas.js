(() => {
  const csrf=document.querySelector('#pool-connect-form [name=csrfmiddlewaretoken]')?.value;
  const date=value=>{const d=new Date(value);return Number.isNaN(d.getTime())?'':d.toLocaleString('zh-CN');};
  const amount=value=>Number(value).toLocaleString('zh-CN',{maximumFractionDigits:4});
  document.querySelectorAll('[data-quota-url]').forEach(card=>{
    const button=card.querySelector('[data-quota-refresh]'),kind=card.querySelector('[data-quota-kind]'),status=card.querySelector('[data-quota-status]');
    button.addEventListener('click',async()=>{
      if(button.disabled)return;button.disabled=true;kind.disabled=true;status.textContent='正在读取厂商额度…';
      try{
        const response=await fetch(card.dataset.quotaUrl,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify({kind:kind.value})});
        if(response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw Error('登录已失效，请重新登录。');
        const data=await response.json();if(!response.ok)throw Error(data.error||'暂时无法查询。');
        card.querySelector('[data-quota-note]').textContent=data.note;const value=card.querySelector('[data-quota-value]');
        value.replaceChildren();
        const line=(text,tag='p')=>{const row=document.createElement(tag);row.textContent=text;value.append(row);};
        if(data.value){
          if(data.value.balance!==undefined)line(amount(data.value.balance)+' '+data.value.currency);
          for(const window of data.value.windows||[]){let quota='暂不可用';if(window.unlimited)quota='不限';else if(window.remaining!==null)quota='剩余 '+amount(window.remaining)+(window.total!==null?' / '+amount(window.total):'');else if(window.remaining_percent!==null)quota='剩余 '+amount(window.remaining_percent)+'%';line(window.label+'：'+quota+(window.reset_at?' · 重置 '+date(window.reset_at):''));}
          line((data.stale?'上次结果 · ':'更新于 ')+date(data.value.updated_at),'small');
        }else line(data.supported?'尚未取得额度。':'请在官方后台查看。');
        status.textContent=data.error||(data.supported?'额度已更新。':'此连接无法仅凭模型 Key 查询。');
      }catch(error){status.textContent=error.message+'；已有结果保留。';}
      finally{button.disabled=false;kind.disabled=false;}
    });
  });
})();
