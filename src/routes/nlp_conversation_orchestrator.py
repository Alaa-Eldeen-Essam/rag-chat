from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from typing import Optional

from models import ResponseSignal
from models.ChatConversationModel import ChatConversationModel
from models.ChatHistoryModel import ChatHistoryModel
from models.db_schemes import Asset, User
from routes.schemes.nlp import ConversationUpdateRequest


async def handle_list_conversations(
    request: Request,
    current_user: User,
):
    conversation_model = await ChatConversationModel.create_instance(db_client=request.app.db_client)
    conversations = await conversation_model.list_conversations(user_id=current_user.id)

    payload = [
        {
            "conversation_id": conversation.conversation_id,
            "title": conversation.conversation_title,
            "is_pinned": conversation.conversation_is_pinned,
            "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
            "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
        }
        for conversation in conversations
    ]

    return JSONResponse(
        content={
            "signal": ResponseSignal.CONVERSATIONS_FETCH_SUCCESS.value,
            "detail_code": "conversation_list_success",
            "conversations": payload,
            "total": len(payload),
        }
    )


async def handle_list_user_doc_types(
    request: Request,
    current_user: User,
):
    async with request.app.db_client() as session:
        conditions = [Asset.asset_document_type.isnot(None)]
        if not getattr(current_user, "is_admin", False):
            conditions.append(
                or_(
                    Asset.asset_is_private.is_(False),
                    Asset.asset_user_id == current_user.id,
                )
            )

        result = await session.execute(
            select(Asset.asset_document_type).where(*conditions).distinct()
        )
        doc_types = sorted(
            {
                (value or "").strip()
                for (value,) in result.all()
                if value and value.strip()
            },
            key=lambda item: item.lower(),
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.VECTORDB_SEARCH_SUCCESS.value,
            "detail_code": "doc_type_list_success",
            "doc_types": doc_types,
            "total": len(doc_types),
        }
    )


async def handle_get_conversation_history(
    request: Request,
    conversation_id: int,
    limit: Optional[int],
    current_user: User,
):
    conversation_model = await ChatConversationModel.create_instance(db_client=request.app.db_client)
    chat_history_model = await ChatHistoryModel.create_instance(db_client=request.app.db_client)

    conversation = await conversation_model.get_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )

    if not conversation:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.PROJECT_NOT_FOUND_ERROR.value,
                "detail_code": "conversation_not_found",
                "detail": "Conversation not found.",
            },
        )

    if limit:
        history = await chat_history_model.get_recent_history_by_conversation(
            conversation_id=conversation_id,
            limit=limit,
        )
    else:
        history = await chat_history_model.get_full_history_by_conversation(
            conversation_id=conversation_id
        )

    history_payload = [
        {
            "id": record.id,
            "prompt": record.prompt,
            "answer": record.answer,
            "model_key": record.model_key,
            "doc_types": record.doc_types,
            "timestamp": record.timestamp.isoformat() if record.timestamp else None,
            "response_time_ms": record.response_time_ms,
            "resources": getattr(record, "resources", None) or [],
        }
        for record in history
    ]

    return JSONResponse(
        content={
            "signal": ResponseSignal.CONVERSATION_HISTORY_SUCCESS.value,
            "detail_code": "conversation_history_success",
            "conversation": {
                "conversation_id": conversation.conversation_id,
                "title": conversation.conversation_title,
                "is_pinned": conversation.conversation_is_pinned,
                "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
                "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
            },
            "history": history_payload,
        }
    )


async def handle_rename_conversation(
    request: Request,
    conversation_id: int,
    update: ConversationUpdateRequest,
    current_user: User,
):
    conversation_model = await ChatConversationModel.create_instance(db_client=request.app.db_client)
    conversation = await conversation_model.get_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.PROJECT_NOT_FOUND_ERROR.value,
                "detail_code": "conversation_not_found",
                "detail": "Conversation not found.",
            },
        )

    new_title = None
    if update.title is not None:
        trimmed = update.title.strip()
        new_title = trimmed or "New Conversation"

    await conversation_model.update_conversation_fields(
        conversation_id=conversation_id,
        user_id=current_user.id,
        title=new_title,
        is_pinned=update.is_pinned,
    )

    return JSONResponse(
        content={
            "signal": ResponseSignal.CONVERSATION_HISTORY_SUCCESS.value,
            "detail_code": "conversation_update_success",
            "conversation_id": conversation_id,
            "title": new_title if new_title is not None else conversation.conversation_title,
            "is_pinned": (
                update.is_pinned
                if update.is_pinned is not None
                else conversation.conversation_is_pinned
            ),
        }
    )


async def handle_delete_conversation(
    request: Request,
    conversation_id: int,
    current_user: User,
):
    conversation_model = await ChatConversationModel.create_instance(db_client=request.app.db_client)
    deleted = await conversation_model.delete_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not deleted:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.PROJECT_NOT_FOUND_ERROR.value,
                "detail_code": "conversation_not_found",
                "detail": "Conversation not found.",
            },
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.FILE_DELETE_SUCCESS.value,
            "detail_code": "conversation_delete_success",
            "conversation_id": conversation_id,
        }
    )
