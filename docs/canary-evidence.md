# Canary observability and evidence

Начиная с v0.23.0 приложение сохраняет forward-only evidence о том, какой consensus **фактически применялся** к configured canary ticker между monitoring snapshots.

Цель слоя — ответить на вопросы, которые нельзя надёжно решить одним historical backtest:

- сколько времени weighted реально оставался активным;
- сколько времени runtime safety переводил ticker обратно в median;
- сколько было отдельных fallback incidents;
- сколько fallback завершились recovery обратно в weighted;
- какие guards чаще всего вызывали fallback;
- насколько длинными были непрерывные стабильные weighted-периоды;
- что реально происходило с median / weighted / active target и expected return.

Этот слой **не расширяет canary и не меняет production policy**. Он только собирает evidence для последующего ручного решения.

## Где хранится evidence

Migration v0.23.0 создаёт:

```text
canary_evidence_snapshots
```

Каждая строка содержит только безопасные ticker-level агрегаты:

```text
ticker
target_year
captured_at
canary_enabled
in_allowlist
configured_mode
effective_mode
active_available
safety_status
fallback_reason
sources
current_price
median_target_price
weighted_target_price
active_target_price
median_expected_return_percent
weighted_expected_return_percent
active_expected_return_percent
```

Таблица **не содержит**:

- `analyst_name`;
- source identity;
- source-level forecasts;
- source-level weights;
- SMTP/recipient data.

## Capture cadence

Canary evidence не получает отдельный scheduler.

Она снимается внутри существующего shadow monitoring cycle:

```text
forecast sync
    ↓
shadow snapshot
    ↓
drift state / notification transition
    ↓
canary evidence snapshot
```

По умолчанию monitoring cycle работает раз в 6 часов с уже существующим 15-минутным offset относительно forecast sync.

Это важно: shadow state, drift classification и фактически применённый Active consensus относятся к одному operational cycle.

Retention переиспользует:

```dotenv
SHADOW_HISTORY_RETENTION_DAYS=730
```

Новых обязательных `.env` параметров для v0.23.0 нет.

## Forward-only принцип

История **не backfill-ится** из данных до установки v0.23.0.

Причина: до появления `Active consensus` нельзя надёжно восстановить, какой runtime guard фактически был бы применён в тот момент. Попытка реконструкции могла бы внести hindsight bias.

Поэтому первая настоящая точка evidence появляется в первом shadow monitoring cycle после обновления до v0.23.0.

## Режимы

Сохраняются одновременно configured и effective mode.

### Median

```text
configured_mode = median
effective_mode  = median
```

Canary выключен либо ticker не находится в активном canary режиме.

### Weighted canary

```text
configured_mode = weighted_canary
effective_mode  = weighted
```

Weighted разрешён и все runtime guards проходят.

### Median fallback

```text
configured_mode = weighted_canary
effective_mode  = median
fallback_reason = <guard reason>
```

Canary настроен на weighted, но runtime safety автоматически демотировал ticker обратно в median.

## Fallback reasons

Сохраняется причина, которую возвращает Active consensus. Основные значения:

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

Это operational reason, а не инвестиционный сигнал.

## Time-weighted uptime

Uptime считается не по числу строк, а по реальному времени между соседними snapshot.

Например:

```text
00:00 weighted
02:00 weighted
08:00 fallback
10:00 weighted
14:00 weighted
```

Интервалы относятся к состоянию **предыдущей** точки:

```text
00:00 → 02:00   weighted  2h
02:00 → 08:00   weighted  6h
08:00 → 10:00   fallback  2h
10:00 → 14:00   weighted  4h
```

Итого:

```text
configured weighted time = 14h
weighted time            = 12h
fallback time            =  2h
weighted uptime          = 85.7%
```

Длительность последней точки **не экстраполируется** от последнего snapshot до текущего времени. Это предотвращает завышение uptime при остановившемся worker.

## Target-year boundary

Переход между прогнозными годами не считается непрерывным canary-периодом.

Например:

```text
2027 fallback
2028 weighted
```

не создаёт ложный `recovery`.

Duration также не переносится через границу `target_year`.

## Fallback incident

Fallback incident считается при входе в состояние:

```text
configured = weighted_canary
effective  = median
```

Повторные snapshot того же непрерывного fallback не увеличивают incident count.

`fallback_reason_counts` считается по входам в incident, а не по количеству строк.

## Recovery

Recovery учитывается только если:

1. предыдущая точка была fallback;
2. новая точка снова `effective_mode=weighted`;
3. обе точки относятся к одному `target_year`;
4. canary был непрерывно configured как `weighted_canary`.

Disable/rollback и новый target year не создают recovery.

## Метрики per ticker

`GET /api/analytics/consensus-canary/evidence/ticker` возвращает:

```text
snapshots
target_years
history_span_hours
configured_weighted_hours
weighted_hours
fallback_hours
weighted_uptime_percent
fallback_incidents
recoveries
longest_weighted_run_hours
longest_fallback_run_hours
fallback_reason_counts
current_* mode/status/target/return
```

## Глобальный evidence overview

```http
GET /api/analytics/consensus-canary/evidence?days=30
```

Возвращает:

- configured tickers;
- tickers with evidence;
- total snapshots;
- total configured weighted time;
- total weighted/fallback time;
- time-weighted portfolio canary uptime;
- fallback incidents;
- recoveries;
- сколько tickers сейчас `WEIGHTED`, `FALLBACK`, `MEDIAN`;
- median history span;
- breakdown по каждому ticker.

Fallback tickers сортируются выше остальных.

## История snapshot

```http
GET /api/analytics/consensus-canary/evidence/history?ticker=SBER&days=30
```

Возвращает chronological forward timeline выбранного ticker.

## Manual capture

Для диагностики из local scope доступен:

```http
POST /api/analytics/consensus-canary/evidence/capture
```

Обычная эксплуатация не требует ручного capture — worker делает это автоматически.

## Analytics UI

На `/analytics/` добавлены два представления.

### Canary observability

Глобальный блок рядом с Production Impact показывает:

- weighted uptime;
- current weighted/fallback counts;
- fallback incidents;
- recoveries;
- median observation span;
- breakdown по ticker;
- fallback reason counts.

Окно можно переключать между 1 / 7 / 30 / 90 днями.

### Canary timeline

После выбора ticker рядом с Active consensus показываются:

- weighted uptime;
- configured canary time;
- fallback time;
- incident/recovery counts;
- longest weighted run;
- последние snapshot с `active / median / weighted target`;
- fallback reason.

## Privacy

Evidence endpoints публично безопасны для read-only internet mode, потому что содержат только агрегированное ticker-level operational state.

Local-only остаётся только manual capture.

## Что v0.23.0 НЕ делает

v0.23.0 не меняет:

```text
global median default
maximum allowlist = 5
canary enable policy
runtime safety thresholds
weighting formula
current Watchlist
stock_rows
volume monitor
shadow drift thresholds
notification state machine
```

Также нет автоматического решения вида:

```text
uptime > X → expand canary
```

Сначала нужно накопить реальную forward history. Критерии расширения canary должны быть отдельным, явно документированным engineering decision.

## Runbook после deployment

Проверить версию:

```bash
cd /home/krapa/moex
cat VERSION
```

Ожидаемо:

```text
0.23.0
```

Проверить evidence overview:

```bash
curl 'http://127.0.0.1:18000/api/analytics/consensus-canary/evidence?days=30'
```

Проверить ticker:

```bash
curl 'http://127.0.0.1:18000/api/analytics/consensus-canary/evidence/ticker?ticker=SBER&days=30'
```

Проверить timeline:

```bash
curl 'http://127.0.0.1:18000/api/analytics/consensus-canary/evidence/history?ticker=SBER&days=30'
```

При необходимости выполнить диагностический capture:

```bash
curl -X POST \
  -H 'X-Moex-Access-Scope: local' \
  http://127.0.0.1:18000/api/analytics/consensus-canary/evidence/capture
```

После первого capture нормальна короткая история и отсутствие time-weighted uptime: для duration нужны минимум две точки одного target year.
