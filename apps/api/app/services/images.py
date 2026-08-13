import warnings
from io import BytesIO

from fastapi import HTTPException, status
from PIL import Image, UnidentifiedImageError


def decode_image(raw: bytes, *, max_bytes: int, max_pixels: int) -> Image.Image:
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty upload")
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Upload too large"
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(BytesIO(raw))
            width, height = probe.size
            if width * height > max_pixels:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Decoded image exceeds pixel limit",
                )
            probe.verify()
        image = Image.open(BytesIO(raw)).convert("RGB")
        image.load()
        return image
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported or invalid image",
        ) from exc
