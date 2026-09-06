from __future__ import annotations

from datetime import datetime, timedelta, timezone

import app.shadow_notifications as notifications
from app.database import Base
from app.shadow_history import ShadowDriftOverviewResult, ShadowDriftResult
from app.shadow_notifications import (
    ShadowDriftNotificationEvent,
    ShadowDriftState,
    ShadowNotificationSettings,
    process_shadow_drift_transitions,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def _settings(*, enabled: bool = True, configured: bool = True, cooldown_hours: float = 24.0):
    return ShadowNotificationSettings(
        enabled=enabled,
        recipient="alerts@example.com" if configured else "",
        cooldown_hours=cooldown_hours,
        history_days=30,
        max_attempts=5,
        smtp_enabled=configured,
        smtp_host="smtp.example.com" if configured else "",
        smtp_port=587,
        smtp_username="user" if configured else "",
        smtp_password="secret" if configured else "",
        smtp_from="moex@example.com" if configured else "",
        smtp_starttls=True,
        smtp_ssl=False,
        public_base_url="https://moex.example.com",
    )


def _drift(ticker: str, status: str, *, target_year: int = 2027) -> ShadowDriftResult:
    reasons = []
    if status == "watch":
        reasons = ["weight_concentration"]
    elif status == "alert":
        reasons = ["large_baseline_divergence"]
    elif status == "insufficient":
        reasons = ["history_too_short"]
    return ShadowDriftResult(
        ticker=ticker,
        target_year=target_year,
        latest_training_snapshot="pre_year",
        status=status,  # type: ignore[arg-type]
        reasons=reasons,
        snapshots=4,
        history_days=30,
        history_span_hours=48.0,
        first_captured_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        last_captured_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
        latest_delta_percent={"stable": 2.0, "watch": 12.0, "alert": 25.0, "insufficient": 2.0}[status],
        previous_delta_percent=2.0,
        delta_step_percentage_points=1.0,
        median_abs_delta_percent=2.0,
        max_abs_delta_percent=25.0,
        latest_weight_concentration_ratio=1.1,
        max_weight_concentration_ratio=1.6,
        median_target_change_percent=1.0,
        weighted_target_change_percent=2.0,
        relative_movement_gap_percentage_points=1.0,
        training_snapshot_changed=False,
    )


def _overview(item: ShadowDriftResult) -> ShadowDriftOverviewResult:
    counts = {"alert": 0, "watch": 0, "stable": 0, "insufficient": 0}
    counts[item.status] += 1
    return ShadowDriftOverviewResult(
        generated_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
        history_days=30,
        universe_tickers=1,
        tickers_with_history=1,
        classified_tickers=0 if item.status == "insufficient" else 1,
        alert_tickers=counts["alert"],
        watch_tickers=counts["watch"],
        stable_tickers=counts["stable"],
        insufficient_tickers=counts["insufficient"],
        actionable_tickers=counts["alert"] + counts["watch"],
        history_coverage_percent=100.0,
        classified_coverage_percent=0.0 if item.status == "insufficient" else 100.0,
        items=[item],
    )


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_bootstrap_records_state_without_email(monkeypatch) -> None:
    engine = _engine()
    sent: list[list[int]] = []
    monkeypatch.setattr(notifications, "build_shadow_drift_overview", lambda db, days: _overview(_drift("SBER", "watch")))
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.append([event.id for event in events]),
    )

    with Session(engine) as db:
        result = process_shadow_drift_transitions(
            db,
            observed_at=datetime(2026, 9, 6, 10, tzinfo=timezone.utc),
            settings=_settings(),
        )
        state = db.scalar(select(ShadowDriftState).where(ShadowDriftState.ticker == "SBER"))
        event = db.scalar(select(ShadowDriftNotificationEvent))

    assert result.state_changes == 1
    assert result.sent == 0
    assert sent == []
    assert state is not None and state.status == "watch"
    assert state.incident_notified is False
    assert event is not None
    assert event.transition_kind == "bootstrap"
    assert event.delivery_status == "not_applicable"


def test_stable_to_watch_sends_once_and_same_state_is_silent(monkeypatch) -> None:
    engine = _engine()
    current = {"status": "stable"}
    sent: list[list[str]] = []
    monkeypatch.setattr(
        notifications,
        "build_shadow_drift_overview",
        lambda db, days: _overview(_drift("SBER", current["status"])),
    )
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.append([event.ticker for event in events]),
    )

    t0 = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)
    with Session(engine) as db:
        process_shadow_drift_transitions(db, observed_at=t0, settings=_settings())
        current["status"] = "watch"
        first = process_shadow_drift_transitions(
            db,
            observed_at=t0 + timedelta(hours=6),
            settings=_settings(),
        )
        repeat = process_shadow_drift_transitions(
            db,
            observed_at=t0 + timedelta(hours=12),
            settings=_settings(),
        )
        events = list(db.scalars(select(ShadowDriftNotificationEvent)).all())

    assert first.sent == 1
    assert repeat.events_created == 0
    assert repeat.sent == 0
    assert sent == [["SBER"]]
    assert [event.delivery_status for event in events] == ["not_applicable", "sent"]


def test_watch_to_alert_bypasses_watch_cooldown(monkeypatch) -> None:
    engine = _engine()
    current = {"status": "stable"}
    sent: list[str] = []
    monkeypatch.setattr(
        notifications,
        "build_shadow_drift_overview",
        lambda db, days: _overview(_drift("SBER", current["status"])),
    )
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.extend(event.to_status for event in events),
    )

    t0 = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)
    with Session(engine) as db:
        process_shadow_drift_transitions(db, observed_at=t0, settings=_settings())
        current["status"] = "watch"
        process_shadow_drift_transitions(db, observed_at=t0 + timedelta(hours=1), settings=_settings())
        current["status"] = "alert"
        escalation = process_shadow_drift_transitions(
            db,
            observed_at=t0 + timedelta(hours=2),
            settings=_settings(),
        )

    assert escalation.sent == 1
    assert sent == ["watch", "alert"]


def test_recovery_only_after_notified_incident(monkeypatch) -> None:
    engine = _engine()
    current = {"status": "watch"}
    sent: list[str] = []
    monkeypatch.setattr(
        notifications,
        "build_shadow_drift_overview",
        lambda db, days: _overview(_drift("SBER", current["status"])),
    )
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.extend(event.to_status for event in events),
    )

    t0 = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)
    with Session(engine) as db:
        process_shadow_drift_transitions(db, observed_at=t0, settings=_settings())
        current["status"] = "stable"
        bootstrap_recovery = process_shadow_drift_transitions(
            db,
            observed_at=t0 + timedelta(hours=1),
            settings=_settings(),
        )
        current["status"] = "watch"
        process_shadow_drift_transitions(db, observed_at=t0 + timedelta(hours=30), settings=_settings())
        current["status"] = "stable"
        notified_recovery = process_shadow_drift_transitions(
            db,
            observed_at=t0 + timedelta(hours=31),
            settings=_settings(),
        )

    assert bootstrap_recovery.sent == 0
    assert notified_recovery.sent == 1
    assert sent == ["watch", "stable"]


def test_cooldown_suppresses_reentry_to_watch(monkeypatch) -> None:
    engine = _engine()
    current = {"status": "stable"}
    sent: list[str] = []
    monkeypatch.setattr(
        notifications,
        "build_shadow_drift_overview",
        lambda db, days: _overview(_drift("SBER", current["status"])),
    )
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.extend(event.to_status for event in events),
    )

    settings = _settings(cooldown_hours=24)
    t0 = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)
    with Session(engine) as db:
        process_shadow_drift_transitions(db, observed_at=t0, settings=settings)
        current["status"] = "watch"
        process_shadow_drift_transitions(db, observed_at=t0 + timedelta(hours=1), settings=settings)
        current["status"] = "stable"
        process_shadow_drift_transitions(db, observed_at=t0 + timedelta(hours=2), settings=settings)
        current["status"] = "watch"
        result = process_shadow_drift_transitions(
            db,
            observed_at=t0 + timedelta(hours=3),
            settings=settings,
        )
        last_event = db.scalars(
            select(ShadowDriftNotificationEvent).order_by(ShadowDriftNotificationEvent.id.desc()).limit(1)
        ).first()

    assert result.sent == 0
    assert result.suppressed == 1
    assert sent == ["watch", "stable"]
    assert last_event is not None
    assert last_event.delivery_status == "suppressed"
    assert last_event.delivery_reason == "cooldown"


def test_target_year_reset_never_sends(monkeypatch) -> None:
    engine = _engine()
    current = {"item": _drift("SBER", "stable", target_year=2027)}
    sent: list[str] = []
    monkeypatch.setattr(
        notifications,
        "build_shadow_drift_overview",
        lambda db, days: _overview(current["item"]),
    )
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.extend(event.to_status for event in events),
    )

    t0 = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)
    with Session(engine) as db:
        process_shadow_drift_transitions(db, observed_at=t0, settings=_settings())
        current["item"] = _drift("SBER", "alert", target_year=2028)
        result = process_shadow_drift_transitions(
            db,
            observed_at=t0 + timedelta(hours=6),
            settings=_settings(),
        )
        event = db.scalars(
            select(ShadowDriftNotificationEvent).order_by(ShadowDriftNotificationEvent.id.desc()).limit(1)
        ).first()

    assert result.sent == 0
    assert sent == []
    assert event is not None
    assert event.transition_kind == "target_year_reset"
    assert event.delivery_status == "not_applicable"


def test_disabled_notifications_record_suppressed_transition(monkeypatch) -> None:
    engine = _engine()
    current = {"status": "stable"}
    monkeypatch.setattr(
        notifications,
        "build_shadow_drift_overview",
        lambda db, days: _overview(_drift("SBER", current["status"])),
    )

    t0 = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)
    with Session(engine) as db:
        process_shadow_drift_transitions(db, observed_at=t0, settings=_settings(enabled=False))
        current["status"] = "watch"
        result = process_shadow_drift_transitions(
            db,
            observed_at=t0 + timedelta(hours=6),
            settings=_settings(enabled=False),
        )
        event = db.scalars(
            select(ShadowDriftNotificationEvent).order_by(ShadowDriftNotificationEvent.id.desc()).limit(1)
        ).first()

    assert result.suppressed == 1
    assert event is not None
    assert event.delivery_status == "suppressed"
    assert event.delivery_reason == "notifications_disabled"


def test_failed_delivery_retries_while_state_matches(monkeypatch) -> None:
    engine = _engine()
    current = {"status": "stable"}
    attempts = {"count": 0}

    monkeypatch.setattr(
        notifications,
        "build_shadow_drift_overview",
        lambda db, days: _overview(_drift("SBER", current["status"])),
    )

    def flaky_send(settings, events):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("smtp down")

    monkeypatch.setattr(notifications, "send_shadow_notification_digest", flaky_send)

    settings = _settings()
    t0 = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)
    with Session(engine) as db:
        process_shadow_drift_transitions(db, observed_at=t0, settings=settings)
        current["status"] = "watch"
        failed = process_shadow_drift_transitions(
            db,
            observed_at=t0 + timedelta(hours=1),
            settings=settings,
        )
        retried = process_shadow_drift_transitions(
            db,
            observed_at=t0 + timedelta(hours=2),
            settings=settings,
        )
        event = db.scalars(
            select(ShadowDriftNotificationEvent).where(
                ShadowDriftNotificationEvent.transition_kind == "transition"
            )
        ).first()

    assert failed.failed == 1
    assert retried.sent == 1
    assert attempts["count"] == 2
    assert event is not None
    assert event.delivery_status == "sent"
    assert event.delivery_attempts == 2


def test_failed_event_is_superseded_when_state_changes(monkeypatch) -> None:
    engine = _engine()
    current = {"status": "stable"}

    monkeypatch.setattr(
        notifications,
        "build_shadow_drift_overview",
        lambda db, days: _overview(_drift("SBER", current["status"])),
    )
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: (_ for _ in ()).throw(RuntimeError("smtp down")),
    )

    settings = _settings()
    t0 = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)
    with Session(engine) as db:
        process_shadow_drift_transitions(db, observed_at=t0, settings=settings)
        current["status"] = "watch"
        process_shadow_drift_transitions(db, observed_at=t0 + timedelta(hours=1), settings=settings)
        current["status"] = "alert"
        process_shadow_drift_transitions(db, observed_at=t0 + timedelta(hours=2), settings=_settings(enabled=False))
        stale = db.scalars(
            select(ShadowDriftNotificationEvent)
            .where(ShadowDriftNotificationEvent.to_status == "watch")
            .order_by(ShadowDriftNotificationEvent.id.desc())
            .limit(1)
        ).first()

    assert stale is not None
    assert stale.delivery_status == "superseded"
    assert stale.delivery_reason == "state_changed_before_delivery"
