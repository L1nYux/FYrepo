# 服务器磁盘占用修正

## 已确认的原因

2026-10-08 的服务器统计显示 `/opt/research-workbench-releases` 占用约 13 GB。
多个旧版本各有约 658 MB 的 `.chromium`。每次升级都创建新虚拟环境，
复制浏览器文件并永久保留旧版本；之前的浏览器复用只节省网络下载。

## 本次修改

- 网页读取使用 `headless=True`，没有指定浏览器 channel 或 executable_path。
  安装改为 `playwright install --with-deps --only-shell chromium`，只准备
  headless shell 和其依赖。无需再安装完整 GUI Chromium。
- 从完整安装的同版本浏览器组件复用文件时，采用硬链接共享磁盘内容。
  仅共享 root 所有、组和其他用户均不能写入的文件。跨文件系统或不支持
  硬链接时使用独立复制，并输出两种文件的数量。
- 各应用版本保留独立的浏览器路径和 Python 环境。删除一个旧目录只删除
  对应硬链接，不会破坏仍然保留的版本。Playwright 的垃圾回收也仅作用于
  当前目录，避免不同版本相互清除运行环境。
- pip 安装增加 `--no-cache-dir`，避免每次升级继续积累下载缓存。
- 正式升级成功后删除隔离的迁移检查副本，执行旧版本保留规则。

Playwright 官方的 headless shell 安装说明：
https://playwright.dev/python/docs/browsers#chromium-headless-shell

## 旧版本清理工具

`deploy/prune_releases.py` 默认只打印清理计划；`--apply` 才执行删除。
它只处理 `/opt/research-workbench-releases/时间戳` 下的正常代码版本目录。

保留：

- 主服务当前版本及一个最近的旧版本；
- 所有服务配置和运行进程引用的版本，包括定时任务和旧工作进程；
- 最近一次完整升级备份中记录的上一运行版本；
- 比当前版本更新的准备目录，以及通过 `--protect` 指定的源码或数据目录；
- 发现 API 密钥文件、正式数据库、环境配置或挂载点的目录。

读取服务/进程信息失败、无法确定当前版本、目录状态变化时停止清理。
不删除 `/var/lib/research-workbench`、`/etc/research-workbench.env` 或
`/var/backups/research-workbench`。备份占用需要单独统计后再制定保留策略。

把清理脚本上传到服务器的 `/tmp/prune_releases.py` 后：

```bash
sudo python3 /tmp/prune_releases.py
```

核对输出中的保留目录和清理目录，再执行：

```bash
sudo python3 /tmp/prune_releases.py --apply
sudo du -h --max-depth=1 /opt/research-workbench-releases
df -h /
```

清理本身不会重启服务或修改数据库，也不会立即将保留版本的浏览器转换为
硬链接。新的浏览器安装规则在下一次使用更新后的升级脚本时生效。

## 核验范围

本地仅做代码审查、Python 和 Bash 语法检查。Windows 环境不能验证 Linux
的 systemd、硬链接、AppArmor 和 Chromium 启动行为。下一次服务器升级仍需
安装脚本自带的沙盒启动检查通过；失败时不会切换服务。
