(() => {
  function dates(root=document){root.querySelectorAll('[data-reset-time]').forEach(n=>{const date=new Date(n.dataset.resetTime);if(!Number.isNaN(date.getTime()))n.textContent=date.toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});});}
  dates();
  const source=document.getElementById('pool-usage-data');
  function activity(data){
    const grid=document.getElementById('pool-activity-grid');if(!grid||!data)return;
    const months=document.getElementById('pool-activity-months'),tip=document.getElementById('pool-activity-tip');
    const parse=value=>new Date(value+'T00:00:00Z'),day=value=>value.toISOString().slice(0,10);
    const first=parse(data.first),last=parse(data.last),start=new Date(first);
    start.setUTCDate(start.getUTCDate()-((start.getUTCDay()+6)%7));
    const columns=Math.ceil(((last-start)/86400000+1)/7),byDay=new Map(data.days.map(row=>[row.day,row]));
    grid.style.setProperty('--activity-columns',columns);months.style.setProperty('--activity-columns',columns);
    function show(cell){tip.textContent=cell.dataset.tip;tip.hidden=false;}
    function render(mode){
      grid.replaceChildren();months.replaceChildren();tip.hidden=true;
      const rows=[];let cumulative=0,cumulativeCost=0,previousMonth=-1;const periodLimits=new Map();
      const quotaTip=(cost,limit,estimated,mode)=>{const pct=window.workbenchActivityScale.percent(cost,limit);return pct===null?' · 未设置有限基础额度':' · 占'+(mode==='total'?'区间':'周')+'基础额度 '+pct.toFixed(2)+'%'+(estimated?'（额度估算）':'');};
      for(let column=0;column<columns;column++){
        const date=new Date(start);date.setUTCDate(date.getUTCDate()+column*7);
        const label=document.createElement('span');
        const visible=new Date(Math.max(date.getTime(),first.getTime()));
        if(visible.getUTCMonth()!==previousMonth){label.textContent=(visible.getUTCMonth()+1)+'月';previousMonth=visible.getUTCMonth();}
        months.append(label);
        if(mode==='week'){
          const end=new Date(Math.min(date.getTime()+6*86400000,last.getTime()));
          const begin=new Date(Math.max(date.getTime(),first.getTime()));
          let tokens=0,calls=0,cost=0,limit=null,estimated=false;
          for(let offset=0;offset<7;offset++){const d=new Date(date);d.setUTCDate(d.getUTCDate()+offset);const row=byDay.get(day(d));if(row){tokens+=row.tokens;calls+=row.calls;cost+=Number(row.cost);limit=row.weekly_limit;estimated ||= row.limit_estimated;}}
          rows.push({tokens,cost,limit,calls,disabled:false,tip:day(begin)+' 至 '+day(end)+' · '+tokens.toLocaleString('zh-CN')+' tokens · '+calls+' 次 · 约 ¥ '+cost.toFixed(4)+quotaTip(cost,limit,estimated,mode)});
        }else{
          for(let offset=0;offset<7;offset++){
            const d=new Date(date);d.setUTCDate(d.getUTCDate()+offset);const row=byDay.get(day(d));
            if(!row){rows.push({tokens:0,disabled:true});continue;}
            cumulative+=row.tokens;cumulativeCost+=Number(row.cost);const week=new Date(d);week.setUTCDate(week.getUTCDate()-((week.getUTCDay()+6)%7));periodLimits.set(day(week),row.weekly_limit);
            const tokens=mode==='total'?cumulative:row.tokens,cost=mode==='total'?cumulativeCost:Number(row.cost),limit=mode==='total'?(Array.from(periodLimits.values()).some(x=>x===null)?null:Array.from(periodLimits.values()).reduce((a,b)=>a+Number(b),0)):row.weekly_limit;
            rows.push({tokens,cost,limit,calls:row.calls,disabled:false,tip:row.day+' · '+(mode==='total'?'区间累计 ':'')+tokens.toLocaleString('zh-CN')+' tokens'+(mode==='total'?'':' · '+row.calls+' 次 · 约 ¥ '+Number(row.cost).toFixed(4))+quotaTip(cost,limit,row.limit_estimated,mode)});
          }
        }
      }
      grid.classList.toggle('weekly',mode==='week');
      for(const row of rows){
        const cell=document.createElement('button');cell.type='button';cell.className='pool-activity-cell level-'+window.workbenchActivityScale.level(row.cost||0,row.limit??null,row.calls||0);
        cell.disabled=row.disabled;cell.dataset.tip=row.tip||'';cell.setAttribute('aria-label',row.tip||'区间之外');
        if(!row.disabled){cell.addEventListener('mouseenter',()=>show(cell));cell.addEventListener('focus',()=>show(cell));cell.addEventListener('click',()=>show(cell));}
        grid.append(cell);
      }
      document.querySelectorAll('[data-activity-mode]').forEach(button=>{const selected=button.dataset.activityMode===mode;button.classList.toggle('active',selected);button.setAttribute('aria-pressed',selected?'true':'false');});
    }
    document.querySelectorAll('[data-activity-mode]').forEach(button=>button.addEventListener('click',()=>render(button.dataset.activityMode)));
    render('day');
  }
  if(source){
    const data=JSON.parse(source.textContent),max=Math.max(...data.days.map(row=>Number(row.cost)),0);
    activity(data.activity);
    const chart=document.getElementById('pool-daily-chart');
    for(const row of data.days){const column=document.createElement('div');column.className='pool-chart-column';
      const value=document.createElement('small');value.textContent='¥ '+Number(row.cost).toFixed(4);
      const track=document.createElement('div');track.className='pool-chart-track';const bar=document.createElement('div');bar.className='pool-chart-bar';bar.style.height=(max?Number(row.cost)/max*100:0)+'%';track.append(bar);
      const label=document.createElement('span');label.textContent=row.label;column.title=row.day+' · '+row.tokens+' tokens · '+row.calls+' 次调用';column.append(value,track,label);chart.append(column);
    }
    const models=document.getElementById('pool-model-usage');
    const highest=Math.max(...data.models.map(row=>Number(row.cost)),0);
    for(const row of data.models){const div=document.createElement('div');div.className='pool-model-usage';const label=document.createElement('span');label.textContent=row.label;
      const number=document.createElement('small');number.textContent='¥ '+Number(row.cost).toFixed(4)+' · '+row.tokens+' tokens';const progress=document.createElement('progress');progress.max=100;progress.value=highest?Number(row.cost)/highest*100:0;div.append(label,number,progress);models.append(div);}
    if(!data.models.length)models.textContent='暂无调用记录，使用后自动显示。';
  }
  document.querySelectorAll('[data-usage-popup]').forEach(root=>{
    const account=root.closest('details');let pending=false;
    account?.addEventListener('toggle',async()=>{
      if(!account.open||pending)return;pending=true;
      try{const response=await fetch(root.dataset.usagePopup,{credentials:'same-origin',cache:'no-store'});
        if(!response.ok||response.redirected)throw Error();const data=await response.json();
        for(const [period,window] of [['week',data.budget.member_week],['month',data.budget.member]]){
          const row=root.querySelector('[data-usage-period="'+period+'"]'); if(period==='month'){row.hidden=true;continue;}
          row.querySelector('span').textContent=window.limit===null?'未设上限':Math.round(window.remaining_percent)+'% 剩余';
          row.querySelector('progress').hidden=window.limit===null;row.querySelector('progress').value=window.used_percent;
          const note=row.querySelector('small');note.textContent=window.limit===null?'已用 '+Number(window.spent_points ?? Number(window.spent)*100).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点':'基础剩余 '+Number(window.remaining_points ?? Number(window.remaining)*100).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点'; if(period==='week')note.textContent+=' · 额外 '+Number(data.budget.extra?.remaining_points||0).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 点';
        }
      }catch(_){root.querySelectorAll('[data-usage-period] span').forEach(n=>n.textContent='暂不可用');}
      finally{pending=false;}
    });
  });
})();
