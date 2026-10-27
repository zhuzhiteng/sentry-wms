"""Shipyard WMS API routes."""

from flask import Blueprint


shipyard_bp = Blueprint("shipyard", __name__)


from routes.shipyard import config, inbound  # noqa: E402, F401
