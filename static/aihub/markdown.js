/* Small DOM-only Markdown renderer. Raw HTML is always text; links are checked. */
(() => {
  function inline(parent, text, sources, depth = 0) {
    if (depth > 3) { parent.append(document.createTextNode(text)); return; }
    const tokens = /`([^`\n]+)`|\*\*([^*\n]+)\*\*|\[((?:[^\[\]\n]|\[[^\[\]\n]*\])+)\]\(([^\s()]+)\)/g;
    let start = 0, match;
    while ((match = tokens.exec(text))) {
      parent.append(document.createTextNode(text.slice(start, match.index)));
      const label = match[1] ?? match[2] ?? match[3];
      let node;
      if (match[1] !== undefined) node = document.createElement('code');
      else if (match[2] !== undefined) node = document.createElement('strong');
      else {
        const href = match[4]; let valid = false, external = false;
        if (sources.has(href)) valid = /^\/(?!\/)[^\\\s]*$/.test(href);
        else {
          try { const url = new URL(href); valid = ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password; external = valid; } catch (_) {}
        }
        node = document.createElement(valid ? 'a' : 'span');
        if (valid) { node.href = href; if (external) { node.target = '_blank'; node.rel = 'noopener noreferrer'; } }
      }
      node.textContent = label; parent.append(node); start = tokens.lastIndex;
    }
    parent.append(document.createTextNode(text.slice(start)));
  }
  function render(container, text, result = {}) {
    container.replaceChildren();
    const sources = new Set((result.sources || []).map(item => item.url));
    const lines = String(text || '').slice(0,160000).replace(/\r\n?/g, '\n').split('\n');
    let paragraph = [], list = null;
    const flush = () => { if (paragraph.length) { const p=document.createElement('p'); inline(p,paragraph.join('\n'),sources);container.append(p);paragraph=[]; } list=null; };
    for (let i=0;i<lines.length;i++) {
      const line=lines[i];
      if (/^\s*```/.test(line)) {
        flush();const pre=document.createElement('pre'),code=document.createElement('code'),block=[];
        while (++i<lines.length && !/^\s*```/.test(lines[i])) block.push(lines[i]);
        code.textContent=block.join('\n');pre.append(code);container.append(pre);continue;
      }
      if (!line.trim()) { flush();continue; }
      const heading=/^#{1,4}\s+(.+)$/.exec(line), item=/^\s*(?:([-*])|\d+[.)])\s+(.+)$/.exec(line);
      if (heading) { flush();const h=document.createElement('h3');inline(h,heading[1],sources);container.append(h); }
      else if (item) {
        if (paragraph.length) flush();const type=item[1]?'ul':'ol';
        if (!list || list.tagName.toLowerCase()!==type) { list=document.createElement(type);container.append(list); }
        const li=document.createElement('li');inline(li,item[2],sources);list.append(li);
      } else if (/^>\s?/.test(line)) { flush();const quote=document.createElement('blockquote');inline(quote,line.replace(/^>\s?/,''),sources);container.append(quote); }
      else { list=null;paragraph.push(line); }
    }
    flush();
  }
  window.workbenchMarkdown = render;
})();
