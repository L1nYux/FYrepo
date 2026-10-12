# 知域 iPhone 客户端

iOS 16 及以上。`Zhiyu-0.6.3-ios-unsigned.ipa` 是真实 iPhone 构建，需要用自己的 Apple ID 签名后安装，不需要购买开发者账号。

## Windows 安装

1. 按 [AltStore Classic 官方 Windows 指南](https://faq.altstore.io/altstore-classic/how-to-install-altstore-windows) 安装 AltServer 及其要求的 Apple 驱动。
2. 用数据线连接并信任 iPhone，通过 AltServer 安装 AltStore。Apple ID 只在自己的签名工具中输入。
3. 按官方指南在手机设置中信任该账号，并开启开发者模式。
4. 将 IPA 保存到 iPhone 的「文件」中，打开 AltStore → My Apps → 左上角 `+`，选择该 IPA。
5. 打开知域，连接团队服务器并登录。服务器需要升级到 0.6.3 才能使用本次手机额度管理修复。

普通 Apple ID 的签名有期限，需要定期在 AltStore 刷新。官方说明见 [Getting Started](https://faq.altstore.io/altstore-classic/your-altstore)。本包不能直接点击安装，也不是 App Store 或 TestFlight 包。

## 构建

在安装 Xcode 的 Mac 上执行 `python tools/prepare_ios.py`，再使用生成的 Xcode 项目构建。GitHub 的 `iPhone IPA` 工作流会生成未签名的设备 IPA，并启动模拟器检查登录页面。

客户端与 Android 共用手机页面资源，支持文件选择、带进度的下载、文件预览和分享、扫码及剪贴板。当前不提供后台推送。发布前检查设备平台、arm64 二进制及共享资源哈希；模拟器检查不等于真机安装验收。
