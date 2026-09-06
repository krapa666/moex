# Stateful shadow drift notifications

## Назначение

С v0.20.0 forward shadow monitoring умеет отправлять email не по каждому шестичасовому snapshot, а только при значимых **переходах состояния** drift.

Это operational model-monitoring. Уведомления:

- не являются торговым сигналом;
- не меняют production consensus;
- не изменяют fair value, expected return или Watchlist;
- используют тот же `stable / watch / alert / insufficient` classifier и те же thresholds, что детальный drift API и global overview.

По умолчанию рассылка выключена.

## Где выполняется обработка

`arsagera-worker` после каждого планового shadow capture выполняет один monitoring-cycle:

```text
forecast/source sync
        ↓
shadow history capture
        ↓
current global drift classification
        ↓
compare with persisted per-ticker state
        ↓
create transition events
        ↓
deliver eligible events as one email digest
```

Startup-cycle выполняется после startup-синхронизаций источников и initial shadow snapshot.

## Persistence

Миграция `0022_shadow_drift_notifications` добавляет две таблицы.

### `shadow_drift_states`

Текущее operational-состояние каждого ticker:

- `ticker`;
- `target_year`;
- текущий `status`;
- `observed_at`;
- `changed_at`;
- `last_notified_at`;
- `incident_notified`.

`incident_notified` нужен, чтобы recovery-письмо отправлялось только для инцидента, о котором пользователь действительно был уведомлён.

### `shadow_drift_notification_events`

Append-only ledger переходов и попыток доставки:

- ticker / target year;
- from/to status;
- transition kind;
- время наблюдения;
- aggregate weighted-vs-median delta;
- drift reasons;
- delivery status/reason;
- число попыток;
- время последней попытки/успешной отправки;
- диагностическая ошибка доставки.

Публичный event API не возвращает текст SMTP-ошибки и не раскрывает credentials или recipient.

## State machine

### Bootstrap

Первое состояние тикера только фиксируется:

```text
unknown → current
```

Письмо **не отправляется**. Это предотвращает flood после установки v0.20.0 или создания новой БД.

### Переходы, которые создают письмо

```text
STABLE → WATCH     notification, subject to cooldown
STABLE → ALERT     immediate notification
WATCH  → ALERT     immediate escalation notification
WATCH  → STABLE    recovery, если incident ранее был отправлен
ALERT  → STABLE    recovery, если incident ранее был отправлен
```

### Переходы без письма

```text
WATCH → WATCH       no event / no mail
ALERT → ALERT       no event / no mail
STABLE → STABLE     no event / no mail
ALERT → WATCH       event only; это ещё не full recovery
* → insufficient    event only
insufficient → *    event only
```

`ALERT → WATCH` не считается recovery: модель всё ещё требует внимания. Full recovery наступает только при `STABLE`.

### Смена target year

При rollover прогнозного года state reset записывается как отдельный event:

```text
transition_kind = target_year_reset
```

Письмо не отправляется. Это защищает от ложного alert/recovery на естественной смене горизонта.

## Cooldown

По умолчанию:

```dotenv
SHADOW_NOTIFICATION_COOLDOWN_HOURS=24
```

Cooldown применяется к повторному входу `STABLE → WATCH`, если по этому ticker недавно уже отправлялось уведомление.

Escalation в `ALERT` cooldown не блокирует:

```text
WATCH → ALERT
STABLE → ALERT
```

Recovery также не блокируется cooldown, если предыдущий actionable incident действительно был отправлен.

## Delivery retry и supersede

Eligible transition сначала получает:

```text
delivery_status = pending
```

При SMTP-ошибке:

```text
delivery_status = failed
```

и событие может быть повторено на следующем monitoring-cycle до:

```dotenv
SHADOW_NOTIFICATION_MAX_ATTEMPTS=5
```

Перед retry проверяется, что текущие `target_year` и drift-status всё ещё соответствуют событию.

Если состояние успело измениться, старое письмо больше не отправляется:

```text
delivery_status = superseded
reason = state_changed_before_delivery
```

## Disabled/configuration states

Default:

```dotenv
SHADOW_NOTIFICATIONS_ENABLED=false
```

Даже при выключенной рассылке state machine продолжает фиксировать текущее состояние и переходы. Would-be notification получает `suppressed`, поэтому после будущего включения не возникает ретроспективной рассылки старых событий.

Если рассылка включена, но SMTP/recipient не настроены, transition сохраняется как suppressed с причиной `delivery_not_configured`.

## SMTP configuration

Shadow notifications переиспользуют существующие **SMTP credentials/transport parameters** volume monitor, но имеют независимый feature-toggle.

Для shadow delivery **не требуется** `VOLUME_SMTP_ENABLED=true`: эта переменная управляет volume-mailing и не должна включаться только ради shadow notifications.

Нужны SMTP transport values:

```dotenv
VOLUME_SMTP_HOST=smtp.example.com
VOLUME_SMTP_PORT=587
VOLUME_SMTP_USERNAME=<smtp-user>
VOLUME_SMTP_PASSWORD=<smtp-secret>
VOLUME_SMTP_FROM=<verified-sender@example.com>
VOLUME_SMTP_STARTTLS=true
VOLUME_SMTP_SSL=false
VOLUME_PUBLIC_BASE_URL=https://moex.junnylab.ru
```

Shadow-specific settings:

```dotenv
SHADOW_NOTIFICATIONS_ENABLED=true
SHADOW_NOTIFICATION_EMAIL=<recipient@example.com>
SHADOW_NOTIFICATION_COOLDOWN_HOURS=24
SHADOW_NOTIFICATION_HISTORY_DAYS=30
SHADOW_NOTIFICATION_MAX_ATTEMPTS=5
```

Если `SHADOW_NOTIFICATION_EMAIL` пуст, используется `VOLUME_NOTIFICATION_EMAIL`.

`VOLUME_SMTP_ENABLED` можно оставить `false`, если volume-monitor email не нужен.

Secrets и реальные адреса получателей должны находиться только в локальном `.env`.

## Email content

Один monitoring-cycle формирует один digest по всем eligible transitions.

Письмо содержит только безопасные aggregate данные:

- ticker;
- переход состояния;
- weighted-vs-median delta;
- operational drift reasons;
- ссылку на Analytics при настроенном `VOLUME_PUBLIC_BASE_URL`.

Не включаются analyst/source identities, source-level forecasts/weights или SMTP credentials.

## API

Публичный безопасный status:

```http
GET /api/analytics/shadow-consensus/notifications/status
```

Возвращает только operational configuration state:

- enabled/configured;
- SMTP configured yes/no;
- recipient configured yes/no;
- cooldown/history window;
- pending/failed counts;
- last event/sent timestamps.

Адрес получателя и SMTP credentials не возвращаются.

Публичный event ledger:

```http
GET /api/analytics/shadow-consensus/notifications/events?limit=50
```

Возвращает transition/delivery metadata без SMTP error text.

Local-only test:

```http
POST /api/analytics/shadow-consensus/notifications/test
X-Moex-Access-Scope: local
```

Test отправляет отдельное диагностическое письмо и не меняет drift state/event ledger.

## Analytics UI

В global shadow overview есть блок **«Уведомления о переходах drift»**.

Он показывает:

- выключена/настроена ли рассылка;
- cooldown;
- monitoring window;
- pending/failed count;
- время последнего успешного письма;
- последние transition events и delivery status.

Local admin при настроенном SMTP видит кнопку test email. Internet/read-only пользователь видит только безопасный operational status/event history.

## Deployment

v0.20.0 требует migration:

```text
0022_shadow_drift_notifications
```

Backend startup автоматически выполняет `alembic upgrade head`; ручной Alembic не требуется.

Для обычного обновления обязательных `.env`-изменений нет, потому что notifications выключены по умолчанию.

Чтобы фактически включить shadow email, настройте SMTP transport values и:

```dotenv
SHADOW_NOTIFICATIONS_ENABLED=true
```

После изменения `.env` перезапустите Compose через `./scripts/compose-up.sh`.

## Production boundary

В v0.20.0 production target price по-прежнему использует median consensus.

Notification layer является только observability-механизмом поверх shadow weighted evidence и ничего автоматически не promotes в production.
