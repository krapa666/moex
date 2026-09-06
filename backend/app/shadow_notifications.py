from __future__ import annotations

import html
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base, SessionLocal
from .shadow_history import ShadowDriftResult, build_shadow_drift_overview

_NOTIFICATION_STATUSES = {"pending", "sent", "suppressed", "failed", "superseded", "not_applicable"}
_MAX_ERROR_LENGTH = 1000
_REASON_LABELS = {
    "large_baseline_divergence": "большое расхождение с медианой",
    "rapid_divergence_change": "быстрый скачок расхождения",
    "weight_concentration": "повышенная концентрация веса",
    "relative_movement_gap": "weighted и median движутся по-разному",
    "training_snapshot_changed": "сменился historical snapshot",
    "too_few_snapshots": "мало snapshot",
    "history_too_short": "история короче 24 часов",
    "no_history": "история ещё не накоплена",
}


class ShadowDriftState(Base):
    __tablename__ = "shadow_drift_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    target_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    incident_notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ShadowDriftNotificationEvent(Base):
    __tablename__ = "shadow_drift_notification_events"
    __table_args__ = (
        Index(
            "ix_shadow_drift_notification_events_ticker_observed_at",
            "ticker",
            "observed_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    transition_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    latest_delta_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    delivery_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


@dataclass(frozen=True)
class ShadowNotificationSettings:
    enabled: bool
    recipient: str
    cooldown_hours: float
    history_days: int
    max_attempts: int
    smtp_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_starttls: bool
    smtp_ssl: bool
    public_base_url: str

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_enabled and self.smtp_host and self.smtp_from)

    @property
    def configured(self) -> bool:
        return bool(self.smtp_configured and self.recipient)


@dataclass(frozen=True)
class ShadowNotificationRunResult:
    generated_at: datetime
    enabled: bool
    configured: bool
    observed_tickers: int
    state_changes: int
    events_created: int
    sent: int
    suppressed: int
    failed: int
    superseded: int


@dataclass(frozen=True)
class ShadowNotificationStatus:
    enabled: bool
    configured: bool
    smtp_configured: bool
    recipient_configured: bool
    cooldown_hours: float
    history_days: int
    pending_events: int
    failed_events: int
    last_event_at: datetime | None
    last_sent_at: datetime | None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_shadow_notification_settings() -> ShadowNotificationSettings:
    recipient = os.getenv("SHADOW_NOTIFICATION_EMAIL", "").strip() or os.getenv(
        "VOLUME_NOTIFICATION_EMAIL", ""
    ).strip()
    settings = ShadowNotificationSettings(
        enabled=_env_bool("SHADOW_NOTIFICATIONS_ENABLED", False),
        recipient=recipient,
        cooldown_hours=max(float(os.getenv("SHADOW_NOTIFICATION_COOLDOWN_HOURS", "24")), 0.0),
        history_days=max(min(int(os.getenv("SHADOW_NOTIFICATION_HISTORY_DAYS", "30")), 180), 2),
        max_attempts=max(min(int(os.getenv("SHADOW_NOTIFICATION_MAX_ATTEMPTS", "5")), 20), 1),
        smtp_enabled=_env_bool("VOLUME_SMTP_ENABLED", False),
        smtp_host=os.getenv("VOLUME_SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("VOLUME_SMTP_PORT", "587")),
        smtp_username=os.getenv("VOLUME_SMTP_USERNAME", ""),
        smtp_password=os.getenv("VOLUME_SMTP_PASSWORD", ""),
        smtp_from=os.getenv("VOLUME_SMTP_FROM", "").strip(),
        smtp_starttls=_env_bool("VOLUME_SMTP_STARTTLS", True),
        smtp_ssl=_env_bool("VOLUME_SMTP_SSL", False),
        public_base_url=os.getenv("VOLUME_PUBLIC_BASE_URL", "").strip(),
    )
    if not 1 <= settings.smtp_port <= 65535:
        raise ValueError("VOLUME_SMTP_PORT is invalid")
    if settings.smtp_ssl and settings.smtp_starttls:
        raise ValueError("VOLUME_SMTP_SSL and VOLUME_SMTP_STARTTLS cannot both be enabled")
    if settings.recipient and ("@" not in settings.recipient or " " in settings.recipient):
        raise ValueError("SHADOW_NOTIFICATION_EMAIL is invalid")
    return settings


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _status_transition_decision(
    state: ShadowDriftState,
    *,
    from_status: str,
    to_status: str,
    now: datetime,
    settings: ShadowNotificationSettings,
) -> tuple[str, str | None]:
    notifiable = False
    cooldown_applies = False

    if from_status == "stable" and to_status == "watch":
        notifiable = True
        cooldown_applies = True
    elif from_status == "stable" and to_status == "alert":
        notifiable = True
    elif from_status == "watch" and to_status == "alert":
        notifiable = True
    elif from_status in {"watch", "alert"} and to_status == "stable":
        if state.incident_notified:
            notifiable = True
        else:
            return "not_applicable", "unnotified_recovery"
    else:
        return "not_applicable", "non_notifiable_transition"

    if not notifiable:
        return "not_applicable", "non_notifiable_transition"
    if not settings.enabled:
        return "suppressed", "notifications_disabled"
    if not settings.configured:
        return "suppressed", "delivery_not_configured"
    if cooldown_applies and state.last_notified_at is not None:
        last_notified = _as_utc(state.last_notified_at)
        if now - last_notified < timedelta(hours=settings.cooldown_hours):
            return "suppressed", "cooldown"
    return "pending", None


def _event_for_transition(
    *,
    item: ShadowDriftResult,
    from_status: str | None,
    transition_kind: str,
    delivery_status: str,
    delivery_reason: str | None,
    observed_at: datetime,
) -> ShadowDriftNotificationEvent:
    if delivery_status not in _NOTIFICATION_STATUSES:
        raise ValueError(f"Unsupported delivery status: {delivery_status}")
    return ShadowDriftNotificationEvent(
        ticker=item.ticker,
        target_year=item.target_year,
        from_status=from_status,
        to_status=item.status,
        transition_kind=transition_kind,
        observed_at=observed_at,
        latest_delta_percent=item.latest_delta_percent,
        reasons=list(item.reasons),
        delivery_status=delivery_status,
        delivery_reason=delivery_reason,
    )


def _render_transition(from_status: str | None, to_status: str) -> str:
    source = (from_status or "—").upper()
    return f"{source} → {to_status.upper()}"


def _send_message(settings: ShadowNotificationSettings, message: EmailMessage) -> None:
    smtp_class = smtplib.SMTP_SSL if settings.smtp_ssl else smtplib.SMTP
    with smtp_class(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def send_shadow_notification_digest(
    settings: ShadowNotificationSettings,
    events: list[ShadowDriftNotificationEvent],
) -> None:
    if not settings.configured or not events:
        return

    has_alert = any(event.to_status == "alert" for event in events)
    has_watch = any(event.to_status == "watch" for event in events)
    if has_alert:
        label = "ALERT"
    elif has_watch:
        label = "WATCH"
    else:
        label = "RECOVERY"

    message = EmailMessage()
    message["Subject"] = f"MOEX shadow drift: {label} — {len(events)} переход(а)"
    message["From"] = settings.smtp_from
    message["To"] = settings.recipient

    lines = ["Изменения состояния shadow weighted consensus:", ""]
    rows: list[str] = []
    for event in events:
        transition = _render_transition(event.from_status, event.to_status)
        delta = "—" if event.latest_delta_percent is None else f"{event.latest_delta_percent:+.1f}%"
        reason_text = ", ".join(_REASON_LABELS.get(reason, reason) for reason in (event.reasons or []))
        lines.append(f"{event.ticker}: {transition}; Δ weighted/median {delta}; {reason_text or 'без дополнительных причин'}")
        ticker_url = ""
        if settings.public_base_url:
            ticker_url = settings.public_base_url.rstrip("/") + f"/analytics/?ticker={event.ticker}"
        ticker_cell = html.escape(event.ticker)
        if ticker_url:
            ticker_cell = f'<a href="{html.escape(ticker_url, quote=True)}">{ticker_cell}</a>'
        rows.append(
            "<tr>"
            f"<td>{ticker_cell}</td>"
            f"<td>{html.escape(transition)}</td>"
            f"<td>{html.escape(delta)}</td>"
            f"<td>{html.escape(reason_text or '—')}</td>"
            "</tr>"
        )

    if settings.public_base_url:
        lines.extend(["", f"Analytics: {settings.public_base_url.rstrip('/')}/analytics/"])
    message.set_content("\n".join(lines))
    message.add_alternative(
        "<html><body>"
        f"<h2>Shadow drift: {html.escape(label)}</h2>"
        "<table border='1' cellpadding='6' cellspacing='0'>"
        "<thead><tr><th>Тикер</th><th>Переход</th><th>Δ weighted / median</th><th>Причины</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "<p>Это operational model-monitoring, а не торговый сигнал.</p>"
        "</body></html>",
        subtype="html",
    )
    _send_message(settings, message)


def send_shadow_notification_test(settings: ShadowNotificationSettings) -> None:
    if not settings.configured:
        raise RuntimeError("Shadow notification SMTP/recipient is not configured")
    message = EmailMessage()
    message["Subject"] = "MOEX: проверка shadow drift уведомлений"
    message["From"] = settings.smtp_from
    message["To"] = settings.recipient
    message.set_content(
        "Это тестовое письмо shadow drift monitoring.\n\n"
        "Если вы его получили, SMTP и адрес получателя настроены корректно.\n"
        "Production consensus остаётся медианным."
    )
    _send_message(settings, message)


def _deliver_events(
    db: Session,
    *,
    settings: ShadowNotificationSettings,
    now: datetime,
) -> tuple[int, int, int]:
    if not settings.enabled or not settings.configured:
        return 0, 0, 0

    candidates = list(
        db.scalars(
            select(ShadowDriftNotificationEvent)
            .where(
                ShadowDriftNotificationEvent.delivery_status.in_(("pending", "failed")),
                ShadowDriftNotificationEvent.delivery_attempts < settings.max_attempts,
            )
            .order_by(ShadowDriftNotificationEvent.observed_at.asc(), ShadowDriftNotificationEvent.id.asc())
        ).all()
    )
    if not candidates:
        return 0, 0, 0

    state_by_ticker = {
        state.ticker: state
        for state in db.scalars(
            select(ShadowDriftState).where(
                ShadowDriftState.ticker.in_({event.ticker for event in candidates})
            )
        ).all()
    }
    deliverable: list[ShadowDriftNotificationEvent] = []
    superseded = 0
    for event in candidates:
        state = state_by_ticker.get(event.ticker)
        if (
            state is None
            or state.target_year != event.target_year
            or state.status != event.to_status
        ):
            event.delivery_status = "superseded"
            event.delivery_reason = "state_changed_before_delivery"
            superseded += 1
            continue
        deliverable.append(event)
    db.commit()
    if not deliverable:
        return 0, 0, superseded

    try:
        send_shadow_notification_digest(settings, deliverable)
    except Exception as exc:
        error = str(exc)[:_MAX_ERROR_LENGTH]
        for event in deliverable:
            event.delivery_status = "failed"
            event.delivery_attempts += 1
            event.last_attempt_at = now
            event.error = error
        db.commit()
        return 0, len(deliverable), superseded

    for event in deliverable:
        event.delivery_status = "sent"
        event.delivery_attempts += 1
        event.last_attempt_at = now
        event.notified_at = now
        event.error = None
        state = state_by_ticker.get(event.ticker)
        if state is not None and state.target_year == event.target_year and state.status == event.to_status:
            state.last_notified_at = now
            if event.to_status in {"watch", "alert"}:
                state.incident_notified = True
            elif event.to_status == "stable":
                state.incident_notified = False
    db.commit()
    return len(deliverable), 0, superseded


def process_shadow_drift_transitions(
    db: Session,
    *,
    observed_at: datetime | None = None,
    settings: ShadowNotificationSettings | None = None,
) -> ShadowNotificationRunResult:
    current = _as_utc(observed_at or datetime.now(timezone.utc))
    effective_settings = settings or get_shadow_notification_settings()
    overview = build_shadow_drift_overview(db, days=effective_settings.history_days)

    existing_states = {
        state.ticker: state
        for state in db.scalars(
            select(ShadowDriftState).where(
                ShadowDriftState.ticker.in_({item.ticker for item in overview.items})
            )
        ).all()
    }

    state_changes = 0
    events_created = 0
    suppressed = 0
    for item in overview.items:
        state = existing_states.get(item.ticker)
        if state is None:
            state = ShadowDriftState(
                ticker=item.ticker,
                target_year=item.target_year,
                status=item.status,
                observed_at=current,
                changed_at=current,
                incident_notified=False,
            )
            db.add(state)
            existing_states[item.ticker] = state
            db.add(
                _event_for_transition(
                    item=item,
                    from_status=None,
                    transition_kind="bootstrap",
                    delivery_status="not_applicable",
                    delivery_reason="initial_state",
                    observed_at=current,
                )
            )
            state_changes += 1
            events_created += 1
            continue

        if state.target_year != item.target_year:
            from_status = state.status
            state.target_year = item.target_year
            state.status = item.status
            state.observed_at = current
            state.changed_at = current
            state.incident_notified = False
            db.add(
                _event_for_transition(
                    item=item,
                    from_status=from_status,
                    transition_kind="target_year_reset",
                    delivery_status="not_applicable",
                    delivery_reason="target_year_changed",
                    observed_at=current,
                )
            )
            state_changes += 1
            events_created += 1
            continue

        if state.status == item.status:
            state.observed_at = current
            continue

        from_status = state.status
        delivery_status, delivery_reason = _status_transition_decision(
            state,
            from_status=from_status,
            to_status=item.status,
            now=current,
            settings=effective_settings,
        )
        db.add(
            _event_for_transition(
                item=item,
                from_status=from_status,
                transition_kind="transition",
                delivery_status=delivery_status,
                delivery_reason=delivery_reason,
                observed_at=current,
            )
        )
        state.status = item.status
        state.observed_at = current
        state.changed_at = current
        if item.status == "insufficient":
            state.incident_notified = False
        state_changes += 1
        events_created += 1
        if delivery_status == "suppressed":
            suppressed += 1

    db.commit()
    sent, failed, superseded = _deliver_events(
        db,
        settings=effective_settings,
        now=current,
    )
    return ShadowNotificationRunResult(
        generated_at=current,
        enabled=effective_settings.enabled,
        configured=effective_settings.configured,
        observed_tickers=len(overview.items),
        state_changes=state_changes,
        events_created=events_created,
        sent=sent,
        suppressed=suppressed,
        failed=failed,
        superseded=superseded,
    )


def process_shadow_drift_transitions_once() -> ShadowNotificationRunResult:
    with SessionLocal() as db:
        return process_shadow_drift_transitions(db)


def list_shadow_notification_events(
    db: Session,
    *,
    limit: int = 50,
) -> list[ShadowDriftNotificationEvent]:
    return list(
        db.scalars(
            select(ShadowDriftNotificationEvent)
            .order_by(
                ShadowDriftNotificationEvent.observed_at.desc(),
                ShadowDriftNotificationEvent.id.desc(),
            )
            .limit(limit)
        ).all()
    )


def build_shadow_notification_status(db: Session) -> ShadowNotificationStatus:
    settings = get_shadow_notification_settings()
    last_event = db.scalars(
        select(ShadowDriftNotificationEvent)
        .order_by(
            ShadowDriftNotificationEvent.observed_at.desc(),
            ShadowDriftNotificationEvent.id.desc(),
        )
        .limit(1)
    ).first()
    last_sent = db.scalars(
        select(ShadowDriftNotificationEvent)
        .where(ShadowDriftNotificationEvent.delivery_status == "sent")
        .order_by(
            ShadowDriftNotificationEvent.notified_at.desc(),
            ShadowDriftNotificationEvent.id.desc(),
        )
        .limit(1)
    ).first()
    pending = len(
        list(
            db.scalars(
                select(ShadowDriftNotificationEvent.id).where(
                    ShadowDriftNotificationEvent.delivery_status == "pending"
                )
            ).all()
        )
    )
    failed = len(
        list(
            db.scalars(
                select(ShadowDriftNotificationEvent.id).where(
                    ShadowDriftNotificationEvent.delivery_status == "failed"
                )
            ).all()
        )
    )
    return ShadowNotificationStatus(
        enabled=settings.enabled,
        configured=settings.configured,
        smtp_configured=settings.smtp_configured,
        recipient_configured=bool(settings.recipient),
        cooldown_hours=settings.cooldown_hours,
        history_days=settings.history_days,
        pending_events=pending,
        failed_events=failed,
        last_event_at=_as_utc(last_event.observed_at) if last_event is not None else None,
        last_sent_at=_as_utc(last_sent.notified_at) if last_sent is not None and last_sent.notified_at else None,
    )
