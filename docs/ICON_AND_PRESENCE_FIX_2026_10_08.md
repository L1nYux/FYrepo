# 0.4.3 图标与在线状态修正

## 已发现的缺漏

- Windows 窗口只传入 `relaunchDisplayName`，没有配套 `relaunchCommand`。
- 任务栏图标引用 EXE 资源，未提供独立的、位于 ASAR 外的 ICO 文件。
- 开发版和安装版使用同一个应用 ID，开发运行可能影响窗口分组识别。
- 新私聊列表、私聊标题和通讯录没有在线状态标记。
- 在线写入和查询使用当前空间的 `UserPresence.objects`，与好友及跨团队聊天不一致。

## 改动

- 补齐应用 ID、显示名称、重新启动命令及 ICO 属性；窗口显式设置同一个 ICO。
- 打包添加 `resources/zhiyu.ico`，从原有品牌图标复制，保留安装版应用 ID。
- 开发版使用独立 ID。启动时只更新目标为当前安装 EXE 的快捷方式图标和 ID；不删除用户快捷方式、清空系统图标缓存或重启 Explorer。
- 添加在线/离线文字及状态点，未知状态单独显示。
- 心跳只更新本人个人空间中的最新时间，跨团队选择不影响状态；不产生业务审计记录。
- 查询范围限于好友及有效共同团队的正式成员。沿用原来的 90 秒活动心跳判定，没有添加活动历史或最后在线时间。
- 在线状态修复需要服务器更新。服务端增量源码包先校验 0.4.2 及待替换文件哈希，在临时目录构造新源码，再调用原保留数据升级脚本；不直接修改运行目录。没有数据库结构迁移。

## 核验范围

Python 解析、Django 模板编译、变更 JavaScript 语法检查及打包文件一致性检查。实际 taskbar 显示需新客户端启动后核对，不能仅凭 EXE 中有图标判断成功。

本轮 computer-use 工具初始化与重置后均报“failed to write kernel assets / 系统找不到指定的路径”，无法自动截图核验。未通过其他 Windows UI 自动化绕过此限制。

## 参考

- [Electron BrowserWindow.setAppDetails](https://www.electronjs.org/docs/latest/api/browser-window#winsetappdetailsoptions-windows)：重启命令和显示名称须同时设置。
- [Windows RelaunchIconResource](https://learn.microsoft.com/en-us/windows/win32/properties/props-system-appusermodel-relaunchiconresource)：可直接指定 ICO 路径，需显式窗口应用 ID。
