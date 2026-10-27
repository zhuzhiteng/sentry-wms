"""Typed errors shared by the shipyard API and service layer."""

from __future__ import annotations

from typing import Any


class ShipyardServiceError(Exception):
    code = "shipyard_error"
    status_code = 400

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ShipyardNotFoundError(ShipyardServiceError):
    code = "shipyard_not_found"
    status_code = 404


class ShipyardConflictError(ShipyardServiceError):
    code = "shipyard_conflict"
    status_code = 409


class ShipyardValidationError(ShipyardServiceError):
    code = "shipyard_validation_error"
    status_code = 400


class ShipyardStateError(ShipyardServiceError):
    code = "shipyard_state_conflict"
    status_code = 409


class ManifestNotFoundError(ShipyardNotFoundError):
    code = "manifest_not_found"


class ManifestStateError(ShipyardStateError):
    code = "manifest_state_conflict"


class DuplicateManifestFileError(ShipyardConflictError):
    code = "duplicate_manifest_file"


class ZoneConfigurationError(ShipyardServiceError):
    code = "zone_configuration_required"
    status_code = 422


class BindingConfigurationError(ShipyardServiceError):
    code = "binding_configuration_required"
    status_code = 422


class WarehouseNotFoundError(ShipyardNotFoundError):
    code = "warehouse_not_found"


class ConfigConflictError(ShipyardConflictError):
    code = "shipyard_config_conflict"


class TicketNotFoundError(ShipyardNotFoundError):
    code = "ticket_not_found"


class TicketStateError(ShipyardStateError):
    code = "ticket_state_conflict"


class PalletValidationError(ShipyardServiceError):
    code = "pallet_validation_failed"
    status_code = 422


class PalletDuplicateError(ShipyardConflictError):
    code = "pallet_duplicate"


class PhotoValidationError(ShipyardServiceError):
    code = "photo_validation_failed"
    status_code = 422


class PhotoNotFoundError(ShipyardNotFoundError):
    code = "photo_not_found"


class ShortageStateError(ShipyardStateError):
    code = "shortage_state_conflict"
