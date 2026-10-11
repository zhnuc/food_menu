# 文件与 AI 任务

所有接口使用账号 Cookie，由服务器查询当前家庭；家庭外资源返回 404。

- `POST /api/files?purpose=avatar|cover|record|recipe-input`：图片二进制，最多 8 MB，返回 `url`。校验真实 JPEG/PNG/WebP、像素和家庭空间，去除 EXIF 并缩放保存。
- `GET /api/files/{id}`：授权读取图片，私有、禁止公共缓存。照片保存为该 URL；旧 data URL 在业务写入时迁移为独立文件。
- `POST /api/jobs`：`{"requestId":"UUID","kind":"text","input":{"prompt":"想做的菜"}}`。kind 可为 `link`（share、article、image_ocr）、`image`（已上传 recipe-input URL）、`text`（prompt）、`ingredients`（ingredients、prompt）。同 requestId/内容返回同任务，不同内容冲突。
- `GET /api/jobs`：当前家庭最近 30 个任务。
- `GET /api/jobs/{id}?after=0`：任务状态、结果及 after 序号之后的事件。事件有 progress/source/recipes，重开页面可恢复。
- `POST /api/jobs/{id}/retry`：失败任务未到次数上限时重试，保留已完成批次。
- `POST /api/jobs/{id}/cancel`：取消待处理或执行中任务，旧 worker 不能再提交结果。正在进行的外部模型请求可能已计费。

任务状态 queued/running/succeeded/failed/cancelled；HTTP 不等待模型处理。图片模式读取图片中的菜谱文字，不凭成品照片猜食材用量。文字与食材创作标为 AI 建议，用户核对后收藏；模型用量逐次归属任务，未知 token 留空。

默认旧 `/api/parse` 返回 410，正式客户端使用任务。开发兼容 `ALLOW_INLINE_PARSE=1` 才恢复旧解析路线；不得在公开部署启用无账号解析。
