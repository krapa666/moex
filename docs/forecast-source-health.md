# Forecast Source Health & Data Quality

Начиная с v0.25.0 приложение строит operational health по автоматическим прогнозным источникам поверх уже существующей истории `forecast_source_runs`.

Цель слоя — быстро отвечать на вопросы:

- был ли источник недавно успешно синхронизирован;
- не задержался ли очередной запуск относительно собственного расписания;
- не завершился ли последний запуск exception-ошибкой;
- не стал ли запуск частичным;
- не упало ли покрытие тикеров относительно собственной недавней истории источника;
- сколько успешных, частичных и failed-запусков было за выбранное окно;
- есть ли серия последовательных failures или successes.

Health не оценивает инвестиционное качество прогноза и не заменяет `source-accuracy`. Это слой качества доставки входных данных.

## Источник данных

Новая таблица для v0.25.0 не создаётся.

Health использует существующую:

```text
forecast_source_runs
```

Каждая запись уже содержит:

```text
source_key
analyst_name
started_at
finished_at
status
tickers_total
tickers_mapped
tickers_updated
tickers_unchanged
tickers_skipped
error_details
error_message
```

Schema head поэтому остаётся:

```text
0024_canary_evidence
```

## Какие источники считаются активными

Backend использует ту же конфигурацию, что и `arsagera-worker`:

- Арсагера — всегда включена;
- ДОХОДЪ — если `DOHOD_ENABLED=true`;
- fin-vista — если `FINVISTA_ENABLED=true`;
- Published Sheets — каждая запись из `FORECAST_SHEETS_SOURCES_JSON`.

Для health в backend через Compose передаются уже существующие параметры source name / enabled / interval. Новых обязательных `.env` параметров нет.

## Expected cadence

Freshness рассчитывается относительно реального interval конкретного источника:

```text
Арсагера          ARSAGERA_SYNC_INTERVAL_HOURS
Published Sheets  FORECAST_SHEETS_SYNC_INTERVAL_HOURS
ДОХОДЪ            DOHOD_SYNC_INTERVAL_HOURS
fin-vista         FINVISTA_SYNC_INTERVAL_HOURS
```

Все значения по умолчанию — 6 часов.

Operational thresholds:

```text
fresh / normal       <= 1.5 × cadence
DEGRADED delay       >  1.5 × cadence
STALE                >  2.5 × cadence
```

Для cadence 6 часов:

```text
normal through 9h
DEGRADED after 9h
STALE after 15h
```

Возраст считается от последнего **завершённого** запуска. Текущая строка `running` не стирает состояние предыдущего завершённого запуска; UI отдельно показывает, что новый sync уже выполняется.

## Health states

### HEALTHY

Последний завершённый запуск:

- не `failed`;
- не `partial`;
- достаточно свежий;
- не имеет подтверждённого существенного падения coverage относительно собственного baseline.

### DEGRADED

Хотя источник ещё не считается полностью недоступным, обнаружен хотя бы один operational warning:

```text
latest_run_delayed
latest_run_partial
coverage_drop
first_run_in_progress
```

### STALE

Используется когда:

- завершённых запусков ещё нет и ничего сейчас не выполняется;
- либо последний завершённый non-failed run старше `2.5 × cadence`.

### FAILED

Имеет наивысший приоритет:

- последний завершённый run имеет `status=failed`;
- либо сама конфигурация источника не может быть разобрана.

Последний failed-run не маскируется freshness. Даже если exception случился минуту назад, состояние остаётся `FAILED`.

## Coverage

Текущее coverage:

```text
coverage = tickers_mapped / tickers_total × 100%
```

Но абсолютное покрытие само по себе **не определяет health**.

Например, источник, который по своей природе стабильно покрывает 55% universe, не становится `DEGRADED` только из-за числа 55%.

### Собственный baseline

Для текущего завершённого `success|partial` запуска берутся предыдущие comparable запуски того же `(source_key, analyst_name)`.

Baseline:

```text
median coverage предыдущих success|partial runs
```

Используется максимум 10 предыдущих запусков.

Сигнал `coverage_drop` разрешён только если есть минимум 3 предыдущих coverage-наблюдения.

Порог:

```text
current coverage <= baseline - 10 п.п.
```

То есть health ищет **аномальное ухудшение источника относительно самого себя**, а не сравнивает разные источники по одному произвольному абсолютному порогу.

## Run history metrics

В выбранном окне 1..180 дней API считает:

- `runs_in_window`;
- `success_runs`;
- `partial_runs`;
- `failed_runs`;
- `consecutive_successes`;
- `consecutive_failures`.

Consecutive-series считается от последнего завершённого запуска назад и обрывается при первом другом status.

## Error diagnostics

Public health содержит только безопасные агрегаты:

```text
latest_error_kind
latest_error_count
```

Примеры `latest_error_kind`:

```text
sync_exception
ticker_errors
partial
configuration
```

Raw exception text и ticker-level `error_details` не выдаются публичному dashboard.

## Public API

```http
GET /api/dashboard/source-health?days=30
```

Допустимое окно:

```text
1..180 дней
```

Public response содержит:

- общий worst health;
- количество источников по состояниям;
- public source label;
- freshness/cadence;
- coverage и собственный baseline;
- run counts;
- structured error kind/count;
- operational reasons.

### Privacy

Встроенные публичные названия безопасны:

```text
Арсагера
ДОХОДЪ
fin-vista (модель)
```

Имена кастомных Published Sheets в интернет-режиме не раскрываются. Они отображаются как:

```text
Published Sheets #1
Published Sheets #2
...
```

`source_id` для них содержит короткий hash вместо analyst name.

## Local-only details API

Для администратора из local scope:

```http
GET /api/dashboard/source-health/details?days=30
X-Moex-Access-Scope: local
```

Дополнительно возвращает:

- фактический `analyst_name`;
- `latest_error_message`;
- ограниченный набор `latest_error_details` последнего запуска.

Без явного local scope endpoint возвращает `403` до обращения к данным.

## Dashboard UI

На `/dashboard/` добавлен блок **«Прогнозные источники»**.

Он показывает:

- overall `HEALTHY / DEGRADED / STALE / FAILED`;
- число источников каждого состояния;
- состояние каждого active source;
- время последнего завершённого запуска и его возраст;
- текущий coverage;
- изменение coverage против собственного baseline;
- количество success/partial/failed runs за окно;
- текущие consecutive-series;
- structured error kind/count;
- причины operational degradation.

Окна:

```text
7 / 30 / 90 / 180 дней
```

Worst states backend сортирует первыми:

```text
FAILED → STALE → DEGRADED → HEALTHY
```

## Разница с другими health/evidence слоями

`Forecast Source Health` отвечает:

> Получаем ли мы прогнозные данные от источника нормально и в ожидаемом объёме?

`Source Accuracy` отвечает:

> Насколько исторически точны прогнозы источника против фактов?

`Canary Capture Health` отвечает:

> Достаточно ли непрерывно собирается forward evidence weighted-canary?

Эти три понятия не следует смешивать.

## Что v0.25.0 не делает

Релиз не меняет:

```text
формулы прогнозов
source parsers
source sync cadence
primary universe
production median
weighted/canary gates
Watchlist
stock_rows
volume monitor
```

`FAILED` или `DEGRADED` также не выключают источник автоматически. Это диагностика для оператора, а не скрытый control plane.

## Database and environment

- новая migration: **нет**;
- schema head: `0024_canary_evidence`;
- обязательные `.env` изменения: **нет**;
- backend лишь получает через Compose уже существующие source-config variables, чтобы использовать тот же cadence/config, что worker.

## Runbook после deployment

```bash
cd /home/krapa/moex
cat VERSION
```

Ожидаемо:

```text
0.25.0
```

Public health:

```bash
curl 'http://127.0.0.1:18000/api/dashboard/source-health?days=30'
```

Local diagnostics:

```bash
curl \
  -H 'X-Moex-Access-Scope: local' \
  'http://127.0.0.1:18000/api/dashboard/source-health/details?days=30'
```

Worker logs:

```bash
docker compose logs --tail=150 arsagera-worker
```
