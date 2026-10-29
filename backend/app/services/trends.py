"""Explainable, versioned trend rule with historical replay and retained human decisions."""

from collections import Counter, defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assessment, TrendAlert
from app.models.entities import utcnow
from app.schemas.location import utc_event_time
from app.services.analytics import month_key, record_time

RULE_VERSION = "trend-rule-v1"
BASELINE_MONTHS = 6
MIN_LATEST = 5
RATIO_THRESHOLD = 2.0
MIN_WINDOW_RECORDS = 10


def shift_month(value: date, offset: int) -> date:
    index = value.year * 12 + value.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def latest_complete_month(now: datetime | None = None) -> date:
    current = now or datetime.now(UTC)
    return shift_month(date(current.year, current.month, 1), -1)


def category_counts(db: Session) -> dict[str, Counter]:
    rows = db.scalars(select(Assessment).where(Assessment.confirmed.is_(True))).all()
    counts: dict[str, Counter] = defaultdict(Counter)
    for item in rows:
        if not item.hazard_category or item.data_source == "simulated":
            continue
        counts[item.hazard_category][month_key(record_time(item))] += 1
    return counts


def evaluate(counts: Counter, target: date) -> dict:
    baseline_months = [shift_month(target, -offset) for offset in range(BASELINE_MONTHS, 0, -1)]
    baseline_total = sum(counts.get(month_key(month), 0) for month in baseline_months)
    baseline = baseline_total / BASELINE_MONTHS
    observed = counts.get(month_key(target), 0)
    sample_size = baseline_total + observed
    sufficient = sample_size >= MIN_WINDOW_RECORDS and baseline_total > 0
    triggered = bool(
        sufficient and observed >= MIN_LATEST and observed >= baseline * RATIO_THRESHOLD
    )
    reason = ""
    if sample_size < MIN_WINDOW_RECORDS:
        reason = f"近 {BASELINE_MONTHS + 1} 个月已确认记录仅 {sample_size} 条，少于 {MIN_WINDOW_RECORDS} 条"
    elif baseline_total == 0:
        reason = "基线月份没有已确认记录，无法计算趋势"
    return {
        "observed": observed, "baseline": baseline, "sample_size": sample_size,
        "sufficient": sufficient, "triggered": triggered, "reason": reason,
    }


def backtest(counts: Counter, target: date) -> dict:
    months = [month for month in counts if month]
    if not months:
        return {"months_evaluated": 0, "triggered": 0, "followed": 0, "sample_size": 0}
    earliest = min(date(int(month[:4]), int(month[5:]), 1) for month in months)
    replay_sample = sum(
        count for month, count in counts.items()
        if earliest <= date(int(month[:4]), int(month[5:]), 1) <= target
    )
    current = shift_month(earliest, BASELINE_MONTHS)
    evaluated = triggered = followed = 0
    while current <= target:
        result = evaluate(counts, current)
        if result["sufficient"]:
            evaluated += 1
            if result["triggered"]:
                triggered += 1
                following = shift_month(current, 1)
                if following <= target:
                    next_count = counts.get(month_key(following), 0)
                    if next_count >= MIN_LATEST and next_count >= result["baseline"] * RATIO_THRESHOLD:
                        followed += 1
        current = shift_month(current, 1)
    return {
        "months_evaluated": evaluated, "triggered": triggered, "followed": followed,
        "sample_size": replay_sample,
    }


def explanation(category: str, target: date, result: dict) -> str:
    return (
        f"{month_key(target)}「{category}」已确认 {result['observed']} 条，"
        f"前 {BASELINE_MONTHS} 个月月均 {result['baseline']:.1f} 条，"
        f"达到 {RATIO_THRESHOLD:g} 倍阈值且不少于 {MIN_LATEST} 条；评估窗口样本 {result['sample_size']} 条。"
    )


def refresh_alerts(db: Session, *, as_of: date | None = None) -> int:
    target = as_of or latest_complete_month()
    created = 0
    for category, counts in category_counts(db).items():
        result = evaluate(counts, target)
        if not result["triggered"]:
            continue
        exists = db.scalar(select(TrendAlert.id).where(
            TrendAlert.rule_version == RULE_VERSION, TrendAlert.scope_type == "category",
            TrendAlert.scope_value == category, TrendAlert.month == month_key(target),
        ))
        if exists:
            continue
        db.add(TrendAlert(
            rule_version=RULE_VERSION, scope_type="category", scope_value=category,
            month=month_key(target), observed=result["observed"], baseline=result["baseline"],
            ratio_threshold=RATIO_THRESHOLD, sample_size=result["sample_size"],
            explanation=explanation(category, target, result),
        ))
        created += 1
    db.commit()
    return created


def alert_out(item: TrendAlert) -> dict:
    return {
        "id": item.id, "rule_version": item.rule_version, "scope_type": item.scope_type,
        "scope_value": item.scope_value, "month": item.month, "observed": item.observed,
        "baseline": item.baseline, "ratio_threshold": item.ratio_threshold,
        "sample_size": item.sample_size, "explanation": item.explanation,
        "status": item.status, "note": item.note, "reviewed_by_name": item.reviewed_by_name,
        "reviewed_at": utc_event_time(item.reviewed_at), "created_at": utc_event_time(item.created_at),
    }


def trend_report(db: Session, *, as_of: date | None = None) -> dict:
    target = as_of or latest_complete_month()
    counts = category_counts(db)
    evaluations = []
    evaluated_months = triggered = followed = backtest_sample = 0
    sufficient_categories = 0
    for category in sorted(counts):
        result = evaluate(counts[category], target)
        if result["sufficient"]:
            sufficient_categories += 1
        replay = backtest(counts[category], target)
        evaluated_months += replay["months_evaluated"]
        triggered += replay["triggered"]
        followed += replay["followed"]
        backtest_sample += replay["sample_size"]
        evaluations.append({
            "category": category, "observed": result["observed"], "baseline": result["baseline"],
            "sample_size": result["sample_size"], "sufficient": result["sufficient"],
            "triggered": result["triggered"], "reason": result["reason"],
        })

    alerts = db.scalars(select(TrendAlert).where(TrendAlert.rule_version == RULE_VERSION)
                        .order_by(TrendAlert.month.desc(), TrendAlert.status, TrendAlert.scope_value)).all()
    if not counts:
        reason = "暂无已确认记录，不能生成趋势提示"
    elif sufficient_categories == 0:
        reason = (f"历史资料不足：每个类别近 {BASELINE_MONTHS + 1} 个月需至少 "
                  f"{MIN_WINDOW_RECORDS} 条已确认记录且基线月份有记录")
    else:
        reason = ""
    return {
        "as_of": month_key(target),
        "rule": {
            "version": RULE_VERSION, "baseline_months": BASELINE_MONTHS,
            "min_latest": MIN_LATEST, "ratio_threshold": RATIO_THRESHOLD,
            "min_window_records": MIN_WINDOW_RECORDS,
        },
        "backtest": {
            "months_evaluated": evaluated_months, "triggered": triggered,
            "followed": followed, "sample_size": backtest_sample,
            "note": "历史触发回放，不是预测准确率；followed 表示次月仍高于同一基线。",
        },
        "sufficiency": {
            "supported": sufficient_categories > 0,
            "reason": reason,
            "categories_sufficient": sufficient_categories,
            "categories_evaluated": len(evaluations),
        },
        "evaluations": evaluations,
        "alerts": [alert_out(item) for item in alerts],
        "false_positive_count": sum(1 for item in alerts if item.status == "false_positive"),
    }


def review_alert(db: Session, item: TrendAlert, status: str, note: str,
                 actor: str | None, actor_id: str | None) -> TrendAlert:
    item.status = status
    item.note = note or None
    item.reviewed_by_name = actor
    item.reviewed_by_id = actor_id
    item.reviewed_at = utcnow()
    db.commit()
    db.refresh(item)
    return item
