"""Prepare a self-contained group delivery with pinned server instructions."""
import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def build(assets, output, commit):
    if not re.fullmatch(r'[0-9a-f]{40}',commit):raise ValueError('Expected full Git commit')
    version=json.loads((ROOT/'desktop/package.json').read_text(encoding='utf-8'))['version']
    names=[f'ResearchWorkbench-{version}-{platform}.{extension}' for platform,extension in [('win-x64','exe'),('mac-arm64','dmg'),('mac-x64','dmg')]]
    for name in names:
        if not (assets/name).is_file() or (assets/name).stat().st_size<1024*1024:raise ValueError('Missing installer: '+name)
    folder=output/f'科研工作台-{version}-安装包'
    folder.mkdir(parents=True,exist_ok=True)
    for name in names:shutil.copy2(assets/name,folder/name)
    server=f'{version}-服务器更新.txt'
    directory=f'/root/workbench-{version}-{commit[:7]}'
    command=f'mkdir -p {directory} && curl -fL --connect-timeout 20 --retry 2 https://codeload.github.com/L1nYux/FYrepo/tar.gz/{commit} -o {directory}/source.tar.gz && tar -xzf {directory}/source.tar.gz -C {directory} --strip-components=1 && bash {directory}/deploy/upgrade_preserve_data.sh --apply'
    (folder/server).write_text(f'科研工作台 {version} 服务器升级\n\n先登录服务器并执行：\nsudo -i\n\n再粘贴：\n{command}\n\n升级脚本备份原数据库、附件和环境配置，保留账户、SMTP 与 API Key。\n请等待“升级完成”，然后重新打开客户端。客户端自动更新不会代替服务器升级。\n部署后检查 /healthz/ 返回 status=ok。\n',encoding='utf-8')
    (folder/'安装与自动更新.txt').write_text(f'科研工作台 {version}\n\nWindows：运行 win-x64.exe 安装，保留原配置。\nApple 芯片 Mac：使用 mac-arm64.dmg；Intel Mac：使用 mac-x64.dmg，拖到应用程序覆盖安装。\n免费 Mac 版本没有 Apple 付费签名；首次安装如被系统拦截，可在系统设置 → 隐私与安全性中批准打开。\n\n已安装 0.2.9 或更高版本：点击头像旁的更新按钮检查、下载并确认安装。免费 Mac 下载后仍需拖动覆盖。\n管理员还需按本文件夹内的 {server} 同步升级服务端。\n',encoding='utf-8')
    shutil.copy2(ROOT/'docs/DESKTOP_RELEASE_NOTES.md',folder/f'{version}-功能与更新说明.md')
    (folder/'群发说明.txt').write_text(f'科研工作台 {version}：按自己的系统选择安装包，更新后仍使用原账户登录。已装 0.2.9 的成员也可以点击头像旁的更新按钮。\n',encoding='utf-8')
    hashes={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in names}
    (folder/'SHA256.txt').write_text(''.join(f'{value}  {name}\n' for name,value in hashes.items()),encoding='utf-8')
    (folder/'构建信息.json').write_text(json.dumps({'version':version,'commit':commit,'installers':hashes},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Check references before archiving; no parent-directory dependencies.
    assert (folder/server).is_file() and '../' not in (folder/'安装与自动更新.txt').read_text(encoding='utf-8')
    archive=output/f'科研工作台-{version}-Windows-Mac-群发包.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as bundle:
        for name in sorted(names+[server,'安装与自动更新.txt',f'{version}-功能与更新说明.md','群发说明.txt','SHA256.txt','构建信息.json']):
            file=folder/name;bundle.write(file,folder.name+'/'+name)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip():raise ValueError('Delivery archive verification failed')
    print(archive)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--commit',required=True)
    args=parser.parse_args()
    build(args.assets,args.output,args.commit)
