from io import BytesIO

from openpyxl import Workbook

from db_test_context import get_raw_connection


def _workbook_bytes(rows, title="外高桥"):
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


def _manifest_bytes(ship_no="H9001", manufacturer="测试船舶配件有限公司"):
    return _workbook_bytes(
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


def _first_bin():
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


def _create_binding(client, headers, ship_no, drawing="D-001"):
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


def _create_zone_mapping(client, headers, ship_no):
    bin_id, _bin_code, _zone_code = _first_bin()
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


def _upload_manifest(client, headers, content, manifest_no="IN-H9001-001"):
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


def test_project_binding_and_zone_mapping_are_listed(client, auth_headers):
    binding = _create_binding(client, auth_headers, "H9101")
    mapping = _create_zone_mapping(client, auth_headers, "H9101")

    bindings = client.get(
        "/api/shipyard/bindings?ship_no=H9101",
        headers=auth_headers,
    )
    assert bindings.status_code == 200
    assert bindings.get_json()["bindings"][0]["binding_id"] == binding["binding_id"]

    mappings = client.get(
        "/api/shipyard/zone-mappings?warehouse_id=1&ship_no=H9101",
        headers=auth_headers,
    )
    assert mappings.status_code == 200
    assert mappings.get_json()["mappings"][0]["mapping_id"] == mapping["mapping_id"]
    assert mappings.get_json()["mappings"][0]["is_primary"] is True


def test_preview_warns_when_ship_has_no_primary_zone(client, auth_headers):
    _create_binding(client, auth_headers, "H9102")
    response = _upload_manifest(
        client,
        auth_headers,
        _manifest_bytes("H9102"),
        manifest_no="IN-H9102-001",
    )

    assert response.status_code == 201, response.get_json()
    data = response.get_json()
    assert data["manifest"]["status"] == "PARSED"
    assert data["validation"]["can_confirm"] is False
    assert data["validation"]["missing_zone_ship_nos"] == ["H9102"]
    assert data["lines"][0]["binding"]["status"] == "MATCHED"
    assert data["lines"][0]["suggested_bin"] is None

    confirm = client.post(
        f"/api/shipyard/inbound/manifests/{data['manifest']['manifest_id']}/confirm",
        json={},
        headers=auth_headers,
    )
    assert confirm.status_code == 422
    assert confirm.get_json()["error"] == "zone_configuration_required"


def test_preview_confirm_creates_one_expected_ticket_per_source_row(
    client, auth_headers
):
    _create_binding(client, auth_headers, "H9103")
    mapping = _create_zone_mapping(client, auth_headers, "H9103")
    preview = _upload_manifest(
        client,
        auth_headers,
        _manifest_bytes("H9103"),
        manifest_no="IN-H9103-001",
    )
    assert preview.status_code == 201, preview.get_json()
    preview_data = preview.get_json()
    assert preview_data["validation"]["can_confirm"] is True
    assert [line["source_row_no"] for line in preview_data["lines"]] == ["1", "2"]
    assert preview_data["lines"][0]["suggested_bin"]["bin_id"] == mapping["bin_id"]
    assert preview_data["tickets"] == []

    confirm = client.post(
        f"/api/shipyard/inbound/manifests/{preview_data['manifest']['manifest_id']}/confirm",
        json={},
        headers=auth_headers,
    )
    assert confirm.status_code == 200, confirm.get_json()
    confirmed = confirm.get_json()
    assert confirmed["manifest"]["status"] == "CONFIRMED"
    assert len(confirmed["tickets"]) == 2
    assert len(confirmed["confirmed_tickets"]) == 2
    assert {ticket["status"] for ticket in confirmed["tickets"]} == {"EXPECTED"}
    assert {
        ticket["location_path_snapshot"] for ticket in confirmed["tickets"]
    } == {mapping["location_path"]}

    repeated = client.post(
        f"/api/shipyard/inbound/manifests/{preview_data['manifest']['manifest_id']}/confirm",
        json={},
        headers=auth_headers,
    )
    assert repeated.status_code == 409
    assert repeated.get_json()["error"] == "manifest_state_conflict"


def test_duplicate_manifest_file_is_rejected(client, auth_headers):
    content = _manifest_bytes("H9104")
    first = _upload_manifest(
        client,
        auth_headers,
        content,
        manifest_no="IN-H9104-001",
    )
    assert first.status_code == 201

    duplicate = _upload_manifest(
        client,
        auth_headers,
        content,
        manifest_no="IN-H9104-002",
    )
    assert duplicate.status_code == 409
    assert duplicate.get_json()["error"] == "duplicate_manifest_file"
    assert duplicate.get_json()["manifest_id"] == first.get_json()["manifest"][
        "manifest_id"
    ]


def test_manifest_list_and_detail_expose_validation_summary(client, auth_headers):
    _create_binding(client, auth_headers, "H9105")
    _create_zone_mapping(client, auth_headers, "H9105")
    preview = _upload_manifest(
        client,
        auth_headers,
        _manifest_bytes("H9105"),
        manifest_no="IN-H9105-001",
    )
    manifest_id = preview.get_json()["manifest"]["manifest_id"]

    listing = client.get(
        "/api/shipyard/inbound/manifests?warehouse_id=1",
        headers=auth_headers,
    )
    assert listing.status_code == 200
    assert listing.get_json()["manifests"][0]["line_count"] == 2
    assert listing.get_json()["manifests"][0]["total_quantity"] == "20.000"

    detail = client.get(
        f"/api/shipyard/inbound/manifests/{manifest_id}",
        headers=auth_headers,
    )
    assert detail.status_code == 200
    assert detail.get_json()["validation"]["summary"]["line_count"] == 2
    assert detail.get_json()["validation"]["summary"]["total_quantity"] == "20.000"
