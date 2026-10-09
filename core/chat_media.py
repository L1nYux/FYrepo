"""Private chat images and consistent non-text conversation summaries."""
import io
import warnings
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.http import FileResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from .models import ConversationPreference, GroupMember


def preview(message, *, author=False):
    if not message:
        return ''
    legacy = getattr(message, 'legacy_message', None)
    if message.withdrawn_at or legacy and legacy.withdrawn_at:
        return '消息已撤回'
    body = message.body.strip()
    if legacy and getattr(legacy, 'kind', '') == 'notice':
        return '【系统提示】' + body[:60]
    gift = getattr(legacy or message, 'point_gift', None)
    if gift:
        result = '【积分转账】' if gift.kind == 'transfer' else '【积分红包】'
    elif getattr(message,'kind','')=='notice':
        result='【系统提示】'+body[:60]
    elif getattr(message,'notice_id',None):
        result = ('【合作邀请】' if '/discover/offers/' in message.notice.target_url else '【申请进度】') + message.notice.title[:60]
    elif body:
        result = body[:80]
    elif getattr(message, 'sticker_id', None) or legacy and legacy.sticker_id:
        result = '【动画表情】'
    else:
        files = list(getattr(message, 'uploads', getattr(message, 'attachments', [])).all()) if hasattr(message, 'uploads') or hasattr(message, 'attachments') else []
        if legacy:
            files += list(legacy.attachments.all())
        labels = []
        for file in files:
            name = file.original_name
            suffix = Path(name).suffix.lower()
            label = '【图片】' if suffix in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic', '.heif'} else '【视频】' if suffix in {'.mp4', '.mov', '.webm', '.mkv'} else '【语音】' if suffix in {'.mp3', '.wav', '.m4a', '.ogg', '.aac'} else '【文件】' + name
            if label not in labels:
                labels.append(label)
        references=getattr(message,'references',None)
        if isinstance(references,list):
            kinds={'task':'任务','experiment':'实验','finance':'财务','entry':'财务','claim':'报销','announcement':'公告','member':'名片','location':'位置'}
            for ref in references:
                if isinstance(ref,dict):
                    label='【'+kinds.get(ref.get('kind',str(ref.get('key','')).split(':')[0]),'引用')+'】'
                    if label not in labels:labels.append(label)
        elif references is not None and hasattr(references,'all'):
            for ref in references.all():
                label='【'+ref.get_kind_display()+'】'
                if label not in labels:labels.append(label)
        result = ' '.join(labels)[:100] or '【消息】'
    if author:
        from .identity import nickname
        sender = getattr(message, 'author', None) or getattr(message, 'sender', None)
        if sender:
            result = nickname(sender) + '：' + result
    return result


def clean_image(upload, *, square=False):
    if not upload or upload.size > 5 * 1024 * 1024:
        raise ValidationError('请选择不超过 5 MB 的图片。')
    raw = upload.read(5 * 1024 * 1024 + 1)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 16_000_000 or getattr(image, 'n_frames', 1) != 1:
                    raise ValidationError('请选择 1600 万像素以内的静态 PNG、JPG 或 WebP 图片。')
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image = ImageOps.exif_transpose(image).convert('RGB')
                if square:
                    image = ImageOps.fit(image, (512, 512), Image.Resampling.LANCZOS)
                else:
                    image.thumbnail((1920, 1920))
                image.info.clear()
                out = io.BytesIO()
                image.save(out, 'WEBP', quality=88)
                return ContentFile(out.getvalue(), name='image.webp')
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError('无法读取图片，请重新选择。')


def group_avatar_url(group):
    return '/app/groups/' + str(group.pk) + '/avatar/'


@login_required
@require_GET
def group_avatar(request, pk):
    from .personal_messages import permitted_group
    group = permitted_group(request, pk)
    if group.avatar:
        response = FileResponse(group.avatar.open('rb'), content_type='image/webp')
    else:
        members = list(GroupMember.objects.filter(group=group, active=True, user__is_active=True).select_related('user__member_profile').order_by('pk')[:9])
        count = len(members)
        side = 1 if count <= 1 else 2 if count <= 4 else 3
        size, gap = 144, 4
        canvas = Image.new('RGB', (size, size), '#e6e8e7')
        tile = (size - gap * (side + 1)) // side
        draw = ImageDraw.Draw(canvas)
        for i, member in enumerate(members):
            col, row = i % side, i // side
            row_count = min(side, count - row * side)
            x = (size - (tile * row_count + gap * (row_count - 1))) // 2 + col * (tile + gap)
            y = (size - (tile * ((count + side - 1) // side) + gap * (((count + side - 1) // side) - 1))) // 2 + row * (tile + gap)
            image = None
            try:
                avatar = member.user.member_profile.avatar
                if avatar:
                    with avatar.open('rb') as file, Image.open(file) as original:
                        image = ImageOps.fit(original.convert('RGB'), (tile, tile), Image.Resampling.LANCZOS)
            except (OSError, AttributeError):
                pass
            if image is None:
                draw.rounded_rectangle((x, y, x + tile, y + tile), radius=4, fill='#cbded2')
                initial = member.user.username[:1].upper()
                draw.text((x + tile // 2, y + tile // 2), initial, fill='#2e5140', anchor='mm')
            else:
                canvas.paste(image, (x, y))
        out = io.BytesIO()
        canvas.save(out, 'PNG')
        response = HttpResponse(out.getvalue(), content_type='image/png')
    response['Cache-Control'] = 'private, no-cache'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_GET
def background(request):
    from .app_experience import channel_access
    key = request.GET.get('channel', '')
    if not channel_access(request, key):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    from django.shortcuts import get_object_or_404
    saved = get_object_or_404(ConversationPreference, user=request.user, channel=key)
    if not saved.background:
        from django.http import Http404
        raise Http404
    response = FileResponse(saved.background.open('rb'), content_type='image/webp')
    response['Cache-Control'] = 'private, no-cache'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
