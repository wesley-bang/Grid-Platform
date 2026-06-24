from __future__ import annotations

import base64
import logging
import math
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import ulid
from fastapi import Depends, FastAPI, File, Form, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import PROJECT_ROOT, get_settings
from app.database import get_db
from app.errors import ApiError, install_exception_handlers, validation_detail
from app.image_processing import process_upload
from app.models import Pack, PackSprite, Sprite, User
from app.schemas import (
    ErrorResponse,
    PackListResponse,
    PackResponse,
    PublicUser,
    SpriteListResponse,
    SpriteResponse,
    TokenResponse,
)
from app.security import (
    ACCESS_TOKEN_SECONDS,
    create_access_token,
    hash_password,
    token_from_request,
    verify_password,
)
from app.validation import (
    LoginRequest,
    PackCreateRequest,
    PackPatchRequest,
    RegisterRequest,
    escape_like,
    normalize_name,
    normalize_search,
    normalize_search_tags,
    normalize_tags,
    ascii_lower,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("grid_platform")
settings = get_settings()

app = FastAPI(
    title="Grid++ 素材庫平台 API",
    version="1.0.0",
    description="32×32 RGBA8888 素材及素材包管理平台",
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = f"req_{ulid.new()}"
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled middleware exception request_id=%s", request_id)
        response = JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "伺服器發生未預期的錯誤",
                    "details": None,
                    "request_id": request_id,
                }
            },
        )
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


install_exception_handlers(app)


COMMON_ERRORS = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    415: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


def iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def require_json_content_type(request: Request) -> None:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE")


def reject_extra_query(request: Request, allowed: set[str]) -> None:
    extras = sorted(set(request.query_params.keys()) - allowed)
    if extras:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            details=[validation_detail(name, "EXTRA_FIELD") for name in extras],
        )


async def reject_extra_form(request: Request, allowed: set[str]) -> None:
    form = await request.form()
    extras = sorted(set(form.keys()) - allowed)
    if extras:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            details=[validation_detail(name, "EXTRA_FIELD") for name in extras],
        )


def current_user(request: Request, db: Session) -> User:
    user_id = token_from_request(request, required=True)
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(401, "AUTH_TOKEN_INVALID")
    return user


def optional_user(request: Request, db: Session) -> User | None:
    user_id = token_from_request(request, required=False)
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(401, "AUTH_TOKEN_INVALID")
    return user


def pagination_payload(page: int, page_size: int, total_items: int) -> dict[str, Any]:
    total_pages = math.ceil(total_items / page_size) if total_items else 0
    return {
        "page": page,
        "page_size": page_size,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_previous": page > 1 and total_pages > 0,
        "has_next": page < total_pages,
    }


def sprite_payload(sprite: Sprite) -> dict[str, Any]:
    return {
        "id": sprite.id,
        "name": sprite.name,
        "tags": sprite.tags,
        "owner_id": sprite.owner_id,
        "created_at": iso_z(sprite.created_at),
        "image_url": f"/sprites/{sprite.id}/image",
    }


def pack_payload(pack: Pack) -> dict[str, Any]:
    links = sorted(pack.sprite_links, key=lambda link: link.position)
    return {
        "id": pack.id,
        "name": pack.name,
        "owner_id": pack.owner_id,
        "created_at": iso_z(pack.created_at),
        "sprites": [
            {
                "position": link.position,
                "id": link.sprite.id,
                "name": link.sprite.name,
                "tags": link.sprite.tags,
                "image_url": f"/sprites/{link.sprite.id}/image",
            }
            for link in links
        ],
    }


def load_pack(db: Session, pack_id: int) -> Pack:
    pack = db.scalar(
        select(Pack)
        .where(Pack.id == pack_id)
        .options(selectinload(Pack.sprite_links).selectinload(PackSprite.sprite))
    )
    if pack is None:
        raise ApiError(404, "PACK_NOT_FOUND", details={"pack_id": pack_id})
    return pack


def validate_sprite_ids(db: Session, sprite_ids: list[int]) -> None:
    duplicates = sorted(
        sprite_id for sprite_id, count in Counter(sprite_ids).items() if count > 1
    )
    details = []
    if duplicates:
        details.append(
            validation_detail(
                "sprite_ids",
                "DUPLICATE_SPRITE_IN_PACK",
                sprite_ids=duplicates,
            )
        )
    unique_ids = set(sprite_ids)
    existing_ids = (
        set(db.scalars(select(Sprite.id).where(Sprite.id.in_(unique_ids))).all())
        if unique_ids
        else set()
    )
    missing = sorted(unique_ids - existing_ids)
    if missing:
        details.append(
            validation_detail("sprite_ids", "SPRITE_IDS_NOT_FOUND", sprite_ids=missing)
        )
    if details:
        raise ApiError(422, "VALIDATION_ERROR", details=details)


def replace_pack_sprites(db: Session, pack_id: int, sprite_ids: Iterable[int]) -> None:
    db.execute(delete(PackSprite).where(PackSprite.pack_id == pack_id))
    db.flush()
    db.add_all(
        [
            PackSprite(pack_id=pack_id, sprite_id=sprite_id, position=position)
            for position, sprite_id in enumerate(sprite_ids)
        ]
    )


@app.post(
    "/auth/register",
    response_model=PublicUser,
    status_code=status.HTTP_201_CREATED,
    responses=COMMON_ERRORS,
)
def register(
    payload: RegisterRequest,
    _content_type: Annotated[None, Depends(require_json_content_type)],
    db: Annotated[Session, Depends(get_db)],
):
    user = User(email=str(payload.email), password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "EMAIL_ALREADY_REGISTERED") from exc
    db.refresh(user)
    return {"id": user.id, "email": user.email, "created_at": iso_z(user.created_at)}


@app.post("/auth/login", response_model=TokenResponse, responses=COMMON_ERRORS)
def login(
    payload: LoginRequest,
    _content_type: Annotated[None, Depends(require_json_content_type)],
    db: Annotated[Session, Depends(get_db)],
):
    user = db.scalar(select(User).where(User.email == str(payload.email)))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS")
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_SECONDS,
    }


@app.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=COMMON_ERRORS,
)
def logout(request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    current_user(request, db)
    return Response(status_code=204)


@app.get("/sprites", response_model=SpriteListResponse, responses=COMMON_ERRORS)
def list_sprites(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    name: str | None = None,
    tags: str | None = None,
    tag_mode: str = "and",
    sort: str = "newest",
):
    reject_extra_query(request, {"page", "page_size", "name", "tags", "tag_mode", "sort"})
    if tag_mode not in {"and", "or"}:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            details=[validation_detail("tag_mode", "INVALID_TAG_MODE")],
        )
    if sort not in {"newest", "oldest", "name_asc", "name_desc"}:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            details=[validation_detail("sort", "INVALID_SORT")],
        )

    conditions = []
    name_term = normalize_search(name)
    if name_term:
        conditions.append(
            func.lower(Sprite.name).like(
                f"%{escape_like(ascii_lower(name_term))}%", escape="\\"
            )
        )
    tag_terms = normalize_search_tags(tags)
    if tag_terms:
        tag_conditions = [
            func.lower(Sprite.tags).like(
                f"%{escape_like(ascii_lower(term))}%", escape="\\"
            )
            for term in tag_terms
        ]
        conditions.append(
            and_(*tag_conditions) if tag_mode == "and" else or_(*tag_conditions)
        )

    base = select(Sprite).where(*conditions)
    total_items = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    orderings = {
        "newest": (Sprite.created_at.desc(), Sprite.id.desc()),
        "oldest": (Sprite.created_at.asc(), Sprite.id.asc()),
        "name_asc": (Sprite.name.collate("NOCASE").asc(), Sprite.id.asc()),
        "name_desc": (Sprite.name.collate("NOCASE").desc(), Sprite.id.desc()),
    }
    items = db.scalars(
        base.order_by(*orderings[sort]).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [sprite_payload(sprite) for sprite in items],
        "pagination": pagination_payload(page, page_size, total_items),
    }


@app.get("/sprites/{sprite_id}/image", responses=COMMON_ERRORS)
def get_sprite_image(sprite_id: int, db: Annotated[Session, Depends(get_db)]) -> Response:
    sprite = db.get(Sprite, sprite_id)
    if sprite is None:
        raise ApiError(404, "SPRITE_NOT_FOUND", details={"sprite_id": sprite_id})
    if len(sprite.image_data) != 4096:
        raise ApiError(500, "INTERNAL_SERVER_ERROR")
    return Response(
        content=sprite.image_data,
        media_type="application/octet-stream",
        headers={"Content-Length": "4096"},
    )


@app.post(
    "/sprites",
    response_model=SpriteResponse,
    status_code=status.HTTP_201_CREATED,
    responses=COMMON_ERRORS,
)
async def create_sprite(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    name: str = Form(...),
    tags: str = Form(""),
):
    await reject_extra_form(request, {"file", "name", "tags"})
    user = current_user(request, db)
    details = []
    try:
        normalized_name = normalize_name(name)
    except ValueError as exc:
        details.append(validation_detail("name", str(exc)))
        normalized_name = ""
    try:
        normalized_tags = normalize_tags(tags)
    except ValueError as exc:
        details.append(validation_detail("tags", str(exc)))
        normalized_tags = ""
    if details:
        raise ApiError(422, "VALIDATION_ERROR", details=details)

    image_data = await process_upload(file)
    sprite = Sprite(
        name=normalized_name,
        tags=normalized_tags,
        image_data=image_data,
        owner_id=user.id,
    )
    db.add(sprite)
    db.commit()
    db.refresh(sprite)
    return sprite_payload(sprite)


@app.delete(
    "/sprites/{sprite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=COMMON_ERRORS,
)
def delete_sprite(
    sprite_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    user = current_user(request, db)
    sprite = db.get(Sprite, sprite_id)
    if sprite is None:
        raise ApiError(404, "SPRITE_NOT_FOUND", details={"sprite_id": sprite_id})
    if sprite.owner_id != user.id:
        raise ApiError(403, "SPRITE_FORBIDDEN", details={"sprite_id": sprite_id})

    affected_pack_ids = db.scalars(
        select(PackSprite.pack_id).where(PackSprite.sprite_id == sprite_id)
    ).all()
    try:
        db.delete(sprite)
        db.flush()
        for pack_id in affected_pack_ids:
            remaining_ids = db.scalars(
                select(PackSprite.sprite_id)
                .where(PackSprite.pack_id == pack_id)
                .order_by(PackSprite.position.asc())
            ).all()
            replace_pack_sprites(db, pack_id, remaining_ids)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return Response(status_code=204)


@app.get("/packs", response_model=PackListResponse, responses=COMMON_ERRORS)
def list_packs(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    name: str | None = None,
    mine: bool = False,
    sort: str = "newest",
):
    reject_extra_query(request, {"page", "page_size", "name", "mine", "sort"})
    if sort not in {"newest", "oldest", "name_asc", "name_desc"}:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            details=[validation_detail("sort", "INVALID_SORT")],
        )
    user = optional_user(request, db)
    if mine and user is None:
        raise ApiError(401, "AUTH_TOKEN_MISSING")

    conditions = []
    if mine:
        conditions.append(Pack.owner_id == user.id)
    name_term = normalize_search(name)
    if name_term:
        conditions.append(
            func.lower(Pack.name).like(
                f"%{escape_like(ascii_lower(name_term))}%", escape="\\"
            )
        )

    total_items = db.scalar(select(func.count(Pack.id)).where(*conditions)) or 0
    sprite_count = (
        select(func.count(PackSprite.sprite_id))
        .where(PackSprite.pack_id == Pack.id)
        .correlate(Pack)
        .scalar_subquery()
    )
    orderings = {
        "newest": (Pack.created_at.desc(), Pack.id.desc()),
        "oldest": (Pack.created_at.asc(), Pack.id.asc()),
        "name_asc": (Pack.name.collate("NOCASE").asc(), Pack.id.asc()),
        "name_desc": (Pack.name.collate("NOCASE").desc(), Pack.id.desc()),
    }
    rows = db.execute(
        select(Pack, sprite_count.label("sprite_count"))
        .where(*conditions)
        .order_by(*orderings[sort])
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            {
                "id": pack.id,
                "name": pack.name,
                "owner_id": pack.owner_id,
                "created_at": iso_z(pack.created_at),
                "sprite_count": count,
            }
            for pack, count in rows
        ],
        "pagination": pagination_payload(page, page_size, total_items),
    }


@app.post(
    "/packs",
    response_model=PackResponse,
    status_code=status.HTTP_201_CREATED,
    responses=COMMON_ERRORS,
)
def create_pack(
    payload: PackCreateRequest,
    request: Request,
    _content_type: Annotated[None, Depends(require_json_content_type)],
    db: Annotated[Session, Depends(get_db)],
):
    user = current_user(request, db)
    validate_sprite_ids(db, payload.sprite_ids)
    pack = Pack(name=payload.name, owner_id=user.id)
    try:
        db.add(pack)
        db.flush()
        db.add_all(
            [
                PackSprite(pack_id=pack.id, sprite_id=sprite_id, position=position)
                for position, sprite_id in enumerate(payload.sprite_ids)
            ]
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return pack_payload(load_pack(db, pack.id))


@app.get("/packs/{pack_id}", response_model=PackResponse, responses=COMMON_ERRORS)
def get_pack(pack_id: int, db: Annotated[Session, Depends(get_db)]):
    return pack_payload(load_pack(db, pack_id))


@app.patch("/packs/{pack_id}", response_model=PackResponse, responses=COMMON_ERRORS)
def update_pack(
    pack_id: int,
    payload: PackPatchRequest,
    request: Request,
    _content_type: Annotated[None, Depends(require_json_content_type)],
    db: Annotated[Session, Depends(get_db)],
):
    user = current_user(request, db)
    if not payload.model_fields_set:
        raise ApiError(
            400,
            "BAD_REQUEST",
            details=[validation_detail("request", "PATCH_FIELDS_REQUIRED")],
        )
    pack = db.get(Pack, pack_id)
    if pack is None:
        raise ApiError(404, "PACK_NOT_FOUND", details={"pack_id": pack_id})
    if pack.owner_id != user.id:
        raise ApiError(403, "PACK_FORBIDDEN", details={"pack_id": pack_id})
    if "sprite_ids" in payload.model_fields_set:
        validate_sprite_ids(db, payload.sprite_ids or [])

    try:
        if "name" in payload.model_fields_set:
            pack.name = payload.name or ""
        if "sprite_ids" in payload.model_fields_set:
            replace_pack_sprites(db, pack.id, payload.sprite_ids or [])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return pack_payload(load_pack(db, pack.id))


@app.delete(
    "/packs/{pack_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=COMMON_ERRORS,
)
def delete_pack(
    pack_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    user = current_user(request, db)
    pack = db.get(Pack, pack_id)
    if pack is None:
        raise ApiError(404, "PACK_NOT_FOUND", details={"pack_id": pack_id})
    if pack.owner_id != user.id:
        raise ApiError(403, "PACK_FORBIDDEN", details={"pack_id": pack_id})
    db.delete(pack)
    db.commit()
    return Response(status_code=204)


@app.get("/packs/{pack_id}/export", responses=COMMON_ERRORS)
def export_pack(pack_id: int, db: Annotated[Session, Depends(get_db)]):
    pack = load_pack(db, pack_id)
    links = sorted(pack.sprite_links, key=lambda link: link.position)
    return {
        "schema_version": 1,
        "pack_id": pack.id,
        "name": pack.name,
        "image_spec": {
            "width": 32,
            "height": 32,
            "pixel_format": "RGBA8888",
            "bytes_per_sprite": 4096,
        },
        "sprites": [
            {
                "position": link.position,
                "id": link.sprite.id,
                "name": link.sprite.name,
                "tags": link.sprite.tags,
                "image_data": base64.b64encode(link.sprite.image_data).decode("ascii"),
            }
            for link in links
        ],
    }


STATIC_DIR = PROJECT_ROOT / "app" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
