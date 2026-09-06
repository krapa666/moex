# Production Impact Simulator и Promotion Decision Dashboard

## Назначение

Начиная с v0.21.0 Analytics оценивает, **что изменилось бы**, если вместо median consensus использовать shadow accuracy-weighted consensus.

Этот слой остаётся evidence/decision-support. С v0.22.0 его `READY_FOR_MANUAL_PROMOTION` используется только как один из обязательных enable-gates для отдельного Controlled Canary control plane.

Сам impact simulator не меняет:

- данные основной таблицы;
- source fair-value расчёты;
- текущий Watchlist;
- persisted forecasts;
- weighting policy;
- readiness/drift thresholds.

## API

Полный impact + promotion dossier:

```http
GET /api/analytics/production-impact?top_n=10&history_days=30
```

Только promotion dossier:

```http
GET /api/analytics/promotion-dossier?top_n=10&history_days=30
```

Оба endpoint являются read-only и безопасны для internet-mode. Они не возвращают реальные `analyst_name`, source-level forecasts или source-level weights.

## Universe

Universe наследуется от `build_shadow_consensus_batch()` и поэтому соответствует primary table приложения.

Бумага считается comparable, если для неё доступны минимум два сопоставимых текущих прогноза и shadow engine способен построить одновременно median и weighted target для target year основной таблицы.

API отдельно показывает:

```text
universe_tickers
comparable_tickers
comparable_coverage_percent
```

Низкое coverage не интерпретируется как доказательство стабильности.

## Изоляция эффекта weighting

Главный методологический принцип: меняется **только price-target layer**.

Для median baseline используется текущая медианная target price и медианная полная ожидаемая доходность сопоставимых источников.

Из median full return выделяется неизменяемый dividend layer:

```text
median_price_potential = median_target / current_price - 1

dividend_layer = median_full_return - median_price_potential
```

Для weighted scenario:

```text
weighted_price_potential = weighted_target / current_price - 1
weighted_full_return = weighted_price_potential + dividend_layer
```

Таким образом impact simulator не смешивает одновременно две гипотезы — новую агрегацию прогнозов и новую дивидендную модель.

Controlled Canary в v0.22.0 использует тот же принцип для Active consensus.

## Portfolio-level metrics

Сравниваются median и weighted scenario на одном и том же comparable universe.

Метрики:

- median/max absolute target-price delta;
- median absolute full-return delta;
- доля случаев, где меняется знак ожидаемой доходности;
- Spearman correlation ранжирования по expected return;
- mean/max absolute rank change;
- Top-N overlap;
- тикеры, входящие и выходящие из Top-N;
- sensitivity Watchlist score.

Default:

```text
Top-N = 10
forward window = 30 days
```

UI позволяет сравнивать Top-10 / Top-20 и forward windows 30 / 90 / 180 дней.

## Важное различие: текущий Watchlist и simulated Watchlist score

Текущий `/watchlist/` технически использует строки **основной таблицы №1** (`forecast_price_year1`, `upside_percent_year1`) и не является median-consensus portfolio.

Поэтому поля:

```text
median_watchlist_score
weighted_watchlist_score
watchlist_score_delta
```

означают **гипотетическую consensus-driven sensitivity**, а не фактическую замену текущего Watchlist.

Score рассчитывается тем же правилом, что `frontend/watchlist/score.js`:

```text
price potential:       0..60 points
remaining dividends:  0..25 points
volume activity:       0..15 points
```

Latest volume signal загружается batch-query; `signal` даёт 15 activity points, `above_range` — 7.

Ни одна simulated value не записывается обратно в `stock_rows`. Controlled Canary также не переключает текущий Watchlist.

## Ранжирование

`median_rank` и `weighted_rank` — ранги по полной ожидаемой доходности соответствующего scenario.

Rank delta:

```text
weighted_rank - median_rank
```

Отрицательное значение означает продвижение бумаги вверх при weighted scenario.

Top-N membership строится по этому же expected-return ranking.

## Promotion dossier

Dossier объединяет три вида evidence:

1. historical readiness;
2. forward shadow/drift coverage;
3. текущий production-impact profile.

### Policy gates

| Gate | Requirement |
| --- | ---: |
| Historical readiness | `11/11 PASS` |
| Comparable impact coverage | `>= 70%` |
| Spearman rank correlation | `>= 0.90` |
| Top-N overlap | `>= 80%` |
| Expected-return sign flips | `<= 10%` |
| Mean absolute simulated Watchlist score delta | `<= 10 points` |
| Forward classified coverage | `>= 80%` |
| Forward ALERT tickers | `0` |
| Forward WATCH + ALERT | `<= 20%` classified |
| Median forward observation span | `>= 7 days` |

Это **engineering promotion policy**, а не статистический критерий доказательства превосходства модели.

### Status

```text
NOT_READY
OBSERVE
READY_FOR_MANUAL_PROMOTION
```

Логика:

- если historical readiness ещё не выполнен → `NOT_READY`;
- если historical readiness выполнен, но хотя бы один impact/forward gate не выполнен → `OBSERVE`;
- только все 10 gates → `READY_FOR_MANUAL_PROMOTION`.

`READY_FOR_MANUAL_PROMOTION` не переключает Active consensus автоматически. Он только разрешает оператору попытаться включить Controlled Canary. После этого дополнительно проверяются per-ticker guards.

## Связь с Controlled Canary

Canary enable требует общего:

```text
promotion.status = READY_FOR_MANUAL_PROMOTION
```

Но этого недостаточно. Для каждого выбранного ticker дополнительно нужны:

```text
real historical weighting >= 2 sources
live divergence < WATCH
live weight concentration < WATCH
forward drift = STABLE
```

Runtime повторяет эти проверки и при ухудшении использует median fallback.

Подробно: [`consensus-canary.md`](consensus-canary.md).

## Privacy

Public response содержит только aggregate/current-company metrics:

- MOEX ticker;
- median/weighted aggregate target;
- expected return/rank/score sensitivity;
- portfolio metrics;
- promotion gates.

Не выдаются:

- реальные source names;
- individual forecasts;
- individual source weights;
- SMTP/private operational data.

## Производительность

Shadow consensus для universe строится batch-engine, который переиспользует общий historical training context.

Latest volume statuses также загружаются batch-query.

Promotion dossier выполняет существующие robustness/readiness и global drift calculations. Endpoint предназначен для Analytics/decision-support, а не для high-frequency request path.

## Database и configuration

Сам v0.21.0 не менял schema. Controlled Canary v0.22.0 добавляет отдельный persisted control/audit layer:

```text
0023_consensus_canary
```

Новых обязательных `.env` параметров нет.

## Production boundary

С v0.22.0 median остаётся default/fail-safe, а weighted может влиять только на `Active consensus` явно выбранных canary ticker.

Не меняются:

- source rows;
- primary-table calculations;
- текущий Watchlist;
- persisted expected returns;
- volume monitor.

Rollback выключает canary state и немедленно возвращает Active consensus к median без восстановления данных.
