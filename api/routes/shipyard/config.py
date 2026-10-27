"""Ship/project bindings and zone-to-ship placement rules."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import g, jsonify, request
from sqlalchemy import text

from middleware.auth_middleware import (
    check_warehouse_access,
    require_admin_or_page_permission,
    require_auth,
)
from middleware.db import with_db
from schemas.shipyard import (
    CreateProjectBindingRequest,
    CreateZoneShipMappingRequest,
    UpdateProjectBindingRequest,
    UpdateZoneShipMappingRequest,
)
from services.audit_service import write_audit_log
from utils.validation import validate_body
from . import shipyard_bp


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _binding_payload(row):
    return {
        "binding_id": row.binding_id,
        "ship_no": row.ship_no,
        "engineering_no": row.engineering_no,
        "production_drawing_no": row.production_drawing_no,
        "manufacturer_name": row.manufacturer_name,
        "status": row.status,
        "effective_from": _iso(row.effective_from),
        "effective_to": _iso(row.effective_to),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _mapping_payload(row):
    return {
        "mapping_id": row.mapping_id,
        "warehouse_id": row.warehouse_id,
        "bin_id": row.bin_id,
        "bin_code": row.bin_code,
        "zone_id": row.zone_id,
        "zone_code": row.zone_code,
        "zone_name": row.zone_name,
        "location_path": " / ".join(
            value for value in (row.zone_code, row.bin_code) if value
        ),
        "ship_no": row.ship_no,
        "is_primary": row.is_primary,
        "status": row.status,
        "effective_from": _iso(row.effective_from),
        "effective_to": _iso(row.effective_to),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


@shipyard_bp.get("/bindings")
@require_auth
@require_admin_or_page_permission("settings")
@with_db
def list_project_bindings():
    ship_no = (request.args.get("ship_no") or "").strip()
    active_only = request.args.get("active_only", "true").lower() != "false"
    clauses = []
    params = {}
    if ship_no:
        clauses.append("ship_no = :ship_no")
        params["ship_no"] = ship_no
    if active_only:
        clauses.append("status = 'ACTIVE'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = g.db.execute(
        text(
            f"""
            SELECT binding_id, ship_no, engineering_no,
                   production_drawing_no, manufacturer_name, status,
                   effective_from, effective_to, created_at, updated_at
              FROM shipyard_project_bindings
              {where}
             ORDER BY ship_no, engineering_no, production_drawing_no,
                      manufacturer_name
            """
        ),
        params,
    ).fetchall()
    return jsonify({"bindings": [_binding_payload(row) for row in rows]})


@shipyard_bp.post("/bindings")
@require_auth
@require_admin_or_page_permission("settings")
@validate_body(CreateProjectBindingRequest)
@with_db
def create_project_binding(validated):
    data = validated.model_dump()
    duplicate = g.db.execute(
        text(
            """
            SELECT binding_id
              FROM shipyard_project_bindings
             WHERE status = 'ACTIVE'
               AND ship_no = :ship_no
               AND engineering_no = :engineering_no
               AND production_drawing_no = :production_drawing_no
               AND manufacturer_name = :manufacturer_name
            """
        ),
        data,
    ).fetchone()
    if duplicate is not None:
        return jsonify(
            {
                "error": "duplicate_project_binding",
                "binding_id": duplicate.binding_id,
            }
        ), 409

    row = g.db.execute(
        text(
            """
            INSERT INTO shipyard_project_bindings
                (ship_no, engineering_no, production_drawing_no,
                 manufacturer_name, effective_from)
            VALUES
                (:ship_no, :engineering_no, :production_drawing_no,
                 :manufacturer_name, COALESCE(:effective_from, NOW()))
            RETURNING binding_id, ship_no, engineering_no,
                      production_drawing_no, manufacturer_name, status,
                      effective_from, effective_to, created_at, updated_at
            """
        ),
        data,
    ).fetchone()
    write_audit_log(
        g.db,
        action_type="SHIPYARD_PROJECT_BINDING_CREATED",
        entity_type="shipyard_project_binding",
        entity_id=row.binding_id,
        user_id=g.current_user["username"],
        warehouse_id=None,
        details={"after": _binding_payload(row)},
    )
    g.db.commit()
    return jsonify({"binding": _binding_payload(row)}), 201


@shipyard_bp.put("/bindings/<int:binding_id>")
@require_auth
@require_admin_or_page_permission("settings")
@validate_body(UpdateProjectBindingRequest)
@with_db
def update_project_binding(binding_id, validated):
    current = g.db.execute(
        text(
            """
            SELECT binding_id, ship_no, engineering_no,
                   production_drawing_no, manufacturer_name, status,
                   effective_from, effective_to, created_at, updated_at
              FROM shipyard_project_bindings
             WHERE binding_id = :binding_id
             FOR UPDATE
            """
        ),
        {"binding_id": binding_id},
    ).fetchone()
    if current is None:
        return jsonify({"error": "binding_not_found"}), 404

    updates = validated.model_dump(exclude_unset=True)
    if updates.get("status") == "INACTIVE" and "effective_to" not in updates:
        updates["effective_to"] = datetime.now(timezone.utc)
    effective_from = updates.get("effective_from", current.effective_from)
    effective_to = updates.get("effective_to", current.effective_to)
    if effective_to is not None and effective_to <= effective_from:
        return jsonify({"error": "invalid_effective_window"}), 400
    if not updates:
        return jsonify({"binding": _binding_payload(current)})

    updates["binding_id"] = binding_id
    assignments = ", ".join(f"{column} = :{column}" for column in updates if column != "binding_id")
    row = g.db.execute(
        text(
            f"""
            UPDATE shipyard_project_bindings
               SET {assignments}, updated_at = NOW()
             WHERE binding_id = :binding_id
            RETURNING binding_id, ship_no, engineering_no,
                      production_drawing_no, manufacturer_name, status,
                      effective_from, effective_to, created_at, updated_at
            """
        ),
        updates,
    ).fetchone()
    write_audit_log(
        g.db,
        action_type="SHIPYARD_PROJECT_BINDING_UPDATED",
        entity_type="shipyard_project_binding",
        entity_id=binding_id,
        user_id=g.current_user["username"],
        warehouse_id=None,
        details={
            "before": _binding_payload(current),
            "after": _binding_payload(row),
        },
    )
    g.db.commit()
    return jsonify({"binding": _binding_payload(row)})


@shipyard_bp.get("/zone-mappings")
@require_auth
@with_db
def list_zone_ship_mappings():
    try:
        warehouse_id = int(request.args.get("warehouse_id", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "warehouse_id is required"}), 400
    ok, denied = check_warehouse_access(warehouse_id)
    if not ok:
        return denied

    ship_no = (request.args.get("ship_no") or "").strip()
    active_only = request.args.get("active_only", "true").lower() != "false"
    clauses = ["b.warehouse_id = :warehouse_id"]
    params = {"warehouse_id": warehouse_id}
    if ship_no:
        clauses.append("m.ship_no = :ship_no")
        params["ship_no"] = ship_no
    if active_only:
        clauses.append("m.status = 'ACTIVE'")
    rows = g.db.execute(
        text(
            f"""
            SELECT m.mapping_id, b.warehouse_id, m.bin_id, b.bin_code,
                   z.zone_id, z.zone_code, z.zone_name, m.ship_no,
                   m.is_primary, m.status, m.effective_from, m.effective_to,
                   m.created_at, m.updated_at
              FROM shipyard_zone_ship_mappings m
              JOIN bins b ON b.bin_id = m.bin_id
              LEFT JOIN zones z ON z.zone_id = b.zone_id
             WHERE {' AND '.join(clauses)}
             ORDER BY m.ship_no, z.zone_code, b.bin_code
            """
        ),
        params,
    ).fetchall()
    return jsonify({"mappings": [_mapping_payload(row) for row in rows]})


def _bin_for_warehouse(db, bin_id: int, warehouse_id: int):
    return db.execute(
        text(
            """
            SELECT b.bin_id, b.bin_code, b.warehouse_id,
                   z.zone_id, z.zone_code, z.zone_name
              FROM bins b
              JOIN zones z ON z.zone_id = b.zone_id
             WHERE b.bin_id = :bin_id
               AND b.warehouse_id = :warehouse_id
            """
        ),
        {"bin_id": bin_id, "warehouse_id": warehouse_id},
    ).fetchone()


@shipyard_bp.post("/zone-mappings")
@require_auth
@require_admin_or_page_permission("settings")
@validate_body(CreateZoneShipMappingRequest)
@with_db
def create_zone_ship_mapping(validated):
    ok, denied = check_warehouse_access(validated.warehouse_id)
    if not ok:
        return denied
    target_bin = _bin_for_warehouse(
        g.db, validated.bin_id, validated.warehouse_id
    )
    if target_bin is None:
        return jsonify({"error": "bin_not_in_warehouse"}), 400

    conflict = g.db.execute(
        text(
            """
            SELECT mapping_id, bin_id
              FROM shipyard_zone_ship_mappings
             WHERE status = 'ACTIVE'
               AND ship_no = :ship_no
               AND is_primary = TRUE
            """
        ),
        {"ship_no": validated.ship_no},
    ).fetchone()
    if conflict is not None:
        return jsonify(
            {
                "error": "ship_already_has_primary_zone",
                "mapping_id": conflict.mapping_id,
                "bin_id": conflict.bin_id,
            }
        ), 409

    row = g.db.execute(
        text(
            """
            INSERT INTO shipyard_zone_ship_mappings
                (bin_id, ship_no, is_primary, effective_from)
            VALUES
                (:bin_id, :ship_no, :is_primary,
                 COALESCE(:effective_from, NOW()))
            RETURNING mapping_id
            """
        ),
        validated.model_dump(),
    ).fetchone()
    payload = g.db.execute(
        text(
            """
            SELECT m.mapping_id, b.warehouse_id, m.bin_id, b.bin_code,
                   z.zone_id, z.zone_code, z.zone_name, m.ship_no,
                   m.is_primary, m.status, m.effective_from, m.effective_to,
                   m.created_at, m.updated_at
              FROM shipyard_zone_ship_mappings m
              JOIN bins b ON b.bin_id = m.bin_id
              LEFT JOIN zones z ON z.zone_id = b.zone_id
             WHERE m.mapping_id = :mapping_id
            """
        ),
        {"mapping_id": row.mapping_id},
    ).fetchone()
    write_audit_log(
        g.db,
        action_type="SHIPYARD_ZONE_SHIP_MAPPING_CREATED",
        entity_type="shipyard_zone_ship_mapping",
        entity_id=row.mapping_id,
        user_id=g.current_user["username"],
        warehouse_id=validated.warehouse_id,
        details={"after": _mapping_payload(payload)},
    )
    g.db.commit()
    return jsonify({"mapping": _mapping_payload(payload)}), 201


@shipyard_bp.put("/zone-mappings/<int:mapping_id>")
@require_auth
@require_admin_or_page_permission("settings")
@validate_body(UpdateZoneShipMappingRequest)
@with_db
def update_zone_ship_mapping(mapping_id, validated):
    current = g.db.execute(
        text(
            """
            SELECT m.mapping_id, b.warehouse_id, m.bin_id, b.bin_code,
                   z.zone_id, z.zone_code, z.zone_name, m.ship_no,
                   m.is_primary, m.status, m.effective_from, m.effective_to,
                   m.created_at, m.updated_at
              FROM shipyard_zone_ship_mappings m
              JOIN bins b ON b.bin_id = m.bin_id
              LEFT JOIN zones z ON z.zone_id = b.zone_id
             WHERE m.mapping_id = :mapping_id
             FOR UPDATE OF m
            """
        ),
        {"mapping_id": mapping_id},
    ).fetchone()
    if current is None:
        return jsonify({"error": "mapping_not_found"}), 404
    ok, denied = check_warehouse_access(current.warehouse_id)
    if not ok:
        return denied

    updates = validated.model_dump(exclude_unset=True)
    if "bin_id" in updates:
        target_bin = _bin_for_warehouse(
            g.db, updates["bin_id"], current.warehouse_id
        )
        if target_bin is None:
            return jsonify({"error": "bin_not_in_warehouse"}), 400
    if updates.get("status") == "INACTIVE" and "effective_to" not in updates:
        updates["effective_to"] = datetime.now(timezone.utc)
    effective_from = updates.get("effective_from", current.effective_from)
    effective_to = updates.get("effective_to", current.effective_to)
    if effective_to is not None and effective_to <= effective_from:
        return jsonify({"error": "invalid_effective_window"}), 400
    if not updates:
        return jsonify({"mapping": _mapping_payload(current)})

    updates["mapping_id"] = mapping_id
    assignments = ", ".join(
        f"{column} = :{column}" for column in updates if column != "mapping_id"
    )
    g.db.execute(
        text(
            f"""
            UPDATE shipyard_zone_ship_mappings
               SET {assignments}, updated_at = NOW()
             WHERE mapping_id = :mapping_id
            """
        ),
        updates,
    )
    payload = g.db.execute(
        text(
            """
            SELECT m.mapping_id, b.warehouse_id, m.bin_id, b.bin_code,
                   z.zone_id, z.zone_code, z.zone_name, m.ship_no,
                   m.is_primary, m.status, m.effective_from, m.effective_to,
                   m.created_at, m.updated_at
              FROM shipyard_zone_ship_mappings m
              JOIN bins b ON b.bin_id = m.bin_id
              LEFT JOIN zones z ON z.zone_id = b.zone_id
             WHERE m.mapping_id = :mapping_id
            """
        ),
        {"mapping_id": mapping_id},
    ).fetchone()
    write_audit_log(
        g.db,
        action_type="SHIPYARD_ZONE_SHIP_MAPPING_UPDATED",
        entity_type="shipyard_zone_ship_mapping",
        entity_id=mapping_id,
        user_id=g.current_user["username"],
        warehouse_id=current.warehouse_id,
        details={
            "before": _mapping_payload(current),
            "after": _mapping_payload(payload),
        },
    )
    g.db.commit()
    return jsonify({"mapping": _mapping_payload(payload)})
