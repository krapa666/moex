# Canary evidence capture health

Начиная с v0.24.0 приложение отдельно оценивает **качество самого потока canary evidence**.

Это необходимо, потому что хороший weighted uptime не является надёжным evidence, если worker пропускает capture cycles или давно не создавал snapshot.

Capture health является monitoring policy. Он **не** включает weighted автоматически, не расширяет canary allowlist и не является торговым сигналом.

## API

```http
GET /api/analytics/consensus-canary/evidence/health?days=30
```

Endpoint публично безопасен: он возвращает только ticker-level operational metadata и не содержит analyst/source names, source forecasts или individual weights.

## Expected cadence

Health использует тот же cadence, что существующий shadow/evidence monitoring cycle:

```dotenv
SHADOW_HISTORY_INTERVAL_HOURS=6
```

Если параметр не задан, используется 6 часов.

Отдельного scheduler для health нет. Он оценивает уже сохранённые `canary_evidence_snapshots`.

## Статусы

Возможны пять состояний:

```text
NOT_CONFIGURED
WARMING_UP
HEALTHY
DEGRADED
STALE
```

### NOT_CONFIGURED

В текущем persisted canary allowlist нет тикеров.

### WARMING_UP

Ticker configured, но ещё нет ни одного сопоставимого interval между двумя snapshot одного `target_year`.

Это нормальное состояние сразу после первого capture или после появления нового target-year series.

### HEALTHY

Одновременно выполняется:

- есть хотя бы один сопоставимый interval;
- последняя точка не старше `1.5 × expected cadence`;
- в выбранном окне не обнаружено вероятных пропусков capture cycle.

При cadence 6 часов freshness threshold равен 9 часам.

### DEGRADED

Хотя бы одно из условий:

- возраст последнего snapshot больше `1.5 × cadence`, но не больше `2.5 × cadence`;
- обнаружен capture gap не меньше `1.75 × cadence`.

Для cadence 6 часов:

```text
delayed after > 9h
probable missed-cycle gap >= 10.5h
```

### STALE

Последний snapshot старше:

```text
2.5 × expected cadence
```

Для стандартных 6 часов это более 15 часов.

`STALE` имеет приоритет над `WARMING_UP`: одна единственная точка возрастом 18 часов считается stale, а не «набирающей историю».

## Gap accounting

Gap считается только между соседними snapshot одного `target_year`.

Переход вида:

```text
2027 snapshot
2028 snapshot
```

не считается пропущенным monitoring cycle и не ухудшает continuity нового target-year series.

Вероятное число пропущенных циклов оценивается из отношения gap к expected cadence после прохождения `1.75×` threshold.

Это operational estimate, а не точный scheduler audit log.

## Continuity

Для ticker рассчитываются:

```text
observed_intervals
missed_cycles_estimate
continuity_percent
```

Формула:

```text
continuity = observed_intervals /
             (observed_intervals + missed_cycles_estimate) × 100%
```

Пример при cadence 6 часов:

```text
00:00 snapshot
12:00 snapshot
18:00 snapshot
```

Между 00:00 и 12:00 оценивается один пропущенный цикл. Поэтому:

```text
observed intervals = 2
missed cycles      = 1
continuity         = 66.7%
```

## Глобальный health overview

Response содержит:

- `status` — худший текущий status среди configured tickers;
- `expected_interval_hours`;
- configured/evidence ticker counts;
- `healthy_tickers`;
- `warming_up_tickers`;
- `degraded_tickers`;
- `stale_tickers`;
- fresh/delayed ticker counts;
- estimated missed cycles;
- gap violations;
- latest capture timestamp/age;
- longest observed gap;
- median continuity по tickers;
- per-ticker breakdown.

Приоритет глобального status:

```text
STALE
DEGRADED
WARMING_UP
HEALTHY
NOT_CONFIGURED
```

## Scope

Глобальный health оценивает только **текущий configured allowlist**.

Ticker, удалённый из allowlist, сохраняет historical evidence в БД, но больше не влияет на текущий capture health.

## Analytics UI

На `/analytics/` рядом с Canary Observability появляется блок **Capture health**.

Он показывает:

- общий status;
- expected cadence;
- latest capture age;
- median continuity;
- missed cycles estimate;
- gap violations;
- longest gap;
- per-ticker health/reasons.

Доступны окна:

```text
1 / 7 / 30 / 90 дней
```

## Важная граница

Capture health не изменяет:

```text
global median default
canary allowlist limit = 5
canary enable policy
runtime divergence/concentration guards
drift thresholds
weighting formula
Watchlist
stock_rows
volume monitor
notification state machine
```

Статус `HEALTHY` не означает, что weighted готов к расширению. Он означает только, что operational evidence stream достаточно свежий и непрерывный для дальнейшего анализа.

## Migration и конфигурация

v0.24.0 **не добавляет migration**.

Schema head остаётся:

```text
0024_canary_evidence
```

Новых обязательных `.env` переменных нет. Health использует существующий `SHADOW_HISTORY_INTERVAL_HOURS`.

## Проверка после deployment

```bash
cd /home/krapa/moex
cat VERSION
```

Ожидаемо:

```text
0.24.0
```

Проверить health:

```bash
curl 'http://127.0.0.1:18000/api/analytics/consensus-canary/evidence/health?days=30'
```

Сразу после первой точки `WARMING_UP` является нормальным результатом. Для `HEALTHY` нужен минимум один сопоставимый interval одного target year.
