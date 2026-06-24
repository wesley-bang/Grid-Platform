from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PublicUser(BaseModel):
    id: int
    email: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class SpriteResponse(BaseModel):
    id: int
    name: str
    tags: str
    owner_id: int | None
    created_at: datetime
    image_url: str


class PackSpriteResponse(BaseModel):
    position: int
    id: int
    name: str
    tags: str
    image_url: str


class PackResponse(BaseModel):
    id: int
    name: str
    owner_id: int | None
    created_at: datetime
    sprites: list[PackSpriteResponse]


class PackListItem(BaseModel):
    id: int
    name: str
    owner_id: int | None
    created_at: datetime
    sprite_count: int


class Pagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_previous: bool
    has_next: bool


class SpriteListResponse(BaseModel):
    items: list[SpriteResponse]
    pagination: Pagination


class PackListResponse(BaseModel):
    items: list[PackListItem]
    pagination: Pagination


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="allow")
    field: str | None = None
    code: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: object | None
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody

