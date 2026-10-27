# 船厂虚拟用户

前期使用虚拟账号验证角色、页面权限和仓库隔离，不需要真实员工账号。

## 创建

仅允许在 `development` 或 `test` 环境运行：

```bash
FLASK_ENV=development \
SHIPYARD_DEMO_WAREHOUSE_IDS=1 \
python scripts/seed_shipyard_demo_users.py
```

脚本是幂等的，可以重复执行。它会更新同名演示账号、移动功能授权和页面
权限，但不会删除其他用户。

默认口令仅用于本地演示，可通过 `SHIPYARD_DEMO_PASSWORD` 覆盖。生产环境
应使用真实账号流程，脚本会拒绝 `FLASK_ENV=production`。

## 账号

| 用户名 | 角色 |
| --- | --- |
| `demo_shipyard_admin` | `ADMIN` |
| `demo_shipyard_manager` | `SHIPYARD_MANAGER` |
| `demo_shipyard_receiver` | `RECEIVER` |
| `demo_shipyard_outbound` | `OUTBOUND` |
| `demo_shipyard_viewer` | `VIEWER` |

## 权限边界

- 管理员拥有全部权限。
- 船厂主管维护绑定和区域定置，导入入库/出库清单并查看审计。
- 收货员只能进入入库页面，调用扫码、照片、实收入和少件补货接口。
- 出库员只能查看出库任务并在小程序执行扫码核销，不能修改单据。
- 审计员只读取已授权仓库的页面和审计记录，所有写接口返回 `403`。
- 所有非管理员仍受 `warehouse_ids` 仓库隔离。
