# Shadow weighted consensus, readiness и forward monitoring

## Назначение

Начиная с v0.17.0 приложение рассчитывает accuracy-weighted consensus **параллельно** с production median.

Shadow-модель:

- видна в Analytics;
- сравнивается с текущей медианой на реальных текущих прогнозах;
- не изменяет production fair value;
- не изменяет Watchlist;
- не изменяет expected return/ranking;
- не изменяет persisted forecast values.

С v0.18.0 shadow сохраняется как forward-only monitoring history, с v0.19.0 агрегируется по всему primary universe, а с v0.20.0 значимые drift transitions могут создавать stateful email-уведомления.

Даже `READY` и наличие стабильного forward-monitoring не переключают production consensus автоматически.

## Текущий target year

Shadow использует тот же базовый год, что production consensus: `forecast_start_year` основной таблицы.

В расчёт попадают источники, у которых для этого года доступны одновременно:

- forecast annual net profit;
- P/E;
- shares.

Для каждого источника:

```text
TargetPrice = NetProfit × P/E / Shares
```

Источник идентифицируется exact `analyst_name`, как и в accuracy/backtest. Минимум для shadow aggregation — два сопоставимых источника.

## Historical snapshot для весов

| Target year | Snapshot |
| --- | --- |
| будущий год | `pre_year` |
| текущий год до 1 июля | `pre_year` |
| текущий год с 1 июля | `mid_year` |
| прошедший год | `year_end` |

Training sample допускается только если:

1. его fiscal year строго раньше текущего target year;
2. у канонического факта известен `reported_at`;
3. `reported_at < as_of`.

Факт без даты публикации не обучает текущий weight.

## Weighting

Default policy:

```text
shrinkage_samples = 5
error_floor_percent = 5
relative_score_cap = 2
```

Если historical training history недоступна, веса становятся равными:

```text
shadow weighted = arithmetic mean
```

Это neutral fallback.

## Batch engine

С v0.18.0 historical training context строится один раз на capture-run и переиспользуется для всех тикеров primary table.

Single-ticker API сохраняется:

```http
GET /api/analytics/shadow-consensus?ticker=SBER
```

## Forward shadow history

Таблица:

```text
shadow_consensus_snapshots
```

Хранятся только безопасные aggregate values:

- ticker / target year / training snapshot / captured_at;
- source/training coverage counts;
- min/max source weight без source identity;
- median/weighted net profit;
- median/weighted target price;
- weighted-vs-median delta;
- current price;
- median/weighted market gap.

Не сохраняются реальные `analyst_name`, source-level forecasts или source-level weights.

### Capture schedule

```dotenv
SHADOW_HISTORY_ENABLED=true
SHADOW_HISTORY_INTERVAL_HOURS=6
SHADOW_HISTORY_RUN_ON_STARTUP=true
SHADOW_HISTORY_RETENTION_DAYS=730
```

Startup capture выполняется после startup source sync. Регулярный capture имеет 15-minute phase offset относительно source-sync phase, чтобы уменьшить риск mixed state.

История начинается только после развёртывания v0.18.0. Backfill из старых `forecast_revisions` намеренно отсутствует, потому что реконструкция старого source set/training knowledge могла бы внести hindsight bias.

History API:

```http
GET /api/analytics/shadow-consensus/history?ticker=SBER&days=90
```

Local-only manual capture:

```http
POST /api/analytics/shadow-consensus/capture
```

## Drift monitoring

```http
GET /api/analytics/shadow-consensus/drift?ticker=SBER&days=30
```

Drift означает operational divergence shadow weighted от median baseline, а не статистически доказанный model/data drift.

Классификация начинается только при:

```text
>= 3 snapshots
>= 24 hours history одного target_year
```

До этого status = `insufficient`.

### Signals

1. current weighted-vs-median target divergence;
2. divergence step к предыдущему snapshot;
3. max-weight concentration относительно equal weight;
4. relative movement gap weighted vs median;
5. training snapshot change.

### Thresholds

| Signal | WATCH | ALERT |
| --- | ---: | ---: |
| `abs(weighted vs median)` | `>= 10%` | `>= 20%` |
| `abs(delta step)` | `>= 5 pp` | `>= 10 pp` |
| weight concentration | `>= 1.5x` | `>= 1.75x` |
| `abs(relative movement gap)` | `>= 5 pp` | `>= 10 pp` |

Training snapshot change добавляет WATCH reason, если более сильного ALERT нет.

Statuses:

- `insufficient`;
- `stable`;
- `watch`;
- `alert`.

## Global drift overview

С v0.19.0:

```http
GET /api/analytics/shadow-consensus/overview?days=30
```

Overview использует **тот же classifier и thresholds**, что per-ticker drift. Второго drift algorithm нет.

Universe = текущая primary table. Тикер без history остаётся видимым:

```text
status = insufficient
reason = no_history
```

Сводка содержит universe size, history/classified coverage, status counts и `actionable = alert + watch`.

Backend batch-loads latest/window snapshots и избегает N+1 query pattern.

Default order:

```text
ALERT → WATCH → STABLE → insufficient
```

Внутри статуса — по убыванию absolute current divergence.

## Stateful drift notifications

С v0.20.0 после каждого shadow capture worker запускает transition processor.

Persisted state:

```text
shadow_drift_states
```

Append-only transition/delivery ledger:

```text
shadow_drift_notification_events
```

Notification engine **не определяет drift заново**: он получает уже классифицированные `stable/watch/alert/insufficient` states из существующего global overview.

### State machine

```text
bootstrap               → без письма
STABLE → WATCH          → письмо, subject to cooldown
STABLE → ALERT          → immediate alert
WATCH  → ALERT          → immediate escalation
WATCH  → STABLE         → recovery, только если incident реально был notified
ALERT  → STABLE         → recovery, только если incident реально был notified
ALERT  → WATCH          → event only; это ещё не full recovery
same status             → no new event / no mail
* ↔ insufficient        → event only
смена target_year       → reset event / no mail
```

Bootstrap без письма предотвращает flood после deployment. Target-year reset также не считается model incident.

### Cooldown

Default:

```dotenv
SHADOW_NOTIFICATION_COOLDOWN_HOURS=24
```

Cooldown применяется к repeated re-entry `STABLE → WATCH`, но не блокирует escalation в ALERT или валидный recovery.

### Delivery retry

SMTP failure сохраняется как `failed`. Retry выполняется на следующем monitoring-cycle до:

```dotenv
SHADOW_NOTIFICATION_MAX_ATTEMPTS=5
```

Перед retry проверяется, что event всё ещё соответствует current target year/status. Устаревший event становится `superseded` и не отправляется.

### Enable/configuration

Default:

```dotenv
SHADOW_NOTIFICATIONS_ENABLED=false
```

Даже при disabled delivery state ledger продолжает обновляться. Would-be notifications сохраняются как suppressed и не отправляются ретроспективно после включения.

SMTP переиспользует `VOLUME_SMTP_*`. Recipient задаётся через `SHADOW_NOTIFICATION_EMAIL` или fallback `VOLUME_NOTIFICATION_EMAIL`.

Полная конфигурация/state-machine/runbook: [`shadow-notifications.md`](shadow-notifications.md).

### Notification API

Public safe:

```http
GET /api/analytics/shadow-consensus/notifications/status
GET /api/analytics/shadow-consensus/notifications/events?limit=50
```

Local-only test:

```http
POST /api/analytics/shadow-consensus/notifications/test
```

Public API не раскрывает recipient, SMTP credentials/error text, source names, source forecasts или source weights.

## Analytics UI

Global panel отображается без выбора тикера и показывает coverage/status table.

После выбора тикера показываются current shadow и forward history/drift.

С v0.20.0 global panel также показывает notification mode, cooldown, pending/failed count, last sent timestamp и recent transition events. Local admin при configured SMTP получает кнопку test email.

## Readiness gate

Readiness — historical evidence-policy, а не feature flag.

| Gate | Requirement |
| --- | ---: |
| Historical observations | `>= 30` |
| Tickers | `>= 10` |
| Fiscal years | `>= 3` |
| Median-sMAPE improvement | `>= +1.0 pp` |
| Mean-sMAPE improvement | `> 0 pp` |
| Positive ticker slices | `>= 60%` |
| Positive year slices | `>= 66.7%` |
| Leave-one-ticker-out preserves | `>= 80%` |
| Leave-one-year-out preserves | `>= 80%` |
| Positive parameter cases | `>= 80%` |
| Worst parameter-grid median delta | `> 0 pp` |

API:

```http
GET /api/analytics/consensus-backtest/robustness?snapshot=pre_year
GET /api/analytics/consensus-readiness?snapshot=pre_year
```

`READY` означает только выполнение current evidence-policy.

## Database

Current schema head начиная с v0.20.0:

```text
0022_shadow_drift_notifications
```

`0021_shadow_consensus_snapshots` хранит forward history; `0022` добавляет notification state/event ledger.

Backend startup выполняет Alembic upgrade автоматически.

## Production boundary

v0.20.0 **не меняет**:

- production median consensus;
- fair-value formulas;
- expected-return calculations;
- Watchlist ranking;
- volume monitor;
- weighting defaults;
- readiness gates;
- drift thresholds.

Forward history, overview и notifications остаются evidence/observability layer перед любым отдельным решением о production promotion.
