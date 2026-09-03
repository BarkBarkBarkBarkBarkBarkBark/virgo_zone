from __future__ import annotations

import json
import os
import shutil
import subprocess
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Any
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.settings import Settings


ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/quicktime",
}
EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}
PILLOW_MIME_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}
MAX_IMAGE_PIXELS = 50_000_000
CHUNK_SIZE = 1024 * 1024


class MediaValidationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class StoredMedia:
    id: str
    media_type: str
    byte_size: int
    original_path: str
    thumbnail_path: str | None
    vision_path: str | None
    width: int | None
    height: int | None
    duration_seconds: float | None

    def database_values(self) -> dict[str, Any]:
        return asdict(self)


class MediaService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def store(self, source: BinaryIO, declared_mime: str | None) -> StoredMedia:
        if declared_mime not in ALLOWED_MIME_TYPES:
            raise MediaValidationError("Unsupported media type", 415)
        expected_limit = (
            self.settings.video_max_bytes
            if declared_mime.startswith("video/")
            else self.settings.image_max_bytes
        )
        self._ensure_space(expected_limit)
        media_id = str(uuid4())
        incoming_dir = self.settings.uploads_dir / ".incoming"
        incoming_dir.mkdir(parents=True, exist_ok=True)
        temporary = incoming_dir / f"{media_id}.part"
        created: list[Path] = [temporary]
        try:
            byte_size = self._stream(source, temporary, expected_limit)
            detected_mime = self._detect(temporary)
            if detected_mime != declared_mime:
                raise MediaValidationError("File contents do not match the declared media type", 415)
            actual_limit = (
                self.settings.video_max_bytes
                if detected_mime.startswith("video/")
                else self.settings.image_max_bytes
            )
            if byte_size > actual_limit:
                raise MediaValidationError("Upload exceeds the configured size limit", 413)

            now = datetime.now(timezone.utc)
            relative_dir = Path(f"{now.year:04d}") / f"{now.month:02d}"
            original_relative = relative_dir / f"{media_id}{EXTENSIONS[detected_mime]}"
            original = self.settings.uploads_dir / original_relative
            original.parent.mkdir(parents=True, exist_ok=True)
            thumbnail_relative: Path | None = None
            vision_relative: Path | None = None
            width: int | None = None
            height: int | None = None
            duration: float | None = None

            if detected_mime.startswith("image/"):
                thumbnail_relative = relative_dir / f"{media_id}-feed.webp"
                vision_relative = relative_dir / f"{media_id}-vision.jpg"
                thumbnail = self.settings.thumbnails_dir / thumbnail_relative
                vision = self.settings.thumbnails_dir / vision_relative
                thumbnail.parent.mkdir(parents=True, exist_ok=True)
                width, height = self._image_derivatives(temporary, thumbnail, vision)
                created.extend((thumbnail, vision))
            else:
                width, height, duration = self._probe_video(temporary)
                if shutil.which("ffmpeg") is not None:
                    poster_relative = relative_dir / f"{media_id}-poster.jpg"
                    poster = self.settings.thumbnails_dir / poster_relative
                    poster.parent.mkdir(parents=True, exist_ok=True)
                    if self._make_video_poster(temporary, poster):
                        thumbnail_relative = poster_relative
                        vision_relative = poster_relative
                        created.append(poster)

            os.replace(temporary, original)
            created[0] = original
            return StoredMedia(
                id=media_id,
                media_type=detected_mime,
                byte_size=byte_size,
                original_path=original_relative.as_posix(),
                thumbnail_path=thumbnail_relative.as_posix() if thumbnail_relative else None,
                vision_path=vision_relative.as_posix() if vision_relative else None,
                width=width,
                height=height,
                duration_seconds=duration,
            )
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise

    def cleanup(self, stored: StoredMedia) -> None:
        paths = [
            self.settings.uploads_dir / stored.original_path,
            self.settings.thumbnails_dir / stored.thumbnail_path if stored.thumbnail_path else None,
            self.settings.thumbnails_dir / stored.vision_path if stored.vision_path else None,
        ]
        for path in {path for path in paths if path is not None}:
            path.unlink(missing_ok=True)

    def _ensure_space(self, incoming_allowance: int) -> None:
        free = shutil.disk_usage(self.settings.data_dir).free
        if free - incoming_allowance < self.settings.min_free_bytes:
            raise MediaValidationError("Storage is too full for this upload", 507)

    @staticmethod
    def _stream(source: BinaryIO, destination: Path, limit: int) -> int:
        total = 0
        with destination.open("xb") as output:
            while chunk := source.read(CHUNK_SIZE):
                total += len(chunk)
                if total > limit:
                    raise MediaValidationError("Upload exceeds the configured size limit", 413)
                output.write(chunk)
        if total == 0:
            raise MediaValidationError("Upload is empty")
        return total

    @staticmethod
    def _detect(path: Path) -> str:
        with path.open("rb") as media_file:
            header = media_file.read(32)
        if header.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if header.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            return "image/webp"
        if len(header) >= 12 and header[4:8] == b"ftyp":
            major_brand = header[8:12]
            if major_brand in {b"qt  ", b"mqt "}:
                return "video/quicktime"
            return "video/mp4"
        raise MediaValidationError("The file signature is not an allowed media format", 415)

    @staticmethod
    def _image_derivatives(source: Path, thumbnail: Path, vision: Path) -> tuple[int, int]:
        previous_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source) as image:
                    image.load()
                    image = ImageOps.exif_transpose(image)
                    width, height = image.size
                    if width * height > MAX_IMAGE_PIXELS:
                        raise MediaValidationError("Image dimensions are too large", 413)
                    frame = image.convert("RGBA")
                    background = Image.new("RGB", frame.size, (8, 8, 10))
                    background.paste(frame, mask=frame.getchannel("A"))
                    feed = background.copy()
                    feed.thumbnail((960, 960), Image.Resampling.LANCZOS)
                    feed.save(thumbnail, format="WEBP", quality=78, method=4)
                    background.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                    background.save(vision, format="JPEG", quality=85, optimize=True)
                    return width, height
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise MediaValidationError("Image data is malformed or unsafe", 415) from exc
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit

    @staticmethod
    def _probe_video(source: Path) -> tuple[int | None, int | None, float | None]:
        if shutil.which("ffprobe") is None:
            return None, None, None
        command = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            str(source),
        ]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
            data = json.loads(result.stdout)
            stream = data.get("streams", [{}])[0]
            duration = data.get("format", {}).get("duration")
            return stream.get("width"), stream.get("height"), float(duration) if duration else None
        except (subprocess.SubprocessError, ValueError, KeyError, IndexError) as exc:
            raise MediaValidationError("Video container could not be decoded", 415) from exc

    @staticmethod
    def _make_video_poster(source: Path, destination: Path) -> bool:
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.1",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=1024:-2:force_original_aspect_ratio=decrease",
            "-y",
            str(destination),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=30)
        except subprocess.SubprocessError:
            destination.unlink(missing_ok=True)
            return False
        return destination.exists() and destination.stat().st_size > 0


def media_to_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "author_id": row["author_id"],
        "author_name": row["author_name"],
        "caption": row["caption"],
        "media_type": row["media_type"],
        "byte_size": row["byte_size"],
        "width": row["width"],
        "height": row["height"],
        "duration_seconds": row["duration_seconds"],
        "created_at": row["created_at"],
        "comment_count": row["comment_count"],
        "original_url": f"/media/uploads/{row['original_path']}",
        "thumbnail_url": (
            f"/media/thumbnails/{row['thumbnail_path']}" if row["thumbnail_path"] else None
        ),
    }
