"""Participant-checked file cards and private, read-only previews."""
import io
import mimetypes
from pathlib import Path
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST


def card(item, kind='upload'):
    route={'upload':'personal_message_file','legacy':'personal_legacy_file','attachment':'attachment_download'}[kind]
    try:size=item.file.size
    except (OSError,ValueError):size=None
    suffix=Path(item.original_name).suffix.lower().lstrip('.')
    value={'id':item.pk,'kind':kind,'name':item.original_name,'url':reverse(route,args=[item.pk]),
           'preview_url':reverse('file_preview',args=[kind,item.pk]),'size':size,'type':suffix.upper() or 'FILE'}
    if kind=='attachment':
        from .message_scope import qualify
        value['url']=qualify(value['url'],item.workspace)
        value['preview_url']=qualify(value['preview_url'],item.workspace)
    return value


def authorized(request, kind, pk):
    # Reuse the download policy, including cleared, withdrawn and hidden records.
    from . import personal_messages, views
    from .models import MessageUpload, Attachment
    if kind not in ('upload','legacy','attachment'):raise Http404
    checker={'upload':personal_messages.upload_file,'legacy':personal_messages.legacy_file,'attachment':views.attachment_download}[kind]
    response=checker(request,pk)
    response.close()
    return get_object_or_404(MessageUpload if kind=='upload' else Attachment.all_objects,pk=pk)


@login_required
@never_cache
@require_GET
def preview(request,kind,pk):
    item=authorized(request,kind,pk)
    value=card(item,kind);suffix=Path(item.original_name).suffix.lower()
    rows=[];error='';format='unsupported'
    if suffix in ('.png','.jpg','.jpeg','.gif','.webp','.bmp'):format='image'
    elif suffix=='.pdf':format='pdf'
    elif suffix=='.docx':
        format='document'
        try:
            import zipfile
            from xml.etree import ElementTree as ET
            with item.file.open('rb') as stream, zipfile.ZipFile(stream) as archive:
                entry=archive.getinfo('word/document.xml')
                if entry.file_size>16*1024*1024:raise ValueError
                root=ET.fromstring(archive.read(entry))
                ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                body=root.find('w:body',ns)
                if body is None:raise ValueError('document body missing')
                for child in body:
                    if child.tag.endswith('}p'):
                        rows.append({'text':''.join(t.text or '' for t in child.findall('.//w:t',ns))})
                    elif child.tag.endswith('}tbl'):
                        rows.append({'table':[[''.join(t.text or '' for t in cell.findall('.//w:t',ns)) for cell in row.findall('w:tc',ns)] for row in child.findall('w:tr',ns)]})
        except (OSError,ValueError,zipfile.BadZipFile,KeyError,ET.ParseError):error='文档无法预览，请下载后用其他应用打开。'
    elif suffix in ('.txt','.csv','.md','.log'):
        format='text'
        with item.file.open('rb') as stream:
            raw=stream.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:error='文本过大，请下载后查看完整文件。'
        rows=[{'text':raw[:2*1024*1024].decode('utf-8',errors='replace')}]
    converted=None
    if suffix in ('.doc','.docx','.odt','.rtf'):
        from .office_preview import pdf_path, PreviewUnavailable
        try:
            converted=pdf_path(item);format='pdf';error=''
        except PreviewUnavailable as failure:
            if suffix!='.docx':error=str(failure)
    source=None;channel='';message_id=''
    if kind=='upload':
        if item.personal_id:
            row=item.personal;peer=row.recipient_id if row.sender_id==request.user.pk else row.sender_id
            source=reverse('personal_chat',args=[peer]);channel='person:'+str(peer);message_id=row.pk
        else:
            row=item.message;source=reverse('group_chat',args=[row.group_id]);channel='group:'+str(row.group_id);message_id=row.pk
    else:
        row=item.chat_message
        if row:
            if row.room=='private':
                peer=row.recipient_id if row.author_id==request.user.pk else row.author_id
                source=reverse('personal_chat',args=[peer]);channel='person:'+str(peer)
                message_id=row.personal_record.pk
            else:source='/messages/?room='+row.room+'&space='+str(item.workspace_id);channel='team:'+str(row.team_id);message_id=row.pk
    image_url=reverse('file_preview_content',args=[kind,pk])
    if kind=='attachment':
        from .message_scope import qualify
        image_url=qualify(image_url,item.workspace)
    from .models import AccountPreferences
    preferences,_=AccountPreferences.objects.get_or_create(user=request.user)
    saved=[kind,pk,getattr(item,'workspace_id',None)]
    pages=min(300,pdf_count(item,converted)) if format=='pdf' else 0
    if format=='pdf' and not pages:error='PDF 无法读取，请下载后用其他应用打开。'
    return render(request,'core/file_preview.html',{'file_card':value,'file_kind':format,'file_rows':rows,'preview_error':error,
        'favorite_url':reverse('file_favorite',args=[kind,pk])+('?space='+str(item.workspace_id) if kind=='attachment' else ''),
        'file_saved':saved in preferences.saved_files,
        'image_url':image_url,'image_page_url':image_url+('&' if '?' in image_url else '?'),'source_url':source,'source_channel':channel,'source_id':message_id,
        'pdf_pages':range(1,pages+1)})


def pdf_count(item,converted=None):
    from pypdf import PdfReader
    try:
        with (converted.open('rb') if converted else item.file.open('rb')) as stream:return len(PdfReader(stream).pages)
    except Exception:return 0


@login_required
@never_cache
@require_GET
def content(request,kind,pk):
    item=authorized(request,kind,pk)
    suffix=Path(item.original_name).suffix.lower()
    converted=None
    if suffix in ('.doc','.docx','.odt','.rtf'):
        from .office_preview import pdf_path, PreviewUnavailable
        try:converted=pdf_path(item)
        except PreviewUnavailable:raise Http404('文档无法预览')
    if (suffix=='.pdf' or converted) and request.GET.get('page'):
        raw=request.GET['page']
        if not raw.isascii() or not raw.isdigit() or not 1<=int(raw)<=300:raise Http404
        import pypdfium2
        try:
            with (converted.open('rb') if converted else item.file.open('rb')) as stream:
                document=pypdfium2.PdfDocument(stream.read())
            try:
                if int(raw)>len(document):raise Http404
                page=document[int(raw)-1]
                try:
                    # Bound render memory for oversized or malicious page dimensions.
                    scale=min(1.5,1800/max(page.get_size()))
                    bitmap=page.render(scale=scale)
                    try:
                        image=bitmap.to_pil();out=io.BytesIO();image.save(out,format='PNG');image.close()
                    finally:bitmap.close()
                finally:page.close()
            finally:document.close()
            return HttpResponse(out.getvalue(),content_type='image/png')
        except (ValueError,OSError,pypdfium2.PdfiumError):raise Http404('PDF 无法预览')
    if not converted and suffix not in ('.pdf','.png','.jpg','.jpeg','.gif','.webp','.bmp'):raise Http404
    response=FileResponse(converted.open('rb') if converted else item.file.open('rb'),as_attachment=False,filename=item.original_name,content_type='application/pdf' if converted else mimetypes.guess_type(item.original_name)[0] or 'application/octet-stream')
    response['X-Content-Type-Options']='nosniff'
    return response


@login_required
@require_POST
def favorite(request,kind,pk):
    from django.db import transaction
    from .models import AccountPreferences
    action=request.POST.get('action')
    if kind not in ('upload','legacy','attachment') or action not in ('add','remove'):
        return JsonResponse({'error':'文件操作无效。'},status=400)
    item=authorized(request,kind,pk) if action=='add' else None
    preference,_=AccountPreferences.objects.get_or_create(user=request.user)
    with transaction.atomic():
        preference=AccountPreferences.objects.select_for_update().get(pk=preference.pk)
        values=[entry for entry in preference.saved_files if entry[:2]!=[kind,pk]]
        if action=='add':
            if len(values)>=100:return JsonResponse({'error':'最多收藏 100 个文件，请先整理收藏。'},status=400)
            values.insert(0,[kind,pk,getattr(item,'workspace_id',None)])
        preference.saved_files=values;preference.save(update_fields=['saved_files'])
    return JsonResponse({'saved':action=='add'})


@login_required
@require_GET
def saved_files(request):
    from django.core.exceptions import PermissionDenied
    from .models import AccountPreferences
    preference,_=AccountPreferences.objects.get_or_create(user=request.user)
    values=[]
    for kind,pk,space in preference.saved_files[:100]:
        try:
            if kind=='attachment':
                from .message_scope import select
                select(request,space)
            values.append(card(authorized(request,kind,pk),kind))
        except (Http404,PermissionDenied):continue
    return render(request,'core/saved_files.html',{'files':values})
