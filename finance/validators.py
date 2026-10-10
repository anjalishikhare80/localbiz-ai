from django.core.exceptions import ValidationError

MAX_BYTES = 2 * 1024 * 1024
# extension -> allowed leading bytes ("magic numbers"); we check content, not just the name
SIGNATURES = {
    "pdf": [b"%PDF"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
}


def validate_receipt(upload):
    """Allow only small PDF/PNG/JPG files whose real content matches their extension."""
    name = (upload.name or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in SIGNATURES:
        raise ValidationError("Only PDF, PNG or JPG receipts are allowed.")
    if upload.size > MAX_BYTES:
        raise ValidationError("Receipt must be 2 MB or smaller.")
    head = upload.read(16)
    upload.seek(0)
    if not any(head.startswith(sig) for sig in SIGNATURES[ext]):
        raise ValidationError("File content does not match its extension.")
