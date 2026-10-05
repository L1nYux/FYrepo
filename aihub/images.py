"""Owned, normalized image inputs. Never accept client-supplied image URLs."""
import base64
import io
import warnings
import uuid
from urllib.parse import urlsplit
from django.core.exceptions import ValidationError
from django.urls import reverse
from PIL import Image, ImageOps, UnidentifiedImageError
from .models import AssistantImage

MAX_UPLOAD=8*1024*1024
MAX_IMAGES=4


def catalog_capability(row):
    if type(row.get('supports_images')) is bool:return row['supports_images']
    architecture=row.get('architecture')
    modalities=architecture.get('input_modalities') if isinstance(architecture,dict) else row.get('input_modalities')
    if isinstance(modalities,list):return 'image' in modalities
    return None


def supports_images(model):
    if model.supports_images is not None:return model.supports_images
    name=model.model_id.lower().removeprefix('models/')
    host=(urlsplit(model.provider.base_url).hostname or '').lower()
    if host in ('api.minimax.io','api.minimaxi.com','api.minimax.cn'):
        return name.startswith('minimax-m3')
    if host in ('dashscope.aliyuncs.com','dashscope-intl.aliyuncs.com','coding.dashscope.aliyuncs.com'):
        return ('vl' in name and name.startswith('qwen')) or name.startswith(('qwen3.5-','qwen3.6-','qwen3.7-','qwen3.8-'))
    if host=='bigmodel.cn' or host.endswith('.bigmodel.cn'):
        return name.startswith(('glm-4.6v','glm-4.5v','glm-4.1v'))
    # Other providers can opt in through model settings after capability checks.
    return False


def normalize(upload):
    if not upload or upload.size>MAX_UPLOAD:raise ValidationError('每张图片最多 8 MB。')
    raw=upload.read(MAX_UPLOAD+1)
    if len(raw)>MAX_UPLOAD:raise ValidationError('每张图片最多 8 MB。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as opened:
                if opened.format not in ('PNG','JPEG','WEBP','GIF','BMP'):raise ValidationError('请选择 PNG、JPG、WebP、GIF 或 BMP 图片。')
                if opened.width*opened.height>20_000_000:raise ValidationError('图片像素过大，请缩小后再发送。')
                opened.seek(0)
                value=ImageOps.exif_transpose(opened)
                value.thumbnail((1536,1536),Image.Resampling.LANCZOS)
                background=Image.new('RGB',value.size,'white')
                if value.mode in ('RGBA','LA') or 'transparency' in value.info:
                    rgba=value.convert('RGBA');background.paste(rgba,mask=rgba.getchannel('A'))
                else:background.paste(value.convert('RGB'))
                output=io.BytesIO();background.save(output,format='JPEG',quality=85,optimize=True)
                if output.tell()>1024*1024:raise ValidationError('图片压缩后仍过大，请缩小后再发送。')
                return 'data:image/jpeg;base64,'+base64.b64encode(output.getvalue()).decode('ascii'),background.width,background.height
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise ValidationError('图片无法读取，请重新截图或选择一张有效图片。') from None


def owned(user,identifiers):
    if not isinstance(identifiers,list) or len(identifiers)>MAX_IMAGES or any(not isinstance(value,str) or len(value)>36 for value in identifiers):
        raise ValidationError('每条消息最多发送 4 张图片。')
    try:identifiers=[str(uuid.UUID(value)) for value in identifiers]
    except (ValueError,AttributeError):raise ValidationError('图片标识无效，请重新粘贴。') from None
    rows=list(AssistantImage.objects.filter(user=user,pk__in=identifiers))
    if len(rows)!=len(set(identifiers)):raise ValidationError('图片已失效或无权使用，请重新粘贴。')
    mapping={str(row.pk):row for row in rows}
    return [mapping[value] for value in dict.fromkeys(identifiers)]


def metadata(rows):
    return [{'id':str(row.pk),'url':reverse('ai_image',args=[row.pk]),'width':row.width,'height':row.height} for row in rows]


def message_images(rows):
    return [row.data for row in rows]
