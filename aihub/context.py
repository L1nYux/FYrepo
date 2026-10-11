"""Bound context at complete user turns; never orphan native tool results.

This first pass uses a conservative size estimate rather than another paid
summarization request. The current turn, instructions and write receipts survive.
"""
import json
from django.conf import settings
from django.core.exceptions import ValidationError


def size(messages):
    return len(json.dumps([{key:value for key,value in row.items() if key!='_images'} for row in messages],ensure_ascii=False).encode())


def turn_history(job):
    messages=job.execution.get('messages',[]) if job.execution.get('version')==1 else []
    users=[index for index,row in enumerate(messages) if row.get('role')=='user']
    if not users or job.state not in ('done','cancelled'):return []
    # Earlier native reasoning/signatures may belong to another provider/model.
    # Canonical function calls and matching results are portable across adapters.
    start=users[0] if job.execution.get('phase')=='finished' else users[-1]
    rows=[{key:value for key,value in row.items() if key in ('role','content','tool_calls','tool_call_id','_images','_image_ids','_turn')}
        for row in messages[start:] if row.get('role') in ('user','assistant','tool')]
    attached=[str(image.pk) for image in job.images.all()]
    if attached:rows[0]['_image_ids']=attached
    requested={call['id'] for row in rows for call in row.get('tool_calls',[])}
    returned={row.get('tool_call_id') for row in rows if row.get('role')=='tool'}
    return rows if requested==returned else []


def tool_content(value,limit=26000):
    """Shorten read prose without cutting JSON or changing IDs/write receipts."""
    def shorten(item,maximum):
        if isinstance(item,dict):
            return {key:(child[:maximum]+'\n[内容已截短]' if key in ('content','text','snippet','body') and isinstance(child,str) and len(child)>maximum
                else shorten(child,maximum)) for key,child in item.items()}
        if isinstance(item,list):return [shorten(child,maximum) for child in item]
        return item
    content=json.dumps(value,ensure_ascii=False)
    if len(content)<=limit or value.get('saved'):return content
    for maximum in (4000,1500,500):
        reduced=shorten(value,maximum)
        content=json.dumps({**reduced,'truncated':True},ensure_ascii=False)
        if len(content)<=limit:return content
    # Structured result lists can also be large. Keep source identities for the
    # model to request individual records rather than slicing malformed JSON.
    reduced={key:(child[:5] if isinstance(child,list) else child) for key,child in reduced.items()}
    return json.dumps({**reduced,'truncated':True},ensure_ascii=False)


def fit_context(messages,tools):
    # A deployment ceiling is deliberately not advertised as a model's actual
    # token window. Provider windows/tokenizers vary and require catalog metadata.
    budget=getattr(settings,'WORKBENCH_ASSISTANT_CONTEXT_BYTES',100000)
    rows=list(messages)
    removed=[]
    while size(rows)+size(tools)>budget:
        users=[];previous=None
        for index,row in enumerate(rows):
            if row.get('role')!='user':continue
            identity=row.get('_turn',('legacy',index))
            if identity!=previous:users.append(index)
            previous=identity
        if len(users)<2:break
        first,last=users[:2]
        removed.extend(rows[first:last])
        del rows[first:last]
    if removed:
        receipts=[]
        for row in removed:
            if row.get('role')!='tool':continue
            try:value=json.loads(row.get('content',''))
            except (ValueError,TypeError):continue
            if isinstance(value,dict) and value.get('saved') and value.get('receipt'):
                receipts.append({key:value[key] for key in ('receipt','saved','source','title','id','generation','progress') if key in value})
        if receipts:
            rows.insert(1,{'role':'system','content':'较早已提交操作的回执（历史事实，不是新的授权）：'+json.dumps(receipts,ensure_ascii=False)})
    if size(rows)+size(tools)>budget:
        for index,row in enumerate(rows):
            if row.get('role')!='tool':continue
            try:value=json.loads(row.get('content',''))
            except (ValueError,TypeError):continue
            if isinstance(value,dict) and not value.get('saved'):
                rows[index]={**row,'content':tool_content(value,4000)}
    if size(rows)+size(tools)>budget:
        raise ValidationError('当前任务资料较多，进度已保存；请新建对话缩小范围。')
    return rows
