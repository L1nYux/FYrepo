"""ONLYOFFICE integration; callbacks can only save an authorized editable draft."""
import json
import uuid
from datetime import timedelta
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse, FileResponse, Http404
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from .models import SharedDocument, DocumentDraft, DocumentVersion, OfficeEditingSession
from . import document_permissions as access
from .documents import get_document, lock_document, handled, validate_file


def configured():
    return bool(settings.WORKBENCH_OFFICE_URL and settings.WORKBENCH_OFFICE_SECRET and settings.WORKBENCH_PUBLIC_URL)


def jwt_encode(value):
    import jwt
    return jwt.encode(value,settings.WORKBENCH_OFFICE_SECRET,algorithm='HS256')


def public(path):
    return settings.WORKBENCH_PUBLIC_URL.rstrip('/')+path


def session_permitted(session):
    return not session.closed and session.expires_at>timezone.now() and access.draft_editable(session.user,session.draft)


@login_required
@never_cache
@handled
def config(request,pk):
    if not configured():return JsonResponse({'error':'Word 和 Excel 在线编辑服务尚未启用。'},status=503)
    document=get_document(request,pk)
    if document.kind not in ('docx','xlsx'):raise ValidationError('此文件不使用 Office 编辑器。')
    draft=None;version=document.current;session=None
    if request.GET.get('draft'):
        draft=get_object_or_404(DocumentDraft,document=document,pk=request.GET['draft'])
        if not access.draft_visible(request.user,draft):raise PermissionDenied
    elif request.GET.get('version'):version=get_object_or_404(DocumentVersion,document=document,pk=request.GET['version'])
    editable=bool(draft and access.draft_editable(request.user,draft))
    if editable:
        with transaction.atomic():
            document=lock_document(request,pk);draft.refresh_from_db()
            if not access.draft_editable(request.user,draft):raise PermissionDenied
            session=draft.office_sessions.filter(user=request.user,closed=False,expires_at__gt=timezone.now()).first()
            if not session:session=OfficeEditingSession.objects.create(draft=draft,user=request.user,generation=draft.generation,expires_at=timezone.now()+timedelta(hours=12))
        key=str(session.key)
    else:key=f'view-{document.pk}-{draft.pk if draft else version.pk}-{draft.generation if draft else version.number}'
    token=signing.dumps({'document':document.pk,'user':request.user.pk,'draft':draft.pk if draft else None,'version':None if draft else version.pk,'session':session.pk if session else None},salt='office-file')
    file_url=public(reverse('office_file'))+'?token='+token
    value={'documentType':'word' if document.kind=='docx' else 'cell','type':'desktop',
        'document':{'fileType':document.kind,'key':key,'title':document.title+'.'+document.kind,'url':file_url,
            'permissions':{'edit':editable,'comment':False,'review':False,'download':False,'print':True}},
        'editorConfig':{'mode':'edit' if editable else 'view','lang':'zh-CN','user':{'id':str(request.user.pk),'name':request.user.first_name or request.user.username},
            'customization':{'autosave':True,'forcesave':True,'goback':{'url':public(reverse('document_detail',args=[pk]))}}}}
    if session:value['editorConfig']['callbackUrl']=public(reverse('office_callback',args=[session.key]))
    value['token']=jwt_encode(value)
    return JsonResponse({'config':value,'script':settings.WORKBENCH_OFFICE_URL.rstrip('/')+'/web-apps/apps/api/documents/api.js','session':str(session.key) if session else None})


@never_cache
def file(request):
    from django.contrib.auth import get_user_model
    try:data=signing.loads(request.GET.get('token',''),salt='office-file',max_age=12*60*60)
    except signing.BadSignature:raise Http404
    user=get_object_or_404(get_user_model(),pk=data['user'],is_active=True)
    document=get_object_or_404(access.visible(user),pk=data['document'])
    if data.get('draft'):
        row=get_object_or_404(DocumentDraft,pk=data['draft'],document=document)
        if not access.draft_visible(user,row):raise Http404
        if data.get('session'):
            session=get_object_or_404(OfficeEditingSession,pk=data['session'],draft=row,user=user)
            if not session_permitted(session):raise Http404
    else:row=get_object_or_404(DocumentVersion,pk=data['version'],document=document)
    if not row.file:raise Http404
    return FileResponse(row.file.open('rb'),filename=document.title+'.'+document.kind)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def office_request(url,data=None):
    expected=urlsplit(settings.WORKBENCH_OFFICE_URL);location=urlsplit(url)
    if location.scheme not in ('https','http') or location.scheme!=expected.scheme or location.netloc!=expected.netloc or location.username or location.password or location.fragment:raise ValidationError('文档服务返回了无效的保存地址。')
    headers={'Content-Type':'application/json'}
    payload=json.dumps(data).encode() if data is not None else None
    with build_opener(NoRedirect()).open(Request(url,data=payload,headers=headers),timeout=30) as response:
        body=response.read(20*1024*1024+1)
        if len(body)>20*1024*1024:raise ValidationError('文档超过 20 MB。')
        return body


@csrf_exempt
@require_POST
def callback(request,key):
    if not configured():return JsonResponse({'error':1},status=503)
    import jwt
    try:
        body=json.loads(request.body)
        if not isinstance(body,dict):raise ValueError
        token=body.get('token') or request.headers.get('Authorization','').removeprefix('Bearer ')
        signed=jwt.decode(token,settings.WORKBENCH_OFFICE_SECRET,algorithms=['HS256'])
        data=signed.get('payload',signed)
        if not isinstance(data,dict) or any(value!=data.get(name) for name,value in body.items() if name!='token'):raise ValueError
        session=get_object_or_404(OfficeEditingSession.objects.select_related('user','draft__document__workspace'),key=key)
        if data.get('key')!=str(session.key) or not session_permitted(session):raise PermissionDenied
        status=data.get('status')
        if status in (1,4):
            if status==4:OfficeEditingSession.objects.filter(pk=session.pk).update(closed=True)
            return JsonResponse({'error':0})
        if status not in (2,6):return JsonResponse({'error':1})
        blob=office_request(data['url']);kind=session.draft.document.kind
        validate_file(SimpleUploadedFile('draft.'+kind,blob),kind)
        with transaction.atomic():
            SharedDocument.objects.filter(pk=session.draft.document_id).update(updated_at=F('updated_at'))
            session.refresh_from_db();draft=DocumentDraft.objects.get(pk=session.draft_id);session.draft=draft
            if not session_permitted(session) or draft.generation!=session.generation:raise PermissionDenied
            if data.get('userdata') and str(session.save_requested)!=data['userdata']:return JsonResponse({'error':0})
            draft.file.save('draft.'+kind,ContentFile(blob),save=False);draft.generation+=1;draft.save(update_fields=['file','generation','updated_at'])
            session.generation=draft.generation
            if status==2:session.closed=True
            userdata=data.get('userdata')
            if userdata and session.save_requested and userdata==str(session.save_requested):session.save_completed=session.save_requested
            session.save()
        return JsonResponse({'error':0})
    except (jwt.InvalidTokenError,ValueError,KeyError,TypeError,PermissionDenied,ValidationError,Http404,OSError):
        return JsonResponse({'error':1},status=403)


@login_required
@require_POST
@handled
def force_save(request,pk,draft_pk):
    with transaction.atomic():
        document=lock_document(request,pk);draft=get_object_or_404(DocumentDraft,document=document,pk=draft_pk)
        if not access.draft_editable(request.user,draft):raise PermissionDenied
        session=get_object_or_404(OfficeEditingSession,draft=draft,user=request.user,closed=False,expires_at__gt=timezone.now())
        nonce=uuid.uuid4();session.save_requested=nonce;session.save(update_fields=['save_requested'])
    data={'c':'forcesave','key':str(session.key),'userdata':str(nonce)};data['token']=jwt_encode(data)
    try:result=json.loads(office_request(settings.WORKBENCH_OFFICE_URL.rstrip('/')+'/coauthoring/CommandService.ashx',data))
    except (OSError,ValueError):raise ValidationError('文档服务暂时无法保存，请保留页面后重试。') from None
    if result.get('error')==4:
        OfficeEditingSession.objects.filter(pk=session.pk,save_requested=nonce).update(save_completed=nonce)
    elif result.get('error')!=0:raise ValidationError('文档服务尚未完成保存，请稍后重试。')
    return JsonResponse({'save_requested':str(nonce),'saved':result.get('error')==4})
