"""Inbound manifest drag-in parsing, review and confirmation."""

from __future__ import annotations

from flask import g, jsonify, request
from sqlalchemy.exc import IntegrityError

from middleware.auth_middleware import (
    check_warehouse_access,
    require_admin_or_page_permission,
    require_auth,
)
from middleware.db import with_db
from schemas.shipyard import ConfirmInboundManifestRequest
from services.shipyard.manifest_parser import ManifestParseError
from services.shipyard.manifest_service import (
    ShipyardServiceError,
    confirm_manifest,
    create_manifest_preview,
    get_manifest_payload,
    list_manifests,
)
from utils.validation import validate_body
from . import shipyard_bp


def _service_error(exc: ShipyardServiceError):
    body = {
        "error": exc.code,
        "message": exc.message,
    }
    body.update(exc.details)
    return jsonify(body), exc.status_code


def _safe_file_name(raw_name: str) -> str:
    name = (raw_name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name[:255]


@shipyard_bp.get("/inbound/manifests")
@require_auth
@require_admin_or_page_permission("inbound")
@with_db
def get_inbound_manifests():
    try:
        warehouse_id = int(request.args.get("warehouse_id", ""))
        limit = int(request.args.get("limit", "50"))
    except (TypeError, ValueError):
        return jsonify({"error": "warehouse_id and limit must be integers"}), 400
    ok, denied = check_warehouse_access(warehouse_id)
    if not ok:
        return denied
    try:
        return jsonify(
            list_manifests(g.db, warehouse_id=warehouse_id, limit=limit)
        )
    except ShipyardServiceError as exc:
        return _service_error(exc)


@shipyard_bp.post("/inbound/manifests/preview")
@require_auth
@require_admin_or_page_permission("inbound")
@with_db
def preview_inbound_manifest():
    if not request.mimetype.startswith("multipart/form-data"):
        return jsonify(
            {
                "error": "unsupported_media_type",
                "message": "请使用 multipart/form-data 上传 Excel 清单",
            }
        ), 415

    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "file_required"}), 400
    source_file_name = _safe_file_name(uploaded.filename)
    if not source_file_name.lower().endswith(".xlsx"):
        return jsonify(
            {
                "error": "unsupported_file_type",
                "message": "首期仅接受 .xlsx 发货清单",
            }
        ), 415

    try:
        warehouse_id = int(request.form.get("warehouse_id", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "warehouse_id is required"}), 400
    ok, denied = check_warehouse_access(warehouse_id)
    if not ok:
        return denied

    content = uploaded.read()
    if not content:
        return jsonify({"error": "empty_file"}), 400
    try:
        payload = create_manifest_preview(
            g.db,
            warehouse_id=warehouse_id,
            manifest_no=request.form.get("manifest_no"),
            source_file_name=source_file_name,
            content=content,
            manufacturer_name=request.form.get("manufacturer_name"),
            created_by=g.current_user["username"],
        )
    except ManifestParseError as exc:
        return jsonify(
            {
                "error": "manifest_parse_failed",
                "message": str(exc),
                "diagnostics": exc.diagnostics,
            }
        ), 422
    except ShipyardServiceError as exc:
        return _service_error(exc)
    except IntegrityError:
        g.db.rollback()
        return jsonify({"error": "manifest_conflict"}), 409
    return jsonify(payload), 201


@shipyard_bp.get("/inbound/manifests/<uuid:manifest_id>")
@require_auth
@require_admin_or_page_permission("inbound")
@with_db
def get_inbound_manifest(manifest_id):
    try:
        payload = get_manifest_payload(g.db, str(manifest_id))
    except ShipyardServiceError as exc:
        return _service_error(exc)
    ok, denied = check_warehouse_access(payload["manifest"]["warehouse_id"])
    if not ok:
        return denied
    return jsonify(payload)


@shipyard_bp.post("/inbound/manifests/<uuid:manifest_id>/confirm")
@require_auth
@require_admin_or_page_permission("inbound")
@validate_body(ConfirmInboundManifestRequest)
@with_db
def confirm_inbound_manifest(manifest_id, validated):
    del validated
    try:
        current = get_manifest_payload(g.db, str(manifest_id))
        ok, denied = check_warehouse_access(current["manifest"]["warehouse_id"])
        if not ok:
            return denied
        payload = confirm_manifest(
            g.db,
            manifest_id=str(manifest_id),
            confirmed_by=g.current_user["username"],
        )
    except ShipyardServiceError as exc:
        return _service_error(exc)
    except IntegrityError:
        g.db.rollback()
        return jsonify({"error": "manifest_confirmation_conflict"}), 409
    return jsonify(payload)
