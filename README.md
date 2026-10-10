# 一起吃饭

分享小红书、B站或抖音链接，获取真实正文和媒体，生成菜谱卡，按选中的菜和份数汇总购物清单。

## 启动

```powershell
.venv/Scripts/python.exe run.py
```

打开 http://127.0.0.1:8767 。后台运行可加 `--background`。启动器复用已运行的服务，只管理自己启动的进程。

新环境安装：`uv venv .venv`，然后 `uv pip install --python .venv/Scripts/python.exe -r requirements.txt`。Python 主程序声明四项依赖：yt-dlp、imageio-ffmpeg、Playwright、Pillow；当前连带依赖总共7个包。Pillow只负责缩放、编号和拼图，不运行本地识别模型；抖音浏览器备用路线使用已安装的 Chrome。

本机已保留 AIClient2API 的 Node.js 生产依赖与 Google 授权，启动器同时启动该网关。只启动主后端可用 `.venv/Scripts/python.exe server.py`，网关需单独保持运行。

GitHub 仓库不包含本机 `.env`、账号数据库、下载媒体、个人授权网关目录或运行缓存。新克隆后先复制 `.env.example` 为 `.env`，配置自己的模型接口和密钥，再运行 `server.py`；账号、厨房与手写菜谱不依赖模型服务。若需要使用 `run.py` 的本机网关启动路线，请自行安装上述 AIClient2API 并配置个人授权。运行截图和模型原始验证结果仅保留在本机，应用使用的图标、插画和字体已随源码提交。

## 运行架构

```text
web/                     手机界面、菜谱流式展示、账号与家庭同步；保留本机体验
server.py                菜谱与账号API、静态文件服务
accounts.py              SQLite账号、密码散列、会话、家庭数据与版本检查
account_http.py          账号HTTP路由、登录Cookie与同源写入检查
recipe_batches.py        独立菜并行、归属不明整篇整理、每组缓存、合并结果
ai.py                    唯一模型配置、HTTP调用、JSON响应解析
local_media.py           小红书获取 + 三个平台共用的批量视觉识别
visual_pack.py           缩放、原图ID标注、四张一组的拼图
video_media.py           B站获取、抖音入口、下载、FFmpeg抽帧、媒体缓存
 douyin_media.py          抖音分享数据与独立无头Chrome备用获取
 bilinote_adapter.py      B站下载失败时的yt-dlp兼容下载
vendor/                  BiliNote下载补丁 + DyNote页面提取子集和许可证
services/AIClient2API/    独立Antigravity网关：授权刷新、Clash代理、模型协议转换
run.py                   一条命令启动后端和网关
```

主后端是 Python 标准库 HTTP 服务，账号与家庭数据使用标准库SQLite，默认保存到`.data/accounts.sqlite3`；不增加数据库安装依赖。AIClient2API仍使用上游授权与协议核心，与产品账号系统各自独立。

## 账号与家庭

手机页面“我的”可以登录或注册。当前使用账号名和密码，昵称可修改，头像可上传或恢复默认；设置里可以退出账号。注册会创建一个个人家庭，可选择把当前本机厨房、菜谱和日历带入新家庭。邀请其他成员使用各自账号输入家庭邀请码后，所有成员共享菜谱、储物空间、库存、菜单、准备进度和做饭记录；角色与当前页面是各设备自己的视图设置。

服务端验证Cookie对应的账号及家庭成员关系，不接收客户端指定的家庭ID作为写入权限。登录会话30天有效，退出立即撤销当前会话。密码采用带随机盐的scrypt，会话Cookie为HttpOnly、SameSite=Strict；密码和登录令牌不写入浏览器localStorage。实现依据：[OWASP密码存储](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)、[会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)。

家庭更改自动保存，前台约每4秒检查更新；相同版本只返回账号和家庭信息，不重复下载照片。多人同时更改会检查版本，拒绝覆盖较新的记录并刷新提示重试。网络失败恢复已保存版本，未保存输入保留在该账号的本机恢复备份中。退出清除当前账号显示缓存，本机体验记录和服务器家庭记录保留。

当前是本地服务器账号，尚未部署公网、接短信或邮箱验证、找回密码。两台手机需要访问同一个后端地址；运行服务器前设置环境变量`HOST=0.0.0.0`可在家庭局域网访问电脑IP与8767端口。`preview_mobile.py`提供的纯静态预览不支持账号API。公网部署使用HTTPS并设置`ACCOUNT_SECURE_COOKIE=1`；数据库路径可通过`ACCOUNT_DB`指定。备份账号与家庭时停止服务后复制SQLite数据库，菜谱导出仅包含菜谱。

## 模型配置

编辑根目录 `.env`，两步AI调用共用接口地址和密钥，可以分别选择模型：

```ini
MODEL_BASE_URL=http://127.0.0.1:3000/v1
MODEL_API_KEY=本地网关访问密钥
MODEL_NAME=gemini-3.8-flash-low
VISION_MODEL_NAME=
RECIPE_MODEL_NAME=
PORT=8767
VISION_BATCH_SIZE=4
VISION_WORKERS=3
VISION_VIDEO_TILE_EDGE=480
VISION_PHOTO_TILE_EDGE=960
RECIPE_BATCH_SIZE=3
RECIPE_WORKERS=4
MEDIA_VIDEO_HEIGHT=480
VIDEO_FRAME_INTERVAL=3
DOUYIN_BROWSER_CHANNEL=chrome
```

`VISION_MODEL_NAME` 控制图片和视频帧识别，`RECIPE_MODEL_NAME` 控制菜谱整理；留空时使用 `MODEL_NAME`。模型名称必须是该接口支持的实际ID，读图模型需要支持图片输入。修改后重启Python后端；再次运行 `run.py` 会复用正在运行的服务，因此需要先停止已有后端。`/api/status` 返回当前两个模型名称。只改模型名称无需重启网关。

实际密钥只在本地配置中，浏览器不持有密钥。网关仍走 Clash http://127.0.0.1:7897，复用已有 Google OAuth 授权；没有复制浏览器Cookie。换读图模型会重做视觉识别；换整理模型会重做菜谱整理，并复用已有识别证据。

## 内容处理

1. 从完整分享文本取链接，按平台展开短链。
2. 获取标题、作者、正文和原始媒体。小红书使用yt-dlp；B站使用DASH画面流，失败时走BiliNote补丁；抖音优先分享页数据，必要时用Playwright和DyNote页面提取函数。
3. 视频用一次FFmpeg解码连续抽帧，间隔至少3秒，长视频限制约30帧。四张原图拼成一张并标注ID；视频拼图单格长边480像素，图文单格960像素，保持比例。每次最多4张拼图、默认3个并发请求；小任务会分配到多个请求，避免一批输出过长。模型只保留食材、用量、做法文字和简短操作，每张保留原图与位置引用，遗漏或重复ID视为识别失败，重试时只补缺失图。
4. 现有读图请求同时标记每段是否可独立整理（standalone），无需额外AI归属判断。只有本图明示菜名并有独立可用的食材和做法、无需其他图片接续时才标记为true；无菜名、备料/调汁/局部步骤、分步教程或不确定时标记false。只有所有图文段落都明确独立且超过3道菜时才并行：每个整理请求默认最多3道菜、最多4个请求并发，12道菜分为4组。任一段归属未确认、旧识别没有独立标记、存在未识别图片或跨帧/字幕证据时，正文和全部识别文字按原顺序交给一个整理请求，由它同时判断归属并生成完整菜谱。视频始终保留跨帧上下文。菜名只辅助分组，不凭图片数或菜名变化拆菜。模型返回紧凑JSON；后端还原原有字段。这一阶段不再次发送原始图片，步骤中的油、水、盐等不能为了精简省略。
5. 后端核对精确用量是否在引用中出现，缺失用量保留为空；食材别名、单位和份数用于合并购物清单。
6. 程序合并各组结果，返回浏览器生成菜谱卡；无需额外AI调用来合并。同菜片段由整理模型合成一张卡，后端拒绝重复拆出的同名卡，不再直接丢弃后面的同名片段以免漏步骤。每组独立缓存，失败组有明确警告，重试复用成功组。媒体及模型结果缓存留在data/，卡片选择和编辑留在原来的浏览器localStorage。timings.recipeRoute返回parallel或whole，便于核对实际路线。

菜谱接口为GET /api/status、POST /api/parse、POST /api/shopping；原始材料通过/media/提供。账号接口包括GET /api/account/session以及POST /api/account/register、login、logout、profile；家庭加入与保存为POST /api/household/join、save。API可供未来移动客户端复用，当前交付为手机网页。

## 耗时优化

媒体优先选择平台提供的低清视频流，不在下载后重新编码来声称节省下载量；小红书复用已获取的媒体信息下载，配图最多4张同时下载。视频连续抽帧使用FFmpeg的select过滤器，拼图使用Pillow缩放与合成（[FFmpeg文档](https://ffmpeg.org/ffmpeg-filters.html#select)、[Pillow文档](https://pillow.readthedocs.io/en/stable/reference/Image.html)）。不裁掉字幕，不强制缩小整张拼图到单格分辨率。

本机同一个小红书短链无缓存处理：优化前22.4秒，保留3秒采样的480像素拼图两轮为14.6和12.8秒；获取加抽帧约3–4秒，读图约5–7.5秒，菜谱约3.8秒。4秒采样虽然更快，但漏掉鸡蛋和淀粉水用量，未启用。抖音图文样例在媒体已缓存、读图和整理均重跑的条件下，完整12张卡从约46秒降至22秒。模型服务有请求超时波动，不能保证首次处理固定10秒。报告位于validation/speed-grid480-cold.json、speed-grid480-repeat.json、speed-grid960-photo.json；失败轮次也保留，不把缺帧结果算作成功提速。

重启后的真实HTTP接口验证：小红书媒体已缓存但重新读图、重新生成约10.3秒，再次使用全部缓存约0.6秒；B站从下载开始约18.3秒。购物接口使用同一份生成结果验证通过。报告分别为validation/http-optimized-speed.json、speed-grid-bili-cold.json。

2026-10-10增加按菜分组整理：图文12道菜拆为4个请求，每个3道菜。完整复测中整理约5.9秒、读图加整理约15.7秒，媒体已缓存；之前单次整理约14.6秒、全程约22.4秒。另一轮完整处理22.4秒（整理12.9秒），说明服务响应仍有波动。固定同一份识别文字单独复测整理为6.6秒。报告见validation/speed-parallel-end-to-end-repeat.json、speed-parallel-full.json、speed-parallel-recipe-repeat.json；只返回6道菜且有读图失败警告的试验不算完整提速。

按菜分组版重启后的真实HTTP验证：完整12道菜，整理5.9秒，全程约17.1秒；再次全部缓存命中约0.04秒。40项单元检查通过，包括四个请求同时运行、分组证据范围、失败组补齐、跨图同菜和视频跨帧上下文。报告见validation/http-parallel-speed.json、parallel-recipe-report.md。

2026-10-10加入保守分组保护：读图顺便标记是否独立，任一不明确段落使整篇一次整理，不增加AI判断调用。44项检查通过；生产HTTP复测12道菜走4组并行，媒体已缓存、重读图与整理共18.2秒，其中整理8.5秒；视频单菜走一次整理。无菜名连续步骤的实际模型回归只返回一张完整卡，原文全部保留。首次不完整识别轮次也保留，最终结果和限制见validation/safe-route-report.md。

## 清理与验证

在根目录执行 `npm ci` 安装 JavaScript 测试依赖，随后运行 `npm test`。前端重新构建在 `frontend` 目录执行 `npm ci` 和 `npm run build`；已构建的 `web/ui` 随仓库保留，直接运行网页无需先构建。

已移除旧人工样例回退、外部媒体服务分支、DeepSeek专属参数、旧双接口密钥配置、DyNote转录和CDP代理分支。当前不运行语音转录、独立OCR或本地大模型。DyNote从1000多行裁至82行，只保留页面采集、媒体查找及最小传输接口。

参考仓库、旧转录脚本和历史测试材料移入 `.archive/development-history/`；含转录依赖的旧Python环境移入 `.archive/previous-python-env/`。归档不参与运行和发布。原媒体data/、Google授权配置和浏览器卡片保持保留。

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -q
node --check web/mobile-app.js
.venv/Scripts/python.exe validation/run_media_check.py https://b23.tv/JkH26jl result.json
```

精简后B站1张、小红书视频1张、抖音图文12张菜谱卡的服务调用验证通过；结果在 validation/simplified-flow-check.json。当前单元检查覆盖模型选择、识别缓存、原文传递、菜谱校验和购物汇总。

公开页面遇到登录或风控仍可能失败，不能保证任意链接可用。视频限制5分钟、100MB；配图最多20张。视频抽帧可能漏掉短暂文字；未提供原文证据的信息不补写成精确用量。
