"""Shared fixtures for shipyard API workflow tests."""

from io import BytesIO

from db_test_context import get_raw_connection
from openpyxl import Workbook

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
)


def workbook_bytes(rows, title="外高桥"):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = title
    for row in rows:
        worksheet.append(row)
    auxiliary = workbook.create_sheet("Sheet1")
    auxiliary.append([None, None])
    auxiliary.append(["辅助物料", 24])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def manifest_bytes(ship_no="H9001", manufacturer="测试船舶配件有限公司"):
    return workbook_bytes(
        [
            [manufacturer],
            ["2026舾装件发货清单"],
            [
                "序号",
                "船号",
                "品名",
                "图号",
                "图名",
                "件数",
                "PO NO",
                "送货单号",
                "PO号",
                "重量",
                "螺丝",
            ],
            [
                "1",
                ship_no,
                "舾装件",
                "D-001",
                "制作图A",
                15,
                "9001",
                "0929501",
                "SWS202600001",
                39,
                "基座",
            ],
            [
                "2",
                ship_no,
                "舾装件",
                "D-002",
                "制作图B",
                5,
                "9002",
                "0929501",
                "SWS202600002",
                8,
                "托架",
            ],
        ]
    )


def single_line_manifest_bytes(
    ship_no,
    *,
    quantity=4,
    drawing="D-001",
    manufacturer="测试船舶配件有限公司",
):
    return workbook_bytes(
        [
            [manufacturer],
            ["2026舾装件发货清单"],
            ["序号", "船号", "品名", "图号", "图名", "件数"],
            ["1", ship_no, "舾装件", drawing, "制作图A", quantity],
        ]
    )


def manifest_bytes_without_drawing(ship_no, manufacturer="测试船舶配件有限公司"):
    return workbook_bytes(
        [
            [manufacturer],
            ["2026舾装件发货清单"],
            ["序号", "船号", "品名", "件数"],
            ["1", ship_no, "舾装件", 5],
        ]
    )


def first_bin():
    conn = get_raw_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.bin_id, b.bin_code, z.zone_code
          FROM bins b
          JOIN zones z ON z.zone_id = b.zone_id
         WHERE b.warehouse_id = 1
         ORDER BY b.bin_id
         LIMIT 1
        """
    )
    row = cur.fetchone()
    cur.close()
    return row


def create_binding(client, headers, ship_no, drawing="D-001"):
    response = client.post(
        "/api/shipyard/bindings",
        json={
            "ship_no": ship_no,
            "engineering_no": ship_no,
            "production_drawing_no": drawing,
            "manufacturer_name": "测试船舶配件有限公司",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["binding"]


def create_zone_mapping(client, headers, ship_no):
    bin_id, _bin_code, _zone_code = first_bin()
    response = client.post(
        "/api/shipyard/zone-mappings",
        json={
            "warehouse_id": 1,
            "bin_id": bin_id,
            "ship_no": ship_no,
            "is_primary": True,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["mapping"]


def upload_manifest(
    client,
    headers,
    content,
    manifest_no="IN-H9001-001",
):
    return client.post(
        "/api/shipyard/inbound/manifests/preview",
        data={
            "warehouse_id": "1",
            "manifest_no": manifest_no,
            "file": (BytesIO(content), "外高桥发货清单.xlsx"),
        },
        content_type="multipart/form-data",
        headers=headers,
    )


def confirm_manifest(client, headers, manifest_id):
    response = client.post(
        f"/api/shipyard/inbound/manifests/{manifest_id}/confirm",
        json={},
        headers=headers,
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def upload_ticket_photo(
    client,
    headers,
    ticket_id,
    *,
    tag_suffix=None,
    photo_kind="PALLET",
    content=PNG_BYTES,
    file_name="pallet.png",
):
    data = {"photo_kind": photo_kind}
    if tag_suffix is not None:
        data["tag_suffix"] = tag_suffix
    return client.post(
        f"/api/shipyard/inbound/tickets/{ticket_id}/photos",
        data={
            **data,
            "file": (BytesIO(content), file_name),
        },
        content_type="multipart/form-data",
        headers=headers,
    )


def receive_ticket(
    client,
    headers,
    ticket_id,
    *,
    quantity=4,
    pallets,
    idempotency_key,
    difference_reason=None,
    group_photo_id=None,
    area_photo_id=None,
    difference_photo_id=None,
):
    payload = {
        "idempotency_key": idempotency_key,
        "received_quantity": quantity,
        "pallets": pallets,
    }
    if difference_reason is not None:
        payload["difference_reason"] = difference_reason
    if group_photo_id is not None:
        payload["group_photo_id"] = group_photo_id
    if area_photo_id is not None:
        payload["area_photo_id"] = area_photo_id
    if difference_photo_id is not None:
        payload["difference_photo_id"] = difference_photo_id
    return client.post(
        f"/api/shipyard/inbound/tickets/{ticket_id}/receipts",
        json=payload,
        headers=headers,
    )


def pallet_payload(
    *,
    photo_id,
    tag_suffix=None,
    ship_no="H9201",
    engineering_no=None,
    drawing="D-001",
    qr_payload=None,
    label_quantity=4,
):
    return {
        "tag_suffix": tag_suffix,
        "qr_payload": qr_payload or f"QR-{ship_no}-{drawing}-{tag_suffix or 'single'}",
        "ship_no": ship_no,
        "engineering_no": engineering_no or ship_no,
        "production_drawing_no": drawing,
        "qr_pallet_no": drawing,
        "batch_no": f"{ship_no}-BATCH-1",
        "manufacturer_name": "测试船舶配件有限公司",
        "installation_pallet_no": f"INSTALL-{tag_suffix or 'single'}",
        "installation_pallet_name": "制作图A",
        "destination": "外高桥",
        "label_quantity": label_quantity,
        "photo_id": photo_id,
    }
