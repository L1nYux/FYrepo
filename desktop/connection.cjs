const fs = require('node:fs');
const path = require('node:path');
const DEFAULT_SERVER_URL = 'http://47.117.89.248';

function serverOrigin(value) {
  let url;
  try { url = new URL(String(value || '').trim()); } catch { throw Error('请输入完整的服务器网址，例如 https://team.example.com'); }
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw Error('服务器网址只能包含协议、域名或 IP、端口，不要填写账户密码或页面路径。');
  }
  return url.origin;
}
class Connection {
  constructor(directory) {
    this.file = path.join(directory, 'server-connection.json');
    this.value = { mode: 'remote', url: DEFAULT_SERVER_URL };
    try {
      const saved = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (saved.mode === 'remote' && saved.url) this.value.url = serverOrigin(saved.url);
    } catch (_) {}
  }
  snapshot() { return { ...this.value }; }
  save(value) {
    if (!value || value.mode !== 'remote') throw Error('工作台使用团队服务器。');
    const next = {mode: 'remote', url: serverOrigin(value.url)};
    fs.writeFileSync(this.file + '.tmp', JSON.stringify(next, null, 2), {mode: 0o600});
    fs.renameSync(this.file + '.tmp', this.file); this.value = next;
    return this.snapshot();
  }
}
module.exports = {Connection, serverOrigin, DEFAULT_SERVER_URL};
