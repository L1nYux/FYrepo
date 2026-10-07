import {Editor} from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import {Table,TableRow,TableHeader,TableCell} from '@tiptap/extension-table';
import Image from '@tiptap/extension-image';
import {renderAsync} from 'docx-preview';
import ExcelJS from 'exceljs';
import * as pdfjs from 'pdfjs-dist';

const root=document.querySelector('[data-document-root]');
if(root){
 const data=JSON.parse(document.getElementById('document-data').textContent),status=root.querySelector('[data-save-status]'),area=root.querySelector('[data-document-content]');
 const csrf=document.querySelector('[name=csrfmiddlewaretoken]')?.value||'';
 let editor,officeEditor,generation=data.generation,dirty=false,flight=null,timer,editable=data.editable,stopped=false;
 const key=`document-draft:${location.origin}:${document.documentElement.dataset.account}:${data.document}:${data.draft}`;
 const announce=message=>{status.textContent=message;};
 async function post(url,body,json=true){const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':csrf,...(json?{'Content-Type':'application/json'}:{})},body:json?JSON.stringify(body):body});let value;try{value=await response.json();}catch(_){throw Error('登录或服务状态已变化，请保留内容后重新打开。');}if(!response.ok)throw Error(value.error||'操作未完成。');return value;}
 async function save(){
  clearTimeout(timer);if(flight){await flight;if(dirty)return save();return;}
  if(!dirty||!editable||!editor)return;
  const value=editor.getJSON();dirty=false;announce('正在保存…');
  flight=post(data.save,{generation,content:value}).then(result=>{generation=result.generation;data.generation=generation;announce(dirty?'还有修改待保存':'已保存');if(!dirty){try{localStorage.removeItem(key);}catch(_){}}}).catch(error=>{dirty=true;stopped=true;announce(error.message);throw error;}).finally(()=>{flight=null;});
  await flight;
 }
 if(data.kind==='online'){
  editor=new Editor({element:area,extensions:[StarterKit.configure({heading:{levels:[1,2,3]}}),Table.configure({resizable:true}),TableRow,TableHeader,TableCell,Image.configure({allowBase64:false})],content:data.content,editable,
   onUpdate(){if(!editable)return;dirty=true;try{localStorage.setItem(key,JSON.stringify({content:editor.getJSON(),generation}));}catch(_){}announce('修改待保存');clearTimeout(timer);if(!stopped)timer=setTimeout(()=>save().catch(()=>{}),900);}});
  if(editable){let recovered;try{recovered=JSON.parse(localStorage.getItem(key));}catch(_){}
   if(recovered?.content){const recovery=root.querySelector('[data-recover]');recovery.hidden=false;recovery.querySelector('button').onclick=()=>{editor.commands.setContent(recovered.content);dirty=true;announce('已恢复本机草稿，请检查后保存');recovery.hidden=true;};}
  }
  root.querySelectorAll('[data-editor-command]').forEach(button=>button.addEventListener('click',()=>{if(!editable)return;const chain=editor.chain().focus();const command=button.dataset.editorCommand;if(command==='table')chain.insertTable({rows:3,cols:3,withHeaderRow:true}).run();else if(command==='heading')chain.toggleHeading({level:2}).run();else if(command==='link'){const href=prompt('链接地址');if(href&&/^https?:\/\//i.test(href))chain.setLink({href}).run();}else chain[command]?.().run();}));
  root.querySelector('[data-editor-image]')?.addEventListener('change',async event=>{const upload=event.target.files[0];if(!upload)return;const body=new FormData();body.append('image',upload);try{const result=await post(data.image,body,false);editor.chain().focus().setImage({src:result.src}).run();}catch(error){announce(error.message);}event.target.value='';});
  root.querySelector('[data-save-now]')?.addEventListener('click',()=>{stopped=false;save().catch(()=>{});});
 }else{
  async function preview(){
   announce('正在打开文档…');const response=await fetch(data.file,{credentials:'same-origin'});if(!response.ok)throw Error('文件无法读取或权限已失效。');const bytes=await response.arrayBuffer();
   if(data.kind==='docx'){await renderAsync(bytes,area,undefined,{inWrapper:true,ignoreLastRenderedPageBreak:false});}
   else if(data.kind==='xlsx'){
    const workbook=new ExcelJS.Workbook();await workbook.xlsx.load(bytes);const tabs=document.createElement('nav');tabs.className='document-sheet-tabs';area.append(tabs);
    const sheetArea=document.createElement('div');sheetArea.className='document-sheet';area.append(sheetArea);
    const show=sheet=>{sheetArea.replaceChildren();const table=document.createElement('table');table.className='document-spreadsheet';
     const rows=Math.min(sheet.rowCount,1000),cols=Math.min(sheet.columnCount,100);for(let r=1;r<=rows;r++){const tr=document.createElement('tr');for(let c=1;c<=cols;c++){const cell=sheet.getCell(r,c),td=document.createElement('td');td.textContent=cell.text;td.title=`${cell.address}${cell.formula?' · '+cell.formula:''}`;if(cell.font?.bold)td.style.fontWeight='bold';tr.append(td);}table.append(tr);}sheetArea.append(table);if(sheet.rowCount>1000||sheet.columnCount>100){const p=document.createElement('p');p.textContent='预览显示前 1000 行、100 列；在线编辑器中可查看完整工作表。';sheetArea.append(p);}
     tabs.querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.sheet===sheet.name)));};
    workbook.eachSheet(sheet=>{const button=document.createElement('button');button.type='button';button.textContent=sheet.name;button.dataset.sheet=sheet.name;button.onclick=()=>show(sheet);tabs.append(button);});if(workbook.worksheets[0])show(workbook.worksheets[0]);
   }else if(data.kind==='pdf'){
    const asset=new URL(root.dataset.pdfWorker,location.href).href;pdfjs.GlobalWorkerOptions.workerSrc=asset;
    const base=new URL('./',asset);const pdf=await pdfjs.getDocument({data:bytes,cMapUrl:new URL('cmaps/',base).href,cMapPacked:true,standardFontDataUrl:new URL('standard_fonts/',base).href,wasmUrl:new URL('wasm/',base).href,isEvalSupported:false}).promise;
    const toolbar=document.createElement('nav');toolbar.className='document-pdf-tools';const previous=document.createElement('button'),next=document.createElement('button'),label=document.createElement('span');previous.textContent='上一页';next.textContent='下一页';toolbar.append(previous,label,next);const canvas=document.createElement('canvas');area.append(toolbar,canvas);let number=1,busy=false;
    async function render(){if(busy)return;busy=true;previous.disabled=next.disabled=true;const page=await pdf.getPage(number),viewport=page.getViewport({scale:1.4});canvas.width=viewport.width;canvas.height=viewport.height;await page.render({canvasContext:canvas.getContext('2d'),viewport}).promise;label.textContent=`${number} / ${pdf.numPages}`;previous.disabled=number===1;next.disabled=number===pdf.numPages;busy=false;root.querySelector('[name=anchor]')?.setAttribute('placeholder',`第 ${number} 页或对应位置（可选）`);}
    previous.onclick=()=>{number--;render();};next.onclick=()=>{number++;render();};await render();
   }
   announce('文档已打开');
  }
  const officeRoot=root.querySelector('[data-office-host]');
  if(officeRoot){fetch(root.dataset.officeConfig,{credentials:'same-origin'}).then(async response=>{const result=await response.json();if(!response.ok)throw Error(result.error);const script=document.createElement('script');script.src=result.script;script.onload=()=>{area.hidden=true;officeEditor=new window.DocsAPI.DocEditor(officeRoot.id,{...result.config,height:'100%',events:{onDocumentReady:()=>announce(editable?'正在编辑修改稿':'正式版本 · 只读'),onError:()=>announce('文档服务未能完成操作，请保留页面并重试。')}});};script.onerror=()=>{announce('在线编辑服务未连接，正在打开应用内预览。');officeRoot.hidden=true;preview().catch(error=>announce(error.message));};document.head.append(script);}).catch(error=>{officeRoot.hidden=true;announce(error.message);preview().catch(error=>announce(error.message));});}
  else preview().catch(error=>announce(error.message));
 }
 root.querySelectorAll('[data-document-action-form]').forEach(form=>form.addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter;let body=new FormData(form);if(button?.name)body.append(button.name,button.value);if(button)button.disabled=true;
  try{
   if(['submit','rebase'].includes(body.get('action'))&&data.kind==='online')await save();
   if(body.get('action')==='submit'&&data.kind!=='online'){
    if(!root.dataset.forceSave)throw Error('在线编辑服务尚未启用，暂不能提交修改稿。');
    announce('正在保存文档…');const token=await post(root.dataset.forceSave,new FormData(),false);let saved=token.saved;
    for(let attempt=0;!saved&&attempt<20;attempt++){await new Promise(resolve=>setTimeout(resolve,1000));const response=await fetch(data.state+'?draft='+data.draft);if(!response.ok)throw Error('权限或登录状态已变化。');const state=await response.json();saved=state.save_completed===token.save_requested;generation=state.generation;}
    if(!saved)throw Error('保存尚未完成，请稍后再提交。');
    body.set('office_save',token.save_requested);
    const current=await fetch(data.state+'?draft='+data.draft,{credentials:'same-origin'});if(!current.ok)throw Error('权限或登录状态已变化。');generation=(await current.json()).generation;
   }
   if(data.draft)body.set('generation',String(generation));
   const response=await fetch(form.action,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':csrf},body});
   if(!response.ok){const value=await response.json();throw Error(value.error||'操作未完成。');}
   if(response.redirected){if(!dirty){try{localStorage.removeItem(key);}catch(_){}}location.href=response.url;}else location.reload();
  }catch(error){announce(error.message);}finally{if(button)button.disabled=false;}
 }));
 document.addEventListener('selectionchange',()=>{const selection=window.getSelection();if(selection?.anchorNode&&area.contains(selection.anchorNode)){const input=root.querySelector('[name=anchor]');if(input)input.value=selection.toString().slice(0,300);}});
 window.addEventListener('beforeunload',event=>{if(dirty||flight){event.preventDefault();event.returnValue='';}});
 if(data.draft)setInterval(async()=>{try{const response=await fetch(data.state+'?draft='+data.draft,{credentials:'same-origin'});if(!response.ok)throw Error('权限或登录状态已变化。');const state=await response.json();if(editable&&!state.editable){editable=false;editor?.setEditable(false);officeEditor?.destroyEditor();root.querySelector('.document-office')?.replaceChildren();announce('修改稿已提交或编辑权限已撤销。');}}catch(error){editable=false;editor?.setEditable(false);officeEditor?.destroyEditor();root.querySelector('.document-office')?.replaceChildren();announce(error.message);}},10000);
}
