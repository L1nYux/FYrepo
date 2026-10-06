(() => {
  const owner=document.documentElement.dataset.resourceOwner;
  const applicable=url=>url.origin===location.origin&&/^\/(?:api-pool|finance|assistant)\//.test(url.pathname);
  const qualify=value=>{const url=new URL(value,location.href);if(owner&&applicable(url)&&!url.searchParams.has('ownership'))url.searchParams.set('ownership',owner);return url.href;};
  if(owner){
    const original=window.fetch.bind(window);window.fetch=(input,init)=>{if(input instanceof Request){const url=qualify(input.url);return original(url===input.url?input:new Request(url,input),init);}return original(qualify(input),init);};
    const fill=node=>{if(node.matches?.('form')){const url=new URL(node.action,location.href);if(applicable(url)&&!node.querySelector('[name=ownership]')){const field=document.createElement('input');field.type='hidden';field.name='ownership';field.value=owner;node.append(field);}}if(node.matches?.('a[href]'))node.href=qualify(node.href);};
    document.querySelectorAll('form,a[href]').forEach(fill);
    new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes){if(node.nodeType!==1)continue;fill(node);node.querySelectorAll('form,a[href]').forEach(fill);}}).observe(document.body,{subtree:true,childList:true});
  }
  document.querySelectorAll('[data-creation-owner]').forEach(select=>{
    const form=select.form,key='resource-creation:'+location.pathname;
    try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved){for(const field of form.elements){if(['text','textarea','number','url'].includes(field.type)&&field.name in saved)field.value=saved[field.name];}sessionStorage.removeItem(key);}}catch(_){}
    select.addEventListener('change',()=>{const draft={};for(const field of form.elements){if(['text','textarea','number','url'].includes(field.type)&&field.name)draft[field.name]=field.value;}try{sessionStorage.setItem(key,JSON.stringify(draft));}catch(_){}const url=new URL(location.href);url.searchParams.set('ownership',select.value);location.assign(url);});
  });
})();
