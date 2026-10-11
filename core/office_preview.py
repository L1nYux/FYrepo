"""Private Office-to-PDF cache; Linux conversions run without network access."""
import hashlib
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from django.conf import settings

logger = logging.getLogger(__name__)


class PreviewUnavailable(ValueError):
    def __init__(self, message, *, diagnostic=''):
        super().__init__(message)
        # Keep component details out of user-facing preview errors. Deployment
        # checks can show them without exposing an uploaded document's contents.
        self.diagnostic = diagnostic


def pdf_path(item):
    executable=shutil.which('libreoffice') or shutil.which('soffice')
    if not executable:
        raise PreviewUnavailable('此服务器尚未安装 Office 预览组件。')
    with item.file.open('rb') as stream:raw=stream.read(25*1024*1024+1)
    if len(raw)>25*1024*1024:raise PreviewUnavailable('此文件过大，请下载后打开。')
    suffix=Path(item.original_name).suffix.lower()
    key=hashlib.sha256(suffix.encode()+raw).hexdigest()
    cache=Path(settings.MEDIA_ROOT)/'.office-preview'
    cache.mkdir(mode=0o700,parents=True,exist_ok=True)
    target=cache/(key+'.pdf')
    if target.is_file():return target
    with tempfile.TemporaryDirectory(prefix='convert-',dir=cache) as folder:
        work=Path(folder);(work/'input').mkdir();(work/'output').mkdir();profile=work/'profile';(profile/'user').mkdir(parents=True)
        (work/'input'/('document'+suffix)).write_bytes(raw)
        (profile/'user/registrymodifications.xcu').write_text('''<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item><item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item></oor:items>''',encoding='utf-8')
        arguments=['--headless','--nologo','--nodefault','--nofirststartwizard','--convert-to','pdf:writer_pdf_Export','--outdir']
        if os.name=='posix':
            sandbox=shutil.which('bwrap')
            if not sandbox:raise PreviewUnavailable('Office 预览隔离组件未安装。')
            command=[sandbox,'--die-with-parent','--unshare-all','--new-session',
                     '--clearenv','--proc','/proc','--dev','/dev','--tmpfs','/tmp',
                     '--dir','/home','--setenv','HOME','/home',
                     '--setenv','PATH','/usr/bin:/bin','--setenv','LANG','C.UTF-8',
                     '--setenv','SAL_USE_VCLPLUGIN','svp',
                     '--setenv','XDG_CACHE_HOME','/home/.cache',
                     '--setenv','XDG_CONFIG_HOME','/home/.config',
                     '--symlink','usr/bin','/bin','--symlink','usr/sbin','/sbin',
                     '--bind',str(work),'/work','--chdir','/work']
            # Ubuntu/Debian keep the registry and sofficerc under /etc/libreoffice;
            # the installed /usr tree contains links to that directory. Omitting
            # it leaves LibreOffice installed but unable to bootstrap conversion.
            for directory in ('/usr','/lib','/lib64','/etc/libreoffice',
                              '/etc/fonts','/var/cache/fontconfig','/etc/ld.so.cache',
                              '/etc/passwd','/etc/group','/etc/nsswitch.conf'):
                if Path(directory).exists():command+=['--ro-bind',directory,directory]
            command += [executable,'-env:UserInstallation=file:///work/profile',*arguments,'/work/output','/work/input/document'+suffix]
        else:
            command=[executable,'-env:UserInstallation='+profile.as_uri(),*arguments,str(work/'output'),str(work/'input'/('document'+suffix))]
        with tempfile.TemporaryFile() as diagnostic_stream:
            try:
                result=subprocess.run(command,stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL,stderr=diagnostic_stream,
                                      timeout=30,check=False)
            except (OSError,subprocess.TimeoutExpired) as error:
                diagnostic_stream.seek(0,os.SEEK_END)
                diagnostic_stream.seek(max(0,diagnostic_stream.tell()-4000))
                detail=diagnostic_stream.read().decode('utf-8',errors='replace')
                raise PreviewUnavailable('文档预览转换超时或组件不可用。',
                                         diagnostic=detail or str(error)) from error
            diagnostic_stream.seek(0,os.SEEK_END)
            diagnostic_stream.seek(max(0,diagnostic_stream.tell()-4000))
            detail=diagnostic_stream.read().decode('utf-8',errors='replace')
        converted=work/'output/document.pdf'
        if result.returncode or not converted.is_file() or converted.stat().st_size>100*1024*1024:
            detail=detail.replace(str(work),'<conversion-directory>').strip()
            logger.warning('Office preview failed (exit=%s): %s',result.returncode,detail)
            raise PreviewUnavailable('文档无法转换预览，请下载后用其他应用打开。',
                                     diagnostic=f'exit={result.returncode}; {detail or "未生成 PDF 文件"}')
        os.replace(converted,target)
    return target
