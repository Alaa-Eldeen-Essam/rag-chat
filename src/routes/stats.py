from fastapi import APIRouter, Depends, Request, status, Query
from fastapi.responses import JSONResponse
from routes.dependencies import get_current_user
from models import ResponseSignal
from models.db_schemes import ChatHistory, ChatConversation, Asset, User
from sqlalchemy.future import select
from sqlalchemy import func
from collections import Counter
from typing import Dict, Any, List, Tuple, Optional
import re

stats_router = APIRouter(
    prefix="/api/v1/stats",
    tags=["api_v1", "stats"],
)

STOPWORDS = {
    "the", "is", "are", "was", "were", "and", "or", "of", "a", "an", "to", "in", "for",
    "on", "with", "that", "this", "it", "as", "by", "be", "what", "how", "where",
    "when", "why", "who", "from", "about", "into", "over", "under", "between"
}


async def _compute_user_stats(session, user_id: int) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}

    total_queries = (
        await session.execute(
            select(func.count(ChatHistory.id)).where(ChatHistory.user_id == user_id)
        )
    ).scalar() or 0

    total_conversations = (
        await session.execute(
            select(func.count(ChatConversation.conversation_id)).where(
                ChatConversation.conversation_user_id == user_id
            )
        )
    ).scalar() or 0

    avg_response_time = (
        await session.execute(
            select(func.avg(ChatHistory.response_time_ms)).where(
                ChatHistory.user_id == user_id,
                ChatHistory.response_time_ms.isnot(None)
            )
        )
    ).scalar()

    total_documents_by_type_result = await session.execute(
        select(Asset.asset_document_type, func.count(Asset.asset_id))
        .where(Asset.asset_user_id == user_id)
        .group_by(Asset.asset_document_type)
    )
    doc_counts = {doc_type or "general": count for doc_type, count in total_documents_by_type_result}
    total_documents = sum(doc_counts.values())
    document_type_breakdown = {
        doc_type: {
            "count": count,
            "percentage": (count / total_documents * 100) if total_documents else 0
        }
        for doc_type, count in doc_counts.items()
    }

    # Fetch chat history records for deeper analytics
    history_records = (
        await session.execute(
            select(ChatHistory).where(ChatHistory.user_id == user_id)
        )
    ).scalars().all()

    response_times = [record.response_time_ms for record in history_records if record.response_time_ms]
    total_response_time_ms = sum(response_times)

    timestamps = [record.timestamp for record in history_records if record.timestamp]
    prompts = [record.prompt for record in history_records if record.prompt]

    # Conversation durations
    conversation_time_rows = await session.execute(
        select(
            ChatHistory.conversation_id,
            func.min(ChatHistory.timestamp),
            func.max(ChatHistory.timestamp),
            func.count(ChatHistory.id)
        )
        .where(ChatHistory.user_id == user_id)
        .group_by(ChatHistory.conversation_id)
    )
    session_durations: List[Tuple[int, float, int]] = []
    total_session_seconds = 0.0
    for conv_id, start_ts, end_ts, message_count in conversation_time_rows:
        if start_ts and end_ts:
            duration = (end_ts - start_ts).total_seconds()
            total_session_seconds += duration
            session_durations.append((conv_id, duration, message_count))

    average_session_duration = (
        total_session_seconds / len(session_durations) if session_durations else 0
    )

    # Peak usage periods (hour of day)
    hour_counter = Counter()
    daily_counter = Counter()
    weekly_counter = Counter()
    for ts in timestamps:
        hour_counter[ts.hour] += 1
        daily_counter[ts.date().isoformat()] += 1
        iso_year, iso_week, _ = ts.isocalendar()
        weekly_counter[f"{iso_year}-W{iso_week:02d}"] += 1

    peak_usage_hours = [
        {"hour": hour, "count": count}
        for hour, count in hour_counter.most_common(3)
    ]

    weekly_trend = [
        {"week": week, "count": count}
        for week, count in sorted(weekly_counter.items())
    ]

    # Document type query frequency
    doc_type_rows = await session.execute(
        select(ChatHistory.doc_types).where(
            ChatHistory.user_id == user_id,
            ChatHistory.doc_types.isnot(None)
        )
    )
    query_doc_counter = Counter()
    for row in doc_type_rows:
        doc_types = row[0]
        if isinstance(doc_types, list):
            query_doc_counter.update(dt.lower() for dt in doc_types)

    # Model usage
    model_usage_rows = await session.execute(
        select(ChatHistory.model_key, func.count(ChatHistory.id))
        .where(ChatHistory.user_id == user_id)
        .group_by(ChatHistory.model_key)
    )
    model_usage = {
        (model_key or "unknown"): count
        for model_key, count in model_usage_rows
    }

    model_usage_percentages = {
        key: (count / total_queries * 100) if total_queries else 0
        for key, count in model_usage.items()
    }

    # Most common query topics
    word_counter = Counter()
    for prompt in prompts:
        words = re.findall(r"\b\w+\b", prompt.lower())
        for word in words:
            if len(word) < 3 or word in STOPWORDS:
                continue
            word_counter[word] += 1
    most_common_topics = [
        {"topic": word, "count": count}
        for word, count in word_counter.most_common(10)
    ]

    stats.update({
        "totals": {
            "queries": total_queries,
            "conversations": total_conversations,
            "documents": total_documents,
        },
        "response_times": {
            "average_ms": float(avg_response_time) if avg_response_time else 0,
            "total_ms": total_response_time_ms,
        },
        "session_activity": {
            "total_seconds": total_session_seconds,
            "average_session_seconds": average_session_duration,
            "sessions": [
                {
                    "conversation_id": conv_id,
                    "duration_seconds": duration,
                    "message_count": message_count,
                }
                for conv_id, duration, message_count in session_durations
            ],
        },
        "document_insights": {
            "counts_by_type": document_type_breakdown,
            "query_frequency": dict(query_doc_counter),
        },
        "time_based": {
            "peak_usage_hours": peak_usage_hours,
            "daily_usage": dict(daily_counter),
            "weekly_trend": weekly_trend,
        },
        "model_preferences": {
            "counts": model_usage,
            "percentages": model_usage_percentages,
        },
        "query_topics": most_common_topics,
    })

    return stats


@stats_router.get("/user")
async def user_statistics(request: Request, current_user: User = Depends(get_current_user)):
    async with request.app.db_client() as session:
        stats = await _compute_user_stats(session, current_user.id)

    return JSONResponse(
        content={
            "signal": ResponseSignal.USER_STATS_SUCCESS.value,
            "statistics": stats
        }
    )


async def _compute_global_stats(session) -> Dict[str, Any]:
    total_users = (
        await session.execute(select(func.count(User.id)))
    ).scalar() or 0

    total_documents = (
        await session.execute(select(func.count(Asset.asset_id)))
    ).scalar() or 0

    document_distribution_rows = await session.execute(
        select(Asset.asset_document_type, func.count(Asset.asset_id))
        .group_by(Asset.asset_document_type)
    )
    document_distribution = {
        doc_type or "general": count
        for doc_type, count in document_distribution_rows
    }

    total_conversations = (
        await session.execute(select(func.count(ChatConversation.conversation_id)))
    ).scalar() or 0

    total_queries = (
        await session.execute(select(func.count(ChatHistory.id)))
    ).scalar() or 0

    average_response_time = (
        await session.execute(
            select(func.avg(ChatHistory.response_time_ms)).where(
                ChatHistory.response_time_ms.isnot(None)
            )
        )
    ).scalar()

    # Global model usage
    global_model_usage_rows = await session.execute(
        select(ChatHistory.model_key, func.count(ChatHistory.id))
        .group_by(ChatHistory.model_key)
    )
    global_model_usage = {
        (model_key or "unknown"): count
        for model_key, count in global_model_usage_rows
    }

    # Global query doc type usage
    global_doc_type_rows = await session.execute(
        select(ChatHistory.doc_types).where(ChatHistory.doc_types.isnot(None))
    )
    global_doc_type_counter = Counter()
    for row in global_doc_type_rows:
        doc_types = row[0]
        if isinstance(doc_types, list):
            global_doc_type_counter.update(dt.lower() for dt in doc_types)

    # Top users by query count
    top_users_rows = await session.execute(
        select(ChatHistory.user_id, func.count(ChatHistory.id))
        .group_by(ChatHistory.user_id)
        .order_by(func.count(ChatHistory.id).desc())
        .limit(10)
    )
    top_users = [
        {"user_id": user_id, "queries": count}
        for user_id, count in top_users_rows
    ]

    global_stats = {
        "totals": {
            "users": total_users,
            "documents": total_documents,
            "conversations": total_conversations,
            "queries": total_queries,
        },
        "document_distribution": document_distribution,
        "global_model_usage": global_model_usage,
        "query_doc_types": dict(global_doc_type_counter),
        "average_response_time_ms": float(average_response_time) if average_response_time else 0,
        "top_users": top_users,
    }

    return global_stats


@stats_router.get("/admin")
async def admin_statistics(
    request: Request,
    user_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
):
    if not getattr(current_user, "is_admin", False):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "Admin privileges required."
            }
        )

    async with request.app.db_client() as session:
        global_stats = await _compute_global_stats(session)
        user_stats = None

        if user_id is not None:
            user_exists = (
                await session.execute(
                    select(User).where(User.id == user_id)
                )
            ).scalar_one_or_none()
            if not user_exists:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={
                        "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                        "detail": f"User with id {user_id} not found."
                    }
                )
            user_stats = await _compute_user_stats(session, user_id)

    response_payload = {
        "signal": ResponseSignal.ADMIN_STATS_SUCCESS.value,
        "global": global_stats,
    }
    if user_stats:
        response_payload["user"] = {"user_id": user_id, "statistics": user_stats}

    return JSONResponse(content=response_payload)
