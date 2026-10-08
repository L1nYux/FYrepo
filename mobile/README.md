# 知域 Android 手机版

原生 Java + 手机系统 WebView，不携带 Chromium 或服务器运行环境。
Android 8.0 及以上。初始服务器：`http://47.117.89.248`。
在右上角「⋯ → 连接设置」更换服务器。

## 手机布局

- 消息：单列会话与通讯录，进入聊天后整屏显示，保留群设置、图片、附件及积分红包。
- AI：整屏对话，侧栏历史、团队和模型选择、图片与工作资料引用。
- 团队：切换团队，直接使用 API Key、模型和额度，查看成员、公告及招募。
- 我：资料、账号安全、人才资料、通知、积分与退出登录。

采集器、样本库、平台后台、API 池配置、Office 编辑和本地仓库操作请在电脑版完成。
手机沿用服务器现有账号、CSRF、成员权限、API 计费和额度。
WebView 只对配置的服务器注入手机版布局；外部链接经确认后交给系统浏览器。
文件通过系统选择器上传和保存，不申请整个手机存储权限。

## 当前限制

- 是连接现有服务器的轻量客户端，需联网使用。
- 暂无后台推送、离线消息或语音通话；关闭到后台后，重新打开同步消息。
- 首版为浅色主题。没有应用商店分发和应用内自动更新。
- 编译与签名检查通过不代表真实 Android 手机上所有交互都已经验证。

## 编译

使用 JDK 17、Gradle 8.11.1、Android SDK 35 与 Build Tools 35.0.0。
设置 `ZHIYU_KEYSTORE` 指向 PKCS12 文件，设置 `ZHIYU_SIGNING_PASSWORD`，
密钥别名为 `zhiyu-mobile`。签名私钥不得提交到仓库。

```text
cd mobile
gradle :app:assembleRelease
```

GitHub Actions 的 `Android APK` 工作流仅在手动触发时编译。
仓库密钥：`ZHIYU_ANDROID_KEYSTORE_BASE64` 与 `ZHIYU_ANDROID_SIGNING_PASSWORD`。
