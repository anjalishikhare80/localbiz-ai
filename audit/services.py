from .models import AuditLog

_SENSITIVE = ("password", "token", "secret", "authorization", "api_key")


def _clean(value):
    if isinstance(value, dict):
        return {k: ("[redacted]" if any(s in str(k).lower() for s in _SENSITIVE) else _clean(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _ip(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def log(*, business, user, action, entity=None, metadata=None, request=None, entity_type="", entity_id=""):
    """Write an audit record. Never include secrets: metadata is scrubbed anyway."""
    if entity is not None:
        entity_type = entity_type or entity._meta.model_name
        entity_id = entity_id or str(entity.pk)
        entity_repr = str(entity)[:200]
    else:
        entity_repr = ""
    return AuditLog.objects.create(
        business=business,
        user=user if getattr(user, "pk", None) else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        entity_repr=entity_repr,
        metadata=_clean(metadata or {}),
        ip_address=_ip(request),
    )
