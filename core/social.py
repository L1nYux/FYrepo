from .tenancy import team_users, membership_for, active_member
"""Member cards and private, verified sticker assets."""
import io
from urllib.parse import quote
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db.models import Q
from django.http import JsonResponse, FileResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from . import permissions as perms
from .models import Sticker, PublicProfile, ChatMessage
from .avatars import avatar_url
from .messages import visible_messages


def require_member(user):
    if not perms.is_team_member(user): raise PermissionDenied


@login_required
@require_GET
def member(request, pk):
    require_member(request.user)
    users = team_users(include_inactive=True, include_deleted=True).select_related('member_profile')
    if not perms.is_admin(request):
        users = users.filter(pk__in=team_users(include_inactive=True, include_deleted=True, member_only=True).values('pk'))
    user = get_object_or_404(users, pk=pk)
    membership = membership_for(user)
    profile = PublicProfile.objects.filter(user=user, is_public=True).first()
    return JsonResponse({'id': user.pk, 'username': user.username, 'name': user.first_name,
        'avatar_url': avatar_url(user), 'initial': user.username[:1].upper(),
        'role': '已离开团队' if membership.deleted_at else perms.role_label(perms.account_role(user)), 'active': active_member(user),
        'display_name': (profile.display_name if profile else '') or user.first_name or user.username,
        'projects': [{'name': p.name, 'url': reverse('project_detail', args=[p.pk])}
                     for p in user.owned_projects.filter(archived_at__isnull=True).order_by('name', 'pk')[:12]] if perms.is_team_member(user) else [],
        'manage_url': reverse('members') + '?q=' + quote(user.username) if perms.is_admin(request) and not membership.deleted_at else '',
        'research_area': profile.research_area if profile else '', 'bio': profile.bio if profile else '',
        'self': user.pk == request.user.pk,
        'chat_url': reverse('profile') if user.pk == request.user.pk else (reverse('messages_private', args=[user.pk]) if user.is_active and perms.is_team_member(user) else '')})


def accessible(user):
    messages = visible_messages(user, ChatMessage.objects.filter(Q(room__in=['developers','public']) | Q(room='private',author=user) | Q(room='private',recipient=user)))
    return Sticker.objects.filter(Q(created_by=user) | Q(favorites=user) | Q(messages__in=messages)).distinct()


def card(sticker):
    return {'id': sticker.pk, 'name': sticker.name, 'url': reverse('sticker_file', args=[sticker.pk])}


@login_required
@require_http_methods(['GET','POST'])
def stickers(request):
    require_member(request.user)
    if request.method == 'GET':
        return JsonResponse({'stickers': [card(s) for s in request.user.favorite_stickers.all()[:200]]})
    action = request.POST.get('action')
    if action in ('favorite','remove'):
        raw = request.POST.get('id','')
        if not raw.isascii() or not raw.isdigit() or len(raw)>18: return JsonResponse({'error':'表情编号无效。'},status=400)
        sticker = get_object_or_404(accessible(request.user), pk=int(raw))
        if action == 'remove': sticker.favorites.remove(request.user)
        elif request.user.favorite_stickers.count()<200: sticker.favorites.add(request.user)
        else: return JsonResponse({'error':'最多收藏 200 个表情。'},status=400)
        return JsonResponse(card(sticker))
    upload = request.FILES.get('file')
    if not upload or upload.size>5*1024*1024: return JsonResponse({'error':'请选择不超过 5 MB 的图片或 GIF。'},status=400)
    if request.user.favorite_stickers.count()>=200: return JsonResponse({'error':'最多收藏 200 个表情。'},status=400)
    try:
        raw=upload.read(5*1024*1024+1)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('PNG','JPEG','WEBP','GIF') or image.width*image.height*getattr(image,'n_frames',1)>16000000: raise ValueError
            if getattr(image,'n_frames',1)>60: raise ValueError
            frames=[];durations=[]
            for frame in ImageSequence.Iterator(image):
                value=ImageOps.exif_transpose(frame).convert('RGBA');value.thumbnail((512,512))
                frames.append(value.copy());durations.append(max(20,min(10000,frame.info.get('duration',100))))
            buffer=io.BytesIO()
            if len(frames)>1:
                frames[0].save(buffer,format='GIF',save_all=True,append_images=frames[1:],duration=durations,loop=0,disposal=2)
                mime='image/gif';ext='gif'
            else:
                frames[0].save(buffer,format='WEBP',quality=90);mime='image/webp';ext='webp'
        sticker=Sticker.objects.create(created_by=request.user,name=upload.name[:80],mime=mime,file=ContentFile(buffer.getvalue(),name='sticker.'+ext))
        sticker.favorites.add(request.user)
        return JsonResponse(card(sticker),status=201)
    except (ValueError,OSError,UnidentifiedImageError,Image.DecompressionBombError):
        return JsonResponse({'error':'图片无效或动画尺寸过大，请缩小后上传。'},status=400)


@login_required
@require_GET
def sticker_file(request, pk):
    require_member(request.user)
    sticker=get_object_or_404(accessible(request.user),pk=pk)
    response=FileResponse(sticker.file.open('rb'),content_type=sticker.mime)
    response['X-Content-Type-Options']='nosniff'
    response['Cache-Control']='private, max-age=3600'
    return response
