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
import asyncio

stats_router = APIRouter(
    prefix="/api/v1/stats",
    tags=["api_v1", "stats"],
)

# ✅ Extended STOPWORDS: English + Arabic + Egyptian dialects
STOPWORDS = {
    # English
    "the", "is", "are", "was", "were", "and", "or", "of", "a", "an", "to", "in", "for",
    "on", "with", "that", "this", "it", "as", "by", "be", "what", "how", "where",
    "when", "why", "who", "from", "about", "into", "over", "under", "between",
    "at", "but", "not", "so", "if", "then", "than", "too", "very", "can", "could",
    "would", "should", "do", "does", "did", "have", "has", "had",
    # Arabic (Modern Standard + Egyptian)
    "من", "في", "على", "إلى", "عن", "هذا", "هذه", "ذلك", "تلك", "هناك", "هو", "هي",
    "هم", "هن", "أنا", "انت", "إنت", "إنتي", "احنا", "إحنا", "انتم", "إنتو", "انتما",
    "كل", "أي", "أين", "متى", "لماذا", "كيف", "ما", "ماذا", "الذي", "التي", "الذين",
    "اللاتي", "اللواتي", "ال", "يا", "ده", "دي", "دول", "كده", "كذا", "كذاك", "أهو",
    "أهي", "أهم", "ايه", "إيه", "ليه", "مش", "مافيش", "مفيش", "مش", "او", "ولا", "بس",
    "كمان", "برضه", "يعني", "طيب", "تمام", "دلوقتي", "لسه", "اوي", "قوي", "كده", "ده",
    "دي", "دول", "كده", "كده", "عشان", "علشان", "علي", "فيه", "فيها", "منها", "فيهم",
    "منهم", "بتاع", "بتاعة", "بتوع", "بتاعي", "بتاعك", "بتاعته", "بتاعتها",
}

# ------------------------------------------------------------------------------------
# Helper 1: User Activity Summary
# ------------------------------------------------------------------------------------
async def _compute_user_activity(session, user_id: int) -> Dict[str, Any]:
    """Compute user activity: uploads, processed files, conversations, summaries generated, and per-project activity."""

    # Total uploads (from Asset table)
    uploads = (
        await session.execute(
            select(func.count(Asset.asset_id)).where(Asset.asset_user_id == user_id)
        )
    ).scalar() or 0

    # Processed files (if asset_processed column exists)
    processed_files = (
        await session.execute(
            select(func.count(Asset.asset_id))
            .where(Asset.asset_user_id == user_id, Asset.asset_processed == True)
        )
    ).scalar() if hasattr(Asset, "asset_processed") else uploads

    # Conversations initiated
    conversations = (
        await session.execute(
            select(func.count(ChatConversation.conversation_id))
            .where(ChatConversation.conversation_user_id == user_id)
        )
    ).scalar() or 0

    # Summaries generated (if is_summary field exists)
    summaries_generated = (
        await session.execute(
            select(func.count(ChatHistory.id))
            .where(ChatHistory.user_id == user_id, ChatHistory.is_summary == True)
        )
    ).scalar() if hasattr(ChatHistory, "is_summary") else 0

    # ✅ Per-project activity summary
    per_project_data = {}

    # Assets per project
    if hasattr(Asset, "project_id"):
        project_assets = await session.execute(
            select(Asset.project_id, func.count(Asset.asset_id))
            .where(Asset.asset_user_id == user_id)
            .group_by(Asset.project_id)
        )
        for project_id, count in project_assets:
            project_key = str(project_id or "unassigned")
            per_project_data.setdefault(project_key, {"uploads": 0, "processed_files": 0, "conversations": 0})
            per_project_data[project_key]["uploads"] = count

        # Processed assets per project (if available)
        if hasattr(Asset, "asset_processed"):
            processed_per_project = await session.execute(
                select(Asset.project_id, func.count(Asset.asset_id))
                .where(Asset.asset_user_id == user_id, Asset.asset_processed == True)
                .group_by(Asset.project_id)
            )
            for project_id, count in processed_per_project:
                project_key = str(project_id or "unassigned")
                per_project_data.setdefault(project_key, {"uploads": 0, "processed_files": 0, "conversations": 0})
                per_project_data[project_key]["processed_files"] = count

    # Conversations per project
    if hasattr(ChatConversation, "project_id"):
        project_convos = await session.execute(
            select(ChatConversation.project_id, func.count(ChatConversation.conversation_id))
            .where(ChatConversation.conversation_user_id == user_id)
            .group_by(ChatConversation.project_id)
        )
        for project_id, count in project_convos:
            project_key = str(project_id or "unassigned")
            per_project_data.setdefault(project_key, {"uploads": 0, "processed_files": 0, "conversations": 0})
            per_project_data[project_key]["conversations"] = count

    # ✅ Compile the final activity object
    activity = {
        "uploads": uploads,
        "processed_files": processed_files,
        "conversations": conversations,
        "summaries_generated": summaries_generated,
    }

    if per_project_data:
        activity["projects"] = per_project_data

    return activity


# ------------------------------------------------------------------------------------
# Helper 2: User Statistics
# ------------------------------------------------------------------------------------
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

    # Peak usage periods (hour of day, daily, weekly)
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

    # Most common query topics (multilingual stopword filtering)
    word_counter = Counter()
    for prompt in prompts:
        words = re.findall(r"\b\w+\b", prompt.lower())
        for word in words:
            if len(word) < 2 or word in STOPWORDS:
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

# ------------------------------------------------------------------------------------
# User Endpoint
# ------------------------------------------------------------------------------------
@stats_router.get("/user")
async def user_statistics(request: Request, current_user: User = Depends(get_current_user)):
    async with request.app.db_client() as session:
        stats = await _compute_user_stats(session, current_user.id)
        activity = await _compute_user_activity(session, current_user.id)

    return JSONResponse(
        content={
            "signal": ResponseSignal.USER_STATS_SUCCESS.value,
            "statistics": stats,
            "activity": activity
        }
    )

# ------------------------------------------------------------------------------------
# Global Statistics
# ------------------------------------------------------------------------------------
async def _compute_global_stats(session) -> Dict[str, Any]:
    total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
    total_documents = (await session.execute(select(func.count(Asset.asset_id)))).scalar() or 0
    total_conversations = (await session.execute(select(func.count(ChatConversation.conversation_id)))).scalar() or 0
    total_queries = (await session.execute(select(func.count(ChatHistory.id)))).scalar() or 0

    average_response_time = (
        await session.execute(
            select(func.avg(ChatHistory.response_time_ms)).where(ChatHistory.response_time_ms.isnot(None))
        )
    ).scalar()

    document_distribution_rows = await session.execute(
        select(Asset.asset_document_type, func.count(Asset.asset_id)).group_by(Asset.asset_document_type)
    )
    document_distribution = {doc_type or "general": count for doc_type, count in document_distribution_rows}

    global_model_usage_rows = await session.execute(
        select(ChatHistory.model_key, func.count(ChatHistory.id)).group_by(ChatHistory.model_key)
    )
    global_model_usage = {(model_key or "unknown"): count for model_key, count in global_model_usage_rows}

    global_doc_type_rows = await session.execute(
        select(ChatHistory.doc_types).where(ChatHistory.doc_types.isnot(None))
    )
    global_doc_type_counter = Counter()
    for row in global_doc_type_rows:
        doc_types = row[0]
        if isinstance(doc_types, list):
            global_doc_type_counter.update(dt.lower() for dt in doc_types)

    top_users_rows = await session.execute(
        select(ChatHistory.user_id, func.count(ChatHistory.id))
        .group_by(ChatHistory.user_id)
        .order_by(func.count(ChatHistory.id).desc())
        .limit(10)
    )
    top_users = [{"user_id": user_id, "queries": count} for user_id, count in top_users_rows]

    return {
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

# ------------------------------------------------------------------------------------
# Admin Endpoint (Paginated)
# ------------------------------------------------------------------------------------
@stats_router.get("/admin")
async def admin_statistics(
    request: Request,
    user_id: Optional[int] = Query(None, description="Fetch stats for a specific user"),
    page: int = Query(1, ge=1, description="Page number for paginated user stats"),
    limit: int = Query(20, ge=1, le=100, description="Number of users per page (max 100)"),
    current_user: User = Depends(get_current_user),
):
    """Admin statistics endpoint:
    - If `user_id` is provided → stats for that specific user.
    - Otherwise → global stats + paginated per-user statistics.
    """
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
        paginated_user_stats = []

        # ✅ Case 1: Fetch stats for a specific user
        if user_id is not None:
            user_exists = (
                await session.execute(select(User).where(User.id == user_id))
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
            user_activity = await _compute_user_activity(session, user_id)

        # ✅ Case 2: Paginated per-user activity
        else:
            total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
            offset = (page - 1) * limit

            all_users = (
                await session.execute(
                    select(User.id).offset(offset).limit(limit)
                )
            ).scalars().all()

            # Parallelized for speed
            tasks = [
                asyncio.gather(_compute_user_stats(session, uid), _compute_user_activity(session, uid))
                for uid in all_users
            ]
            results = await asyncio.gather(*tasks)

            for uid, (stats, activity) in zip(all_users, results):
                paginated_user_stats.append({
                    "user_id": uid,
                    "statistics": stats,
                    "activity": activity
                })

    # ✅ Build final response
    response_payload = {
        "signal": ResponseSignal.ADMIN_STATS_SUCCESS.value,
        "global": global_stats,
    }

    if user_stats:
        response_payload["user"] = {
            "user_id": user_id,
            "statistics": user_stats,
            "activity": user_activity,
        }
    else:
        response_payload["users"] = paginated_user_stats
        response_payload["pagination"] = {
            "page": page,
            "limit": limit,
            "total_users": total_users,
            "total_pages": (total_users + limit - 1) // limit,
        }

    return JSONResponse(content=response_payload)
