from fastapi import APIRouter, Depends, Request, status, Query
from fastapi.responses import JSONResponse
from routes.dependencies import get_current_user
from models import ResponseSignal
from models.db_schemes import ChatHistory, ChatConversation, Asset, User
from sqlalchemy.future import select
from sqlalchemy import func, or_
from collections import Counter
from typing import Dict, Any, List, Tuple, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
import re
import asyncio

stats_router = APIRouter(
    prefix="/api/v1/stats",
    tags=["api_v1", "stats"],
)


class FeedbackRequest(BaseModel):
    message_id: int
    rating: Optional[int] = None  # 1-5
    is_helpful: Optional[bool] = None

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

    # Quality / feedback statistics
    ratings = [
        record.rating for record in history_records if getattr(record, "rating", None) is not None
    ]
    avg_rating = (sum(ratings) / len(ratings)) if ratings else 0.0
    helpful_count = sum(
        1 for record in history_records if getattr(record, "is_helpful", None) is True
    )
    unhelpful_count = sum(
        1 for record in history_records if getattr(record, "is_helpful", None) is False
    )
    rated_count = helpful_count + unhelpful_count
    fallback_count = sum(
        1 for record in history_records if getattr(record, "fallback_used", None) is True
    )

    # Retrieval statistics
    retrieved_counts = [
        record.retrieved_chunks
        for record in history_records
        if getattr(record, "retrieved_chunks", None) is not None
    ]
    avg_retrieved_chunks = (
        sum(retrieved_counts) / len(retrieved_counts) if retrieved_counts else 0.0
    )
    bucket_0 = 0
    bucket_1_5 = 0
    bucket_6_10 = 0
    bucket_gt_10 = 0
    for value in retrieved_counts:
        v = int(value or 0)
        if v == 0:
            bucket_0 += 1
        elif 1 <= v <= 5:
            bucket_1_5 += 1
        elif 6 <= v <= 10:
            bucket_6_10 += 1
        else:
            bucket_gt_10 += 1

    retrieved_doc_type_counter = Counter()
    for record in history_records:
        doc_types_meta = getattr(record, "retrieved_doc_types", None)
        if isinstance(doc_types_meta, list):
            retrieved_doc_type_counter.update(
                (dt or "").strip().lower()
                for dt in doc_types_meta
                if isinstance(dt, str) and dt.strip()
            )

    # Engagement statistics: conversation length buckets
    conv_length_buckets = {"1-3": 0, "4-10": 0, ">10": 0}
    for _, _, message_count in session_durations:
        if message_count <= 3:
            conv_length_buckets["1-3"] += 1
        elif 4 <= message_count <= 10:
            conv_length_buckets["4-10"] += 1
        else:
            conv_length_buckets[">10"] += 1

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
        "quality": {
            "average_rating": avg_rating,
            "rated_count": rated_count,
            "helpful_count": helpful_count,
            "unhelpful_count": unhelpful_count,
            "fallback_count": fallback_count,
        },
        "retrieval": {
            "average_retrieved_chunks": avg_retrieved_chunks,
            "chunk_histogram": {
                "0": bucket_0,
                "1-5": bucket_1_5,
                "6-10": bucket_6_10,
                ">10": bucket_gt_10,
            },
            "doc_type_hits": dict(retrieved_doc_type_counter),
        },
        "engagement": {
            "conversation_length_buckets": conv_length_buckets,
        },
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


@stats_router.post("/feedback")
async def submit_feedback(
    request: Request,
    feedback: FeedbackRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Attach simple feedback (rating / helpfulness) to a chat history message
    owned by the current user.
    """
    # Basic validation for rating range
    if feedback.rating is not None and not (1 <= feedback.rating <= 5):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.USER_STATS_SUCCESS.value,
                "detail": "Rating must be between 1 and 5.",
            },
        )

    async with request.app.db_client() as session:
        result = await session.execute(
            select(ChatHistory).where(
                ChatHistory.id == feedback.message_id,
                ChatHistory.user_id == current_user.id,
            )
        )
        record = result.scalar_one_or_none()

        if record is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                    "detail": f"Message with id {feedback.message_id} not found for current user.",
                },
            )

        async with session.begin():
            if feedback.rating is not None:
                record.rating = feedback.rating
            if feedback.is_helpful is not None:
                record.is_helpful = feedback.is_helpful
            session.add(record)

        await session.commit()

    return JSONResponse(
        content={
            "signal": ResponseSignal.USER_STATS_SUCCESS.value,
            "detail": "Feedback recorded.",
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

    # Latency percentiles (P50/P90/P95/P99)
    response_rows = await session.execute(
        select(ChatHistory.response_time_ms).where(ChatHistory.response_time_ms.isnot(None))
    )
    response_values = [
        int(val) for (val,) in response_rows.all() if val is not None
    ]

    def _percentile(values: List[int], percentile: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * percentile / 100.0
        f = int(k)
        c = min(f + 1, len(sorted_vals) - 1)
        if f == c:
            return float(sorted_vals[int(k)])
        d0 = sorted_vals[f] * (c - k)
        d1 = sorted_vals[c] * (k - f)
        return float(d0 + d1)

    latency_percentiles = {
        "p50": _percentile(response_values, 50),
        "p90": _percentile(response_values, 90),
        "p95": _percentile(response_values, 95),
        "p99": _percentile(response_values, 99),
    }

    # Requests per hour (last 24 hours)
    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)
    hourly_rows = await session.execute(
        select(
            func.date_trunc("hour", ChatHistory.timestamp),
            ChatHistory.model_key,
            func.count(ChatHistory.id),
        )
        .where(ChatHistory.timestamp >= day_ago)
        .group_by(func.date_trunc("hour", ChatHistory.timestamp), ChatHistory.model_key)
        .order_by(func.date_trunc("hour", ChatHistory.timestamp))
    )
    requests_per_hour: List[Dict[str, Any]] = []
    for ts, model_key, count in hourly_rows.all():
        requests_per_hour.append(
            {
                "hour": ts.isoformat() if ts else None,
                "model": model_key or "unknown",
                "count": count,
            }
        )

    # DAU / WAU and new users (last 7 days)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = today_start - timedelta(days=7)
    dau = (
        await session.execute(
            select(func.count(func.distinct(ChatHistory.user_id))).where(
                ChatHistory.timestamp >= today_start
            )
        )
    ).scalar() or 0
    wau = (
        await session.execute(
            select(func.count(func.distinct(ChatHistory.user_id))).where(
                ChatHistory.timestamp >= seven_days_ago
            )
        )
    ).scalar() or 0

    new_users_rows = await session.execute(
        select(User.created_at).where(User.created_at >= seven_days_ago)
    )
    new_users_last_7_days = len(new_users_rows.all())

    # Queries by department
    dept_rows = await session.execute(
        select(User.department, func.count(ChatHistory.id))
        .join(ChatHistory, ChatHistory.user_id == User.id)
        .group_by(User.department)
    )
    queries_by_department = {
        (dept or "Unknown"): count for dept, count in dept_rows.all()
    }

    # Usage by visibility (document counts)
    visibility_usage: Dict[str, int] = {}
    if hasattr(Asset, "asset_visibility"):
        vis_rows = await session.execute(
            select(Asset.asset_visibility, func.count(Asset.asset_id)).group_by(
                Asset.asset_visibility
            )
        )
        for vis, count in vis_rows.all():
            key = (vis or "private").lower()
            visibility_usage[key] = count

    # Global retrieval statistics (if any metadata has been recorded)
    retr_rows = await session.execute(
        select(
            ChatHistory.retrieved_chunks,
            ChatHistory.retrieved_doc_types,
            ChatHistory.fallback_used,
            ChatHistory.rating,
        )
    )
    retrieved_counts: List[int] = []
    retrieved_doc_type_counter = Counter()
    global_ratings: List[int] = []
    fallback_total = 0
    for r_chunks, r_doc_types, r_fallback, r_rating in retr_rows.all():
        if r_chunks is not None:
            retrieved_counts.append(int(r_chunks))
        if isinstance(r_doc_types, list):
            retrieved_doc_type_counter.update(
                (dt or "").strip().lower()
                for dt in r_doc_types
                if isinstance(dt, str) and dt.strip()
            )
        if r_rating is not None:
            global_ratings.append(int(r_rating))
        if r_fallback:
            fallback_total += 1

    avg_retrieved_chunks = (
        sum(retrieved_counts) / len(retrieved_counts) if retrieved_counts else 0.0
    )
    bucket_0 = 0
    bucket_1_5 = 0
    bucket_6_10 = 0
    bucket_gt_10 = 0
    for value in retrieved_counts:
        v = int(value or 0)
        if v == 0:
            bucket_0 += 1
        elif 1 <= v <= 5:
            bucket_1_5 += 1
        elif 6 <= v <= 10:
            bucket_6_10 += 1
        else:
            bucket_gt_10 += 1

    avg_global_rating = (
        sum(global_ratings) / len(global_ratings) if global_ratings else 0.0
    )

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
        "latency_percentiles": latency_percentiles,
        "requests_per_hour": requests_per_hour,
        "engagement": {
            "dau": dau,
            "wau": wau,
            "new_users_last_7_days": new_users_last_7_days,
        },
        "quality": {
            "average_rating": avg_global_rating,
            "fallback_count": fallback_total,
        },
        "retrieval": {
            "average_retrieved_chunks": avg_retrieved_chunks,
            "chunk_histogram": {
                "0": bucket_0,
                "1-5": bucket_1_5,
                "6-10": bucket_6_10,
                ">10": bucket_gt_10,
            },
            "doc_type_hits": dict(retrieved_doc_type_counter),
        },
        "department_stats": {
            "queries_by_department": queries_by_department,
            "usage_by_visibility": visibility_usage,
        },
    }

# ------------------------------------------------------------------------------------
# Admin Endpoint (Paginated – legacy, retained for compatibility)
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


# ------------------------------------------------------------------------------------
# New Admin Endpoints: system-wide + per-user overviews
# ------------------------------------------------------------------------------------
@stats_router.get("/system")
async def system_statistics(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    System-wide statistics for admins:
    aggregates across all users, conversations, and documents.
    """
    if not getattr(current_user, "is_admin", False):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "Admin privileges required.",
            },
        )

    async with request.app.db_client() as session:
        global_stats = await _compute_global_stats(session)

    return JSONResponse(
        content={
            "signal": ResponseSignal.ADMIN_STATS_SUCCESS.value,
            "statistics": global_stats,
        }
    )


@stats_router.get("/users")
async def users_overview_statistics(
    request: Request,
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number for paginated user stats"),
    limit: int = Query(20, ge=1, le=100, description="Number of users per page (max 100)"),
    search: Optional[str] = Query(
        None,
        description="Optional search filter for username or department (case-insensitive)",
    ),
):
    """
    Paginated overview of all users for admins, with lightweight stats per user
    (totals, average latency, last activity, model usage).
    """
    if not getattr(current_user, "is_admin", False):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "Admin privileges required.",
            },
        )

    async with request.app.db_client() as session:
        base_query = select(User.id, User.username, User.department, User.is_admin)

        if search:
            pattern = f"%{search.lower()}%"
            base_query = base_query.where(
                or_(
                    func.lower(User.username).like(pattern),
                    func.lower(User.department).like(pattern),
                )
            )
            total_users_query = select(func.count(User.id)).where(
                or_(
                    func.lower(User.username).like(pattern),
                    func.lower(User.department).like(pattern),
                )
            )
        else:
            total_users_query = select(func.count(User.id))

        total_users = (await session.execute(total_users_query)).scalar() or 0
        offset = (page - 1) * limit

        rows = (await session.execute(base_query.offset(offset).limit(limit))).all()
        if not rows:
            return JSONResponse(
                content={
                    "signal": ResponseSignal.ADMIN_STATS_SUCCESS.value,
                    "users": [],
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total_users": total_users,
                        "total_pages": (total_users + limit - 1) // limit,
                    },
                }
            )

        user_ids = [row[0] for row in rows]

        # Compute per-user stats (queries, conversations, docs, avg latency, model usage)
        stats_tasks = [
            _compute_user_stats(session, user_id=uid) for uid in user_ids
        ]
        stats_results = await asyncio.gather(*stats_tasks)

        # Compute last activity in a single grouped query
        last_activity_rows = await session.execute(
            select(ChatHistory.user_id, func.max(ChatHistory.timestamp))
            .where(ChatHistory.user_id.in_(user_ids))
            .group_by(ChatHistory.user_id)
        )
        last_activity_map = {
            user_id: last_ts for user_id, last_ts in last_activity_rows.all()
        }

        users_payload = []
        for (uid, username, department, is_admin), stats in zip(rows, stats_results):
            totals = stats.get("totals", {}) if isinstance(stats, dict) else {}
            response_times = (
                stats.get("response_times", {}) if isinstance(stats, dict) else {}
            )
            model_prefs = (
                stats.get("model_preferences", {}) if isinstance(stats, dict) else {}
            )

            model_counts = model_prefs.get("counts", {}) or {}
            avg_ms = response_times.get("average_ms") or 0
            last_ts = last_activity_map.get(uid)

            users_payload.append(
                {
                    "user_id": uid,
                    "username": username,
                    "department": department,
                    "is_admin": bool(is_admin),
                    "total_queries": totals.get("queries") or 0,
                    "total_conversations": totals.get("conversations") or 0,
                    "total_documents": totals.get("documents") or 0,
                    "avg_response_ms": float(avg_ms) if avg_ms is not None else 0.0,
                    "last_active_at": last_ts.isoformat() if last_ts else None,
                    "model_usage": model_counts,
                }
            )

        return JSONResponse(
            content={
                "signal": ResponseSignal.ADMIN_STATS_SUCCESS.value,
                "users": users_payload,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total_users": total_users,
                    "total_pages": (total_users + limit - 1) // limit,
                },
            }
        )


@stats_router.get("/users/{user_id}")
async def user_statistics_admin(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_user),
):
    """
    Detailed statistics for a specific user, for admins.
    Returns the same structure as /stats/user, plus basic user info.
    """
    if not getattr(current_user, "is_admin", False):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "Admin privileges required.",
            },
        )

    async with request.app.db_client() as session:
        user_record = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()

        if user_record is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                    "detail": f"User with id {user_id} not found.",
                },
            )

        stats = await _compute_user_stats(session, user_id)
        activity = await _compute_user_activity(session, user_id)

    return JSONResponse(
        content={
            "signal": ResponseSignal.ADMIN_STATS_SUCCESS.value,
            "user": {
                "user_id": user_record.id,
                "username": user_record.username,
                "department": user_record.department,
                "is_admin": user_record.is_admin,
                "statistics": stats,
                "activity": activity,
            },
        }
    )
