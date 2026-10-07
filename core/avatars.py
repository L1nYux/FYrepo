from django.contrib.auth import get_user_model
"""Verified avatars with private storage and access-controlled delivery."""
import io
import warnings
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from .models import MemberProfile, PublicProfile

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 16_000_000

def avatar_url(user):
    if not user or not getattr(user, 'pk', None): return ''
    try: name = user.member_profile.avatar.name
    except MemberProfile.DoesNotExist: return ''
    return reverse('member_avatar', args=[user.pk, Path(name).stem]) if name else ''

class AvatarForm(forms.Form):
    avatar = forms.FileField(label='选择图片', widget=forms.FileInput(attrs={
        'accept': 'image/png,image/jpeg,image/webp', 'data-avatar-file': '',
    }))

    def clean_avatar(self):
        upload = self.cleaned_data['avatar']
        if upload.size > MAX_BYTES: raise ValidationError('图片不能超过 5 MB。')
        raw = upload.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES: raise ValidationError('图片不能超过 5 MB。')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in ('PNG', 'JPEG', 'WEBP'):
                        raise ValidationError('请选择 PNG、JPG 或 WebP 图片。')
                    if image.width * image.height > MAX_PIXELS:
                        raise ValidationError('图片尺寸过大，请缩小到 1600 万像素以内。')
                    if getattr(image, 'n_frames', 1) != 1: raise ValidationError('请选择静态图片。')
                    image.verify()
                with Image.open(io.BytesIO(raw)) as image:
                    image.load()
                    image = ImageOps.exif_transpose(image).convert('RGBA')
                    size = min(512, image.width, image.height)
                    image = ImageOps.fit(image, (size, size), Image.Resampling.LANCZOS)
                    image.info.clear()
                    buffer = io.BytesIO()
                    image.save(buffer, format='WEBP', quality=88)
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
                Image.DecompressionBombWarning):
            raise ValidationError('无法读取这张图片，请重新选择有效的 PNG、JPG 或 WebP 图片。')
        return ContentFile(buffer.getvalue(), name='avatar.webp')

def save_avatar(user, content=None):
    new_name = ''
    storage = MemberProfile._meta.get_field('avatar').storage
    try:
        with transaction.atomic():
            MemberProfile.objects.filter(user=user).update(avatar=F('avatar'))
            profile, _ = MemberProfile.objects.get_or_create(user=user)
            profile = MemberProfile.objects.select_for_update().get(pk=profile.pk)
            old_name = profile.avatar.name
            if content is not None:
                profile.avatar.save('avatar.webp', content, save=False)
                new_name = profile.avatar.name
            else: profile.avatar = ''
            profile.save(update_fields=['avatar'])
            if old_name: transaction.on_commit(lambda: storage.delete(old_name))
        user._state.fields_cache.pop('member_profile', None)
    except Exception:
        if new_name: storage.delete(new_name)
        raise

@require_GET
@never_cache
def member_avatar(request, pk, version):
    from .tenancy import team_users
    if pk != getattr(request.user,'pk',None) and not team_users(include_inactive=True,include_deleted=True).filter(pk=pk).exists():
        from .social import discoverable
        candidate=get_object_or_404(get_user_model(),pk=pk)
        if not discoverable(request.user,candidate): raise Http404
    profile = get_object_or_404(MemberProfile.objects.select_related('user'), user_id=pk)
    if not profile.user.is_active: raise Http404
    if not request.user.is_authenticated and not PublicProfile.objects.filter(user_id=pk, is_public=True).exists():
        raise Http404
    if not profile.avatar or Path(profile.avatar.name).stem != version: raise Http404
    try: file = profile.avatar.open('rb')
    except (FileNotFoundError, OSError): raise Http404
    response = FileResponse(file, content_type='image/webp')
    response['X-Content-Type-Options'] = 'nosniff'
    return response
