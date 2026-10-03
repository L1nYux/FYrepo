const fs = require('node:fs');
const path = require('node:path');

function serverOrigin(value) {
  let url;
  try { url = new URL(String(value || '').trim()); } catch { throw Error('请输入完整的服务器网址，例如 https://team.example.com'); }
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw Error('服务器网址只能包含协议、域名或 IP、端口，不要填写账户密码或页面路径。');
  }
  return url.origin;
}
class Connection {
  constructor(directory, packaged) {
    this.file = path.join(directory, 'server-connection.json'); this.packaged = packaged;
    this.value = { mode: packaged ? 'remote' : 'local', url: '' };
    try {
      const saved = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (saved.mode === 'local' && !packaged) this.value.mode = 'local';
      else if (saved.mode === 'remote') this.value.mode = 'remote';
      if (saved.url) this.value.url = serverOrigin(saved.url);
    } catch (_) {}
  }
  snapshot() { return { ...this.value, localAvailable: !this.packaged }; }
  save(value) {
    if (!value || !['remote', 'local'].includes(value.mode)) throw Error('请选择连接模式。');
    if (value.mode === 'local' && this.packaged) throw Error('安装版使用团队服务器；本地预览请从源码启动。');
    const next = {mode: value.mode, url: value.mode === 'remote' ? serverOrigin(value.url) : this.value.url};
    fs.writeFileSync(this.file + '.tmp', JSON.stringify(next, null, 2), {mode: 0o600});
    fs.renameSync(this.file + '.tmp', this.file); this.value = next;
    return this.snapshot();
  }
}
module.exports = {Connection, serverOrigin};
