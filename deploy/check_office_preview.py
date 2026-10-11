"""Fail upgrade preparation when the service user cannot convert a document."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from django.conf import settings
from django.core.files.base import ContentFile
from pypdf import PdfReader

with TemporaryDirectory(prefix='workbench-office-probe-') as folder:
    settings.configure(MEDIA_ROOT=folder)
    from core.office_preview import pdf_path, PreviewUnavailable
    item=SimpleNamespace(original_name='probe.rtf',file=ContentFile(b'{\\rtf1\\ansi Office preview sandbox probe.}'))
    try:
        converted=pdf_path(item)
    except PreviewUnavailable as error:
        print('Office 预览检查失败：'+str(error),file=sys.stderr)
        if error.diagnostic:
            print('转换组件输出：\n'+error.diagnostic,file=sys.stderr)
        print('升级尚未切换服务，请先解决此检查错误。',file=sys.stderr)
        raise SystemExit(1) from None
    with converted.open('rb') as stream:
        document=PdfReader(stream)
        assert len(document.pages)==1 and 'sandbox probe' in document.pages[0].extract_text()
print('PASS: Office preview conversion as service user, with private cache and isolated network.')
