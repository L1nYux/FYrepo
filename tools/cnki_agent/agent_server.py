"""Loopback bridge to the pinned sample-llm engine; never receives workbench cookies."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HOST, PORT = '127.0.0.1', 8765
HERE = Path(__file__).resolve().parent
RUNTIME = HERE / 'runtime'
ENGINE_ROOT = None
JOBS = {}
LOCK = threading.RLock()
ALLOWED_ORIGINS = {'http://127.0.0.1:8000', 'http://localhost:8000'}
TOKEN_PATH = Path.home() / '.fyrepo_cnki_agent_token'


def _token():
    if TOKEN_PATH.exists():
        value = TOKEN_PATH.read_text(encoding='utf-8').strip()
        if value:
            return value
    value = secrets.token_urlsafe(24)
    TOKEN_PATH.write_text(value, encoding='utf-8')
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass
    return value


AGENT_TOKEN = _token()


def _find_engine_root():
    explicit = os.environ.get('SAMPLING_ENGINE_ROOT', '').strip()
    if explicit:
        path = Path(explicit)
        return path.resolve() if (path / 'integrations/cnki_external.py').is_file() else None
    candidates = [HERE.parents[1] / 'vendor/sample_llm', HERE.parents[2] / 'sample-llm',
                  HERE.parents[2] / 'sample-llm-main']
    return next((p.resolve() for p in candidates if (p / 'integrations/cnki_external.py').is_file()), None)


def _load_engine():
    global ENGINE_ROOT
    ENGINE_ROOT = _find_engine_root()
    if ENGINE_ROOT is None:
        return False, '未找到采集引擎，请完整解压 FYrepo 或设置 SAMPLING_ENGINE_ROOT'
    if str(ENGINE_ROOT) not in sys.path:
        sys.path.insert(0, str(ENGINE_ROOT))
    try:
        from integrations import cnki_external
        from sampling_core.metadata import read_candidates
        return True, str(ENGINE_ROOT)
    except Exception as exc:
        return False, f'采集依赖未安装：{exc}'


def _engine():
    ok, message = _load_engine()
    if not ok:
        raise ValueError(message)
    from integrations import cnki_external
    from sampling_core.metadata import read_candidates
    return cnki_external, read_candidates


def _save(job):
    RUNTIME.mkdir(exist_ok=True)
    target = RUNTIME / f"{job['job_id']}.json"
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
    temp.replace(target)


def load_jobs():
    if not RUNTIME.exists():
        return
    for path in RUNTIME.glob('*.json'):
        try:
            job = json.loads(path.read_text(encoding='utf-8'))
            if job['status'] in ('queued', 'running'):
                job.update(status='stopped', message='采集器曾中断，可重新开始并续接已完成批次')
                _save(job)
            JOBS[job['job_id']] = job
        except (KeyError, ValueError, OSError):
            continue


def _update(jid, **values):
    with LOCK:
        JOBS[jid].update(values)
        _save(JOBS[jid])


def _log(jid, message):
    if not message:
        return
    with LOCK:
        job = JOBS[jid]
        job['message'] = str(message)
        job['log'] = (job['log'] + [str(message)])[-300:]
        _save(job)


def _finish_error(jid, exc):
    _log(jid, str(exc))
    _update(jid, status='failed', message=str(exc))


def _start_collection(jid, config):
    _update(jid, status='running')
    try:
        cnki, read_candidates = _engine()
        import pandas as pd
        frame = pd.DataFrame(config.get('frame') or [])
        if frame.empty:
            raise ValueError('没有有效抽样框')
        # 同一 scope 保持 workspace，复用上游已完成的原生导出批次。
        signature = hashlib.sha256(json.dumps(config.get('frame'), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        workspace = ENGINE_ROOT / 'runtime_outputs/workbench_agent' / f"run_{config.get('run_id')}_{signature}"
        _update(jid, workspace=str(workspace), scope_signature=config.get('scope_signature', ''))
        last_unique = ''
        for event in cnki.collect(frame, workspace, batch_size=500,
                                  concurrency=max(1, min(3, int(config.get('concurrency', 2)))),
                                  year_chunk_size=max(1, min(3, int(config.get('year_chunk_size', 2))))):
            _log(jid, event.get('message', ''))
            if event.get('unique_json'):
                last_unique = event['unique_json']
            if event.get('stopped'):
                _update(jid, status='stopped'); return
        path = Path(last_unique) if last_unique else workspace / 'merged/unique.json'
        if not path.exists():
            raise ValueError('采集结束但没有题录输出，未生成候选数据')
        records = read_candidates([str(path)]).fillna('').to_dict('records')
        _update(jid, status='completed', records=records, message=f'采集完成，{len(records)} 条去重题录')
    except Exception as exc:
        _finish_error(jid, exc)


def _start_install(jid, body):
    _update(jid, status='running')
    try:
        cnki, _ = _engine()
        for event in cnki.install_package():
            _log(jid, event.get('message', ''))
        status = cnki.package_status()
        if not status['installed'] or not status['browser_ready']:
            raise ValueError('采集组件或浏览器未就绪，请查看安装日志')
        _update(jid, status='completed', message='采集组件已安装，浏览器已就绪')
    except Exception as exc:
        _finish_error(jid, exc)


def _start_pdf(jid, body):
    _update(jid, status='running')
    try:
        _engine()
        from integrations.pdf_downloader import download_selected
        out = ENGINE_ROOT / 'runtime_outputs/selected_pdfs' / jid
        records = body['records']
        result = download_selected(records, out)
        # 上游识别到浏览器 download 事件不等于得到 PDF；校验文件头后才允许回传。
        for row in result:
            path = Path(row.get('pdf_file') or '')
            if row.get('pdf_file'):
                if not path.is_file() or b'%PDF-' not in path.read_bytes()[:1024]:
                    row['pdf_file'] = ''; row['status'] = 'not_a_pdf_or_permission_page'
                else:
                    row['original_name'] = path.name
        done = {r['paper_id'] for r in result}
        result += [{'paper_id': r['paper_id'], 'status': 'stopped', 'pdf_file': ''} for r in records if r['paper_id'] not in done]
        downloads = sum(bool(r.get('pdf_file')) for r in result)
        _update(jid, status='completed', workspace=str(out), records=result,
                message=f'处理 {len(result)} 篇，取得 {downloads} 份 PDF；其余需人工下载')
    except Exception as exc:
        _finish_error(jid, exc)


def _start_job(kind, body, worker):
    with LOCK:
        if any(x['status'] in ('queued', 'running') for x in JOBS.values()):
            raise ValueError('已有本地任务在运行，请先完成或停止任务')
        jid = str(uuid.uuid4())
        JOBS[jid] = {'job_id': jid, 'kind': kind, 'status': 'queued', 'message': '任务已创建', 'log': [],
                     'records': [], 'run_id': body.get('run_id'), 'scope_signature': body.get('scope_signature','')}
        _save(JOBS[jid])
    threading.Thread(target=worker, args=(jid, body), daemon=True).start()
    return jid


class Handler(BaseHTTPRequestHandler):
    server_version = 'FYrepoCNKIAgent/2.0'

    def log_message(self, *args):
        pass

    def _origin_ok(self):
        # 限制 Host 防止 DNS rebinding；Origin 来自真实工作台的显式允许名单。
        host = self.headers.get('Host', '').split(':')[0]
        origin = self.headers.get('Origin')
        return host in ('127.0.0.1', 'localhost') and (origin is None or origin in ALLOWED_ORIGINS)

    def _cors(self):
        origin = self.headers.get('Origin')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Sampling-Agent-Token')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Vary', 'Origin')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')

    def _json(self, data, status=200):
        content = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status); self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(content))); self.end_headers(); self.wfile.write(content)

    def _allowed(self):
        if not self._origin_ok():
            self._json({'error': '工作台域名未获本机允许，请配置 SAMPLING_WORKBENCH_ORIGINS'}, 403); return False
        if not secrets.compare_digest(self.headers.get('X-Sampling-Agent-Token', ''), AGENT_TOKEN):
            self._json({'error': '连接码不正确'}, 401); return False
        return True

    def _body(self):
        n = int(self.headers.get('Content-Length', '0'))
        if n < 0 or n > 2 * 1024 * 1024:
            raise ValueError('请求内容过大')
        data = json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
        if not isinstance(data, dict):
            raise ValueError('请求须为字段对象')
        return data

    def do_OPTIONS(self):
        if not self._origin_ok():
            return self._json({'error': '不允许的工作台域名'}, 403)
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if not self._allowed(): return
        path = urlparse(self.path).path
        if path == '/status':
            ok, message = _load_engine()
            status = {}
            if ok:
                cnki, _ = _engine(); status = cnki.package_status()
            return self._json({'ok': True, 'version': '2.0', 'engine_available': ok,
                               'engine_ready': bool(ok and status.get('installed') and status.get('browser_ready')),
                               'login_ready': bool(status.get('login_profile_ready')), 'message': message, 'package': status})
        match = re.fullmatch(r'/jobs/([0-9a-f-]+)(/result|/files/([PHR][0-9]+))?', path)
        if not match: return self._json({'error': '接口不存在'}, 404)
        with LOCK:
            job = JOBS.get(match[1])
            if job is None: return self._json({'error': '任务不存在'}, 404)
            job = dict(job)
        if match[2] and job['status'] != 'completed': return self._json({'error': '任务尚未完成'}, 409)
        if match[3]:
            row = next((r for r in job.get('records', []) if r.get('paper_id') == match[3] and r.get('pdf_file')), None)
            if job['kind'] != 'pdf' or not row: return self._json({'error': 'PDF 不存在'}, 404)
            file = Path(row['pdf_file']).resolve()
            if not file.is_relative_to(Path(job['workspace']).resolve()) or not file.is_file():
                return self._json({'error': 'PDF 不存在'}, 404)
            data = file.read_bytes()
            if len(data) > 20 * 1024 * 1024: return self._json({'error': 'PDF 超过 20 MB，请手动上传'}, 413)
            self.send_response(200); self._cors(); self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data); return
        if match[2] == '/result':
            return self._json({'ok': True, 'records': job.get('records', []), 'run_id': job.get('run_id'), 'scope_signature': job.get('scope_signature','')})
        return self._json({k: v for k, v in job.items() if k != 'records'})

    def do_POST(self):
        if not self._allowed(): return
        path = urlparse(self.path).path
        try:
            if path in ('/login/open', '/login/finish'):
                if any(j['status'] in ('queued','running') for j in JOBS.values()):
                    raise ValueError('本地任务进行中，请先停止任务')
                cnki, _ = _engine()
                return self._json({'ok': True, 'message': cnki.start_login() if path.endswith('open') else cnki.finish_login()})
            if path in ('/collect', '/pdf', '/install'):
                body = self._body()
                if path == '/collect' and (not isinstance(body.get('frame'), list) or not body['frame']):
                    raise ValueError('工作台未返回有效研究范围')
                if path == '/pdf':
                    rows = body.get('records')
                    if not isinstance(rows, list) or not rows or len(rows) > 1000:
                        raise ValueError('没有可下载论文或队列过大')
                    for row in rows:
                        if not isinstance(row, dict) or not re.fullmatch(r'[PHR][0-9]+', str(row.get('paper_id',''))):
                            raise ValueError('PDF 样本编号不正确')
                        if row.get('url'):
                            host = (urlparse(row['url']).hostname or '').lower()
                            if not (host == 'cnki.net' or host.endswith('.cnki.net') or host == 'cnki.com.cn' or host.endswith('.cnki.com.cn')):
                                raise ValueError('自动下载只接受知网来源链接')
                kind = path[1:]; worker = {'collect':_start_collection, 'pdf':_start_pdf, 'install':_start_install}[kind]
                jid = _start_job(kind, body, worker)
                return self._json({'ok': True, 'job_id': jid}, 202)
            match = re.fullmatch(r'/jobs/([0-9a-f-]+)/stop', path)
            if match:
                job = JOBS.get(match[1])
                if job is None: return self._json({'error':'任务不存在'}, 404)
                if job['status'] not in ('queued','running'): return self._json({'ok':True,'message':'任务已结束'})
                cnki, _ = _engine()
                if job['kind'] == 'pdf':
                    from integrations.pdf_downloader import request_stop_pdf
                    message = request_stop_pdf()
                elif job['kind'] == 'collect': message = cnki.request_stop()
                else: raise ValueError('组件安装中，请等待安装结束')
                _log(match[1], message)
                return self._json({'ok':True,'message':message})
            return self._json({'error':'接口不存在'}, 404)
        except (ValueError, RuntimeError, KeyError, TypeError) as exc:
            return self._json({'error': str(exc)}, 400)
        except Exception as exc:
            return self._json({'error': f'本机操作失败：{exc}'}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', choices=['127.0.0.1'], default=HOST)
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--allow-origin', action='append', default=[])
    args = parser.parse_args()
    origins = args.allow_origin + [x.strip() for x in os.environ.get('SAMPLING_WORKBENCH_ORIGINS','').split(',') if x.strip()]
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            parser.error('allow-origin 须为完整域名，例如 https://workbench.example.com，不含路径或末尾斜杠')
    ALLOWED_ORIGINS.update(origins)
    load_jobs()
    ok, message = _load_engine()
    print('FYrepo 本地知网采集器 2.0', flush=True)
    print(f'地址：http://127.0.0.1:{args.port}', flush=True)
    print('允许工作台：' + ', '.join(sorted(ALLOWED_ORIGINS)), flush=True)
    print('连接码：' + AGENT_TOKEN, flush=True)
    print('引擎：' + message, flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
