# Shadow weighted consensus, readiness и forward monitoring

## Назначение

Начиная с v0.17.0 приложение рассчитывает accuracy-weighted consensus параллельно с median baseline.

Shadow-модель:

- видна в Analytics;
- сравнивается с медианой на реальных текущих прогнозах;
- не меняет source rows;
- не меняет текущий primary-table Watchlist;
- не переписывает persisted forecast values.

Эволюция evidence layer:

- v0.18.0 — forward-only shadow history;
- v0.19.0 — global drift overview;
- v0.20.0 — stateful drift notifications;
- v0.21.0 — Production Impact Simulator + promotion dossier;
- v0.22.0 — Controlled Canary, который может вручную применить weighted только к Active consensus небольшого allowlist.

`READY` и `READY_FOR_MANUAL_PROMOTION` сами по себе ничего не включают.

## Текущий target year

Shadow использует базовый год основной таблицы: `forecast_start_year`.

Для каждого source должны быть доступны:

- annual net profit forecast;
- P/E;
- shares.

```text
TargetPrice = NetProfit × P/E / Shares
```

Источник идентифицируется exact `analyst_name`. Минимум для shadow aggregation — два сопоставимых источника.

## Historical snapshot для весов

| Target year | Snapshot |
| --- | --- |
| будущий год | `pre_year` |
| текущий год до 1 июля | `pre_year` |
| текущий год с 1 июля | `mid_year` |
| прошедший год | `year_end` |

Training sample допускается только если:

1. fiscal year строго раньше target year;
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

Если historical training history недоступна:

```text
shadow weighted = arithmetic mean
```

Это neutral fallback для shadow/evidence. **Controlled Canary не считает такой equal-weight fallback полноценным production weighted**: enable/runtime требует исторические веса минимум по двум sources.

## Batch engine

Historical training context строится один раз на batch capture и переиспользуется для primary universe.

Single-ticker API:

```http
GET /api/analytics/shadow-consensus?ticker=SBER
```

## Forward shadow history

Таблица:

```text
shadow_consensus_snapshots
```

Хранятся только aggregate values:

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

Startup capture выполняется после startup source sync. Регулярный capture имеет phase offset, чтобы уменьшить риск mixed state.

History forward-only и не backfill-ится из старых revisions.

```http
GET /api/analytics/shadow-consensus/history?ticker=SBER&days=90
POST /api/analytics/shadow-consensus/capture   # local
```

## Drift monitoring

```http
GET /api/analytics/shadow-consensus/drift?ticker=SBER&days=30
```

Классификация начинается только при:

```text
>= 3 snapshots
>= 24 hours history одного target_year
```

Statuses:

```text
insufficient
stable
watch
alert
```

Signals:

1. weighted-vs-median target divergence;
2. divergence step;
3. max-weight concentration относительно equal weight;
4. relative movement gap weighted vs median;
5. training snapshot change.

Thresholds:

| Signal | WATCH | ALERT |
| --- | ---: | ---: |
| `abs(weighted vs median)` | `>= 10%` | `>= 20%` |
| `abs(delta step)` | `>= 5 pp` | `>= 10 pp` |
| weight concentration | `>= 1.5x` | `>= 1.75x` |
| `abs(relative movement gap)` | `>= 5 pp` | `>= 10 pp` |

Drift — operational policy, а не статистический тест или торговый сигнал.

## Global drift overview

```http
GET /api/analytics/shadow-consensus/overview?days=30
```

Universe = текущая primary table. Тикер без history остаётся видимым как `insufficient/no_history`.

Default order:

```text
ALERT → WATCH → STABLE → insufficient
```

## Stateful drift notifications

После каждого shadow capture worker запускает transition processor.

Persisted state:

```text
shadow_drift_states
shadow_drift_notification_events
```

Основная state machine:

```text
bootstrap               → без письма
STABLE → WATCH          → письмо с cooldown
STABLE → ALERT          → immediate alert
WATCH  → ALERT          → immediate escalation
WATCH/ALERT → STABLE    → recovery, если incident реально был notified
ALERT → WATCH           → event only
same status             → no event/mail
* ↔ insufficient        → event only
смена target_year       → reset event
```

Delivery по умолчанию выключен:

```dotenv
SHADOW_NOTIFICATIONS_ENABLED=false
```

Public safe:

```http
GET /api/analytics/shadow-consensus/notifications/status
GET /api/analytics/shadow-consensus/notifications/events?limit=50
```

Local-only test:

```http
POST /api/analytics/shadow-consensus/notifications/test
```

Подробнее: [`shadow-notifications.md`](shadow-notifications.md).

## Historical readiness

Readiness — historical evidence-policy из 11 gates.

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

```http
GET /api/analytics/consensus-backtest/robustness?snapshot=pre_year
GET /api/analytics/consensus-readiness?snapshot=pre_year
```

`READY` означает только выполнение historical evidence-policy.

## Production impact и promotion dossier

С v0.21.0:

```http
GET /api/analytics/production-impact?top_n=10&history_days=30
GET /api/analytics/promotion-dossier?top_n=10&history_days=30
```

Impact simulator измеряет target/return/rank/Top-N divergence и гипотетическую Watchlist-score sensitivity на одном comparable universe.

Promotion dossier добавляет forward coverage/stability и portfolio impact gates.

```text
NOT_READY
OBSERVE
READY_FOR_MANUAL_PROMOTION
```

Текущий `/watchlist/` основан на primary table №1, поэтому median/weighted Watchlist score из dossier — simulation, а не текущая production ranking.

Подробнее: [`production-impact.md`](production-impact.md).

## Controlled Canary

С v0.22.0 weighted может быть вручную применён только к **Active consensus** выбранных тикеров.

```http
GET  /api/analytics/consensus-canary
PUT  /api/analytics/consensus-canary                  # local
POST /api/analytics/consensus-canary/rollback         # local
GET  /api/analytics/consensus-canary/events           # local
GET  /api/analytics/active-consensus?ticker=SBER
```

Canary defaults:

```text
enabled = false
max allowlist = 5
```

Enable требует:

```text
promotion dossier = READY_FOR_MANUAL_PROMOTION
shadow available
historical weighting >= 2 sources
live divergence < 10%
live concentration < 1.5x
forward drift = STABLE
```

Runtime повторяет guards. Если configured ticker перестаёт проходить safety:

```text
configured_mode = weighted_canary
effective_mode  = median
fallback_reason = ...
```

Это fail-safe демоция. Автоматического promotion или расширения allowlist нет.

Подробнее: [`consensus-canary.md`](consensus-canary.md).

## Analytics UI

Без выбора тикера доступны global shadow overview, notifications и Production Impact Dashboard.

Local admin в v0.22.0 также видит Controlled Canary controls и audit trail.

После выбора ticker показываются:

- analyst consensus baseline;
- Active consensus effective mode;
- current shadow weighted;
- forward history/drift.

## Database

Текущий schema head:

```text
0023_consensus_canary
```

- `0021_shadow_consensus_snapshots` — forward history;
- `0022_shadow_drift_notifications` — notification state/event ledger;
- `0023_consensus_canary` — persisted canary state и audit events.

Backend startup выполняет Alembic upgrade автоматически.

## Production boundary

Median остаётся fail-safe default.

v0.22.0 может изменить только Active consensus выбранного canary ticker. Не изменяются:

- source analyst tables;
- primary-table fair-value fields;
- persisted expected-return fields;
- текущий primary-table Watchlist;
- volume monitor;
- weighting defaults;
- readiness gates;
- drift thresholds;
- notification state machine.

Rollback выключает canary state и немедленно возвращает Active consensus к median.
