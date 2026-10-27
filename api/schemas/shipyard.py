"""Request schemas for the shipyard warehouse domain."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _strip_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip()


class CreateProjectBindingRequest(BaseModel):
    ship_no: str = Field(..., min_length=1, max_length=64)
    engineering_no: str = Field(default="", max_length=64)
    production_drawing_no: str = Field(default="", max_length=128)
    manufacturer_name: str = Field(default="", max_length=200)
    effective_from: Optional[datetime] = None

    @field_validator(
        "ship_no",
        "engineering_no",
        "production_drawing_no",
        "manufacturer_name",
    )
    @classmethod
    def strip_binding_fields(cls, value: str) -> str:
        return value.strip()


class UpdateProjectBindingRequest(BaseModel):
    ship_no: Optional[str] = Field(None, min_length=1, max_length=64)
    engineering_no: Optional[str] = Field(None, max_length=64)
    production_drawing_no: Optional[str] = Field(None, max_length=128)
    manufacturer_name: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = Field(None, pattern="^(ACTIVE|INACTIVE)$")
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None

    @field_validator(
        "ship_no",
        "engineering_no",
        "production_drawing_no",
        "manufacturer_name",
    )
    @classmethod
    def strip_optional_binding_fields(cls, value: Optional[str]) -> Optional[str]:
        return _strip_text(value)


class CreateZoneShipMappingRequest(BaseModel):
    warehouse_id: int = Field(..., gt=0)
    bin_id: int = Field(..., gt=0)
    ship_no: str = Field(..., min_length=1, max_length=64)
    is_primary: bool = True
    effective_from: Optional[datetime] = None

    @field_validator("ship_no")
    @classmethod
    def strip_ship_no(cls, value: str) -> str:
        return value.strip()


class UpdateZoneShipMappingRequest(BaseModel):
    bin_id: Optional[int] = Field(None, gt=0)
    ship_no: Optional[str] = Field(None, min_length=1, max_length=64)
    is_primary: Optional[bool] = None
    status: Optional[str] = Field(None, pattern="^(ACTIVE|INACTIVE)$")
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None

    @field_validator("ship_no")
    @classmethod
    def strip_optional_ship_no(cls, value: Optional[str]) -> Optional[str]:
        return _strip_text(value)


class ConfirmInboundManifestRequest(BaseModel):
    """Confirmation intentionally carries no editable location or quantity."""
