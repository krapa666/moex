import html
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from zoneinfo import ZoneInfo

from .volume_config import VolumeSettings


def _send_message(settings: VolumeSettings, message: EmailMessage) -> None:
    smtp_class = smtplib.SMTP_SSL if settings.smtp_ssl else smtplib.SMTP
    with smtp_class(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def send_signal_digest(
    settings: VolumeSettings,
    recipient: str,
    signals: list[dict[str, Any]],
) -> None:
    if not settings.smtp_configured or not recipient or not signals:
        return

    day = signals[0]["trade_date"].strftime("%d.%m.%Y")
    message = EmailMessage()
    message["Subject"] = f"MOEX: аномальный объём — {len(signals)} сигнал(а), {day}"
    message["From"] = settings.smtp_from
    message["To"] = recipient

    lines = [f"Сигналы по объёму торгов за {day}:", ""]
    rows = []
    for signal in signals:
        turnover_mln = signal["turnover_rub"] / 1_000_000
        average_mln = signal["average_rub"] / 1_000_000
        lines.append(
            f"{signal['ticker']} — {signal['ratio']:.2f}×; "
            f"оборот {turnover_mln:,.1f} млн ₽; средний {average_mln:,.1f} млн ₽."
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(signal['ticker'])}</td>"
            f"<td>{signal['ratio']:.2f}×</td>"
            f"<td>{turnover_mln:,.1f} млн ₽</td>"
            f"<td>{average_mln:,.1f} млн ₽</td>"
            "</tr>"
        )
    if settings.public_base_url:
        lines.extend(["", f"Интерфейс: {settings.public_base_url.rstrip('/')}/volumes/"])

    message.set_content("\n".join(lines))
    link = ""
    if settings.public_base_url:
        safe_url = html.escape(settings.public_base_url.rstrip("/") + "/volumes/", quote=True)
        link = f'<p><a href="{safe_url}">Открыть монитор</a></p>'
    message.add_alternative(
        "<html><body>"
        f"<h2>Сигналы по объёму торгов за {html.escape(day)}</h2>"
        "<table border='1' cellpadding='6' cellspacing='0'>"
        "<thead><tr><th>Тикер</th><th>Коэффициент</th><th>Оборот</th><th>Среднее</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>{link}</body></html>",
        subtype="html",
    )

    _send_message(settings, message)


def send_test_email(settings: VolumeSettings, recipient: str, notification_scope: str) -> None:
    sent_at = datetime.now(ZoneInfo(settings.schedule_timezone)).strftime("%d.%m.%Y %H:%M:%S %Z")
    scope_label = "все акции TQBR" if notification_scope == "all" else "только акции IMOEX"
    message = EmailMessage()
    message["Subject"] = "MOEX: проверка почтовых уведомлений"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    lines = [
        "Это тестовое письмо монитора объёмов MOEX.",
        "",
        "Если вы его получили, подключение к SMTP и адрес получателя работают.",
        f"Текущая область биржевых уведомлений: {scope_label}.",
        f"Время проверки: {sent_at}.",
    ]
    if settings.public_base_url:
        lines.extend(["", f"Интерфейс: {settings.public_base_url.rstrip('/')}/volumes/"])
    message.set_content("\n".join(lines))
    message.add_alternative(
        "<html><body><h2>Проверка почтовых уведомлений MOEX</h2>"
        "<p>Если вы получили это письмо, подключение к SMTP и адрес получателя работают.</p>"
        f"<p>Область биржевых уведомлений: <strong>{html.escape(scope_label)}</strong>.</p>"
        f"<p>Время проверки: {html.escape(sent_at)}.</p></body></html>",
        subtype="html",
    )
    _send_message(settings, message)
