import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.config import settings

security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    valid_user = secrets.compare_digest(credentials.username.encode(), settings.admin_username.encode())
    valid_password = secrets.compare_digest(credentials.password.encode(), settings.admin_password.encode())
    if not (valid_user and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверные учётные данные",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
