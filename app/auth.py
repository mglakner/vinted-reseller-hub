from itsdangerous import BadSignature, URLSafeSerializer
from starlette.requests import Request
from starlette.responses import RedirectResponse

from . import config

_serializer = URLSafeSerializer(config.SECRET_KEY, salt="vintedhub-session")
_resource_serializer = URLSafeSerializer(config.SECRET_KEY, salt="vintedhub-resource")

COOKIE_NAME = "vintedhub_session"


def make_resource_token(kind: str, value) -> str:
    """Signeret token der giver adgang til én bestemt ressource (pakke/foto)
    uden login — så userscriptet på vinted.dk kan hente den på tværs af domæner."""
    return _resource_serializer.dumps({"k": kind, "v": str(value)})


def verify_resource_token(token: str, kind: str, value) -> bool:
    if not token:
        return False
    try:
        data = _resource_serializer.loads(token)
    except BadSignature:
        return False
    return data.get("k") == kind and data.get("v") == str(value)


def make_session_cookie() -> str:
    return _serializer.dumps({"auth": True})


def is_authenticated(request: Request) -> bool:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return False
    try:
        data = _serializer.loads(raw)
        return bool(data.get("auth"))
    except BadSignature:
        return False


def login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)
