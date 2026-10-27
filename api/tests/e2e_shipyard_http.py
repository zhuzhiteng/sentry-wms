"""Run the shipyard OCR workflow against a real loopback HTTP server.

This is intentionally a standalone script rather than a pytest test: pytest's
autouse transaction fixture binds the application to one SQLAlchemy connection,
which is not a realistic multi-threaded HTTP setup. The script still refuses to
run unless TEST_DATABASE_URL points at the dedicated test database.

Example inside the API container:

    TEST_DATABASE_URL=postgresql://.../sentry_test \
      python tests/e2e_shipyard_http.py
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from io import BytesIO
from urllib.parse import urlsplit

import psycopg2
import requests
from werkzeug.serving import make_server


def _test_database_url() -> str:
    test_url = (os.environ.get("TEST_DATABASE_URL") or "").strip()
    if not test_url:
        raise RuntimeError("TEST_DATABASE_URL is required")
    database_name = urlsplit(test_url).path.lstrip("/")
    if database_name != "sentry_test":
        raise RuntimeError("Refusing to run destructive E2E setup outside sentry_test")
    current_url = (os.environ.get("DATABASE_URL") or "").strip()
    if current_url and current_url == test_url:
        raise RuntimeError("TEST_DATABASE_URL must differ from DATABASE_URL")
    return test_url


TEST_DATABASE_URL = _test_database_url()
os.environ["FLASK_ENV"] = "development"
os.environ["SENTRY_ALLOW_INTERNAL_WEBHOOKS"] = "false"
os.environ["SENTRY_ALLOW_HTTP_WEBHOOKS"] = "false"

# conftest performs the same test-DB routing and deterministic admin seeding
# used by the regular suite. Importing it here deliberately keeps E2E setup and
# credentials identical to the tested environment.
import conftest
from shipyard.helpers import (
    PNG_BYTES,
    outbound_manifest_bytes,
    single_line_manifest_bytes,
)

from app import create_app
from services.shipyard import (
    outbound_turnover_service,
    receipt_service,
)
from services.shipyard.label_ocr import LabelOcrResult


def _ocr_result(fields: dict) -> LabelOcrResult:
    return LabelOcrResult(
        provider="e2e-stub",
        raw_text="\n".join(f"{key}: {value}" for key, value in fields.items()),
        raw_lines=[f"{key}: {value}" for key, value in fields.items()],
        fields=fields,
        confidence=0.99,
    )


def _json(response: requests.Response, expected_status: int) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = {"body": response.text[:1000]}
    if response.status_code != expected_status:
        raise AssertionError(
            f"{response.request.method} {response.request.url} "
            f"returned {response.status_code}: {payload}"
        )
    return payload


def _first_bin_id() -> int:
    connection = psycopg2.connect(TEST_DATABASE_URL)
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT bin_id
              FROM bins
             WHERE warehouse_id = 1
             ORDER BY bin_id
             LIMIT 1
            """
        )
        return cursor.fetchone()[0]
    finally:
        connection.close()


def _set_expected_pallet_count(ticket_id: str, count: int) -> None:
    connection = psycopg2.connect(TEST_DATABASE_URL)
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE shipyard_cargo_tickets
               SET expected_pallet_count = %s
             WHERE ticket_id = %s
            """,
            (count, ticket_id),
        )
        connection.commit()
    finally:
        connection.close()


def _database_evidence(ticket_id: str, confirmation_id: str) -> dict:
    connection = psycopg2.connect(TEST_DATABASE_URL)
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT on_hand_quantity, status
              FROM shipyard_cargo_tickets
             WHERE ticket_id = %s
            """,
            (ticket_id,),
        )
        on_hand_quantity, ticket_status = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*),
                   COUNT(label_recognition_id),
                   COUNT(photo_id)
              FROM shipyard_outbound_confirmation_pallets
             WHERE confirmation_id = %s
            """,
            (confirmation_id,),
        )
        pallet_count, recognition_links, photo_links = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(quantity_delta), 0)
              FROM shipyard_stock_ledger
             WHERE ticket_id = %s
               AND source_type = 'OUTBOUND'
            """,
            (ticket_id,),
        )
        ledger_count, outbound_delta = cursor.fetchone()
        return {
            "on_hand_quantity": str(on_hand_quantity),
            "ticket_status": ticket_status,
            "confirmation_pallets": pallet_count,
            "recognition_links": recognition_links,
            "photo_links": photo_links,
            "outbound_ledger_count": ledger_count,
            "outbound_delta": str(outbound_delta),
        }
    finally:
        connection.close()


class _ServerThread:
    def __init__(self, app):
        self.server = make_server("127.0.0.1", 0, app, threaded=True)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="shipyard-e2e-http",
            daemon=True,
        )

    def __enter__(self) -> str:
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}/api"

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.thread.join(timeout=5)


def run() -> dict:
    conftest._seed_database()
    app = create_app()
    app.config["TESTING"] = False

    run_id = uuid.uuid4().hex[:10].upper()
    ship_no = f"HE2E{run_id[:6]}"
    material_code = f"MAT-E2E-{run_id}"
    item_name = "E2E 船用支架"
    suffixes = ("1-1", "1-2")

    inbound_ocr = [
        _ocr_result(
            {
                "ship_no": ship_no,
                "engineering_no": ship_no,
                "production_drawing_no": "D-001",
                "material_code": material_code,
                "item_name": item_name,
                "batch_no": f"{ship_no}-BATCH-1",
                "tag_suffix": suffix,
                "label_quantity": "4",
            }
        )
        for suffix in suffixes
    ]
    outbound_ocr = [
        _ocr_result(
            {
                "material_code": material_code,
                "item_name": item_name,
                "batch_no": f"{ship_no}-BATCH-1",
                "label_quantity": "4",
            }
        ),
        _ocr_result(
            {
                "material_code": material_code,
                "item_name": item_name,
                "batch_no": f"{ship_no}-BATCH-1",
                "tag_suffix": suffixes[1],
                "label_quantity": "4",
            }
        ),
    ]
    receipt_service.recognize_label_image = lambda _content: inbound_ocr.pop(0)
    outbound_turnover_service.recognize_label_image = lambda _content: outbound_ocr.pop(
        0
    )

    steps = []
    try:
        with _ServerThread(app) as api_base:
            session = requests.Session()
            login = _json(
                session.post(
                    f"{api_base}/auth/login",
                    json={"username": "admin", "password": "admin"},
                    timeout=10,
                ),
                200,
            )
            session.headers["Authorization"] = f"Bearer {login['token']}"
            steps.append("管理员通过真实 HTTP 登录")

            _json(
                session.post(
                    f"{api_base}/shipyard/bindings",
                    json={
                        "ship_no": ship_no,
                        "engineering_no": ship_no,
                        "production_drawing_no": "D-001",
                        "manufacturer_name": "E2E 测试配件厂",
                    },
                    timeout=10,
                ),
                201,
            )
            _json(
                session.post(
                    f"{api_base}/shipyard/zone-mappings",
                    json={
                        "warehouse_id": 1,
                        "bin_id": _first_bin_id(),
                        "ship_no": ship_no,
                        "is_primary": True,
                    },
                    timeout=10,
                ),
                201,
            )
            steps.append("创建船号绑定和唯一存放区域")

            inbound_preview = _json(
                session.post(
                    f"{api_base}/shipyard/inbound/manifests/preview",
                    data={
                        "warehouse_id": "1",
                        "manifest_no": f"IN-E2E-{run_id}",
                    },
                    files={
                        "file": (
                            "inbound-e2e.xlsx",
                            BytesIO(
                                single_line_manifest_bytes(
                                    ship_no,
                                    quantity=4,
                                    drawing="D-001",
                                    manufacturer="E2E 测试配件厂",
                                    material_code=material_code,
                                    item_name=item_name,
                                    item_spec="S-E2E",
                                )
                            ),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                    },
                    timeout=30,
                ),
                201,
            )
            manifest_id = inbound_preview["manifest"]["manifest_id"]
            inbound_confirmed = _json(
                session.post(
                    f"{api_base}/shipyard/inbound/manifests/{manifest_id}/confirm",
                    json={},
                    timeout=20,
                ),
                200,
            )
            ticket = inbound_confirmed["tickets"][0]
            _set_expected_pallet_count(ticket["ticket_id"], 2)
            steps.append("导入并确认到货清单，生成两张托盘任务")

            pallets = []
            receipt_photo_ids = []
            for suffix in suffixes:
                recognition = _json(
                    session.post(
                        f"{api_base}/shipyard/inbound/tickets/"
                        f"{ticket['ticket_id']}/label-recognition",
                        files={
                            "file": (
                                f"inbound-{suffix}.png",
                                BytesIO(PNG_BYTES),
                                "image/png",
                            )
                        },
                        timeout=10,
                    ),
                    201,
                )
                if not recognition["matched"]:
                    raise AssertionError(recognition)
                if recognition["recognized"]["tag_suffix"] != suffix:
                    raise AssertionError("入货 OCR 后缀不一致")
                receipt_photo_ids.append(recognition["photo"]["photo_id"])
                pallets.append(
                    {
                        "tag_suffix": suffix,
                        "label_recognition_id": recognition["recognition"][
                            "recognition_id"
                        ],
                        "photo_id": recognition["photo"]["photo_id"],
                    }
                )

            receipt = _json(
                session.post(
                    f"{api_base}/shipyard/inbound/tickets/"
                    f"{ticket['ticket_id']}/receipts",
                    json={
                        "idempotency_key": f"receipt-e2e-{run_id}",
                        "client_device_id": f"wx-e2e-{run_id}",
                        "received_quantity": 4,
                        "pallets": pallets,
                    },
                    timeout=20,
                ),
                200,
            )
            if receipt["ticket"]["on_hand_quantity"] != "4.000":
                raise AssertionError(receipt["ticket"])
            if receipt["ticket"]["status"] != "IN_STOCK":
                raise AssertionError(receipt["ticket"])
            steps.append("逐托拍照 OCR 收货，两托各一次拍摄，库存 4.000")

            outbound_preview = _json(
                session.post(
                    f"{api_base}/shipyard/outbound/formal-manifests/preview",
                    data={"warehouse_id": "1"},
                    files={
                        "file": (
                            "outbound-e2e.xlsx",
                            BytesIO(
                                outbound_manifest_bytes(
                                    ship_no=ship_no,
                                    manufacturer="E2E 测试配件厂",
                                    material_code=material_code,
                                    item_name=item_name,
                                    item_spec="S-E2E",
                                    demand_quantity=4,
                                )
                            ),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                    },
                    timeout=30,
                ),
                201,
            )
            outbound_manifest_id = outbound_preview["manifest"]["manifest_id"]
            outbound_order = _json(
                session.post(
                    f"{api_base}/shipyard/outbound/formal-manifests/"
                    f"{outbound_manifest_id}/confirm",
                    json={},
                    timeout=20,
                ),
                200,
            )
            task = outbound_order["tasks"][0]
            steps.append("导入并确认正式出库清单，生成整票任务")

            evidence = []
            first_recognition = _json(
                session.post(
                    f"{api_base}/shipyard/outbound/tasks/"
                    f"{task['task_id']}/label-recognition",
                    files={
                        "file": (
                            "outbound-1.png",
                            BytesIO(PNG_BYTES),
                            "image/png",
                        )
                    },
                    timeout=10,
                ),
                201,
            )
            if not first_recognition["needs_suffix"]:
                raise AssertionError("E2E 场景应触发缺后缀恢复")
            evidence.append(
                {
                    "tag_suffix": suffixes[0],
                    "label_recognition_id": first_recognition["recognition"][
                        "recognition_id"
                    ],
                    "photo_id": first_recognition["photo"]["photo_id"],
                }
            )
            steps.append("第一托 OCR 漏读后缀，返回剩余托盘供现场补选")

            second_recognition = _json(
                session.post(
                    f"{api_base}/shipyard/outbound/tasks/"
                    f"{task['task_id']}/label-recognition",
                    files={
                        "file": (
                            "outbound-2.png",
                            BytesIO(PNG_BYTES),
                            "image/png",
                        )
                    },
                    timeout=10,
                ),
                201,
            )
            if not second_recognition["matched"]:
                raise AssertionError(second_recognition)
            evidence.append(
                {
                    "tag_suffix": suffixes[1],
                    "label_recognition_id": second_recognition["recognition"][
                        "recognition_id"
                    ],
                    "photo_id": second_recognition["photo"]["photo_id"],
                }
            )
            steps.append("第二托 OCR 一次匹配，无额外输入")

            confirmed = _json(
                session.post(
                    f"{api_base}/shipyard/outbound/tasks/{task['task_id']}/confirm",
                    json={
                        "idempotency_key": f"outbound-e2e-{run_id}",
                        "client_device_id": f"wx-e2e-{run_id}",
                        "pallets": evidence,
                    },
                    timeout=20,
                ),
                200,
            )
            if confirmed["confirmation"]["balance_after"] != "0.000":
                raise AssertionError(confirmed["confirmation"])
            steps.append("整票两张照片核销，库存扣减到 0.000")

            loaded = _json(
                session.post(
                    f"{api_base}/shipyard/outbound/orders/"
                    f"{outbound_order['order']['outbound_order_id']}/loading",
                    json={
                        "idempotency_key": f"loading-e2e-{run_id}",
                        "client_device_id": f"wx-e2e-{run_id}",
                        "notes": "E2E 两托已装车",
                    },
                    timeout=20,
                ),
                200,
            )
            if loaded["order"]["status"] != "LOADED":
                raise AssertionError(loaded["order"])
            steps.append("整单装车确认，出库单进入 LOADED")

            refreshed_order = _json(
                session.get(
                    f"{api_base}/shipyard/outbound/orders/"
                    f"{outbound_order['order']['outbound_order_id']}",
                    timeout=10,
                ),
                200,
            )
            if refreshed_order["order"]["status"] != "LOADED":
                raise AssertionError(refreshed_order["order"])
            if refreshed_order["order"].get("loading", {}).get("notes") != (
                "E2E 两托已装车"
            ):
                raise AssertionError(refreshed_order["order"])
            steps.append("后台重新查询出库单，状态和装车备注同步")

            first_photo = session.get(
                f"{api_base}/shipyard/photos/{receipt_photo_ids[0]}",
                timeout=10,
            )
            if first_photo.status_code != 200 or first_photo.content != PNG_BYTES:
                raise AssertionError(f"照片证据读取失败: {first_photo.status_code}")
            steps.append("原图证据可重新读取且字节一致")

            evidence_summary = _database_evidence(
                ticket["ticket_id"],
                confirmed["confirmation"]["confirmation_id"],
            )
            expected_database = {
                "on_hand_quantity": "0.000",
                "ticket_status": "OUTBOUND",
                "confirmation_pallets": 2,
                "recognition_links": 2,
                "photo_links": 2,
                "outbound_ledger_count": 1,
                "outbound_delta": "-4.000",
            }
            if evidence_summary != expected_database:
                raise AssertionError(evidence_summary)

            return {
                "status": "passed",
                "api": api_base,
                "run_id": run_id,
                "ship_no": ship_no,
                "steps": steps,
                "order_status": refreshed_order["order"]["status"],
                "on_hand_quantity": "0.000",
                "confirmation_id": confirmed["confirmation"]["confirmation_id"],
                "database": evidence_summary,
                "ocr": "deterministic stub (no public credential configured)",
            }
    finally:
        conftest._seed_database()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
