# 服务端部署与恢复

API、任务 worker、PostgreSQL、HTTPS 入口分别运行，图片和平台媒体使用持久卷。现在交付部署配置，实际阿里云目标和域名仍待确认，尚未上线。

## 阿里云测试环境

在确认的 Linux 服务器安装 Docker Engine 与 Compose。仓库克隆后：

```sh
cp deploy/production.env.example deploy/production.env
# 私下填写数据库密码、域名、模型接口和密钥。
# 数据库密码使用随机十六进制字符串，避免 URL 转义问题。
docker compose --env-file deploy/production.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/production.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/production.env -f deploy/compose.yaml ps
```

DNS 指向该服务器，安全组开放 80/443；数据库和 API 没有对公网映射端口。Caddy 自动申请证书，需实际域名及可访问的 80/443。若服务器已有其他站点占用这些端口，应接入已有反向代理，不能直接替换。新环境不依赖本机个人网关；配置可用于商业服务的模型 API。

`GET /api/health` 检查数据库，`workerActive` 反映共享卷心跳是否在一分钟内更新。worker 每 20 秒续租，意外中断后其他 worker 可以接管；同一道菜在同一任务内使用稳定编号。外部模型请求存在重复计费可能：进程在调用完成但保存前崩溃时，恢复需要重新调用。

任务默认每账号最多 3 个待处理、每日 30 个新任务、3 次执行机会；家庭图片默认 250 MB。模型用量保存成功状态、模型名、token 和耗时，未知 token 留空。当前没有支付、套餐或虚构的模型价格。

## 私有备份与跨数据库迁移

```sh
python database_tools.py backup /private-backups/kitchen-20261012.zip
# 只允许恢复到空数据库；设置目标 DATABASE_URL 与 BLOB_ROOT 后执行。
python database_tools.py restore /private-backups/kitchen-20261012.zip
# 迁移旧 SQLite 时保留原文件，并在空 PostgreSQL 执行：
python database_tools.py import-sqlite /private-backups/accounts.sqlite3
```

备份 ZIP 包含账号密码散列、会话、家庭、业务回执、任务事件、用量和私有图片。它不是可以公开分享的菜谱导出；应加密存放并限制权限。恢复失败事务回滚，新增图片撤回；拒绝路径穿越和覆盖不同内容。备份文件名必须全新，避免覆盖上一份。

平台抽帧、下载媒体在 `media` 持久卷，单独备份该卷，并与数据库/图片备份配套恢复。暂停 worker 后做成套备份可避免正在下载的媒体缺失；API 停止时也禁止写入。SQLite 在线备份和 PostgreSQL 一致性读取保证数据库快照，跨卷不能自动保证同一时刻。

上线前至少完成一次异机恢复演练，检查两账号、家庭菜谱、库存、照片、来源证据和任务重试。可执行 `python scripts/clean_orphans.py` 清理超过 24 小时且没有文件元数据的回滚遗留图片；现有业务图片和来源证据不自动删除。

## 本机运行与 App

`python run.py` 启动 API 和 worker，按配置复用本机网关；`python server.py` 只启动 API，另开 `python worker.py`。SQLite 可用于本机验收，正式部署通过 `DATABASE_URL` 使用 PostgreSQL。

安卓构建：安装 Node 22、Java 21 和 Android SDK 35，执行 `npm ci`、`python scripts/sync_native.py`、`npx cap sync android`，再在 android 目录运行 `gradlew assembleDebug`。`APP_API_URL` 指定服务端根地址，模拟器使用 `http://10.0.2.2:8767`，真实手机使用可访问的服务器地址。登录前可在 App 设置里修改连接地址；发布构建设置 `APP_RELEASE=1`，强制 HTTPS。

调试 APK 适合安装测试。正式签名密钥、AAB、商店资料和发布流程尚需配置，私钥不入 Git。iOS 必须使用 macOS/Xcode，仓库 CI 会尝试无签名模拟器编译、安装、启动并留截图；模拟器 .app 不能当作 iPhone 可安装 IPA，真机/TestFlight 需要 Apple 开发者签名。

离线支持已同步的菜谱、做饭记录、下载完成的照片和编辑草稿。后台按账号下载照片，网络中断可能留下待下载图片；共享库存与本餐写入仍需联网确认。退出清除该账号本地留档。

原服务器无法连接且 App 显示离线时，可在「我的 → 设置 → 服务器连接」明确确认「退出本机，重新连接」。这会清除设备 Cookie 以及该账号的留档、照片和草稿，随后可设置新地址；云端数据保留，无法联系的旧服务器会话尚未撤销。在线时通过正常退出撤销服务端会话，再切换地址。

## 尚待上线验证

实际服务器资源与 DNS/HTTPS；真实 Android 手机及 iPhone；真实平台链接的限流/验证码和模型商业授权；账号找回、邀请失效及家庭管理完整规则；持久卷容量告警、定时备份和保留期限。商业公开前还需要隐私条款和运营规则。
