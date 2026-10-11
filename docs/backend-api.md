# 家庭业务与任务 API

更新：2026-10-12。FastAPI/Uvicorn，支持 SQLite 和 PostgreSQL。部署与恢复见 [部署说明](deployment.md)，验收状态见 [后端进度](backend-progress.md)。

## 读取与认证

沿用 `/api/account/register`、`login`、`logout`、`profile`，以及 `/api/household/join`。使用 HttpOnly 会话 Cookie；写入要求同源 JSON。服务端根据会话查用户及所属家庭，不接受客户端指定家庭作为权限依据。

`GET /api/account/session` 返回账号、成员、家庭、revision、schemaVersion 和兼容页面的 `snapshot: {state, recipeData}`。查询参数 revision 和 household 都匹配时可省略快照；参数只是读取优化，不是访问凭据。

## 操作协议

`POST /api/household/commands`：

```json
{
  "id": "前端生成的唯一操作编号，建议 UUID",
  "revision": 12,
  "kind": "meal.prepare",
  "role": "chef",
  "mealId": "当前餐次编号",
  "payload": {
    "needId": "服务端返回的需求编号",
    "direction": "right",
    "quantity": 500,
    "unit": "克"
  }
}
```

revision 为操作前家庭版本。所有 meal.* 操作必须携带当前 mealId，防止旧页面操作下一餐。服务端自行计算需求、可用量、预留、消耗和记录时间。响应含当前家庭状态、操作 result 和 duplicate；客户端确认后再显示成功。

同一家庭内，同一用户使用相同 id 和内容重试，只执行一次，返回原操作结果及最新家庭状态。响应丢失时，旧 revision 不阻止同回执重试。同一编号被其他用户或不同内容使用，返回 409。

新操作版本冲突返回 409，不覆盖较新数据。客户端刷新后由用户重新操作，不用新编号自动重放旧库存意图。发送前将回执存到当前账号的本地存储，响应不确定时保留，刷新后用原编号恢复确认；它不是离线写入队列。

role 是成员可切换的界面分工，不是管理员权限。美食家可点菜、调份数、添加餐次照片；其他操作需主厨视图。身份与家庭访问权限始终来自服务端会话。

## 操作列表

| kind | payload | 行为 |
|---|---|---|
| meal.pick | recipeId, selected | 选中或移除一道菜，只限选菜中 |
| meal.select | recipeIds, selected（默认 true） | 批量选菜，用于随机菜结果 |
| meal.servings | recipeId, servings | 调整本餐份数 |
| meal.lock | 空对象 | 固定菜谱快照并计算需求 |
| meal.prepare | needId, direction, quantity, unit；可选 stockIds | left 预留已有库存；right 增加录入总量，仅预留本餐缺量 |
| meal.declare | needId | 未知用量标记已备好，不自动扣库存 |
| meal.undo | operationId | 准备阶段撤销；后续已使用的补录量不能撤销 |
| meal.begin | 空对象 | 进入烹饪中 |
| meal.finish | 空对象 | 扣减预留，保存记录；同餐不会重复扣减 |
| meal.cancel | 空对象 | 释放预留，保留已补录库存 |
| meal.new | 空对象 | 完成或取消后创建新餐次 |
| stock.add | name, quantity, unit, space, zone；可选 iconId | 增加库存，位置空时留待安置 |
| stock.reduce | stockId, quantity | 日常减少，不得减少预留部分 |
| stock.move | stockId, space, zone | 移动位置，数量和预留保持 |
| space.create | name, type, layout, zones | 新增储物空间 |
| space.update | spaceId, name, layout, zones | 重命名、改分区；减少分区时食材移入最后分区 |
| space.delete | spaceId | 删除空间，食材留待安置，保留预留 |
| recipe.upsert | recipe；可选 evidence 字典 | 保存菜谱并验证来源，不改变已固定菜单 |
| record.photo | recordId, photo | 保存照片引用；兼容受限 data URL，服务端转换为独立图片 |

布局为 four、two、horizontal；类型为 fridge、cupboard。数量最多四位小数，拒绝负数、非有限值及无效类型。物理单位转换用于库存计算；未知用量不补成精确数值。

错误：400 无效输入、401 未登录/会话过期、403 同源/分工检查失败、404 实体不存在、409 版本/状态/回执冲突、413 请求过大。旧 `/api/household/save` 对已登录请求返回 410；刷新后使用操作接口。

## 存储与迁移

库存、空间、菜谱、证据、餐次、准备操作、库存分配、记录、回执分表。库存分配有同家庭外键及正数量约束。业务写入、版本、回执在同一事务；读取使用一致性事务。

首次启动校验已有快照并事务迁移，原 households.snapshot 保留作迁移备份。注册带入的本机数据同样校验。实体内容仍用 JSON，但已改为变动行局部更新；PostgreSQL 库存生成数值列用于索引和约束，后续可继续细化字段。

解析与媒体权限、独立上传、持久化任务、配置部署已接入，见 [文件与任务接口](jobs-api.md)。实际部署、密码找回、成员退出及邀请失效规则仍待完成。
