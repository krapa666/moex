from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
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


def _status_values(
    settings: VolumeSettings,
    current: Decimal,
    baseline: list[Decimal],
    baseline_sessions: int,
):
    return evaluate_turnover(
        current,
        baseline[-baseline_sessions:],
        minimum_count=baseline_sessions,
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


def _monitor_preferences(settings: VolumeSettings) -> tuple[str | None, str, int]:
    with SessionLocal() as session:
        stored = session.get(VolumeMonitorSettings, 1)
        if stored is None:
            return settings.notification_email or None, "imoex", settings.baseline_sessions
        scope = stored.notification_scope if stored.notification_scope in {"imoex", "all"} else "imoex"
        baseline_sessions = stored.baseline_sessions
        if not 10 <= baseline_sessions <= 250:
            baseline_sessions = settings.baseline_sessions
        return settings.notification_email or None, scope, baseline_sessions


def _notification_matches_scope(scope: str, is_imoex: bool) -> bool:
    return scope == "all" or is_imoex


def _select_notification_candidates(
    candidates: list[dict],
    *,
    imoex_anomalies: int,
    broad_market_threshold: int,
) -> tuple[list[dict], int]:
    broad_market = imoex_anomalies > broad_market_threshold
    if not broad_market:
        return candidates, 0
    selected = [item for item in candidates if item["status"] != "above_range"]
    return selected, len(candidates) - len(selected)


async def _fetch_security_snapshot(
    moex: VolumeMoexClient,
    ticker: str,
    history_rows: int,
    *,
    refresh_history: bool,
):
    if refresh_history:
        return await asyncio.gather(
            moex.fetch_history(ticker, history_rows),
            moex.fetch_current(ticker),
        )
    return [], await moex.fetch_current(ticker)


def _stored_baseline(
    security_id: int,
    *,
    before_date: date,
    baseline_sessions: int,
) -> list[Decimal]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(VolumeObservation.turnover_rub)
                .where(
                    VolumeObservation.security_id == security_id,
                    VolumeObservation.trade_date < before_date,
                    VolumeObservation.is_final.is_(True),
                )
                .order_by(VolumeObservation.trade_date.desc())
                .limit(baseline_sessions)
            ).all()
        )


async def collect_once(
    settings: VolumeSettings,
    *,
    allow_notifications: bool = True,
    refresh_history: bool = True,
) -> dict[str, int | str | None]:
    recipient, notification_scope, baseline_sessions = _monitor_preferences(settings)
    logger.info(
        "Starting TQBR equity volume collection; notifications_allowed=%s refresh_history=%s notification_scope=%s baseline_sessions=%d",
        allow_notifications,
        refresh_history,
        notification_scope,
        baseline_sessions,
    )
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
        logger.info("Skipping TQBR equity volume collection because another run holds the lock")
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
    notification_candidates: list[dict] = []
    signals_detected = 0
    imoex_anomalies_found = 0
    notifications_suppressed = 0
    notifications_sent = 0
    history_securities_refreshed = 0
    updated = 0
    total = 0

    try:
        try:
            async with VolumeMoexClient(settings) as moex:
                securities, imoex_constituents = await asyncio.gather(
                    moex.fetch_tqbr_equities(),
                    moex.fetch_imoex_constituents(),
                )
                imoex_by_ticker = {item["ticker"]: item for item in imoex_constituents}
                for item in securities:
                    index_item = imoex_by_ticker.get(item["ticker"])
                    item["is_imoex"] = index_item is not None
                    item["weight"] = index_item["weight"] if index_item else None
                total = len(securities)

                with SessionLocal() as session:
                    session.execute(update(VolumeSecurity).values(active=False))
                    now = datetime.now(UTC)
                    for item in securities:
                        statement = pg_insert(VolumeSecurity).values(
                            ticker=item["ticker"],
                            short_name=item["short_name"],
                            security_type=item["security_type"],
                            is_imoex=item["is_imoex"],
                            weight=item["weight"],
                            active=True,
                            updated_at=now,
                        )
                        statement = statement.on_conflict_do_update(
                            index_elements=[VolumeSecurity.ticker],
                            set_={
                                "short_name": item["short_name"],
                                "security_type": item["security_type"],
                                "is_imoex": item["is_imoex"],
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
                    history_rows = max(
                        settings.moex_history_rows,
                        baseline_sessions + settings.display_sessions,
                    )
                    return await _fetch_security_snapshot(
                        moex,
                        ticker,
                        history_rows,
                        refresh_history=refresh_history,
                    )

                results = await asyncio.gather(
                    *(fetch_all(item["ticker"]) for item in securities),
                    return_exceptions=True,
                )

                for security, fetched in zip(securities, results, strict=True):
                    ticker = security["ticker"]
                    if isinstance(fetched, BaseException):
                        errors.append(f"{ticker}: {fetched}")
                        logger.error("Failed to collect volume for %s: %s", ticker, fetched)
                        continue

                    history, current = fetched
                    security_id = security_ids[ticker]
                    stored_baseline: list[Decimal] = []
                    if refresh_history:
                        history_securities_refreshed += 1
                    elif current is not None:
                        stored_baseline = _stored_baseline(
                            security_id,
                            before_date=current["trade_date"],
                            baseline_sessions=baseline_sessions,
                        )
                        if len(stored_baseline) < baseline_sessions:
                            try:
                                history_rows = max(
                                    settings.moex_history_rows,
                                    baseline_sessions + settings.display_sessions,
                                )
                                history = await moex.fetch_history(ticker, history_rows)
                                history_securities_refreshed += 1
                            except Exception as exc:
                                errors.append(f"{ticker}: {exc}")
                                logger.error(
                                    "Failed to refresh fallback history for %s: %s",
                                    ticker,
                                    exc,
                                )
                                continue
                    baseline: list[Decimal] = []
                    market_today = datetime.now(ZoneInfo(settings.schedule_timezone)).date()
                    with SessionLocal() as session:
                        for item in history:
                            result = _status_values(
                                settings,
                                item["turnover_rub"],
                                baseline,
                                baseline_sessions,
                            )
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
                            completed = (
                                [
                                    item["turnover_rub"]
                                    for item in history
                                    if item["trade_date"] < current["trade_date"]
                                ]
                                if history
                                else stored_baseline
                            )
                            result = _status_values(
                                settings,
                                current["turnover_rub"],
                                completed,
                                baseline_sessions,
                            )
                            _upsert_observation(
                                session,
                                security_id,
                                current,
                                result,
                                is_final=False,
                                source="intraday",
                            )
                            if result.status in {"signal", "above_range"}:
                                signals_detected += 1
                                if security["is_imoex"]:
                                    imoex_anomalies_found += 1
                                if _notification_matches_scope(
                                    notification_scope,
                                    security["is_imoex"],
                                ):
                                    already_sent = session.scalar(
                                        select(VolumeNotification.id).where(
                                            VolumeNotification.security_id == security_id,
                                            VolumeNotification.trade_date == current["trade_date"],
                                        )
                                    )
                                    if already_sent is None:
                                        notification_candidates.append(
                                            {
                                                "security_id": security_id,
                                                "ticker": ticker,
                                                "trade_date": current["trade_date"],
                                                "turnover_rub": current["turnover_rub"],
                                                "average_rub": result.average,
                                                "ratio": result.ratio,
                                                "status": result.status,
                                            }
                                        )
                        session.commit()
                    updated += 1

            signals, notifications_suppressed = _select_notification_candidates(
                notification_candidates,
                imoex_anomalies=imoex_anomalies_found,
                broad_market_threshold=settings.broad_market_signal_threshold,
            )
            if imoex_anomalies_found > settings.broad_market_signal_threshold:
                logger.info(
                    "Broad-market volume condition detected; imoex_anomalies=%d threshold=%d high_ratio_notifications_suppressed=%d",
                    imoex_anomalies_found,
                    settings.broad_market_signal_threshold,
                    notifications_suppressed,
                )

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
                notifications_sent = len(signals)

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
                run.imoex_anomalies_found = imoex_anomalies_found
                run.notifications_suppressed = notifications_suppressed
                run.notifications_sent = notifications_sent
                run.history_securities_refreshed = history_securities_refreshed
                run.error_message = error_message
                session.commit()
        logger.info(
            "Finished TQBR equity volume collection; status=%s total=%d updated=%d history_refreshed=%d anomalies=%d imoex_anomalies=%d notifications_sent=%d notifications_suppressed=%d errors=%d",
            status,
            total,
            updated,
            history_securities_refreshed,
            signals_detected,
            imoex_anomalies_found,
            notifications_sent,
            notifications_suppressed,
            len(errors),
        )
        return {
            "status": status,
            "securities_total": total,
            "securities_updated": updated,
            "signals_found": signals_detected,
            "imoex_anomalies_found": imoex_anomalies_found,
            "notifications_sent": notifications_sent,
            "notifications_suppressed": notifications_suppressed,
            "history_securities_refreshed": history_securities_refreshed,
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
