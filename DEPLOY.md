# Pixel Memory V9 · 部署说明

## 推荐架构

```text
网页 / 微信小程序
        │
        ├── HTTPS REST：创建房间、读取房间、保存内容、上传录音
        │
        └── WSS：人物移动、聊天、庆祝、Memory Quest 实时同步
                         │
                   V9 Node Server
```

## 方案 A：前后端一起部署（最省事）

V9 的 `server/server.js` 会直接托管项目根目录，因此部署整个 `pixel-memory-world-v9` 后，只需要一个域名：

```text
https://memory.example.com
```

网页、API、WSS、录音文件都在同域。

服务器命令：

```bash
node server/server.js
```

或用根目录旁提供的 Dockerfile：

```bash
docker build -f server/Dockerfile -t pixel-memory-v9 .
docker run -p 8787:8787 pixel-memory-v9
```

## 方案 B：GitHub Pages + 独立实时服务器

网页继续部署在 GitHub Pages：

```text
https://you.github.io/pixel-memory-world/
```

Node 服务部署在：

```text
https://api.example.com
```

第一次访问网页加参数：

```text
https://you.github.io/pixel-memory-world/?server=https://api.example.com
```

V9 会把这个服务器地址保存在浏览器 localStorage，之后自动使用。

## 微信小程序

1. 在微信公众平台注册小程序并取得 AppID。
2. 微信开发者工具 → 导入项目 → 选择 `miniprogram/`。
3. 将 `project.config.json` 的 `touristappid` 换成自己的 AppID。
4. 把 `miniprogram/app.js` 的 `serverUrl` 换成公网 HTTPS 域名。
5. 微信公众平台配置：
   - request 合法域名：`https://api.example.com`
   - socket 合法域名：`wss://api.example.com`
6. 开发工具中测试创建房间、邀请码加入、移动、聊天、录音。
7. 完成小程序隐私说明、类目和审核材料后提交体验版 / 审核版。

## 正式上线前的后端升级

当前 V9 是可跑的 Demo 服务，单实例就能测试真实联机。正式产品建议：

- rooms.json → CloudBase / PostgreSQL
- uploads → COS / CloudBase Storage / R2
- 游客 playerId → OpenID / 匿名账号体系
- WebSocket 单实例 → 支持多实例广播的实时层
- 给房间增加过期时间、房主权限、踢人/锁房、限流与文件安全校验
- 照片/录音增加访问权限与删除机制
