# 第三方组件与复用范围

- [AIClient2API](https://github.com/justlovemaki/AIClient2API)：独立Node.js Antigravity网关，授权刷新、代理和模型协议转换实际使用。运行源码与LICENSE保留在 services/AIClient2API；版本4c4c774930c85f3760e9c89a1ef481f74eac4d00，许可证见其GPLv3 LICENSE。仅配置gemini-antigravity提供商；保留上游运行依赖和管理界面，开发文档、测试和Git元数据归档。
- [JefferyHcool/BiliNote](https://github.com/JefferyHcool/BiliNote)：MIT；实际复用bilibili_dm_patch.py，保留源码、LICENSE和SOURCE.json于vendor/bilinote，作为B站下载失败时的兼容补丁。未部署完整BiliNote应用。
- [Rimagination/dy-note](https://github.com/Rimagination/dy-note)：MIT；vendor/dynote保留经过裁剪的collect_page_info、find_media_url，及LICENSE、上游版本记录。2026-10-10移除了转录、Markdown笔记、CDP代理和CLI；浏览器传输由本项目Playwright提供。
- [yyyzl/bilinote](https://github.com/yyyzl/bilinote)和[bilibili-video-reader](https://github.com/yichen11818/bilibili-video-reader)：仅曾作为设计参考，不是运行依赖，完整参考源码已移到.archive/development-history。
- Python直接依赖：yt-dlp、imageio-ffmpeg、Playwright。FFmpeg执行文件来自imageio-ffmpeg，浏览器备用获取使用Chrome。
- [Konsta UI](https://github.com/konstaui/konsta)：5.5.0，MIT；实际使用 Vue 组件版本的 App、Navbar、Button、Card、Chip、Segmented、Tabbar。弹窗使用原生 dialog 保持焦点管理，内部使用同一套 Material 主题与组件。固定 Material 浅色主题，绿色种子 `#4caf50`，整套颜色由其官方插件生成。前端源码和依赖锁文件在 frontend，打包资源在 web/ui。
- [Vue](https://github.com/vuejs/core)：3.5.43，MIT；用于 Konsta 组件渲染。Vite、Vue 编译插件和 Tailwind CSS 仅用于构建，后端仍提供静态文件，不需要新增 Node.js 运行服务。
- Noto Sans SC Variable：通过 `@fontsource-variable/noto-sans-sc` 打包的本地中文字体，SIL Open Font License 1.1。浏览器按文字的 Unicode 范围加载字体分片，不依赖 Google Fonts 网络请求；字体与完整许可位于 `web/ui/fonts`，构建逻辑在 `frontend/font-assets.js`。

小红书分享页适配由本项目实现，不是BiliNote的原生小红书功能。第三方文件保留各自许可证及版本记录；归档材料不进入运行依赖。
