"""Local-only login fixture for the iOS simulator; cannot authenticate or write data."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == '/messages/social/':
            self.send_response(302)
            self.send_header('Location', '/login/')
            self.end_headers()
            return
        if path.startswith('/static/'):
            file = (ROOT / path.lstrip('/')).resolve()
            if not file.is_relative_to((ROOT / 'static').resolve()) or not file.is_file():
                self.send_error(404)
                return
            mime = {'.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'}.get(file.suffix, 'application/octet-stream')
        elif path == '/login/':
            file = ROOT / 'ios/Preview/login.html'
            mime = 'text/html; charset=utf-8'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.end_headers()
        self.wfile.write(file.read_bytes())

    def do_POST(self):
        self.send_error(403, 'Preview only; no accounts or writes.')


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
