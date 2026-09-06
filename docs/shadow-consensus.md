# Shadow weighted consensus и readiness gate

## Назначение

Начиная с v0.17.0 приложение рассчитывает accuracy-weighted consensus **параллельно** с текущей production-медианой.

Это shadow-модель:

- она видна в Analytics;
- её можно сравнивать с текущей медианой на реальных текущих прогнозах;
- она не изменяет production fair value;
- она не изменяет Watchlist;
- она не изменяет расчёт ожидаемой доходности;
- она не меняет ranking или какие-либо persisted forecast values.

Даже если readiness gate показывает `READY`, переключение production consensus остаётся отдельным релизным решением.

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

Текущий прогноз может находиться на разных расстояниях от целевого года. Поэтому shadow engine не использует один и тот же historical snapshot во всех ситуациях.

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

Используется та же консервативная схема, что и в v0.15 backtest:

```text
shrinkage_samples = 5
error_floor_percent = 5
relative_score_cap = 2
```

Для каждого текущего источника учитывается медианная historical sMAPE, затем ошибка shrink-ится к общему prior и score ограничивается cap.

Если у текущих источников нет доступной исторической training history, все веса становятся одинаковыми. В этом случае:

```text
shadow weighted = арифметическое среднее
```

Это намеренный neutral fallback.

## Что возвращает shadow endpoint

```http
GET /api/analytics/shadow-consensus?ticker=SBER
```

Ответ содержит только агрегаты:

- target year;
- historical snapshot для весов;
- число текущих источников;
- сколько из них имеют historical training history;
- число training samples;
- minimum/maximum текущего веса без раскрытия источника;
- median / mean / weighted net profit;
- median / mean / weighted target price;
- delta weighted target к production median;
- текущую цену;
- market gap для median и weighted.

Ответ не содержит `analyst_name`, source-level forecasts или source-level weights и безопасен для internet/read-only режима.

## Readiness gate

Readiness — явная engineering policy для будущего promotion weighted consensus. Это не статистический тест значимости и не автоматический feature flag.

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

Readiness вычисляется поверх v0.16 robustness data.

Основной robustness endpoint теперь возвращает readiness вместе с тем же расчётом:

```http
GET /api/analytics/consensus-backtest/robustness?snapshot=pre_year
```

В response есть поле:

```json
{
  "readiness": {
    "ready": false,
    "gates_passed": 7,
    "gates_total": 11,
    "gates": []
  }
}
```

Это позволяет Analytics построить robustness и readiness одним тяжёлым backend-прогоном, без двойного 27-case parameter sweep.

Отдельный API также доступен:

```http
GET /api/analytics/consensus-readiness?snapshot=pre_year
```

Он удобен для автоматической диагностики и внешних read-only consumers.

## Интерфейс

### Shadow weighted consensus

После выбора тикера в `/analytics/` рядом с production consensus появляется отдельный блок `Shadow weighted consensus`.

Он показывает:

- production median target;
- shadow weighted target;
- delta между ними;
- market gap обоих вариантов;
- median/weighted net profit;
- диапазон текущих весов;
- выбранный historical snapshot;
- число training samples.

Ни одно значение из этого блока не используется в production расчётах.

### Readiness

Под robustness-анализом отображается таблица всех policy gates со статусами `PASS` / `WAIT`.

`SHADOW` означает, что хотя бы один gate не выполнен.

`READY` означает только, что текущая историческая evidence-policy выполнена для выбранного snapshot. После этого всё равно требуется отдельный review и отдельный release для изменения production consensus.

## Что v0.17.0 намеренно не делает

- не сохраняет shadow target в БД;
- не строит отдельную историю shadow targets;
- не меняет production median;
- не меняет Watchlist;
- не применяет weighted target в доходности;
- не включает feature flag для promotion;
- не меняет схему БД;
- не добавляет `.env`-параметры.

История shadow-расчётов может быть отдельным следующим этапом, если текущая модель покажет полезный и устойчивый разрыв относительно медианы.
