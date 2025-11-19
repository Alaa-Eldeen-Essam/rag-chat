from fastapi import APIRouter, Request, status, Depends, Query
from fastapi.responses import JSONResponse
from routes.schemes.users import (
    UserRegisterRequest,
    AdminCreateRequest,
    DepartmentUpdateRequest,
    UserAdminUpdateRequest,
    UserBasicUpdateRequest,
)
from controllers import UserController
from models.UserModel import UserModel
from models import ResponseSignal
from models.db_schemes import User
from routes.dependencies import get_current_user
from sqlalchemy import select, delete, update, func

users_router = APIRouter(
    prefix="/api/v1/users",
    tags=["api_v1", "users"],
)


@users_router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    return JSONResponse(
        content={
            "id": current_user.id,
            "username": current_user.username,
            "is_admin": current_user.is_admin,
            "department": current_user.department,
        }
    )

@users_router.post("/register")
async def register_user(request: Request, register_request: UserRegisterRequest):
    user_model = await UserModel.create_instance(
        db_client=request.app.db_client
    )
    user_controller = UserController()

    user, signal = await user_controller.register_user(
        user_model=user_model,
        username=register_request.username,
        password=register_request.password,
    )

    if not user:
        if signal == ResponseSignal.USER_ALREADY_EXISTS.value:
            status_code_response = status.HTTP_409_CONFLICT
        else:
            status_code_response = status.HTTP_400_BAD_REQUEST
        return JSONResponse(
            status_code=status_code_response,
            content={
                "signal": signal
            }
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "signal": signal,
            "user": {
                "id": user.id,
                "username": user.username,
                "is_admin": user.is_admin,
            },
        },
    )


@users_router.post("/create")
async def admin_create_user(
    request: Request,
    create_request: AdminCreateRequest,
    current_user: User = Depends(get_current_user),
):
    if not getattr(current_user, "is_admin", False):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "Only admins can create users.",
            },
        )

    user_model = await UserModel.create_instance(
        db_client=request.app.db_client
    )

    from helpers.security import hash_password

    existing_user = await user_model.get_user_by_username(
        username=create_request.username
    )
    if existing_user:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"signal": ResponseSignal.USER_ALREADY_EXISTS.value},
        )

    is_admin = (create_request.role or "user") == "admin"
    department = create_request.department
    if is_admin:
        department = department or "Admins"
    else:
        department = department or "Global"

    password_hash = hash_password(password=create_request.password)
    user = await user_model.create_user(
        username=create_request.username,
        password_hash=password_hash,
        is_admin=is_admin,
        department=department,
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "signal": ResponseSignal.USER_CREATED_SUCCESS.value,
            "user": {
                "id": user.id,
                "username": user.username,
                "is_admin": user.is_admin,
                "department": user.department,
            },
        },
    )

@users_router.get("/")
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
):
    if not getattr(current_user, "is_admin", False):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value},
        )

    async with request.app.db_client() as session:
        offset = (page - 1) * limit
        result = await session.execute(
            select(User)
            .order_by(User.id)
            .offset(offset)
            .limit(limit)
        )
        users = result.scalars().all()

        count_result = await session.execute(
            select(func.count(User.id))
        )
        total_users = count_result.scalar_one() or 0

    payload = [
        {
            "id": u.id,
            "username": u.username,
            "is_admin": u.is_admin,
            "department": u.department,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in users
    ]

    return JSONResponse(
        content={
            "signal": ResponseSignal.FILE_LIST_SUCCESS.value,
            "users": payload,
            "total": total_users,
            "page": page,
            "limit": limit,
        }
    )


@users_router.get("/departments")
async def list_departments(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    List distinct departments in the system.
    - Admins: see all departments.
    - Normal users: see only their own department.
    """
    async with request.app.db_client() as session:
        if getattr(current_user, "is_admin", False):
            result = await session.execute(
                select(func.distinct(User.department))
            )
        else:
            result = await session.execute(
                select(func.distinct(User.department)).where(
                    User.department == current_user.department
                )
            )
        rows = result.all()

    departments = sorted(
        { (dept or "").strip() for (dept,) in rows if dept and dept.strip() }
    )

    return JSONResponse(
        content={
            "signal": ResponseSignal.FILE_LIST_SUCCESS.value,
            "departments": departments,
            "total": len(departments),
        }
    )


@users_router.post("/admin")
async def create_admin_user(
    request: Request,
    admin_request: AdminCreateRequest,
    current_user: User = Depends(get_current_user),
):
    user_model = await UserModel.create_instance(
        db_client=request.app.db_client
    )
    user_controller = UserController()

    user, signal = await user_controller.create_admin_user(
        user_model=user_model,
        requesting_user=current_user,
        username=admin_request.username,
        password=admin_request.password,
        department=admin_request.department or "Global",
    )

    if not user:
        status_code_response = status.HTTP_403_FORBIDDEN if signal == ResponseSignal.ACCESS_FORBIDDEN_ERROR.value else status.HTTP_400_BAD_REQUEST
        if signal == ResponseSignal.USER_ALREADY_EXISTS.value:
            status_code_response = status.HTTP_409_CONFLICT
        return JSONResponse(
            status_code=status_code_response,
            content={
                "signal": signal
            }
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "signal": signal,
            "user": {
                "id": user.id,
                "username": user.username,
                "is_admin": user.is_admin,
                "department": user.department,
            }
        }
    )

@users_router.patch("/users/{user_id}/department")
async def update_user_department(
    request: Request,
    user_id: int,
    update_request: DepartmentUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    if not getattr(current_user, "is_admin", False):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "Only admins can modify departments.",
            },
        )

    user_model = await UserModel.create_instance(
        db_client=request.app.db_client
    )

    async with request.app.db_client() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user_record = result.scalar_one_or_none()

    if user_record is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                "detail": f"User with id {user_id} not found.",
            },
        )

    await user_model.update_department(user_id=user_id, department=update_request.department)

    return JSONResponse(
        content={
            "signal": ResponseSignal.USER_CREATED_SUCCESS.value,
            "user": {
                "id": user_id,
                "username": user_record.username,
                "is_admin": user_record.is_admin,
                "department": update_request.department,
            },
        }
    )


@users_router.patch("/users/{user_id}/admin")
async def update_user_admin(
    request: Request,
    user_id: int,
    update_request: UserAdminUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    if not getattr(current_user, "is_admin", False):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "Only admins can modify admin status.",
            },
        )

    async with request.app.db_client() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user_record = result.scalar_one_or_none()
            if user_record is None:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={
                        "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                        "detail": f"User with id {user_id} not found.",
                    },
                )
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(is_admin=update_request.is_admin)
            )

    return JSONResponse(
        content={
            "signal": ResponseSignal.USER_CREATED_SUCCESS.value,
            "user": {
                "id": user_id,
                "username": user_record.username,
                "is_admin": update_request.is_admin,
                "department": user_record.department,
            },
        }
    )


@users_router.patch("/users/{user_id}")
async def update_user_basic(
    request: Request,
    user_id: int,
    update_request: UserBasicUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    if not getattr(current_user, "is_admin", False):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "Only admins can update users.",
            },
        )

    user_model = await UserModel.create_instance(
        db_client=request.app.db_client
    )

    async with request.app.db_client() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user_record = result.scalar_one_or_none()

    if user_record is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                "detail": f"User with id {user_id} not found.",
            },
        )

    if update_request.username:
        await user_model.update_username(user_id=user_id, username=update_request.username)

    if update_request.reset_password:
        from helpers.security import hash_password

        default_password_hash = hash_password(password="123456")
        await user_model.reset_password(user_id=user_id, password_hash=default_password_hash)

    async with request.app.db_client() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        updated_user = result.scalar_one()

    return JSONResponse(
        content={
            "signal": ResponseSignal.USER_CREATED_SUCCESS.value,
            "user": {
                "id": updated_user.id,
                "username": updated_user.username,
                "is_admin": updated_user.is_admin,
                "department": updated_user.department,
            },
        }
    )


@users_router.delete("/users/{user_id}")
async def delete_user(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_user),
):
    if not getattr(current_user, "is_admin", False):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "Only admins can delete users.",
            },
        )

    async with request.app.db_client() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user_record = result.scalar_one_or_none()
            if user_record is None:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={
                        "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                        "detail": f"User with id {user_id} not found.",
                    },
                )
            await session.execute(
                delete(User).where(User.id == user_id)
            )
        await session.commit()

    return JSONResponse(
        content={
            "signal": ResponseSignal.FILE_DELETE_SUCCESS.value,
            "user_id": user_id,
        }
    )
