"""Shipyard WMS API routes."""

import logging

from flask import Blueprint, g, jsonify
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from services.shipyard.errors import ShipyardServiceError

shipyard_bp = Blueprint("shipyard", __name__)
_LOGGER = logging.getLogger(__name__)


@shipyard_bp.errorhandler(ShipyardServiceError)
def _service_error(exc):
    body = {
        "error": exc.code,
        "message": exc.message,
    }
    body.update(exc.details)
    return jsonify(body), exc.status_code


@shipyard_bp.errorhandler(IntegrityError)
def _integrity_error(exc):
    try:
        if g.db.is_active:
            g.db.rollback()
    except SQLAlchemyError:
        _LOGGER.warning("Failed to roll back shipyard integrity error", exc_info=True)
    diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None) if diagnostic else None
    body = {"error": "shipyard_conflict"}
    if constraint:
        body["constraint"] = constraint
    return jsonify(body), 409


@shipyard_bp.errorhandler(SQLAlchemyError)
def _database_error(exc):
    try:
        if g.db.is_active:
            g.db.rollback()
    except SQLAlchemyError:
        _LOGGER.warning("Failed to roll back shipyard database error", exc_info=True)
    _LOGGER.error(
        "Shipyard database operation failed",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return jsonify({"error": "shipyard_database_unavailable"}), 503


from routes.shipyard import config, inbound, receipts  # noqa: F401
