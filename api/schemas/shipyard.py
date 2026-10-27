"""Request schemas for the shipyard warehouse domain."""

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from constants import SHIPYARD_STATUS_ACTIVE, SHIPYARD_STATUS_INACTIVE


def _strip_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


def _strip_required_text(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("must not be blank")
    return text


class CreateProjectBindingRequest(BaseModel):
    ship_no: str = Field(..., min_length=1, max_length=64)
    engineering_no: str = Field(default="", max_length=64)
    production_drawing_no: str = Field(default="", max_length=128)
    manufacturer_name: str = Field(default="", max_length=200)
    effective_from: AwareDatetime | None = None

    @field_validator("ship_no")
    @classmethod
    def strip_required_ship_no(cls, value: str) -> str:
        return _strip_required_text(value)

    @field_validator(
        "engineering_no",
        "production_drawing_no",
        "manufacturer_name",
    )
    @classmethod
    def strip_binding_fields(cls, value: str) -> str:
        return value.strip()


class UpdateProjectBindingRequest(BaseModel):
    ship_no: str | None = Field(None, min_length=1, max_length=64)
    engineering_no: str | None = Field(None, max_length=64)
    production_drawing_no: str | None = Field(None, max_length=128)
    manufacturer_name: str | None = Field(None, max_length=200)
    status: str | None = Field(None, max_length=16)
    effective_from: AwareDatetime | None = None
    effective_to: AwareDatetime | None = None

    @field_validator("ship_no")
    @classmethod
    def strip_optional_ship_no(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strip_required_text(value)

    @field_validator(
        "engineering_no",
        "production_drawing_no",
        "manufacturer_name",
    )
    @classmethod
    def strip_optional_binding_fields(cls, value: str | None) -> str | None:
        return _strip_text(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in (
            SHIPYARD_STATUS_ACTIVE,
            SHIPYARD_STATUS_INACTIVE,
        ):
            raise ValueError("status must be ACTIVE or INACTIVE")
        return value


class CreateZoneShipMappingRequest(BaseModel):
    warehouse_id: int = Field(..., gt=0)
    bin_id: int = Field(..., gt=0)
    ship_no: str = Field(..., min_length=1, max_length=64)
    is_primary: bool = True
    effective_from: AwareDatetime | None = None
    effective_to: AwareDatetime | None = None

    @field_validator("ship_no")
    @classmethod
    def strip_ship_no(cls, value: str) -> str:
        return _strip_required_text(value)


class UpdateZoneShipMappingRequest(BaseModel):
    bin_id: int | None = Field(None, gt=0)
    ship_no: str | None = Field(None, min_length=1, max_length=64)
    is_primary: bool | None = None
    status: str | None = Field(None, max_length=16)
    effective_from: AwareDatetime | None = None
    effective_to: AwareDatetime | None = None

    @field_validator("ship_no")
    @classmethod
    def strip_optional_ship_no(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strip_required_text(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in (
            SHIPYARD_STATUS_ACTIVE,
            SHIPYARD_STATUS_INACTIVE,
        ):
            raise ValueError("status must be ACTIVE or INACTIVE")
        return value


class ConfirmInboundManifestRequest(BaseModel):
    """Confirmation intentionally carries no editable location or quantity."""


class VoidInboundManifestRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return _strip_required_text(value)
