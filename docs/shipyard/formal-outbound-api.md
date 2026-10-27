# 船厂正式出库、整票核销与装车 API（第四切片）

本文记录船厂固定出库清单识别、库存分配、整票多吊牌核销、照片留证、库存扣减、
装车确认和微信小程序接口。所有接口位于 `/api/shipyard/outbound`，复用 Sentry
的登录、角色、仓库权限、审计日志和数据库事务。

## 数据边界

086 新增两层独立单据：

- `shipyard_outbound_manifests`：船厂下发的原始出库需求，保留原文件、模板版本、
  清单行和库存匹配预览。
- `shipyard_outbound_orders`：管理员确认后生成的正式出库单，包含不可拆的整票
  `shipyard_outbound_tasks`。

票据层级如下：

```text
船厂正式出库清单
  → 正式出库单
    → 出库需求行
      → 1..N 张整票任务（每张任务对应一个 cargo ticket）
        → 全部托盘吊牌照片
          → 一次库存扣减
```

清单确认只把票货置为 `ALLOCATED`，不改变库存数量。只有现场扫齐全部托盘吊牌并
提交整票核销时，才在同一事务中扣减 `on_hand_quantity`、写库存流水、更新照片和
出库单状态。

## 物料与库存强校验

正式出库清单的以下字段必须存在：

- 船号；
- 工程号；
- 制作图编号；
- 物料编码；
- 物料名称；
- 需求数量。

库存匹配同时要求：

- 船号/工程号/制作图命中当前生效的项目绑定；
- `material_code`、`item_name`、`item_spec` 规范化后完全一致；
- 票货有可用在库数量；
- 全部实际托盘后缀存在、唯一且属于同一票货；
- 出库清单给出的预计托盘数和托盘后缀与库存一致；
- 一张票货只分配一次，不能跨出库任务复用。

系统不会按品名静默建立 SKU，也不会在物料编码缺失时退化为品名匹配。历史入库票货
若没有物料编码，会在预览中显示为无匹配，需先补齐来源数据或走受控调整。

## 出库清单识别

### 上传预览

`POST /api/shipyard/outbound/formal-manifests/preview`

使用 `multipart/form-data`：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `warehouse_id` | 是 | 所属仓库 |
| `file` | 是 | 固定模板 `.xlsx`，最大 10 MiB |
| `factory_shipment_no` | 否 | 文件未提供船厂出货单号时补充 |
| `manifest_no` | 否 | 内部导入号；不填则自动生成 |

固定模板至少需要识别：

- 清单行号；
- 船厂出货单号；
- 船号、工程号、制作图号；
- 物料编码、物料名称、规格；
- 需求数量、单位、需求日期；
- 预计托盘数、托盘后缀。

接口返回逐行绑定状态、候选整票、区域快照、托盘后缀和库存缺口。同一文件
SHA-256 或未作废的内部导入号重复时返回 `409`。

### 查询、原文件和生命周期

```text
GET  /api/shipyard/outbound/formal-manifests?warehouse_id=1
GET  /api/shipyard/outbound/formal-manifests/<manifest_id>
GET  /api/shipyard/outbound/formal-manifests/<manifest_id>/file
POST /api/shipyard/outbound/formal-manifests/<manifest_id>/confirm
POST /api/shipyard/outbound/formal-manifests/<manifest_id>/void
```

确认接口无编辑字段，使用服务端重新计算后的分配结果生成正式出库单。库存不足不会
被写成负库存；没有合适整票的需求行保留 `SHORTAGE`。已生成出库单的清单不能作废。

## 正式出库单和移动任务

管理端查询：

```text
GET /api/shipyard/outbound/orders?warehouse_id=1
GET /api/shipyard/outbound/orders/<outbound_order_id>
```

小程序查询：

```text
GET /api/shipyard/outbound/mobile/orders?warehouse_id=1
GET /api/shipyard/outbound/mobile/orders/<outbound_order_id>
```

出库单状态：

- `PENDING`：已生成，等待现场出库；
- `PARTIAL`：多张整票中部分已完成，或仍有库存缺口；
- `OUTBOUND`：全部已分配整票完成且无缺口；
- `LOADED`：整单装车已确认。

单张任务只有 `PENDING → OUTBOUND`，不存在单票部分出库。

## 整票扫码与照片

### 扫码预校验

`POST /api/shipyard/outbound/tasks/<task_id>/scan`

```json
{
  "tag_suffix": "1-1",
  "qr_payload": "工厂吊牌二维码原文",
  "ship_no": "H1613",
  "engineering_no": "H1613",
  "production_drawing_no": "D-001",
  "material_code": "MAT-001",
  "item_name": "船用支架",
  "batch_no": "H1613-B01",
  "label_quantity": 4
}
```

服务端以二维码 SHA-256 找到已收货托盘，再校验：

- 吊牌属于当前票货和当前整票任务；
- 托盘后缀与实际库存一致；
- `material_code` 和 `item_name` 必须由当前吊牌实际识别结果提供，不读取任务快照
  代替吊牌值；
- 船号、工程号、制作图、批次和整票数量若传入则必须一致；
- 托盘仍为 `STORED`，任务仍为 `PENDING`。

扫描其他任务的吊牌会返回 `422 outbound_validation_failed`，响应中的
`matched_task_id`/`matched_task_no`/`matched_outbound_order_id` 用于现场直接跳转到
正确任务。

### 上传吊牌照片

`POST /api/shipyard/outbound/tasks/<task_id>/photos`

`multipart/form-data`：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file` | 是 | JPEG、PNG 或 WebP，最大 10 MiB |
| `tag_suffix` | 是 | 当前整票任务中的某个托盘后缀 |

照片先作为当前任务证据保存。正式核销时会再次校验上传人、票货、任务、托盘和照片
后缀，并将照片绑定到出库核销记录。

小程序正常路径先完成扫码预校验，校验通过后才调用相机拍摄并上传留证照片。这样扫错
任务、重复吊牌或字段不一致时不会先产生一张未绑定照片。

## 确认整票出库

`POST /api/shipyard/outbound/tasks/<task_id>/confirm`

```json
{
  "idempotency_key": "outbound-20261027-0001",
  "client_device_id": "WX-MINI-001",
  "pallets": [
    {
      "tag_suffix": "1-1",
      "qr_payload": "QR-H1613-D-001-1-1",
      "material_code": "MAT-001",
      "item_name": "船用支架",
      "label_quantity": 4,
      "photo_id": "00000000-0000-0000-0000-000000000000"
    },
    {
      "tag_suffix": "1-2",
      "qr_payload": "QR-H1613-D-001-1-2",
      "material_code": "MAT-001",
      "item_name": "船用支架",
      "label_quantity": 4,
      "photo_id": "11111111-1111-1111-1111-111111111111"
    }
  ]
}
```

事务顺序：

1. 锁定任务、票货和全部托盘；
2. 校验扫描后缀集合与任务托盘集合完全相等，缺托、多托、重复托均拒绝；
3. 校验全部二维码、物料字段、批次和每托唯一照片；
4. 写一条出库核销记录和逐托关联记录；
5. 将票货 `on_hand_quantity` 置零、状态改为 `OUTBOUND`，全部托盘改为
   `OUTBOUND`；
6. 写一条负数库存流水和审计日志；
7. 更新需求行、整票任务和整单状态。

任一步失败整笔回滚。同一任务用相同幂等键重试返回首次结果；使用新键重复核销返回
`409 outbound_state_conflict`。

## 装车确认

`POST /api/shipyard/outbound/orders/<outbound_order_id>/loading`

```json
{
  "idempotency_key": "loading-20261027-0001",
  "client_device_id": "WX-MINI-001",
  "notes": "车辆沪A12345，两托已装车"
}
```

只有全部整票任务完成且所有需求行无库存缺口时，整单才处于 `OUTBOUND` 并允许装车。
确认后写 `shipyard_outbound_loading_confirmations`，状态变为 `LOADED`，记录装车人、
装车时间、设备和备注。装车动作不改库存，不得与逐票出库合并。

## 微信小程序

`miniprogram/` 提供：

- 收货任务与整票连续拍摄；
- 出库单、整票任务和区域路径；
- 多吊牌连续扫码与逐托照片；
- 整票核销和整单装车确认。

小程序使用 `/api/auth/login` 获取现有 JWT，不创建第二套用户。正式部署须配置
HTTPS API 域名、微信 request/uploadFile 合法域名和真实 AppID。

## 当前限制

- 船厂库存仍以 `shipyard_cargo_tickets`/`shipyard_stock_ledger` 为权威账，尚未
  同步到 Sentry 通用 `items`/`inventory` 聚合表。
- 当前没有主管异常强出、撤销装车和撤销出库审批流；相关入口保留为后续切片。
- `wx.scanCode` 和微信相机拍摄是两个系统 API。当前实现把扫码原文与吊牌照片成对
  保存并分别校验；若要求二者来自同一张原始照片，需接原生单帧解码相机插件。
- 固定模板字段别名覆盖常见船厂表头，但正式上线前仍需用真实样例锁定模板版本。

## 验证

- 全后端：`3032 passed, 55 skipped, 11 warnings`；
- 086 迁移在开发库和 `sentry_test` 连续执行两次成功；
- 全新空库执行 `db/schema.sql` 后，正式出库、任务、核销和装车 4 类核心表均存在；
- 管理端：32 个测试文件、203 项测试通过，生产构建通过；
- 本次触及的管理端文件 ESLint 通过；
- 微信小程序：17 项 Node 测试通过，全部 JavaScript 文件语法检查通过；
- Ruff、格式检查、Bandit、`git diff --check` 通过；
- `pip-audit` 无已知漏洞，`npm audit` 为 0 个漏洞。

本切片还使用本地开发库做了一次真实 HTTP 闭环：创建船号绑定和区域 → 导入并确认
到货清单 → 相机证据上传模拟 → 单托收货入库 → 导入并确认正式出库清单 → 扫码
核验物料编码/品名 → 上传出库照片 → 扣减库存 → 整单装车。最终库存余额为
`0.000`、出库单为 `LOADED`，后台刷新后同步显示现场出库人和时间。该验证不等于
真实仓库 UAT；小程序真机、真实吊牌和 Chrome 文件选择仍待现场/设备验证。
