from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, StrictInt, field_validator, model_validator


ASCII_UPPER = re.compile(r"[A-Z]")


class ValidationCodeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def contains_control(value: str) -> bool:
    return any(unicodedata.category(char) == "Cc" for char in value)


def text_weight(value: str) -> int:
    value = unicodedata.normalize("NFC", value)
    return sum(
        2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        for char in value
    )


def normalize_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationCodeError("NAME_INVALID_TYPE")
    if contains_control(value):
        raise ValidationCodeError("NAME_CONTROL_CHARACTER")
    normalized = unicodedata.normalize("NFC", value.strip())
    if not normalized:
        raise ValidationCodeError("NAME_REQUIRED")
    if text_weight(normalized) > 40:
        raise ValidationCodeError("NAME_TOO_LONG")
    return normalized


def ascii_lower(value: str) -> str:
    return ASCII_UPPER.sub(lambda match: match.group(0).lower(), value)


def normalize_tags(value: Any) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise ValidationCodeError("TAGS_INVALID_TYPE")

    raw_parts = value.split(",")
    normalized_parts: list[str] = []
    seen: set[str] = set()
    for raw in raw_parts:
        if contains_control(raw):
            raise ValidationCodeError("TAG_CONTROL_CHARACTER")
        tag = ascii_lower(unicodedata.normalize("NFC", raw.strip()))
        if not tag:
            raise ValidationCodeError("TAG_REQUIRED")
        if text_weight(tag) > 20:
            raise ValidationCodeError("TAG_TOO_LONG")
        if tag not in seen:
            seen.add(tag)
            normalized_parts.append(tag)

    if len(normalized_parts) > 20:
        raise ValidationCodeError("TOO_MANY_TAGS")
    return ",".join(normalized_parts)


def normalize_search(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", value.strip())
    return normalized or None


def normalize_search_tags(value: str | None) -> list[str]:
    if value is None:
        return []
    terms = []
    for part in value.split(","):
        term = normalize_search(part)
        if term:
            terms.append(term)
    return terms


def escape_like(value: str, escape: str = "\\") -> str:
    return (
        value.replace(escape, escape + escape)
        .replace("%", escape + "%")
        .replace("_", escape + "_")
    )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValidationCodeError("EMAIL_INVALID")
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValidationCodeError("PASSWORD_TOO_SHORT")
        if len(value) > 128:
            raise ValidationCodeError("PASSWORD_TOO_LONG")
        return value


class LoginRequest(StrictModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValidationCodeError("EMAIL_INVALID")
        return value.strip().lower()


class PackCreateRequest(StrictModel):
    name: str
    sprite_ids: list[StrictInt]

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: Any) -> str:
        return normalize_name(value)


class PackPatchRequest(StrictModel):
    name: str | None = None
    sprite_ids: list[StrictInt] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: Any) -> str:
        return normalize_name(value)

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> "PackPatchRequest":
        if "sprite_ids" in self.model_fields_set and self.sprite_ids is None:
            raise ValidationCodeError("SPRITE_IDS_REQUIRED")
        return self
