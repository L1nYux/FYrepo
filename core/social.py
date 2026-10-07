from .tenancy import team_users, membership_for, active_member
"""Member cards and private, verified sticker assets."""
import io
from urllib.parse import quote
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.core.files.base import ContentFile
from django.db.models import Q
from django.http import JsonResponse, FileResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from . import permissions as perms
from .models import Sticker, PublicProfile, ChatMessage, FriendRequest, Friendship, Team
from .avatars import avatar_url
from .identity import nickname, account_id
from .messages import visible_messages


def require_member(user):
    if not perms.is_team_member(user): raise PermissionDenied


def discoverable(viewer,user):
    if user.pk==getattr(viewer,'pk',None): return True
    if not user.is_active: return False
    if PublicProfile.objects.filter(user=user,is_public=True).exists(): return True
    if Team.objects.filter(owner=user,active=True,listed=True).exists(): return True
    if viewer.is_authenticated:
        from .personal_messages import permitted_peer
        return permitted_peer(viewer,user) or FriendRequest.objects.filter(sender=viewer,recipient=user,state='pending').exists() or FriendRequest.objects.filter(sender=user,recipient=viewer,state='pending').exists()
    return False


@login_required
@never_cache
@require_GET
def member(request, pk):
    user=get_object_or_404(User.objects.select_related('member_profile'),pk=pk)
    local=team_users(include_inactive=True,include_deleted=True)
    if not perms.is_admin(request): local=local.filter(pk__in=team_users(include_inactive=True,include_deleted=True,member_only=True).values('pk'))
    local=local.filter(pk=pk).exists()
    if not local and not discoverable(request.user,user): raise PermissionDenied('成员资料不可用。')
    membership=membership_for(user) if local else None
    profile=PublicProfile.objects.filter(user=user,is_public=True).first()
    mine=user.pk==request.user.pk
    pair=sorted([user.pk,request.user.pk])
    is_friend=not mine and Friendship.objects.filter(first_id=pair[0],second_id=pair[1]).exists()
    outgoing=FriendRequest.objects.filter(sender=request.user,recipient=user,state='pending').exists() if not mine else False
    incoming=FriendRequest.objects.filter(sender=user,recipient=request.user,state='pending').first() if not mine else None
    state='self' if mine else 'friends' if is_friend else 'sent' if outgoing else 'received' if incoming else 'none'
    from .personal_messages import permitted_peer
    chat_url=reverse('profile') if mine else reverse('personal_chat',args=[pk]) if user.is_active and permitted_peer(request.user,user) else ''
    return JsonResponse({'id':pk,'username':account_id(user),'name':user.first_name if local else '',
        'avatar_url':avatar_url(user),'initial':nickname(user)[:1].upper(),
        'role':('已离开团队' if membership.deleted_at else perms.role_label(perms.account_role(user))) if membership else '好友' if is_friend else '个人账号',
        'active':active_member(user) if membership else user.is_active,
        'display_name':nickname(user),
        'projects':[{'name':p.name,'url':reverse('project_detail',args=[p.pk])} for p in user.owned_projects.filter(archived_at__isnull=True).order_by('name','pk')[:12]] if local and perms.is_team_member(user) else [],
        'manage_url':reverse('messages_team_members')+'?team='+str(membership.team_id)+'&q='+quote(user.username) if local and perms.is_admin(request) and membership and not membership.deleted_at else '',
        'real_name':user.first_name if local else '',
        'research_area':profile.research_area if profile else '', 'bio':profile.bio if profile else '',
        'self':mine,'chat_url':chat_url,'friend_state':state,'csrf_token':get_token(request),
        'friend_url':(reverse('friend_action',args=[incoming.pk]) if incoming else reverse('request_friend')) if state in ('none','received') and user.is_active else ''})


def accessible(user):
    from .models import PersonalMessage, GroupMessage
    from .communication import groups_for
    messages = visible_messages(user, ChatMessage.objects.filter(Q(room__in=['developers','public']) | Q(room='private',author=user) | Q(room='private',recipient=user)))
    personal=PersonalMessage.objects.filter(Q(sender=user)|Q(recipient=user),withdrawn_at__isnull=True).exclude(hidden_by=user).exclude(legacy_message__withdrawn_at__isnull=False).exclude(legacy_message__hidden_by=user)
    groups=GroupMessage.objects.filter(group__in=groups_for(user),withdrawn_at__isnull=True).exclude(hidden_by=user)
    return Sticker.all_objects.filter(Q(created_by=user)|Q(favorites=user)|Q(messages__in=messages)|Q(personal_messages__in=personal)|Q(group_messages__in=groups)).distinct()


def card(sticker):
    return {'id': sticker.pk, 'name': sticker.name, 'url': reverse('sticker_file', args=[sticker.pk])}


@login_required
@require_http_methods(['GET','POST'])
def stickers(request):
    require_member(request.user)
    if request.method == 'GET':
        return JsonResponse({'stickers': [card(s) for s in Sticker.all_objects.filter(favorites=request.user)[:200]]})
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
