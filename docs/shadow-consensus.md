# Shadow weighted consensus, readiness и forward monitoring

## Назначение

Начиная с v0.17.0 приложение рассчитывает accuracy-weighted consensus **параллельно** с текущей production-медианой.

Это shadow-модель:

- она видна в Analytics;
- её можно сравнивать с текущей медианой на реальных текущих прогнозах;
- она не изменяет production fair value;
- она не изменяет Watchlist;
- она не изменяет расчёт ожидаемой доходности;
- она не меняет ranking или persisted forecast values.

Даже если readiness gate показывает `READY`, переключение production consensus остаётся отдельным релизным решением.

С v0.18.0 shadow-расчёт дополнительно сохраняется во времени как **forward-only monitoring history**. Эта история нужна для наблюдения за реальным поведением weighted-модели после её внедрения в shadow-режиме.

С v0.19.0 тот же forward-monitoring агрегируется по всему universe основной таблицы в единый operational overview. Overview не вводит отдельные thresholds и не переопределяет статус: `ALERT/WATCH/STABLE/insufficient` для строки overview вычисляется тем же policy, что и детальный drift endpoint конкретного тикера.

## Текущий целевой год

Shadow consensus использует тот же базовый год, что и текущий production consensus: `forecast_start_year` основной таблицы (`sort_order=1`).

В расчёт попадают только источники, у которых для этого календарного года одновременно доступны:

- прогноз годовой чистой прибыли;
- P/E;
- число акций.

Для каждого источника текущая target price рассчитывается той же базовой формулой:

```text
TargetPrice = NetProfit × P/E / Shares
```

Источник идентифицируется текущим точным `analyst_name`, как и в существующей accuracy/backtest-модели. Если несколько таблиц имеют одинаковый `analyst_name`, shadow engine считает их одним источником и берёт первую по текущему порядку таблиц.

Минимум для shadow-агрегации — два сопоставимых источника.

## Как выбирается historical snapshot для весов

Для даты расчёта `as_of`:

| Целевой год | Historical snapshot |
| --- | --- |
| `target_year > as_of.year` | `pre_year` |
| `target_year == as_of.year` и дата до 1 июля | `pre_year` |
| `target_year == as_of.year` и дата с 1 июля | `mid_year` |
| `target_year < as_of.year` | `year_end` |

Идея — сравнивать текущую фазу прогноза с максимально близким фиксированным историческим горизонтом, не используя более позднюю информацию.

## Какие исторические факты допускаются в веса

После выбора snapshot используются те же no-lookahead правила, что и в backtest:

1. historical sample должен относиться к финансовому году строго раньше текущего `target_year`;
2. у канонического факта должен быть известен `reported_at`;
3. `reported_at` должен быть строго раньше текущего `as_of`.

Факт с неизвестной датой публикации не обучает текущий shadow-вес.

## Формирование весов

Используется та же консервативная схема, что и в backtest:

```text
shrinkage_samples = 5
error_floor_percent = 5
relative_score_cap = 2
```

Если у текущих источников нет доступной historical training history, все веса становятся одинаковыми:

```text
shadow weighted = арифметическое среднее
```

Это намеренный neutral fallback.

## Batch shadow engine

С v0.18.0 текущий shadow engine умеет считать все тикеры основной таблицы за один проход.

Historical accuracy samples и допустимый training set строятся **один раз на capture-run**, а затем переиспользуются для всех тикеров. Это критично для периодического мониторинга: без batch-context полный accuracy history пришлось бы заново строить для каждой бумаги.

Публичный одиночный endpoint сохраняет прежний контракт:

```http
GET /api/analytics/shadow-consensus?ticker=SBER
```

## Forward shadow history

Таблица:

```text
shadow_consensus_snapshots
```

Для каждой доступной бумаги сохраняются только безопасные агрегаты:

- ticker;
- target year;
- training snapshot;
- время capture;
- число текущих sources;
- число sources с training history;
- число training samples;
- min/max weight без связи с конкретным source;
- median/weighted net profit;
- median/weighted target price;
- delta weighted к median;
- текущая цена;
- market gap median/weighted.

**Не сохраняются:**

- реальные `analyst_name`;
- source-level forecasts;
- source-level weights.

Поэтому history и overview API безопасны для internet/read-only режима.

### Расписание

По умолчанию history capture включён:

```dotenv
SHADOW_HISTORY_ENABLED=true
SHADOW_HISTORY_INTERVAL_HOURS=6
SHADOW_HISTORY_RUN_ON_STARTUP=true
SHADOW_HISTORY_RETENTION_DAYS=730
```

`arsagera-worker`:

1. выполняет обычные initial forecast/actual sync;
2. после них снимает initial shadow snapshot;
3. затем повторяет capture каждые 6 часов;
4. регулярный capture сдвинут на 15 минут относительно стартовой фазы forecast-sync jobs;
5. при capture удаляет записи старше retention.

Параметры опциональны: существующий `.env` менять необязательно.

### Почему нет backfill

История начинается только после установки v0.18.0.

Старые `forecast_revisions` не преобразуются задним числом в shadow history, потому что достоверный historical shadow потребовал бы реконструировать тогдашние:

- доступный набор источников;
- source identity;
- training history;
- known-at-the-time actual facts;
- weighting regime.

Использование текущего состояния для такого backfill создало бы риск hindsight bias.

## History API

```http
GET /api/analytics/shadow-consensus/history?ticker=SBER&days=90
```

Параметры:

- `ticker` — MOEX ticker;
- `days` — окно 1..730 дней, default 90;
- `limit` — максимум 1000 точек, default 500.

Ответ отсортирован по времени от старых точек к новым.

Ручной capture доступен только local scope:

```http
POST /api/analytics/shadow-consensus/capture
```

Он предназначен для диагностики/проверки deployment. Плановый production capture выполняет worker.

## Drift monitoring

Публичный endpoint:

```http
GET /api/analytics/shadow-consensus/drift?ticker=SBER&days=30
```

Drift здесь означает **операционное расхождение shadow weighted с median baseline**, а не статистически доказанный data/model drift.

При расчёте сравниваются только snapshots того же `target_year`, что и последняя точка. Старый прогнозный год не смешивается с новым.

До классификации требуется:

```text
минимум 3 snapshots
и минимум 24 часа forward history
```

До выполнения обоих условий статус:

```text
insufficient
```

### Наблюдаемые признаки

1. **Baseline divergence** — текущее абсолютное расхождение weighted target с median.
2. **Divergence step** — изменение этого расхождения относительно предыдущего snapshot.
3. **Weight concentration ratio**:

```text
max source weight / equal source weight
```

Например при трёх sources равный вес — `33.3%`; max weight `50%` означает concentration `1.5×`.

4. **Relative movement gap** — разница процентного движения weighted и median от первой точки текущего monitoring-window до последней.
5. **Training snapshot change** — смена `pre_year / mid_year / year_end`; это ожидаемый regime change, но он отмечается для интерпретации скачка.

### Operational thresholds

| Признак | WATCH | ALERT |
| --- | ---: | ---: |
| `abs(weighted vs median)` | `>= 10%` | `>= 20%` |
| `abs(delta step)` | `>= 5 п.п.` | `>= 10 п.п.` |
| weight concentration | `>= 1.5×` | `>= 1.75×` |
| `abs(relative movement gap)` | `>= 5 п.п.` | `>= 10 п.п.` |

Смена training snapshot добавляет `WATCH`, если более сильного `ALERT` уже нет.

Эти thresholds — прозрачная engineering policy. Они **не являются статистическим тестом значимости и не являются торговым сигналом**.

Статусы:

- `insufficient` — истории пока недостаточно;
- `stable` — ни один threshold не достигнут;
- `watch` — достигнут хотя бы WATCH threshold;
- `alert` — достигнут хотя бы ALERT threshold.

## Global drift overview

С v0.19.0 доступен публичный агрегированный endpoint:

```http
GET /api/analytics/shadow-consensus/overview?days=30
```

Параметр `days` использует тот же диапазон, что и детальный drift monitor: 2..180 дней, default 30.

Universe определяется **текущей основной таблицей** — первой по `sort_order`, затем `id`. Это совпадает с выбором основной таблицы для production/shadow target year.

Overview специально включает и бумаги без накопленной forward history. Они получают:

```text
status = insufficient
reason = no_history
```

Это позволяет отличить реальное отсутствие аномалий от слабого monitoring coverage.

Сводка возвращает:

- `universe_tickers`;
- `tickers_with_history`;
- `classified_tickers`;
- числа `alert/watch/stable/insufficient`;
- `actionable_tickers = alert + watch`;
- history coverage;
- classified coverage;
- список тех же `ShadowDriftResult` по каждому тикеру.

Backend загружает последние snapshots и monitoring-window пакетно, а не вызывает детальный endpoint отдельно для каждого тикера. Это избегает N+1-query pattern.

Порядок по умолчанию:

```text
ALERT → WATCH → STABLE → insufficient
```

Внутри одного статуса выше показывается бумага с большим абсолютным текущим расхождением weighted к median.

Overview не хранит новых данных и не создаёт новой схемы БД — это read-only проекция существующей `shadow_consensus_snapshots`.

## Analytics UI

### Global shadow drift

Глобальный блок отображается без выбора тикера и показывает:

- размер universe;
- долю бумаг, у которых уже есть history;
- число классифицированных бумаг;
- количество `ALERT`, `WATCH`, `STABLE`, `insufficient`;
- количество бумаг, требующих внимания (`ALERT + WATCH`);
- таблицу с текущей delta, шагом delta, концентрацией веса, movement gap, длительностью history и причинами статуса;
- фильтр `Все / ALERT+WATCH / ALERT / WATCH / STABLE / Накопление`;
- переключатель monitoring-window 7 / 30 / 90 / 180 дней.

Тикер является ссылкой на детальную Analytics-карточку этой бумаги.

### Shadow weighted consensus

После выбора тикера показывается текущий state:

- production median target;
- shadow weighted target;
- delta;
- market gap;
- median/weighted net profit;
- диапазон текущих весов;
- выбранный historical snapshot;
- training samples.

### Shadow history и drift

Forward monitoring конкретного тикера показывает:

- drift status;
- число snapshots;
- фактическую длительность history;
- latest delta и median absolute delta;
- weight concentration ratio;
- relative movement gap;
- график `median vs weighted`;
- последние snapshot rows;
- причины `WATCH/ALERT`.

График не соединяет разные `target_year`.

## Readiness gate

Readiness — отдельная historical evidence-policy для будущего promotion weighted consensus. Это не статистический тест значимости и не автоматический feature flag.

Для выбранного historical snapshot должны пройти **все** критерии:

| Gate | Требование |
| --- | ---: |
| Historical observations | `>= 30` |
| Tickers | `>= 10` |
| Fiscal years | `>= 3` |
| Overall median-sMAPE improvement | `>= +1.0 pp` |
| Overall mean-sMAPE improvement | `> 0 pp` |
| Positive ticker slices | `>= 60%` |
| Positive year slices | `>= 66.7%` |
| Leave-one-ticker-out preserves improvement | `>= 80%` |
| Leave-one-year-out preserves improvement | `>= 80%` |
| Positive parameter cases | `>= 80%` |
| Worst parameter-grid median delta | `> 0 pp` |

Основной robustness endpoint возвращает readiness вместе с тем же расчётом:

```http
GET /api/analytics/consensus-backtest/robustness?snapshot=pre_year
```

Отдельный API:

```http
GET /api/analytics/consensus-readiness?snapshot=pre_year
```

`READY` означает только, что текущая historical evidence-policy выполнена. Для изменения production consensus всё равно нужен отдельный review и отдельный release.

## Production boundary

v0.19.0 **не меняет**:

- production median consensus;
- fair-value formulas;
- expected-return calculations;
- Watchlist ranking;
- volume monitor;
- source weighting defaults.

Global overview, readiness и forward monitoring остаются evidence/observability layers перед любым возможным promotion weighted consensus.
