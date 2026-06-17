from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_db
from app.deps import require_roles
from app.models.enums import Role
from app.schemas.user import RoleUpdate, UserOut
from app.services.serializers import serialize_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
async def list_users(_: dict = Depends(require_roles(Role.ADMIN))):
    cursor = get_db().users.find().sort("createdAt", 1)
    return [serialize_user(u) async for u in cursor]


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def update_role(
    user_id: str,
    payload: RoleUpdate,
    _: dict = Depends(require_roles(Role.ADMIN)),
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    result = await get_db().users.find_one_and_update(
        {"_id": ObjectId(user_id)},
        {"$set": {"role": payload.role.value}},
        return_document=True,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return serialize_user(result)
