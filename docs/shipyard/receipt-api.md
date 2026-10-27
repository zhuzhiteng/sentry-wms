# 船厂扫码收货与少件补货 API（第二切片）

本文记录吊牌扫码校验、照片留证、按实收入库、少件报送和原批次补货接口。
所有接口位于 `/api/shipyard`，复用 Sentry 的账号、仓库授权、审计日志和
数据库事务。

## 运行时识别边界

- 二维码/条形码由小程序或 PDA 本地解码，服务端不调用 AI。
- 固定 Excel 清单由程序按模板解析，不调用 AI。
- 打印文字 OCR 是可选适配层，可本地或私有化部署，不是首期必需能力。
- 服务端只接收识别后的结构化字段，并重新执行绑定、票货、托盘后缀、数量和
  照片校验。照片作为证据保存，不参与 AI 判断。

## 接口

### 扫码预校验

`POST /api/shipyard/inbound/tickets/<ticket_id>/scan`

```json
{
  "tag_suffix": "1-1",
  "qr_payload": "工厂二维码原始内容",
  "ship_no": "H1613",
  "engineering_no": "H1613",
  "production_drawing_no": "132ME201EM",
  "qr_pallet_no": "132ME201EM",
  "batch_no": "H1613杰宇-0",
  "manufacturer_name": "上海杰宇",
  "installation_pallet_no": "132FE120121",
  "installation_pallet_name": "132分段电舾装件制作图（B）",
  "destination": "外高桥",
  "label_quantity": 45
}
```

预校验不写库存，返回唯一匹配的票货、清单、指定区域、已有托盘后缀和标准化
后的吊牌字段。二维码原文按工厂规则原样保存，服务端不重新解释制码规则。

### 上传照片

`POST /api/shipyard/inbound/tickets/<ticket_id>/photos`

使用 `multipart/form-data`：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file` | 是 | JPEG、PNG 或 WebP，最大 10 MiB |
| `photo_kind` | 否 | `PALLET`（默认）、`GROUP`、`AREA`、`DIFFERENCE` |
| `tag_suffix` | 托盘照片必填 | 多托盘票货使用 `1-1`、`1-2` 格式 |

每个实际托盘必须有独立的 `PALLET` 照片。照片先上传为未绑定证据，正式收货
确认时再与收货记录和托盘原子关联。相同照片不能复用到多个托盘或多次收货。

### 确认收货

`POST /api/shipyard/inbound/tickets/<ticket_id>/receipts`

```json
{
  "idempotency_key": "receipt-20261027-0001",
  "received_quantity": 3,
  "difference_reason": "少 1 件，已联系工厂补货",
  "client_device_id": "PDA-A01",
  "pallets": [
    {
      "tag_suffix": "1-1",
      "qr_payload": "工厂二维码原始内容",
      "ship_no": "H1613",
      "engineering_no": "H1613",
      "production_drawing_no": "132ME201EM",
      "qr_pallet_no": "132ME201EM",
      "batch_no": "H1613杰宇-0",
      "manufacturer_name": "上海杰宇",
      "installation_pallet_no": "132FE120121",
      "label_quantity": 4,
      "photo_id": "00000000-0000-0000-0000-000000000000"
    }
  ],
  "group_photo_id": null,
  "area_photo_id": null,
  "difference_photo_id": null
}
```

同一次请求包含多个托盘时，后缀必须同属一个托组号、互不重复，并保持
`1-1`、`1-2` 格式。若票货已配置预计托盘数，则整票数量到齐时必须同时完成
托盘齐套，未齐套不能标记为全部到货。

### 少件报送

`PUT /api/shipyard/inbound/tickets/<ticket_id>/shortage`

```json
{
  "status": "REPORTED",
  "note": "已微信通知工厂补 1 件"
}
```

`status` 支持 `REPORTED`（已报工厂）和 `IN_TRANSIT`（补货在途）。只有尚未
全部到货的票货可以登记。

### 查看照片

`GET /api/shipyard/photos/<photo_id>`

需具备对应仓库访问权限，以附件方式返回原图。

## 原子入库动作

确认收货在同一数据库事务中完成：

1. 校验仓库权限、清单状态、票货状态和剩余应收数量。
2. 校验船号、工程号、制作图、厂家和吊牌数量。
3. 校验二维码全局唯一、托盘后缀唯一、托组号一致及预计托盘数。
4. 新增票货下的托盘单元，并记录二维码原文、二维码托盘号、安装托盘号、
   批次号、收货人和到货时间。
5. 新增收货确认、托盘关联、照片关联和库存流水。
6. 按本次实收数量增加票货累计实收和在库数量，吊牌总件数不重复累加。
7. 更新清单行和清单状态，少件保留待补数量但不冻结已收库存。
8. 写审计日志并提交；任一步失败则整笔回滚。

`idempotency_key` 以票货为作用域唯一。网络重试或连续点击返回首次成功结果，
不会重复增加库存。

## 状态

票货状态：

- `EXPECTED`：待收货。
- `PARTIAL`：部分到货，已收库存可正常使用。
- `IN_STOCK`：计划数量已经全部实收。

缺件状态：

- `NONE`：无缺件。
- `PENDING_REPORT`：存在缺件，等待报工厂。
- `REPORTED`：已报工厂。
- `IN_TRANSIT`：工厂补货在途。
- `PARTIAL_REPLENISHMENT`：已经补到一部分，仍有缺口。
- `REPLENISHED`：原票货累计数量已经补足。

清单状态在收货过程中由 `CONFIRMED` 自动转为 `PARTIAL`，全部票货到齐后转为
`CLOSED`。

## 当前限制

- `shipyard_cargo_tickets`、`shipyard_receipts` 和
  `shipyard_stock_ledger` 当前是船厂库存的权威账。
- 尚未把船厂票货同步到 Sentry 通用 `items` / `inventory` 聚合表；需要先确定
  船厂物料编码和通用物料主数据映射，不能按品名静默创建 SKU。
- 配送需求、派工单、发货单和打印已由第三切片实现，见
  [`outbound-documents-api.md`](outbound-documents-api.md)。
- 船厂正式出库清单识别、整票扫码扣库、出库照片和装车确认仍属于下一功能
  切片。

## 验证

- 船厂业务、082-084 迁移：54 项通过；
- 船厂业务、迁移和认证回归：110 项通过；
- 全后端：3000 项通过、55 项跳过、0 项失败；
- `services/shipyard` 覆盖率：90%；
- Ruff、格式检查、Bandit、迁移幂等检查通过。
