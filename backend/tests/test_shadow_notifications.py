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

T0 = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)


def _settings(
    *, enabled: bool = True, configured: bool = True, cooldown_hours: float = 24.0
) -> ShadowNotificationSettings:
    return ShadowNotificationSettings(
        enabled=enabled,
        recipient="alerts@example.com" if configured else "",
        cooldown_hours=cooldown_hours,
        history_days=30,
        max_attempts=5,
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
    reasons = {
        "stable": [],
        "watch": ["weight_concentration"],
        "alert": ["large_baseline_divergence"],
        "insufficient": ["history_too_short"],
    }[status]
    delta = {"stable": 2.0, "watch": 12.0, "alert": 25.0, "insufficient": 2.0}[status]
    return ShadowDriftResult(
        ticker=ticker,
        target_year=target_year,
        latest_training_snapshot="pre_year",  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        reasons=reasons,
        snapshots=4,
        history_days=30,
        history_span_hours=48.0,
        first_captured_at=T0 - timedelta(days=2),
        last_captured_at=T0,
        latest_delta_percent=delta,
        previous_delta_percent=2.0,
        delta_step_percentage_points=1.0,
        median_abs_delta_percent=2.0,
        max_abs_delta_percent=delta,
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
        generated_at=T0,
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


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _install_overview(monkeypatch, current: dict[str, ShadowDriftResult]) -> None:
    monkeypatch.setattr(
        notifications,
        "build_shadow_drift_overview",
        lambda db, days: _overview(current["item"]),
    )


def test_bootstrap_records_state_without_email(monkeypatch) -> None:
    current = {"item": _drift("SBER", "watch")}
    _install_overview(monkeypatch, current)
    sent: list[str] = []
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.extend(event.ticker for event in events),
    )

    with _db() as db:
        result = process_shadow_drift_transitions(db, observed_at=T0, settings=_settings())
        state = db.scalar(select(ShadowDriftState))
        event = db.scalar(select(ShadowDriftNotificationEvent))

    assert result.state_changes == 1
    assert result.sent == 0
    assert sent == []
    assert state is not None and state.status == "watch" and not state.incident_notified
    assert event is not None
    assert (event.transition_kind, event.delivery_status) == ("bootstrap", "not_applicable")


def test_stable_to_watch_sends_once_and_same_watch_is_silent(monkeypatch) -> None:
    current = {"item": _drift("SBER", "stable")}
    _install_overview(monkeypatch, current)
    sent: list[str] = []
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.extend(event.to_status for event in events),
    )

    with _db() as db:
        process_shadow_drift_transitions(db, observed_at=T0, settings=_settings())
        current["item"] = _drift("SBER", "watch")
        first = process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=6), settings=_settings()
        )
        repeat = process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=12), settings=_settings()
        )

    assert first.sent == 1
    assert repeat.events_created == 0
    assert repeat.sent == 0
    assert sent == ["watch"]


def test_watch_to_alert_bypasses_watch_cooldown(monkeypatch) -> None:
    current = {"item": _drift("SBER", "stable")}
    _install_overview(monkeypatch, current)
    sent: list[str] = []
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.extend(event.to_status for event in events),
    )

    with _db() as db:
        process_shadow_drift_transitions(db, observed_at=T0, settings=_settings())
        current["item"] = _drift("SBER", "watch")
        process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=1), settings=_settings()
        )
        current["item"] = _drift("SBER", "alert")
        escalation = process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=2), settings=_settings()
        )

    assert escalation.sent == 1
    assert sent == ["watch", "alert"]


def test_recovery_only_after_incident_was_actually_notified(monkeypatch) -> None:
    current = {"item": _drift("SBER", "watch")}
    _install_overview(monkeypatch, current)
    sent: list[str] = []
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.extend(event.to_status for event in events),
    )

    with _db() as db:
        process_shadow_drift_transitions(db, observed_at=T0, settings=_settings())
        current["item"] = _drift("SBER", "stable")
        no_recovery = process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=1), settings=_settings()
        )
        current["item"] = _drift("SBER", "watch")
        process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=30), settings=_settings()
        )
        current["item"] = _drift("SBER", "stable")
        recovery = process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=31), settings=_settings()
        )

    assert no_recovery.sent == 0
    assert recovery.sent == 1
    assert sent == ["watch", "stable"]


def test_cooldown_suppresses_fast_reentry_to_watch(monkeypatch) -> None:
    current = {"item": _drift("SBER", "stable")}
    _install_overview(monkeypatch, current)
    sent: list[str] = []
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.extend(event.to_status for event in events),
    )
    settings = _settings(cooldown_hours=24)

    with _db() as db:
        process_shadow_drift_transitions(db, observed_at=T0, settings=settings)
        current["item"] = _drift("SBER", "watch")
        process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=1), settings=settings
        )
        current["item"] = _drift("SBER", "stable")
        process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=2), settings=settings
        )
        current["item"] = _drift("SBER", "watch")
        result = process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=3), settings=settings
        )
        event = db.scalars(
            select(ShadowDriftNotificationEvent)
            .order_by(ShadowDriftNotificationEvent.id.desc())
            .limit(1)
        ).first()

    assert result.sent == 0 and result.suppressed == 1
    assert sent == ["watch", "stable"]
    assert event is not None
    assert (event.delivery_status, event.delivery_reason) == ("suppressed", "cooldown")


def test_target_year_reset_is_recorded_without_mail(monkeypatch) -> None:
    current = {"item": _drift("SBER", "stable", target_year=2027)}
    _install_overview(monkeypatch, current)
    sent: list[str] = []
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: sent.extend(event.to_status for event in events),
    )

    with _db() as db:
        process_shadow_drift_transitions(db, observed_at=T0, settings=_settings())
        current["item"] = _drift("SBER", "alert", target_year=2028)
        result = process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=6), settings=_settings()
        )
        event = db.scalars(
            select(ShadowDriftNotificationEvent)
            .order_by(ShadowDriftNotificationEvent.id.desc())
            .limit(1)
        ).first()

    assert result.sent == 0 and sent == []
    assert event is not None
    assert (event.transition_kind, event.delivery_status) == (
        "target_year_reset",
        "not_applicable",
    )


def test_disabled_delivery_records_suppressed_transition(monkeypatch) -> None:
    current = {"item": _drift("SBER", "stable")}
    _install_overview(monkeypatch, current)

    with _db() as db:
        process_shadow_drift_transitions(
            db, observed_at=T0, settings=_settings(enabled=False)
        )
        current["item"] = _drift("SBER", "watch")
        result = process_shadow_drift_transitions(
            db,
            observed_at=T0 + timedelta(hours=6),
            settings=_settings(enabled=False),
        )
        event = db.scalars(
            select(ShadowDriftNotificationEvent)
            .order_by(ShadowDriftNotificationEvent.id.desc())
            .limit(1)
        ).first()

    assert result.suppressed == 1
    assert event is not None
    assert (event.delivery_status, event.delivery_reason) == (
        "suppressed",
        "notifications_disabled",
    )


def test_failed_delivery_retries_while_state_still_matches(monkeypatch) -> None:
    current = {"item": _drift("SBER", "stable")}
    _install_overview(monkeypatch, current)
    attempts = {"count": 0}

    def flaky_send(settings, events):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("smtp down")

    monkeypatch.setattr(notifications, "send_shadow_notification_digest", flaky_send)

    with _db() as db:
        process_shadow_drift_transitions(db, observed_at=T0, settings=_settings())
        current["item"] = _drift("SBER", "watch")
        failed = process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=1), settings=_settings()
        )
        retried = process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=2), settings=_settings()
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
    assert (event.delivery_status, event.delivery_attempts) == ("sent", 2)


def test_failed_event_becomes_superseded_after_state_change(monkeypatch) -> None:
    current = {"item": _drift("SBER", "stable")}
    _install_overview(monkeypatch, current)
    monkeypatch.setattr(
        notifications,
        "send_shadow_notification_digest",
        lambda settings, events: (_ for _ in ()).throw(RuntimeError("smtp down")),
    )

    with _db() as db:
        process_shadow_drift_transitions(db, observed_at=T0, settings=_settings())
        current["item"] = _drift("SBER", "watch")
        process_shadow_drift_transitions(
            db, observed_at=T0 + timedelta(hours=1), settings=_settings()
        )
        current["item"] = _drift("SBER", "alert")
        process_shadow_drift_transitions(
            db,
            observed_at=T0 + timedelta(hours=2),
            settings=_settings(enabled=False),
        )
        stale = db.scalars(
            select(ShadowDriftNotificationEvent)
            .where(ShadowDriftNotificationEvent.to_status == "watch")
            .order_by(ShadowDriftNotificationEvent.id.desc())
            .limit(1)
        ).first()

    assert stale is not None
    assert (stale.delivery_status, stale.delivery_reason) == (
        "superseded",
        "state_changed_before_delivery",
    )
