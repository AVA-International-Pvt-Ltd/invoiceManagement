from __future__ import annotations

from .config import is_allowed_org_email
from .supabase_store import SupabaseStoreError, get_client


class OrgAuthError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


def verify_org_user(access_token: str) -> dict[str, str]:
    try:
        response = get_client().auth.get_user(access_token)
    except SupabaseStoreError as exc:
        raise OrgAuthError(str(exc), status_code=503) from exc
    except Exception as exc:
        raise OrgAuthError("Sign in with your @avaipl.com Google account.") from exc

    user = getattr(response, "user", None)
    if user is None:
        raise OrgAuthError("Sign in with your @avaipl.com Google account.")

    email = getattr(user, "email", None) or ""
    if not is_allowed_org_email(email):
        raise OrgAuthError(
            "Only @avaipl.com Google accounts can use this app.",
            status_code=403,
        )

    user_id = getattr(user, "id", None) or ""
    if not user_id:
        raise OrgAuthError("Sign in with your @avaipl.com Google account.")
    return {"id": str(user_id), "email": email.strip().lower()}
