# Controlled consensus canary

## Назначение

Начиная с v0.22.0 приложение умеет вручную переводить небольшой allowlist тикеров с median consensus на accuracy-weighted consensus в режиме controlled canary.

Canary не является автоматическим продолжением readiness/promotion dossier. Оператор должен явно включить его из local scope.

Базовое правило:

```text
canary disabled                -> median
canary enabled, ticker outside -> median
canary enabled, ticker inside  -> weighted только если safety guards PASS
safety guard fails             -> median fallback
manual rollback                -> median немедленно для всего allowlist
```

## Production boundary

Canary влияет только на **Active consensus**:

```http
GET /api/analytics/active-consensus?ticker=SBER
```

Он не переписывает:

- `stock_rows`;
- прогнозы аналитиков;
- `forecast_price_year*` отдельных source rows;
- `upside_percent_year*` отдельных source rows;
- текущую страницу `/watchlist/`, которая использует primary table №1;
- volume monitor;
- historical revisions.

Таким образом rollback не требует пересчёта/восстановления прогнозных данных: достаточно выключить canary state.

## Persisted state

Таблица:

```text
consensus_canary_settings
```

Хранит singleton state:

- `enabled`;
- allowlist `tickers`;
- `updated_by`;
- `updated_at`.

Максимальный allowlist:

```text
5 тикеров
```

По умолчанию после migration:

```text
enabled = false
allowlist = []
```

Никакой `.env` feature flag не требуется: control plane хранится в БД, а write API доступен только local scope.

## Audit trail

Каждое изменение сохраняется в:

```text
consensus_canary_events
```

Event содержит:

- `occurred_at`;
- `action`;
- previous/new enabled state;
- previous/new allowlist;
- local actor;
- optional operator note;
- promotion status при enable.

Actions:

```text
configure
reconfigure
enable
disable
rollback
```

Audit endpoint local-only:

```http
GET /api/analytics/consensus-canary/events?limit=50
```

## Требования для enable

`PUT /api/analytics/consensus-canary` с `enabled=true` проходит fail-closed validation.

### 1. Promotion dossier

Общий статус должен быть:

```text
READY_FOR_MANUAL_PROMOTION
```

`OBSERVE` и `NOT_READY` блокируют enable.

### 2. Universe

Каждый выбранный ticker должен существовать в текущей primary table.

### 3. Реальные historical weights

Для каждого canary ticker:

```text
shadow_available = true
weighting_uses_history = true
sources_with_training_history >= 2
```

Если weighting фактически является neutral equal-weight fallback, canary не включается.

### 4. Live divergence guard

Текущий weighted-vs-median target divergence должен оставаться ниже WATCH threshold:

```text
abs(weighted_vs_median_target_delta_percent) < 10%
```

Неизвестное значение также блокирует canary.

### 5. Live concentration guard

Текущая max source weight concentration относительно equal-weight baseline должна быть ниже WATCH threshold:

```text
max_weight / equal_weight < 1.5x
```

Неизвестная концентрация также блокирует canary.

### 6. Forward drift

Текущий forward drift status каждого canary ticker должен быть:

```text
STABLE
```

`WATCH`, `ALERT` и `insufficient` блокируют enable.

## Runtime safety

Enable-time gates недостаточны: данные меняются после включения.

Поэтому каждый запрос Active consensus для canary ticker заново проверяет:

1. shadow weighted доступен;
2. есть historical weighting минимум по двум sources;
3. live divergence ниже WATCH;
4. live weight concentration ниже WATCH;
5. forward drift остаётся `STABLE`.

Если любой guard не проходит:

```text
configured_mode = weighted_canary
effective_mode  = median
fallback_reason = <причина>
```

Это автоматическая **демоция**, а не автоматическое promotion.

Possible fallback reasons:

```text
shadow_unavailable
insufficient_weight_history
live_divergence_unknown
live_divergence_watch
live_weight_concentration_unknown
live_weight_concentration_watch
drift_insufficient
drift_watch
drift_alert
```

## Active consensus return

Median expected return берётся только по тем же source rows, у которых есть сопоставимая target price выбранного target year.

Weighted scenario меняет только price-target layer. Dividend contribution фиксируется на median baseline, как в Production Impact Simulator:

```text
MedianReturn = MedianPricePotential + DividendLayer

WeightedReturn = WeightedPricePotential + same DividendLayer
```

Это не смешивает изменение aggregator и изменение dividend model.

## API

### Public safe status

```http
GET /api/analytics/consensus-canary
```

Возвращает:

- enabled;
- allowlist ticker symbols;
- max allowlist size;
- safety policy;
- updated timestamp.

Не возвращает analyst/source identity или source weights.

### Local configure/enable/disable

```http
PUT /api/analytics/consensus-canary
X-Moex-Access-Scope: local
Content-Type: application/json

{
  "enabled": true,
  "tickers": ["SBER", "LKOH"],
  "note": "manual canary after promotion gates"
}
```

При нарушении policy API возвращает `409` и не меняет persisted state.

### Local rollback

```http
POST /api/analytics/consensus-canary/rollback
X-Moex-Access-Scope: local
Content-Type: application/json

{
  "note": "manual rollback"
}
```

Rollback разрешён независимо от текущего promotion status и не очищает allowlist: он только выключает active canary, чтобы можно было позже повторно оценить тот же набор.

### Active consensus

```http
GET /api/analytics/active-consensus?ticker=SBER
```

Ключевые поля:

```text
configured_mode
effective_mode
safety_status
fallback_reason
median_target_price
weighted_target_price
active_target_price
median_expected_return_percent
weighted_expected_return_percent
active_expected_return_percent
```

## Analytics UI

Production Impact Dashboard содержит блок **Controlled canary**.

Internet/read-only user видит:

- enabled/disabled state;
- текущий allowlist;
- safety policy.

Local admin дополнительно получает:

- allowlist input;
- audit note;
- `Сохранить выключенным`;
- `Включить canary`;
- `Rollback → median`;
- последние audit events.

После выбора тикера отдельная карточка **Active consensus** показывает именно effective mode:

```text
MEDIAN
WEIGHTED CANARY
MEDIAN FALLBACK
```

Это специально отделено от блока analyst consensus, который продолжает показывать исходный диапазон source targets и median baseline.

## Runbook включения

1. Открыть `/analytics/` из local scope.
2. Проверить Promotion Decision Dashboard.
3. Убедиться, что статус `READY FOR MANUAL PROMOTION`.
4. Выбрать 1–5 тикеров с достаточной историей.
5. Ввести allowlist и audit note.
6. Нажать `Включить canary`.
7. Убедиться, что global badge показывает `ENABLED`.
8. Открыть каждый выбранный ticker.
9. Проверить карточку Active consensus:
   - `WEIGHTED CANARY` — weighted реально применяется;
   - `MEDIAN FALLBACK` — safety guard уже демотировал ticker.
10. Продолжать наблюдение за shadow drift/notifications.

## Runbook rollback

UI:

```text
Analytics -> Production Impact Simulator -> Controlled canary -> Rollback -> median
```

API/CLI через локальный backend:

```bash
curl -X POST \
  -H 'X-Moex-Access-Scope: local' \
  -H 'Content-Type: application/json' \
  -d '{"note":"manual rollback"}' \
  http://127.0.0.1:18000/api/analytics/consensus-canary/rollback
```

Проверить:

```bash
curl http://127.0.0.1:18000/api/analytics/consensus-canary
```

Ожидается:

```json
{"enabled":false,...}
```

После rollback любой ticker получает `effective_mode=median`.

## Database migration

v0.22.0 добавляет:

```text
0023_consensus_canary
```

Таблицы:

```text
consensus_canary_settings
consensus_canary_events
```

Backend startup автоматически выполняет `alembic upgrade head`.

## Что canary не делает

- не включает weighted автоматически;
- не расширяет allowlist автоматически;
- не игнорирует promotion dossier;
- не разрешает equal-weight fallback как production weighted;
- не продолжает weighted при WATCH/ALERT;
- не меняет текущий Watchlist;
- не удаляет median baseline;
- не хранит source identities в публичном API.
