const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFile } = require('node:child_process');

const TEXT_LIMIT = 2 * 1024 * 1024;
const CONFLICT = new Set(['DD', 'AU', 'UD', 'UA', 'DU', 'AA', 'UU']);
const DOCUMENTS = new Set(['.txt', '.md', '.markdown', '.csv', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.rtf']);
const TEXT_FILES = new Set(['.txt', '.md', '.markdown', '.csv', '.tsv', '.py', '.js', '.cjs', '.mjs', '.jsx', '.ts', '.tsx', '.json', '.jsonl', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.html', '.css', '.scss', '.svg', '.xml', '.r', '.sql', '.sh', '.bat', '.cmd', '.ps1', '.c', '.h', '.cpp', '.hpp', '.java', '.go', '.rs', '.tex', '.gitignore', '.gitattributes']);
const hash = value => crypto.createHash('sha256').update(value).digest('hex');

class Repository {
  constructor(directory, enabled) { this.directory = directory; this.enabled = enabled; this.busy = false; }
  requireEnabled() { if (!this.enabled()) throw Error('请在设置的能力模块中启用本地仓库。'); }
  root() { this.requireEnabled(); if(!this.directory)throw Error('请打开或新建仓库，或先选择文件保存位置。');return fs.realpathSync(this.directory); }
  context() { return hash(this.root()); }
  requireContext(context) { if (context !== this.context()) throw Error('所选仓库已改变，请重新打开文件。'); }
  resolve(file, creating = false) {
    const root = this.root();
    if (typeof file !== 'string' || !file || file.length > 4000 || /[\x00-\x1f:]/.test(file) || path.isAbsolute(file)) throw Error('文件路径无效。');
    const pieces = file.replaceAll('\\', '/').split('/');
    if (pieces.some(piece => !piece || piece === '.' || piece === '..' || piece.toLowerCase() === '.git' || /[<>"|?*]|[. ]$/.test(piece) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(piece))) throw Error('文件路径无效，或不在所选仓库内。');
    const target = path.resolve(root, ...pieces);
    const within = value => { const relative = path.relative(root, value); return relative && relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative); };
    if (!within(target)) throw Error('文件不在所选仓库内。');
    let ancestor = target;
    while (!fs.existsSync(ancestor)) {
      if (!creating) throw Error('文件已不存在，可在改动列表查看删除内容。');
      ancestor = path.dirname(ancestor);
    }
    const real = fs.realpathSync(ancestor);
    if (real !== root && !within(real)) throw Error('该链接指向仓库外部，不能在这里读写。');
    if (fs.existsSync(target) && fs.lstatSync(target).isSymbolicLink()) throw Error('链接文件请在文件管理器中处理。');
    return target;
  }
  git(args, options = {}) {
    this.requireEnabled();
    return new Promise((resolve, reject) => execFile('git', ['--literal-pathspecs', '-C', this.directory, '-c', 'color.ui=false', ...args], {
      windowsHide: true, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024,
      timeout: options.network ? 60000 : 20000,
      env: {...process.env, GIT_TERMINAL_PROMPT:'0', GCM_INTERACTIVE:'never', GIT_MERGE_AUTOEDIT:'no'}
    }, (error, stdout, stderr) => {
      if (!error || options.noMatches && error.code === 1) return resolve(stdout || '');
      let message = 'Git 操作未完成，请确认仓库和 Git 安装正常。';
      if (/authentication|permission denied|could not read Username|403|401/i.test(stderr || '')) message = '本机 Git 尚未登录，或没有远程仓库权限。请先完成 Git 登录后重试；本地修改仍保留。';
      else if (/user\.email|identity unknown|unable to auto-detect email/i.test(stderr || '')) message = '首次提交需要填写 Git 姓名和邮箱。';
      else if (/CONFLICT|unmerged|resolve your current index/i.test(stderr || '')) message = '合并遇到冲突。打开标有冲突的文件，修正后保存并标记已解决，再次同步。';
      else if (/rejected|non-fast-forward|fetch first/i.test(stderr || '')) message = '远程已有新提交，本地版本已保留。请拉取更新后再次同步。';
      else if (/index\.lock|another git process/i.test(stderr || '')) message = '仓库正在被其他 Git 操作使用，请稍后重试。';
      else if (/Could not resolve|Failed to connect|timed out|unable to access/i.test(stderr || '') || error.killed) message = '远程连接未完成，请检查网络后重试；本地修改仍保留。';
      reject(Error(message));
    }));
  }
  async status() {
    const root = this.root();
    if(this.plain)return {context:this.context(),path:root,name:path.basename(root),branch:'本地文件夹',plain:true,files:[],conflicts:0,ahead:0,behind:0,hasRemote:false,detached:true};
    const raw = await this.git(['status', '--porcelain=v1', '-z', '--untracked-files=all']);
    const entries = raw.split('\0'), files = [];
    for (let i = 0; i < entries.length; i++) {
      if (!entries[i]) continue;
      const code = entries[i].slice(0,2), file = entries[i].slice(3);
      const oldFile = /[RC]/.test(code) ? entries[++i] : null;
      files.push({code, file, oldFile, conflict:CONFLICT.has(code)});
    }
    const values = await Promise.all([
      this.git(['branch','--show-current']),
      this.git(['rev-parse','HEAD']).catch(() => ''),
      this.git(['rev-parse','--abbrev-ref','--symbolic-full-name','@{upstream}']).catch(() => ''),
      this.git(['config','user.name']).catch(() => ''),
      this.git(['config','user.email']).catch(() => ''),
      this.git(['rev-parse','-q','--verify','MERGE_HEAD']).catch(() => '')
    ]);
    const [branch, head, upstream, authorName, authorEmail, mergeHead] = values.map(value => value.trim());
    const remote = branch ? (await this.git(['config',`branch.${branch}.remote`]).catch(() => '')).trim() || 'origin' : 'origin';
    const remoteURL = (await this.git(['remote','get-url',remote]).catch(() => '')).trim();
    const remoteBranch = branch ? (await this.git(['config',`branch.${branch}.merge`]).catch(() => '')).trim().replace(/^refs\/heads\//,'') || branch : '';
    const githubMatch = remoteURL.match(/github\.com[/:]([^/\s]+\/[^/\s]+?)(?:\.git)?$/);
    let remoteDisplay = '';
    try { const url = new URL(remoteURL); remoteDisplay = url.hostname + url.pathname; } catch (_) { remoteDisplay = remoteURL.replace(/^.*@/,''); }
    const counts = upstream ? (await this.git(['rev-list','--left-right','--count','HEAD...@{upstream}']).catch(() => '0\t0')).trim().split(/\s+/).map(Number) : [0,0];
    const stamps = files.map(item => {
      try { const stat = fs.lstatSync(this.resolve(item.file)); return [item.file,stat.size,stat.mtimeMs,stat.ctimeMs]; }
      catch (_) { return [item.file,null]; }
    });
    const indexPath = (await this.git(['rev-parse','--git-path','index'])).trim();
    let indexStamp = ''; try { const stat = fs.statSync(path.resolve(root,indexPath)); indexStamp = `${stat.size}:${stat.mtimeMs}:${stat.ctimeMs}`; } catch (_) {}
    return {context:this.context(), path:root, name:path.basename(root), branch:branch || '分离 HEAD', detached:!branch,
      files, mergePending:Boolean(mergeHead), conflicts:files.filter(file => file.conflict).length,
      ahead:counts[0] || 0, behind:counts[1] || 0, remote, remoteBranch, remoteDisplay, hasRemote:Boolean(remoteURL),
      authorName, authorEmail, needsIdentity:!authorName || !authorEmail,
      github:githubMatch ? 'https://github.com/' + githubMatch[1] : '',
      snapshot:hash(JSON.stringify([this.context(),raw,head,upstream,indexStamp,stamps,remote,remoteBranch,remoteURL]))};
  }
  async files() {
    if(this.plain){const root=this.root(),files=[];const visit=(folder,prefix='')=>{for(const item of fs.readdirSync(folder,{withFileTypes:true})){if(files.length>=20000)return;if(item.isSymbolicLink()||['.git','node_modules'].includes(item.name))continue;const name=prefix+item.name;if(item.isDirectory())visit(path.join(folder,item.name),name+'/');else if(item.isFile())files.push(name);}};visit(root);return {context:this.context(),files,truncated:files.length>=20000};}
    const raw = await this.git(['ls-files','--cached','--others','--exclude-standard','-z']);
    const files = [...new Set(raw.split('\0').filter(Boolean))].sort((a,b) => a.localeCompare(b));
    return {context:this.context(), files:files.slice(0,20000), truncated:files.length > 20000};
  }
  read(file) {
    const target = this.resolve(file), stat = fs.statSync(target);
    if (!stat.isFile()) throw Error('请选择一个文件。');
    const extension = path.extname(file).toLowerCase();
    const info = {file, context:this.context(), size:stat.size, editable:false, canOpen:DOCUMENTS.has(extension)};
    if (['.pdf','.doc','.docx','.xls','.xlsx','.ppt','.pptx','.rtf'].includes(extension)) return {...info,kind:'external',hint:'使用本机软件查看或编辑此文档。'};
    if (stat.size > TEXT_LIMIT) return {...info, kind:'external', hint:'文件较大，请使用本机软件打开。'};
    const bytes = fs.readFileSync(target), version = hash(bytes);
    if (['.png','.jpg','.jpeg','.gif','.webp','.bmp'].includes(extension)) {
      const type = {'.jpg':'jpeg','.jpeg':'jpeg','.bmp':'bmp'}[extension] || extension.slice(1);
      return {...info,version,kind:'image',url:`data:image/${type};base64,${bytes.toString('base64')}`};
    }
    let encoding = 'utf8', bom = '';
    let content = bytes;
    if (bytes[0] === 0xff && bytes[1] === 0xfe) { encoding='utf16le'; bom='fffe'; content=bytes.subarray(2); }
    else if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) { bom='efbbbf'; content=bytes.subarray(3); }
    else if (bytes.includes(0)) return {...info,version,kind:'external',hint:'此文件请使用本机软件查看或编辑。'};
    try {
      const text = new TextDecoder(encoding === 'utf16le' ? 'utf-16le' : 'utf-8',{fatal:true}).decode(content);
      return {...info,version,kind:'text',editable:true,text,encoding,bom,eol:text.includes('\r\n') ? '\r\n' : '\n'};
    } catch (_) { return {...info,version,kind:'external',hint:'当前编码不适合直接编辑，请使用本机软件打开。'}; }
  }
  async save(value) {
    if (this.busy) throw Error('正在同步仓库，请等待完成后保存。');
    this.requireContext(value?.context);
    if (typeof value.text !== 'string' || value.text.length > TEXT_LIMIT) throw Error('文本超过编辑大小限制。');
    const item = this.read(value.file);
    if (!item.editable) throw Error('该文件不能在工作区直接编辑。');
    if (item.version !== value.version) throw Error('文件已被其他软件修改，未覆盖。请先保留当前文字，再重新打开文件。');
    if (value.resolveConflict && /^(<<<<<<< |=======\s*$|>>>>>>> )/m.test(value.text)) throw Error('文件仍有冲突标记，请修正后再标记已解决。');
    const text = value.text.replace(/\r\n|\r/g,'\n').replaceAll('\n',item.eol);
    const bytes = Buffer.concat([Buffer.from(item.bom,'hex'),Buffer.from(text,item.encoding)]);
    if (bytes.length > TEXT_LIMIT) throw Error('文本超过编辑大小限制。');
    const target = this.resolve(value.file), temporary = path.join(path.dirname(target), '.workbench-save-' + crypto.randomBytes(8).toString('hex'));
    try {
      fs.writeFileSync(temporary,bytes,{flag:'wx',mode:fs.statSync(target).mode});
      if (hash(fs.readFileSync(target)) !== item.version) throw Error('文件刚被其他软件修改，未覆盖。');
      fs.renameSync(temporary,target);
    } finally { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); }
    if (value.resolveConflict) await this.git(['add','--',value.file]);
    return this.read(value.file);
  }
  create(file, context) {
    if (this.busy) throw Error('正在同步仓库，请等待完成后创建文件。');
    this.requireContext(context);
    const extension = path.extname(file).toLowerCase();
    if (!TEXT_FILES.has(extension) && !['README','LICENSE','Dockerfile','Makefile','.gitignore','.gitattributes'].includes(path.basename(file))) throw Error('请创建文本、Markdown 或源码文件；文档可通过文件管理器加入。');
    const target = this.resolve(file,true);
    fs.mkdirSync(path.dirname(target),{recursive:true});
    try { fs.writeFileSync(target,'',{flag:'wx'}); } catch (error) { if (error.code === 'EEXIST') throw Error('同名文件已存在，请直接打开。'); throw error; }
    return this.read(file);
  }
  async search(query, context) {
    this.requireContext(context);
    if (typeof query !== 'string' || !query.trim() || query.length > 160 || /[\r\n\x00]/.test(query)) return [];
    const raw = await this.git(['-c','core.quotePath=false','grep','--untracked','-n','-I','-i','-F','-m','3','-e',query,'--'],{noMatches:true});
    const result=[];
    for (const row of raw.split('\n')) {
      const match=row.match(/^(.+?):(\d+):(.*)$/); if (!match) continue;
      try { this.resolve(match[1]); } catch (_) { continue; }
      result.push({file:match[1],line:Number(match[2]),text:match[3].slice(0,250)});
      if (result.length >= 120) break;
    }
    return result;
  }
  async diff(file) {
    const status = await this.status(), item=status.files.find(row => row.file === file);
    if (!item) return '该文件暂无改动。';
    if (item.code === '??') { const value=this.read(file); return value.editable ? '── 新文件 ──\n' + value.text : '新文件，使用本机软件查看。'; }
    const working = await this.git(['diff','--no-ext-diff','--no-textconv','--',file]);
    const staged = await this.git(['diff','--cached','--no-ext-diff','--no-textconv','--',file]);
    return [staged && '── 已暂存 ──\n'+staged,working && '── 工作区 ──\n'+working].filter(Boolean).join('\n') || '该文件暂无文本差异。';
  }
  async history() {
    const raw = await this.git(['log','-30','--format=%h%x09%s%x09%an%x09%ar']).catch(() => '');
    return raw.trim().split('\n').filter(Boolean).map(line => { const [hash,subject,author,ago]=line.split('\t'); return {hash,subject,author,ago}; });
  }
  async identity(status, value) {
    if (!status.needsIdentity) return;
    const name=String(value?.name || '').trim(), email=String(value?.email || '').trim();
    if (!name || name.length > 100 || /[\r\n\x00]/.test(name) || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254) throw Error('首次提交请填写 Git 姓名和邮箱，只需设置一次。');
    await this.git(['config','--local','user.name',name]);
    await this.git(['config','--local','user.email',email]);
  }
  async perform(action, value) {
    if (this.busy) throw Error('仓库操作正在进行，请等待完成。');
    this.requireContext(value?.context);
    this.busy=true;
    let committed=false;
    try {
      const status=await this.status();
      if (status.snapshot !== value.snapshot) throw Error('改动已经变化，请重新查看同步列表后再确认。');
      if (status.detached) throw Error('当前没有选中的分支，请先在 Git 工具中选择分支。');
      if (status.conflicts) throw Error('请先修正标有冲突的文件，保存并标记已解决，然后同步。');
      if (!['commit','sync','pull'].includes(action)) throw Error('操作无效。');
      if (action !== 'commit' && !status.hasRemote) throw Error('尚未关联远程仓库。可以先保存本地版本，再在 Git 工具中配置远程。');
      if (action !== 'commit' && !/^[a-zA-Z0-9][\w.-]*$/.test(status.remote)) throw Error('远程名称不适合快速同步，请使用 Git 工具处理。');
      if (action === 'pull' && status.files.length) throw Error('有未保存为版本的改动，请先提交或同步，再拉取。');
      if (status.files.length || status.mergePending) {
        const note=String(value.message || '').trim() || (status.mergePending ? '合并团队更新' : '更新 ' + status.files.length + ' 个文件');
        if (note.length > 500 || /\x00/.test(note)) throw Error('提交说明过长。');
        await this.identity(status,value.identity);
        const names=[...new Set(status.files.flatMap(item => item.oldFile ? [item.file,item.oldFile] : [item.file]))];
        if (names.length > 300) throw Error('改动文件较多，请使用 Git 工具分批提交。');
        if (names.length) await this.git(['add','--all','--',...names]);
        await this.git(['commit','-m',note]); committed=true;
      }
      if (action === 'commit') return {message:committed ? '本地版本已保存。' : '没有需要提交的改动。',status:await this.status()};
      await this.git(['fetch',status.remote],{network:true});
      const remoteRef='refs/remotes/'+status.remote+'/'+status.remoteBranch;
      const exists=await this.git(['rev-parse','--verify',remoteRef]).catch(() => '');
      if (exists) {
        const counts=(await this.git(['rev-list','--left-right','--count','HEAD...'+remoteRef])).trim().split(/\s+/).map(Number);
        if (counts[1]) {
          if (counts[0]) await this.identity(status,value.identity);
          await this.git(['merge','--no-edit',remoteRef]);
        }
      } else if (action === 'pull') throw Error('远程还没有这个分支，可点击同步上传。');
      if (action === 'sync') await this.git(['push','--set-upstream',status.remote,'HEAD:refs/heads/'+status.remoteBranch],{network:true});
      return {message:action === 'pull' ? '已拉取团队更新。' : '已提交并同步到远程仓库。',status:await this.status()};
    } catch (error) {
      if (committed) error.message += ' 本地提交已保存，无需重复提交。';
      throw error;
    } finally { this.busy=false; }
  }
}
module.exports = {Repository, DOCUMENTS};
