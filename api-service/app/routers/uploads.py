"""Media uploads: images and short videos for forum posts, comments and
messages (guideline E: media on posts, comments and DMs; and the system must
survive "huge video files sent to overload the database").

Defences, in order of when they bite:

* **Per-user write budget** - uploads count as content creation.
* **Real type detection** - the file's magic bytes decide the type, not the
  client's claimed Content-Type or extension. Only a small allowlist of
  image and video formats is accepted.
* **Hard size caps by type** - MAX_IMAGE_BYTES (5 MiB) and MAX_VIDEO_BYTES
  (25 MiB). The gateway-wide 1 MiB body limit exempts this route; instead
  the upload is streamed to disk chunk by chunk and aborted the moment the
  cap is crossed, so a "huge video" never sits in memory or reaches the
  database (only a few bytes of metadata do).
* **Unguessable ids** - files are served at ``/uploads/<random id>`` with
  the detected content type and immutable caching. They are public by URL
  (browsers cannot send an Authorization header for an <img>), which is why
  the id is random rather than sequential.
"""
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.rate_limit import rate_limit_writes
from app.schemas.upload import UploadOut

logger = logging.getLogger(__name__)

router = APIRouter(tags=["uploads"])

_CHUNK = 1 << 20  # 1 MiB
_IMAGE = "image"
_VIDEO = "video"


def sniff(head: bytes) -> tuple[str, str] | None:
    """Return (kind, content_type) from the leading bytes, or None."""
    if head.startswith(b"\xff\xd8\xff"):
        return _IMAGE, "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return _IMAGE, "image/png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return _IMAGE, "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return _IMAGE, "image/webp"
    if head[4:8] == b"ftyp":
        return _VIDEO, "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return _VIDEO, "video/webm"
    return None


def _cap(kind: str) -> int:
    return settings.max_image_bytes if kind == _IMAGE else settings.max_video_bytes


def uploads_dir() -> Path:
    path = Path(settings.uploads_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def url_for(upload_id: str) -> str:
    return f"/uploads/{upload_id}"


async def upload_exists(url: str) -> bool:
    """True if ``url`` points at a stored upload (used to validate references)."""
    prefix = "/uploads/"
    if not url.startswith(prefix):
        return False
    upload_id = url[len(prefix):]
    if not upload_id.isalnum():
        return False
    return await get_db().uploads.find_one({"_id": upload_id}) is not None


@router.post("/api/uploads", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile,
    user: dict = Depends(get_current_user),
    _: None = Depends(rate_limit_writes),
):
    head = await file.read(16)
    detected = sniff(head)
    if detected is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only JPEG, PNG, GIF, WebP images and MP4/WebM videos are accepted.",
        )
    kind, content_type = detected
    cap = _cap(kind)

    upload_id = secrets.token_hex(16)
    dest = uploads_dir() / upload_id
    size = 0
    try:
        with open(dest, "wb") as out:
            out.write(head)
            size = len(head)
            while chunk := await file.read(_CHUNK):
                size += len(chunk)
                if size > cap:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"{kind.capitalize()}s are limited to {cap // (1 << 20)} MiB.",
                    )
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception:  # noqa: BLE001 - never leave a partial file behind
        dest.unlink(missing_ok=True)
        logger.exception("Upload %s failed", upload_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Upload failed."
        ) from None
    finally:
        await file.close()

    doc = {
        "_id": upload_id,
        "ownerId": user["_id"],
        "kind": kind,
        "contentType": content_type,
        "size": size,
        "filename": (file.filename or upload_id)[:200],
        "createdAt": datetime.now(UTC),
    }
    await get_db().uploads.insert_one(doc)
    return UploadOut(
        id=upload_id, url=url_for(upload_id), kind=kind, content_type=content_type,
        size=size, filename=doc["filename"],
    )


@router.get("/uploads/{upload_id}", include_in_schema=False)
async def serve(upload_id: str):
    if not upload_id.isalnum():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    meta = await get_db().uploads.find_one({"_id": upload_id})
    path = uploads_dir() / upload_id
    if meta is None or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return FileResponse(
        path,
        media_type=meta["contentType"],
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Disposition": "inline",
            # Never let a browser sniff an upload into something executable.
            "X-Content-Type-Options": "nosniff",
        },
    )
