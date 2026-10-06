"""Trusted release metadata and idempotent system announcements."""
import json
import re
import logging
from pathlib import Path
from urllib.request import Request, urlopen
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from .models import Announcement
from . import permissions as perms

PATHS={'/assistant/','/api-pool/','/workspace/','/messages/','/experiments/','/account/','/manage/members/','/teams/','/team-square/','/messages/social/','/manage/'}
def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)',value): raise ValueError('Invalid version')
    return tuple(map(int,value.split('.')))

def validate(data):
    version(data.get('version'))
    features=[{'title':str(v.get('title',''))[:160],'description':str(v.get('description',''))[:500],'path':v['path']} for v in data.get('features',[])[:12] if isinstance(v,dict) and v.get('path') in PATHS]
    installers={k:{'name':v['name'],'size':v['size']} for k,v in data.get('installers',{}).items() if k in ('win-x64','mac-arm64','mac-x64') and isinstance(v,dict) and isinstance(v.get('size'),int) and 0<v['size']<1024**3 and v.get('name')==f"ResearchWorkbench-{data['version']}-{k}."+('exe' if k=='win-x64' else 'dmg')}
    return {'version':data['version'],'title':str(data.get('title','版本更新'))[:160],'features':features,'fixes':[str(v)[:500] for v in data.get('fixes',[])[:20]],'installers':installers}

def bundled():
    return validate(json.loads((Path(settings.BASE_DIR)/'desktop/release-info.json').read_text(encoding='utf-8')))

def fetch_json(url):
    request=Request(url,headers={'User-Agent':'ResearchWorkbench-release-notices','Accept':'application/json'})
    with urlopen(request,timeout=5) as response:
        raw=response.read(262145)
    if len(raw)>262144: raise ValueError('Release response too large')
    return json.loads(raw)

def latest():
    release=fetch_json('https://api.github.com/repos/L1nYux/FYrepo/releases/latest')
    tag=release.get('tag_name','');v=tag[1:];version(v)
    if tag!='v'+v or release.get('draft') or release.get('prerelease'): raise ValueError('Not a stable release')
    info=validate(fetch_json(f'https://github.com/L1nYux/FYrepo/releases/download/v{v}/release-info.json'))
    if info['version']!=v: raise ValueError('Release mismatch')
    for platform in ('win-x64','mac-arm64','mac-x64'):
        name=f'ResearchWorkbench-{v}-{platform}.'+('exe' if platform=='win-x64' else 'dmg')
        asset=next((a for a in release.get('assets',[]) if a.get('name')==name),None)
        if not asset: raise ValueError('Incomplete desktop release')
        info['installers'][platform]={'name':name,'size':asset['size']}
    return validate(info)

def publish(info):
    info=validate(info)
    body='\n'.join([info['title']]+[v['title']+'：'+v['description'] for v in info['features']]+info['fixes'])[:5000]
    item,created=Announcement.objects.get_or_create(release_version=info['version'],defaults={'title':'科研工作台 '+info['version']+' 版本更新','body':body,'release_data':info})
    if item.release_data!=info:
        item.release_data=info;item.save(update_fields=['release_data'])
    return item,created

def sync(check_latest=False):
    local=bundled();publish(local)
    if check_latest:
        try:
            info=latest()
            if version(info['version'])>=version(local['version']): publish(info)
        except Exception:
            logging.getLogger(__name__).warning('Version announcement sync unavailable; existing announcements retained')

@login_required
@require_GET
def current(request):
    if not perms.is_team_member(request): return JsonResponse({'error':'仅团队成员可查看'},status=403)
    info=bundled()
    return JsonResponse({'server_version':info['version'],'release':info})
