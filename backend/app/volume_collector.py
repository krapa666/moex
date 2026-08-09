from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from zoneinfo import ZoneInfo

from .database import SessionLocal
from .models import (
    VolumeCollectionRun,
    VolumeMonitorSettings,
    VolumeNotification,
    VolumeObservation,
    VolumeSecurity,
)
from .volume_config import VolumeSettings
from .volume_mailer import send_signal_digest
from .volume_moex import VolumeMoexClient
from .volume_signals import evaluate_turnover

logger = logging.getLogger(__name__)
COLLECTION_ADVISORY_LOCK_ID = 6_620_260_840


def _status_values(settings: VolumeSettings, current: Decimal, baseline: list[Decimal]):
    return evaluate_turnover(
        current,
        baseline[-settings.baseline_sessions :],
        minimum_count=settings.min_baseline_sessions,
        min_ratio=Decimal(str(settings.signal_min_ratio)),
        max_ratio=Decimal(str(settings.signal_max_ratio)),
    )


def _upsert_observation(
    session,
    security_id: int,
    item: dict,
    result,
    *,
    is_final: bool,
    source: str,
) -> None:
    values = {
        "security_id": security_id,
        "trade_date": item["trade_date"],
        "turnover_rub": item["turnover_rub"],
        "volume_units": item.get("volume_units"),
        "close_price": item.get("close_price"),
        "baseline_average_rub": result.average,
        "baseline_count": result.count,
        "ratio": result.ratio,
        "signal_status": result.status,
        "is_final": is_final,
        "source": source,
        "observed_at": datetime.now(UTC),
    }
    statement = pg_insert(VolumeObservation).values(**values)
    statement = statement.on_conflict_do_update(
        constraint="uq_volume_observation_security_date",
        set_={key: value for key, value in values.items() if key not in {"security_id", "trade_date"}},
    )
    session.execute(statement)


def _notification_recipient() -> str | None:
    with SessionLocal() as session:
        stored = session.get(VolumeMonitorSettings, 1)
        if stored is None or not stored.notification_email:
            return None
        return stored.notification_email.strip() or None


async def collect_once(
    settings: VolumeSettings,
    *,
    allow_notifications: bool = True,
) -> dict[str, int | str | None]:
    logger.info("Starting IMOEX volume collection; notifications_allowed=%s", allow_notifications)
    lock_session = SessionLocal()
    try:
        lock_acquired = bool(
            lock_session.scalar(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": COLLECTION_ADVISORY_LOCK_ID},
            )
        )
    except Exception:
        lock_session.close()
        raise
    if not lock_acquired:
        lock_session.close()
        logger.info("Skipping IMOEX volume collection because another run holds the lock")
        return {"status": "skipped", "detail": "Сбор уже выполняется"}

    try:
        with SessionLocal() as session:
            run = VolumeCollectionRun(started_at=datetime.now(UTC), status="running")
            session.add(run)
            session.commit()
            run_id = run.id
    except Exception:
        try:
            lock_session.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": COLLECTION_ADVISORY_LOCK_ID},
            )
        finally:
            lock_session.close()
        raise

    errors: list[str] = []
    signals: list[dict] = []
    signals_detected = 0
    updated = 0
    total = 0

    try:
        try:
            async with VolumeMoexClient(settings) as moex:
                constituents = await moex.fetch_imoex_constituents()
                total = len(constituents)

                with SessionLocal() as session:
                    session.execute(update(VolumeSecurity).values(active=False))
                    now = datetime.now(UTC)
                    for item in constituents:
                        statement = pg_insert(VolumeSecurity).values(
                            ticker=item["ticker"],
                            short_name=item["short_name"],
                            weight=item["weight"],
                            active=True,
                            updated_at=now,
                        )
                        statement = statement.on_conflict_do_update(
                            index_elements=[VolumeSecurity.ticker],
                            set_={
                                "short_name": item["short_name"],
                                "weight": item["weight"],
                                "active": True,
                                "updated_at": now,
                            },
                        )
                        session.execute(statement)
                    session.commit()
                    security_ids = dict(
                        session.execute(select(VolumeSecurity.ticker, VolumeSecurity.id)).all()
                    )

                async def fetch_all(ticker: str):
                    history, current = await asyncio.gather(
                        moex.fetch_history(ticker, settings.moex_history_rows),
                        moex.fetch_current(ticker),
                    )
                    return history, current

                results = await asyncio.gather(
                    *(fetch_all(item["ticker"]) for item in constituents),
                    return_exceptions=True,
                )

                for constituent, fetched in zip(constituents, results, strict=True):
                    ticker = constituent["ticker"]
                    if isinstance(fetched, BaseException):
                        errors.append(f"{ticker}: {fetched}")
                        logger.error("Failed to collect volume for %s: %s", ticker, fetched)
                        continue

                    history, current = fetched
                    security_id = security_ids[ticker]
                    baseline: list[Decimal] = []
                    market_today = datetime.now(ZoneInfo(settings.schedule_timezone)).date()
                    with SessionLocal() as session:
                        for item in history:
                            result = _status_values(settings, item["turnover_rub"], baseline)
                            _upsert_observation(
                                session,
                                security_id,
                                item,
                                result,
                                is_final=item["trade_date"] < market_today,
                                source="history",
                            )
                            baseline.append(item["turnover_rub"])

                        if current is not None:
                            completed = [
                                item["turnover_rub"]
                                for item in history
                                if item["trade_date"] < current["trade_date"]
                            ]
                            result = _status_values(settings, current["turnover_rub"], completed)
                            _upsert_observation(
                                session,
                                security_id,
                                current,
                                result,
                                is_final=False,
                                source="intraday",
                            )
                            if result.status == "signal":
                                signals_detected += 1
                                already_sent = session.scalar(
                                    select(VolumeNotification.id).where(
                                        VolumeNotification.security_id == security_id,
                                        VolumeNotification.trade_date == current["trade_date"],
                                    )
                                )
                                if already_sent is None:
                                    signals.append(
                                        {
                                            "security_id": security_id,
                                            "ticker": ticker,
                                            "trade_date": current["trade_date"],
                                            "turnover_rub": current["turnover_rub"],
                                            "average_rub": result.average,
                                            "ratio": result.ratio,
                                        }
                                    )
                        session.commit()
                    updated += 1

            recipient = _notification_recipient()
            if allow_notifications and settings.smtp_configured and recipient and signals:
                await asyncio.to_thread(send_signal_digest, settings, recipient, signals)
                with SessionLocal() as session:
                    sent_at = datetime.now(UTC)
                    for signal_item in signals:
                        statement = (
                            pg_insert(VolumeNotification)
                            .values(
                                security_id=signal_item["security_id"],
                                trade_date=signal_item["trade_date"],
                                sent_at=sent_at,
                                recipient=recipient,
                                ratio=signal_item["ratio"],
                            )
                            .on_conflict_do_nothing(
                                constraint="uq_volume_notification_security_date"
                            )
                        )
                        session.execute(statement)
                    session.commit()

            status = "partial" if errors else "success"
            error_message = "\n".join(errors[:20]) or None
        except Exception as exc:
            logger.exception("Volume collection run failed")
            status = "failed"
            error_message = str(exc)

        with SessionLocal() as session:
            run = session.get(VolumeCollectionRun, run_id)
            if run:
                run.finished_at = datetime.now(UTC)
                run.status = status
                run.securities_total = total
                run.securities_updated = updated
                run.signals_found = signals_detected
                run.error_message = error_message
                session.commit()
        logger.info(
            "Finished IMOEX volume collection; status=%s total=%d updated=%d signals=%d errors=%d",
            status,
            total,
            updated,
            signals_detected,
            len(errors),
        )
        return {
            "status": status,
            "securities_total": total,
            "securities_updated": updated,
            "signals_found": signals_detected,
            "detail": error_message,
        }
    finally:
        try:
            lock_session.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": COLLECTION_ADVISORY_LOCK_ID},
            )
        finally:
            lock_session.close()
