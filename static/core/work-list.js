/* Fixed list components. Navigation requests data; record actions keep their own pages. */
(() => {
  'use strict';
  const root=document.querySelector('[data-work-list]'),runtime=window.zhiyuRuntime;
  if(!root||!runtime)return;
  runtime.mount('work-list',root,scope=>{
    const form=root.querySelector('[data-work-filters]'),items=root.querySelector('[data-work-items]');
    const status=root.querySelector('[data-work-status]'),title=root.querySelector('[data-work-title]');
    const lookup=scope.latest(),account=document.documentElement.dataset.account;
    const paths={projects:root.dataset.projectsUrl,tasks:root.dataset.tasksUrl};
    let current,epoch=0,searchTimer,scrollTimer;
    const node=(tag,text,cls)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;if(cls)value.className=cls;return value;};
    const kindOf=url=>Object.keys(paths).find(kind=>url.origin===location.origin&&url.pathname===paths[kind]);
    const field=name=>form.elements.namedItem(name);
    const link=(text,address,cls)=>{const value=node('a',text,cls);const url=new URL(address,location.href);if(url.origin!==location.origin)throw Error('列表链接不属于当前服务。');value.href=url.href;return value;};
    function options(select,choices,first){select.replaceChildren(new Option(first,''));for(const choice of choices)select.append(new Option(choice.name,choice.id));}
    function controls(kind,filters,spaces,statuses){
      root.dataset.kind=kind;title.textContent=kind==='projects'?'项目管理':'任务';
      root.querySelector('[data-work-description]').textContent=kind==='projects'?'查看项目负责人、状态与整体进度。':'按负责人、类型和状态找到要推进的工作。';
      const create=root.querySelector('[data-work-create]');create.textContent=kind==='projects'?'＋ 新建项目':'＋ 新建任务';create.hidden=true;
      if(spaces){options(field('ownership'),[{id:'all',name:'全部团队'},...spaces],'选择归属');field('ownership').options[0].remove();}
      if(statuses)options(field('status'),statuses,'全部状态');
      field('ownership').value=filters.ownership;field('q').value=filters.q;field('mine').checked=filters.mine;
      field('status').value=filters.status;field('category').hidden=kind==='projects';field('category').disabled=kind==='projects';field('category').value=filters.category;
      field('q').placeholder=kind==='projects'?'搜索项目':'搜索任务、项目或比赛';
      for(const tab of root.querySelectorAll('[data-work-tab]')){
        const selected=tab.dataset.workTab===kind;tab.classList.toggle('active',selected);
        if(selected)tab.setAttribute('aria-current','page');else tab.removeAttribute('aria-current');
        tab.href=paths[tab.dataset.workTab]+'?ownership='+encodeURIComponent(filters.ownership);
      }
      for(const tab of document.querySelectorAll('.shell-nav-item')){
        if(kindOf(new URL(tab.href,location.href)))tab.classList.toggle('selected',new URL(tab.href).pathname===paths[kind]);
      }
    }
    function cards(data){
      const grid=node('div',undefined,'cards');
      for(const row of data.items){
        const card=link('',row.url,'project-card'),head=node('div',undefined,'card-head');
        head.append(node('h3',row.title),node('small',row.ownership,'ownership-tag'),node('span',row.status_label,'badge '+row.status));
        const bar=node('div',undefined,'progress large');bar.setAttribute('role','img');bar.setAttribute('aria-label','项目进度 '+row.progress+'%');const fill=node('span');fill.style.width=Math.max(0,Math.min(100,Number(row.progress)||0))+'%';bar.append(fill);
        const meta=node('p',undefined,'project-meta');meta.append(node('strong',row.progress+'%'),node('span','未结项任务 '+row.open_tasks+' 个'));
        card.append(head,node('p','负责人：'+row.owner+(row.participant?' · 我是成员':''),'muted'),bar,meta);grid.append(card);
      }
      if(!data.items.length)grid.append(node('p','没有符合条件的项目。','empty'));return grid;
    }
    function table(data){
      const section=node('section',undefined,'card table-card task-list-table'),table=node('table'),head=node('thead'),labels=['任务','项目 / 比赛','负责人','截止日期','进度','状态'],tr=node('tr');
      labels.forEach(label=>tr.append(node('th',label)));head.append(tr);const body=node('tbody');
      for(const row of data.items){
        const tr=node('tr'),cells=labels.map(label=>{const td=node('td'),content=node('div',undefined,'work-list-cell-content');td.dataset.label=label;td.append(content);tr.append(td);return content;});
        cells[0].append(link(row.title,row.url,'strong'),node('br'),node('small',row.level+' · '+row.category_label));
        cells[1].append(link(row.project,row.project_url));if(row.competition){const small=node('small');small.append(link(row.competition,row.competition_url));cells[1].append(node('br'),small);}cells[1].append(node('br'),node('small',row.ownership,'ownership-tag'));
        cells[2].textContent=row.owner||'—';cells[3].textContent=row.due_date;if(row.overdue)cells[3].append(node('br'),node('small','已逾期','danger-text'));
        cells[4].textContent=row.progress+'%';cells[5].append(node('span',row.status_label,'badge '+row.status));body.append(tr);
      }
      if(!data.items.length){const tr=node('tr'),td=node('td','没有符合条件的任务。','empty');td.colSpan=6;tr.append(td);body.append(tr);}
      table.append(head,body);section.append(table);return section;
    }
    function paint(data,renderItems=true){
      if(data.contract!=='work-list-v1'||data.account!==account||!paths[data.kind]||!Array.isArray(data.items))throw Error('服务器需要同步升级才能使用此列表。');
      current=data;controls(data.kind,data.filters,data.spaces,data.statuses);
      const create=root.querySelector('[data-work-create]');create.href=data.create_url;create.hidden=!data.can_create;
      if(renderItems)items.replaceChildren(data.kind==='projects'?cards(data):table(data));items.removeAttribute('aria-busy');
      status.textContent=data.pagination.total+(data.kind==='projects'?' 个项目':' 个任务');
      const pagination=root.querySelector('[data-work-pagination]');pagination.hidden=data.pagination.pages<=1;
      root.querySelector('[data-work-page]').textContent='第 '+data.pagination.number+' / '+data.pagination.pages+' 页';
      for(const [selector,address] of [['[data-work-prev]',data.pagination.previous],['[data-work-next]',data.pagination.next]]){const button=root.querySelector(selector);button.hidden=!address;button.href=address||'#';}
    }
    function snapshot(){history.replaceState({...history.state,zhiyuWorkList:true,scrollY:scrollY},'',location.href);}
    function parsed(url,kind){return {ownership:url.searchParams.get('ownership')||current.filters.ownership,q:url.searchParams.get('q')||'',mine:url.searchParams.get('mine')==='1'||kind==='projects'&&url.searchParams.get('scope')==='mine',category:kind==='tasks'?(url.searchParams.get('category')||''):'',status:url.searchParams.get('status')||''};}
    async function navigate(address,{push=true,restore=false}={}){
      const url=new URL(address,location.href),kind=kindOf(url);if(!kind)return;
      clearTimeout(searchTimer);const token=++epoch,oldKind=root.dataset.kind,restoreY=restore?Number(history.state?.scrollY)||0:0;
      if(!url.searchParams.has('ownership'))url.searchParams.set('ownership',current.filters.ownership);
      if(push){snapshot();if(url.href!==location.href)history.pushState({zhiyuWorkList:true,scrollY:0},'',url.href);}
      controls(kind,parsed(url,kind),null,kind===current.kind?current.statuses:kind==='projects'?[{id:'active',name:'进行中'},{id:'paused',name:'已暂停'},{id:'closed',name:'已结项'}]:[{id:'open',name:'进行中'},{id:'submitted',name:'待审核'},{id:'completed',name:'已结项'}]);
      items.setAttribute('aria-busy','true');items.replaceChildren(node('p','正在读取…','work-list-loading'));status.textContent='';root.querySelector('[data-work-pagination]').hidden=true;
      try{
        const data=await lookup.run(async signal=>{
          const read=()=>runtime.query(url.href,{signal,headers:{'X-Zhiyu-Component':'work-list-v1'}});
          try{return await read();}catch(error){if(error.name==='AbortError'&&!signal.aborted)return read();throw error;}
        });
        if(token!==epoch)return;paint(data);
        history.replaceState({...history.state,zhiyuWorkList:true},'',data.url);
        if(restore)window.scrollTo({top:restoreY,behavior:'instant'});
        else if(oldKind!==kind){title.focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});}
      }catch(error){
        if(token!==epoch||!scope.alive())return;
        items.removeAttribute('aria-busy');items.replaceChildren();status.textContent=error.name==='AbortError'?'数据已变化，请重新读取。':error.message;
        const retry=node('button','重新读取','button');retry.type='button';retry.onclick=()=>navigate(url.href,{push:false,restore:true});items.append(retry);
      }
    }
    function submit(){const url=new URL(paths[root.dataset.kind],location.href);for(const [name,value] of new FormData(form)){if(value)url.searchParams.set(name,value);}navigate(url.href);}
    scope.on(form,'submit',event=>{event.preventDefault();submit();});
    scope.on(form,'change',event=>{if(event.target.matches('select,input[type=checkbox]'))submit();});
    scope.on(field('q'),'input',()=>{lookup.cancel();epoch++;clearTimeout(searchTimer);searchTimer=setTimeout(submit,250);});
    scope.on(document,'click',event=>{
      if(event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
      const anchor=event.target.closest('a[href]');if(!anchor||anchor.download||anchor.target&&anchor.target!=='_self')return;
      const url=new URL(anchor.href,location.href);if(!kindOf(url))return;
      event.preventDefault();navigate(url.href);
    });
    scope.on(window,'popstate',()=>{if(kindOf(new URL(location.href)))navigate(location.href,{push:false,restore:true});else location.reload();});
    scope.on(window,'pageshow',event=>{if(event.persisted)navigate(location.href,{push:false,restore:true});});
    scope.on(document,'visibilitychange',()=>{if(!document.hidden)navigate(location.href,{push:false,restore:true});});
    scope.on(window,'scroll',()=>{clearTimeout(scrollTimer);scrollTimer=setTimeout(snapshot,150);},{passive:true});
    scope.cleanup(()=>{clearTimeout(searchTimer);clearTimeout(scrollTimer);});
    try{paint(JSON.parse(document.getElementById('work-list-data').textContent),false);snapshot();}
    catch(error){status.textContent=error.message;}
  });
})();
