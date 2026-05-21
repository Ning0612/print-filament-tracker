ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def is_valid_image(header: bytes) -> bool:
    """Validate image magic bytes (first 12 bytes)."""
    if header[:8] == b'\x89PNG\r\n\x1a\n':
        return True
    if header[:3] == b'\xff\xd8\xff':
        return True
    if header[:4] in (b'GIF8',) and header[4:5] in (b'7', b'9'):
        return True
    if header[:4] == b'RIFF' and len(header) >= 12 and header[8:12] == b'WEBP':
        return True
    return False
