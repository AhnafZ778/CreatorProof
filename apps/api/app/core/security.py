import secrets

from fastapi import HTTPException, Request, status


def require_tenant(request: Request, x_api_key: str) -> str:
    settings = request.app.state.container.settings
    if not secrets.compare_digest(x_api_key, settings.dev_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return settings.dev_tenant_id
