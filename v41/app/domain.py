"""Nordviks validering och åtkomstregler, oberoende av Azure SDK."""
import base64
import binascii
import io
import re
from PIL import Image, UnidentifiedImageError

ROLES = {"Tenant", "PropertyManager", "Finance"}
CATEGORIES = {"varme", "vatten", "las", "ovrigt"}
STATUSES = {"Ny", "Pågår", "Avslutad"}
MAX_IMAGE = 5 * 1024 * 1024

class AccessDenied(Exception):
    pass


def identity(principal, tenant_id):
    if not isinstance(principal, dict):
        raise AccessDenied("Logga in.")
    claims = principal.get("claims", [])
    def values(*types):
        return [c.get("val", "") for c in claims if c.get("typ") in types]
    oid = values("oid", "http://schemas.microsoft.com/identity/claims/objectidentifier")
    tid = values("tid", "http://schemas.microsoft.com/identity/claims/tenantid")
    roles = set(values("roles", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role")) & ROLES
    if len(oid) != 1 or len(tid) != 1 or tid[0] != tenant_id or not roles:
        raise AccessDenied("Kontot saknar portalbehörighet.")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", oid[0]):
        raise AccessDenied("Kontot saknar giltig identitet.")
    return {"oid": oid[0], "roles": roles}


def assignment(user, mapping):
    entry = mapping.get(user["oid"], {})
    properties = entry.get("properties", [])
    if not isinstance(properties, list) or not all(isinstance(x, str) for x in properties):
        raise AccessDenied("Kontots fastigheter är inte konfigurerade.")
    return set(properties)


def can_read(user, record, mapping):
    roles = user["roles"]
    if "Finance" in roles:
        return True
    if "PropertyManager" in roles and record["propertyId"] in assignment(user, mapping):
        return True
    return "Tenant" in roles and record["ownerId"] == user["oid"]


def can_manage(user, record, mapping):
    return "PropertyManager" in user["roles"] and record["propertyId"] in assignment(user, mapping)


def validate_ticket(value, user, mapping):
    if "Tenant" not in user["roles"]:
        raise AccessDenied("Bara hyresgäster skapar felanmälningar.")
    if not isinstance(value, dict):
        raise ValueError("Skicka ett JSON objekt.")
    result = {}
    for key, limit in [("title", 150), ("description", 4000), ("propertyId", 40), ("category", 20)]:
        text = value.get(key)
        if not isinstance(text, str) or not text.strip() or len(text) > limit:
            raise ValueError("Fyll i rubrik, beskrivning, fastighet och kategori.")
        result[key] = text.strip()
    if result["propertyId"] not in assignment(user, mapping):
        raise AccessDenied("Du kan bara anmäla fel i din egen fastighet.")
    if result["category"] not in CATEGORIES:
        raise ValueError("Välj en giltig kategori.")
    result["urgent"] = result["category"] in {"varme", "vatten", "las"}
    return result


def image_bytes(value):
    if not isinstance(value, str) or len(value) > ((MAX_IMAGE + 2)//3)*4:
        raise ValueError("Bilden får vara högst 5 MB.")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Bilden måste vara giltig base64.") from None
    if not raw or len(raw) > MAX_IMAGE:
        raise ValueError("Bilden får vara högst 5 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in {"JPEG", "PNG"} or im.width*im.height > 20_000_000:
                raise ValueError("Använd PNG eller JPEG med högst 20 miljoner pixlar.")
            im.verify()
        # Ny kodning tar bort filmetadata, exempelvis bildens GPS position.
        with Image.open(io.BytesIO(raw)) as im:
            out = io.BytesIO()
            im.convert("RGB").save(out, format="JPEG", quality=90)
        cleaned = out.getvalue()
        if len(cleaned) > MAX_IMAGE:
            raise ValueError("Den bearbetade bilden är för stor.")
        return cleaned
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("Bilden kunde inte läsas.") from None
