# 小小世界 · Pixel Memory V9

V9 在 V8 的“纪念大厅 + 房间里的门 + Memory Quest 回忆寻宝”基础上，正式加入了 **跨设备联网架构**，并附带一个可导入微信开发者工具的 **微信小程序轻量版**。

## V9 最重要的变化

### 1. 六位邀请码现在可以真正跨设备联机
网页端仍使用熟悉的 6 位门牌号，例如 `8L3Q2K`，但实时层从 V8 的 `BroadcastChannel` 升级成：

- HTTP API：创建 / 查询 / 保存房间
- WebSocket：人物位置、聊天、庆祝、碰撞、Reaction、Memory Quest 同步
- 上传接口：录音等文件
- 本地兜底：没有服务器时自动回退到 BroadcastChannel，仍可做单机 / 同浏览器演示

这样部署服务器后，A 在电脑、B 在手机、C 在另一座城市，只要进入同一个房间码，就能处在同一个实时房间。

### 2. 同一个房间协议同时给网页和微信小程序使用
`server/` 是共享后端；网页端和 `miniprogram/` 都连接：

- `POST /api/rooms`
- `GET /api/rooms/:code`
- `PUT /api/rooms/:code`
- `POST /api/uploads`
- `WS /ws?room=...&channel=...&player=...`

因此“网页房间”和“小程序房间”不是两套孤岛。

### 3. Memory Quest 也进入联网模式
V8 的“想去看看外面？”保持不变：

**房间 → 靠近发光的门 → 想去看看外面？ → 进入回忆寻宝地图。**

V9 中，回忆地图的宝藏放置与路线更新可通过 WebSocket 同步；新设备进来时，服务器也会把已经保存的路线发给它。

### 4. 录音可以真正跨设备
V8 录音主要存在浏览器 IndexedDB。

V9 在配置联网服务器后，会同时把录音上传到 `/api/uploads`，宝藏保存 `voiceUrl`。因此朋友在另一台设备找到这个宝藏时，也能听到原来留下的声音。

## 目录结构

```text
pixel-memory-world-v9/
├── index.html
├── styles.css
├── app.js
├── quest.js
├── network.js           # V9 联网适配层
├── server/
│   ├── server.js        # REST + WebSocket + 文件上传
│   ├── package.json
│   ├── data/
│   └── uploads/
└── miniprogram/         # 微信小程序轻量版
    ├── app.js
    ├── app.json
    ├── app.wxss
    ├── project.config.json
    └── pages/
        ├── index/
        └── room/
```

# 本地运行：真正测试两台设备

## 1. 安装并启动服务器

```bash
cd server
npm install
npm start
```

默认启动：

```text
http://localhost:8787
```

服务器本身也会把 V9 网页一起托管出来，所以电脑直接打开：

```text
http://localhost:8787
```

即可。

## 2. 同一局域网手机测试

查电脑局域网 IP，例如 `192.168.1.20`，让电脑防火墙允许 8787 端口，然后手机浏览器打开：

```text
http://192.168.1.20:8787
```

电脑创建一个房间，把六位邀请码输到手机，即可测试真实跨设备状态同步。

> 这是开发测试。真正发给异地朋友时，服务器需要部署到公网 HTTPS，WebSocket 会自动使用 WSS。

# GitHub Pages 怎么办？

GitHub Pages 只能托管静态前端，不能运行 Node WebSocket 后端。

可以：

1. V9 前端继续放 GitHub Pages；
2. `server/` 部署到 CloudBase / Render / Railway / 云服务器等；
3. 打开前端时使用：

```text
https://你的用户名.github.io/pixel-memory-world/?server=https://你的后端域名
```

V9 会把这个服务器地址记在浏览器里，之后自动连接。

更省事的方式是让 Node 服务直接托管前端，这样前端和 WebSocket 同域，不需要额外配置。

# 微信小程序版

`miniprogram/` 可以作为微信开发者工具项目导入。

当前轻量版已经实现：

- 创建联网房间
- 六位邀请码加入
- 分享微信卡片，房间码直接写进分享路径
- 同房间在线人物
- 简单像素房间
- 方向按钮移动
- 实时聊天
- 全员“庆祝”状态
- 一键录音 / 停止
- 录音上传并广播给其他设备
- 播放最近收到的语音

V9 小程序的目标不是强行把网页 DOM 地图复制进去，而是先验证“同一房间后端 + 微信传播入口”。下一阶段可以把 Memory Quest 用 Canvas / 原生 View 或 Taro 逐步迁入。

## 小程序上线前必须改的配置

### `miniprogram/project.config.json`
把：

```json
"appid": "touristappid"
```

换成你自己的小程序 AppID。

### `miniprogram/app.js`
把：

```js
serverUrl: 'http://localhost:8787'
```

换成公网 HTTPS 服务，例如：

```js
serverUrl: 'https://memory.example.com'
```

并在微信公众平台配置对应的 request 合法域名和 socket 合法域名。生产环境应使用 HTTPS / WSS。

# V9 服务器的原型限制

为了让你现在就能跑通，`server/` 使用：

- 单个 Node 进程
- `rooms.json` 保存房间元数据
- 本地 `uploads/` 保存语音文件
- WebSocket 内存房间

这已经可以做公网 Demo，但不是最终生产架构。

真正上线建议把：

- `rooms.json` → CloudBase / PostgreSQL
- 本地 uploads → CloudBase Storage / COS / R2
- 单实例 WebSocket → CloudBase WebSocket / Redis pub-sub / 专门实时房间服务
- 游客 ID → 微信 OpenID / 匿名账号

这样才适合长期保存纪念日数据和多实例扩容。

# V9 推荐试玩顺序

1. `cd server && npm install && npm start`
2. 电脑打开 `http://localhost:8787`
3. 创建房间，得到六位邀请码
4. 手机通过局域网地址打开同一个 V9
5. 输入邀请码
6. 两边分别移动人物、聊天、按庆祝
7. 从房间的门进入 Memory Quest
8. 放下一段带录音的回忆
9. 在另一台设备走过去找到它并播放声音
10. 再把 `miniprogram/` 导入微信开发者工具，用相同后端测试微信入口
