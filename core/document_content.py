"""Validate structured editor data without storing arbitrary executable HTML."""
import json
from urllib.parse import urlsplit
from django.core.exceptions import ValidationError

EMPTY = {'type':'doc','content':[{'type':'paragraph'}]}
NODES = {'doc','paragraph','text','heading','bulletList','orderedList','listItem','blockquote','codeBlock','hardBreak','horizontalRule','table','tableRow','tableHeader','tableCell','image'}
MARKS = {'bold','italic','strike','underline','code','link'}
ATTRS = {'heading':{'level'},'orderedList':{'start'},'codeBlock':{'language'},'tableCell':{'colspan','rowspan','colwidth'},'tableHeader':{'colspan','rowspan','colwidth'},'image':{'src','alt','title'},'inlineMath':{'latex'},'blockMath':{'latex'}}


def clean(value, document_id=None):
    if not isinstance(value,dict) or value.get('type')!='doc':raise ValidationError('文档格式无效。')
    if len(json.dumps(value,ensure_ascii=False).encode())>1024*1024:raise ValidationError('文档内容超过 1 MB，请拆分章节。')
    count=0
    def walk(node, depth=0):
        nonlocal count
        count+=1
        if depth>30 or count>30000 or not isinstance(node,dict) or node.get('type') not in NODES:raise ValidationError('文档结构无效。')
        kind=node['type'];out={'type':kind}
        if kind=='text':
            if not isinstance(node.get('text'),str) or not node['text']:raise ValidationError('文字内容无效。')
            out['text']=node['text']
        attrs=node.get('attrs') or {}
        if not isinstance(attrs,dict):raise ValidationError('文档属性无效。')
        selected={key:val for key,val in attrs.items() if key in ATTRS.get(kind,set())}
        if kind=='image':
            src=selected.get('src','')
            if not isinstance(src,str) or not src.startswith(f'/documents/{document_id}/images/') or not src.endswith('/'):raise ValidationError('图片必须上传到本份文档。')
            if not src[len(f'/documents/{document_id}/images/'):-1].isdigit():raise ValidationError('图片地址无效。')
        if kind=='heading' and selected.get('level') not in (1,2,3):raise ValidationError('标题级别无效。')
        if kind in ('inlineMath','blockMath') and (not isinstance(selected.get('latex'),str) or len(selected['latex'])>5000):raise ValidationError('公式无效。')
        for key in ('colspan','rowspan','start'):
            if key in selected and (type(selected[key]) is not int or not 1<=selected[key]<=1000):raise ValidationError('表格或列表属性无效。')
        if 'colwidth' in selected and selected['colwidth'] is not None and (not isinstance(selected['colwidth'],list) or len(selected['colwidth'])>1000 or any(type(x) is not int or not 1<=x<=10000 for x in selected['colwidth'])):raise ValidationError('表格宽度无效。')
        for key in ('alt','title','language'):
            if key in selected and (not isinstance(selected[key],str) or len(selected[key])>1000):raise ValidationError('文档属性无效。')
        if selected:out['attrs']=selected
        if 'marks' in node:
            if not isinstance(node['marks'],list) or len(node['marks'])>10:raise ValidationError('文字格式无效。')
            out['marks']=[]
            for mark in node['marks']:
                if not isinstance(mark,dict) or mark.get('type') not in MARKS:raise ValidationError('文字格式无效。')
                item={'type':mark['type']}
                if item['type']=='link':
                    link_attrs=mark.get('attrs',{})
                    if not isinstance(link_attrs,dict):raise ValidationError('链接格式无效。')
                    href=link_attrs.get('href','')
                    if not isinstance(href,str) or len(href)>2000 or urlsplit(href).scheme not in ('https','http','mailto'):raise ValidationError('链接地址无效。')
                    item['attrs']={'href':href,'target':'_blank','rel':'noopener noreferrer'}
                out['marks'].append(item)
        if 'content' in node:
            if not isinstance(node['content'],list):raise ValidationError('文档内容无效。')
            out['content']=[walk(child,depth+1) for child in node['content']]
        return out
    return walk(value)


def text(value):
    if not isinstance(value,dict):return ''
    return value.get('text','') + ('\n' if value.get('type') in ('paragraph','heading','tableRow','hardBreak') else '') + ''.join(text(child) for child in value.get('content',[]))
