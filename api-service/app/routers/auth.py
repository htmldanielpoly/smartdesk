from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.database import get_db
from app.models.enums import Role
from app.rate_limit import rate_limit
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, _: None = Depends(rate_limit)):
    doc = {
        "email": payload.email.lower(),
        "passwordHash": hash_password(payload.password),
        "displayName": payload.display_name,
        "role": Role.USER.value,
        "department": None,
        "createdAt": datetime.now(UTC),
    }
    try:
        result = await get_db().users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None

    token = create_access_token(str(result.inserted_id), Role.USER.value)
    return TokenResponse(access_token=token, role=Role.USER)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, _: None = Depends(rate_limit)):
    user = await get_db().users.find_one({"email": payload.email.lower()})
    if user is None or not verify_password(payload.password, user["passwordHash"]):
        # Same error for both cases to avoid leaking which emails exist.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(str(user["_id"]), user["role"])
    return TokenResponse(access_token=token, role=Role(user["role"]))


@router.get("/directory")
async def get_user_directory():
    # Ensure your database dependency (e.g., get_db) is imported
    cursor = get_db().users.find().sort("display_name", 1)
    return [
        {
            "id": str(u["_id"]),
            # FIX: Fallback to email prefix if display_name is missing
            "display_name": u.get("display_name") or u.get("email", "Unknown").split("@")[0],
            "role": u.get("role", "USER")
        }
        async for u in cursor
    ]