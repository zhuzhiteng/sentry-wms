# 船厂入库 API（第一切片）

本文记录船厂业务域的第一组可用接口。接口位于 `/api/shipyard`，复用
Sentry WMS 的账号、仓库授权、审计日志和数据库事务。

## 已实现范围

### 船号/工程号/制作图绑定

- `GET /api/shipyard/bindings`
- `POST /api/shipyard/bindings`
- `PUT /api/shipyard/bindings/<binding_id>`

同一组 `ship_no + engineering_no + production_drawing_no +
manufacturer_name` 只能存在一条有效绑定。

### 船号与二级区域定置

- `GET /api/shipyard/zone-mappings?warehouse_id=1`
- `POST /api/shipyard/zone-mappings`
- `PUT /api/shipyard/zone-mappings/<mapping_id>`

二级区域直接使用 Sentry 的 `bins`，完整路径由所属 `zones` 和 `bins`
组成。一个区域可以配置多个船号；一个船号当前只能有一个有效主入库区域。

### 入库清单识别

- `POST /api/shipyard/inbound/manifests/preview`
- `GET /api/shipyard/inbound/manifests?warehouse_id=1`
- `GET /api/shipyard/inbound/manifests/<manifest_id>`
- `POST /api/shipyard/inbound/manifests/<manifest_id>/confirm`

预览接口使用 `multipart/form-data`：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `warehouse_id` | 是 | 收货仓库 |
| `file` | 是 | `.xlsx` 工厂发货清单 |
| `manifest_no` | 否 | 不填时按日期和文件哈希生成 |
| `manufacturer_name` | 否 | 不填时从清单标题中的公司名提取 |

预览会创建状态为 `PARSED` 的入库清单和逐行明细，并返回：

- 识别出的表头行、工作表、忽略的辅助工作表；
- 每条清单行的来源行号、船号、图号、图名、件数、送货单号和 PO 号；
- 按船号计算出的指定二级区域；
- 缺少主区域的船号；
- 是否允许确认 `validation.can_confirm`。

清单行合同固定为：

> 一个来源清单行 = 一张票货/托组，行内件数 = 整票或整托组总件数。

因此多托 `1-1/1-2` 不会在清单阶段把总件数重复相加。预计托盘数、每托
吊牌和实际实收数量由后续小程序扫码收货接口补充。

## 确认规则

确认接口只接受空 JSON 对象 `{}`。确认时系统重新读取当前区域配置，并执行：

1. 只允许 `PARSED` 状态确认，重复确认返回 `409`；
2. 每个船号必须存在且只存在一个有效主入库区域；
3. 一条清单行生成一张状态为 `EXPECTED` 的票货；
4. 票货保存区域路径快照，后续区域改名不破坏历史；
5. 票货写入 Sentry 的 `stock_lot_number` 映射值，为后续库存入账预留；
6. 清单状态改为 `CONFIRMED`，同时写入审计日志。

未配置区域时允许预览，但禁止确认，确保现场不能绕过船号定置规则。

## 模板识别

解析器不写死 Excel 行号，而是在前 30 行中查找规范化后的表头。当前支持
的主要别名包括：

- 船号；
- 品名/物料名称/物资名称；
- 图号/制作图编号/制作图号；
- 图名/制作图名称/安装托盘名称；
- 件数/数量/整票件数；
- 送货单号；
- PO 号、PO NO；
- 送货地点、采购员、重量和货物类别。

当前验证样例：

- 工作表：`外高桥 `；
- 表头行：第 3 行；
- 业务行：36；
- 船号：7；
- 合计件数：2,326；
- `Sheet1`：识别为辅助页并忽略。

## 验证命令

```powershell
docker compose exec -T `
  -e TEST_DATABASE_URL=$testDbUrl `
  -e FLASK_ENV=development `
  -e SENTRY_ALLOW_INTERNAL_WEBHOOKS=false `
  -e SENTRY_ALLOW_HTTP_WEBHOOKS=false `
  api python -m pytest tests/shipyard tests/test_082_shipyard_core_migration.py -q
```

第一切片验证结果：`18 passed`。
