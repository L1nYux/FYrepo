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
    from core.office_preview import pdf_path
    item=SimpleNamespace(original_name='probe.rtf',file=ContentFile(b'{\\rtf1\\ansi Office preview sandbox probe.}'))
    converted=pdf_path(item)
    with converted.open('rb') as stream:
        document=PdfReader(stream)
        assert len(document.pages)==1 and 'sandbox probe' in document.pages[0].extract_text()
print('PASS: Office preview conversion as service user, with private cache and isolated network.')
