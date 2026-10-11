# 客户端、服务端及 App 验收 · 2026-10-12

本轮交付范围为 P1 规则、P2 运行与数据库、P3 本地留档、P4 私有文件及持久任务、P5 部署服务和验证、Android 调试 App 及 iOS 可用构建条件。用户确认 SSH 目标后，追加完成阿里云公网部署；商店发布仍需配置。下方早期验收保留为检查点，当前结果见末尾云端验收。

## 已验证

- Python 118 项通过，包含真实 PostgreSQL、并发事务、幂等回执、任务租约和跨数据库备份恢复。完整结果见最终 CI 后端任务日志；本机 validation/backend-postgres-tests.log 保留早期 PostgreSQL 子集检查点。
- JavaScript 最终 69 项全部通过；涵盖家庭规则、界面交互、账号隔离、IndexedDB 草稿与照片，以及原生断网退出恢复。结果 validation/javascript-final.txt。
- 真实模型：文字生成一道菜；图片中的菜谱原文识别后整理，鸡蛋 2 个、番茄 200 克、盐 1 克、油 10 毫升保留。三次调用 token 与耗时落库，本机详情 validation/backend-real-ai.json。
- Android 15 模拟器实际安装 APK：注册、邀请入同家庭、Cookie 登录跨重启保持；App 点菜、网页锁定、App 使用 300 克并完成，另一端看到 500 → 200 克库存及一条做饭记录。实际图片上传创建持久任务成功。
- 原生断网验证使用仅针对测试端口 8771 的模拟器网络阻断：重开 App 可查看账号、6 道菜、1 餐和已下载头像；撤销阻断后恢复连接。没有重复启动服务器。
- 新增恢复路径：断网时从设置进入服务器连接，先展示本地留档/照片/草稿删除说明，用户确认后设备 Cookie 和当前账号 IndexedDB 留档均清空，重新设置连接地址成功。旧服务端会话未撤销的限制在界面说明。网络阻断规则已撤销。
- 最终安装包默认模拟器服务 http://10.0.2.2:8767。真机需在「我的 → 设置 → 服务器连接」输入实际可访问的服务器根地址。未把模型密钥、账号口令或服务器文件打包。
- CI [38162189586](https://github.com/zhnuc/food_menu/actions/runs/38162189586) 后端、Android、macOS iOS 三项成功；后端任务额外完成 Docker 镜像构建、Compose 配置验证和容器健康接口启动。
- 最终提交 f6d808e 的 CI [38171891049](https://github.com/zhnuc/food_menu/actions/runs/38171891049) 三项全部成功。后端日志确认 69 项 JavaScript、118 项 Python 全部通过；安卓 APK 和 iOS 模拟器 .app 均重新构建成功。
- 远程 iPhone 16 Pro 模拟器安装启动 .app 成功。检查新版截图确认状态栏安全区域修复有效，Logo、标题和导航正常显示；截图保存在 output/ios-simulator-latest/output/ios/launched.png。

## 产物与边界

- Android：output/together-kitchen-android-debug.apk，适合测试安装；不是商店签名 AAB。
- iOS：output/ios-simulator-latest.zip，内含模拟器 .app、启动信息和截图；不能作为真机 IPA 使用。CI 暂未配置实际 API 域名，iOS 只验收访客界面启动，没有验收真实家庭联网流程。
- 阿里云：deploy/compose.yaml、Caddyfile、配置模板及 docs/deployment.md 已交付。缺少明确 SSH 目标和域名，没有将项目部署到不明旧服务器。两台真实手机公网验收、Apple 签名、商店发布仍待后续。
- 商业开放前还有找回密码、家庭退出及邀请码规则、支付套餐、运营和隐私等工作。当前验收不等于完整商业上线。

## 追加实际阿里云验收

- 用户确认末尾 .204 的既有服务器，公钥登录成功；部署 PostgreSQL、API、worker、私有模型网关和 Caddy，保留原服务。敏感模型授权、数据库密码及备份均在服务器私有目录，未入 Git/App。
- 公网 https://47.98.127.204:58900 使用受信任的 IP 证书。443 在安全组链路不通，采用原已开放且空闲的 58900；保留 80 验证及证书持久卷自动续期。没有跳过 TLS 验证。
- 公网三个测试账号验证注册、Secure Cookie、家庭邀请、业务重放、500 → 200 克及只存一餐。图片对家庭成员开放、外部家庭 404、未登录 401。云端文字生成和图片 OCR 整理均真实调用，鸡蛋 2 个、番茄 200 克保留；3 次 token 用量及耗时落库。
- 云端 Chromium 实际启动成功。首次私有数据/图片及媒体备份成功，恢复至独立 SQLite，校验 3 个账号、3 个家庭、1 张图片、1 餐、2 个任务和 3 次用量。每日台北时间 03:00 的 systemd timer 已启用；异机备份、容量告警与保留策略尚待补充。
- 安卓新 APK 默认云端 HTTPS、禁止设置明文 HTTP。模拟器通过云端登录、重启、真实网络断开后恢复本地账号、恢复网络重连及原生头像上传。发现并修复切换服务器重载的名称遮蔽问题，实际重载已验证。
- 2f8890e 的 CI [38178098446](https://github.com/zhnuc/food_menu/actions/runs/38178098446) 后端、Android、iOS 三项全部成功；iOS 已重建为真实云端默认地址的模拟器包，不能用于真机安装，没有宣称 iPhone 家庭流程已完成。
- 测试结束按精确 ID 清理三个 QA 账号/家庭和两张测试图片，非测试账号保留。原生测试设备已退出 QA 账号，恢复联网；备份仍为私有。完整机器结果 output/cloud-acceptance-20261012.json，截图 output/playwright/cloud-*，iOS 云端版本 output/ios-simulator-cloud.zip。
