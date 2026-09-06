# Analytics

Страница `/analytics/` объединяет текущий consensus, историю прогнозных ревизий, динамику consensus, оценку исторической точности источников, backtest способов агрегирования прогнозов чистой прибыли, robustness-проверку weighted-метода, текущий shadow weighted consensus, readiness gate, forward shadow monitoring, глобальный drift overview, stateful notification history, Production Impact Simulator и Controlled Canary control plane.

## Режим доступа

Analytics использует общий сетевой access scope приложения:

- local-клиент (`/api/auth/me` → `is_admin=true`) видит реальные `analyst_name` и локальные органы управления;
- internet-клиент работает read-only и видит нейтральные подписи `Аналитик 1`, `Аналитик 2` и т. д.;
- если scope определить не удалось, интерфейс безопасно трактует пользователя как guest.

Маскирование имён применяется к selector, текущему consensus, истории, графикам и рейтингу точности. Публичные backtest/robustness/shadow/readiness/history/drift/overview/notification/production-impact/canary-status/active-consensus сводки не содержат source-level имён изначально.

## Текущий consensus

Блок **«Консенсус аналитиков»** использует:

```http
GET /api/ticker-comparison?ticker=...
```

Базовый прогнозный год берётся из основной таблицы (`table_number=1`). В агрегаты попадают только оценки этого же календарного года.

Правила:

- цели другого года не смешиваются;
- минимум/максимум считаются по сопоставимым `forecast_price`;
- медиана нечётного набора — центральное значение;
- медиана чётного набора — среднее двух центральных;
- показатель «Рынок» — медиана доступных `current_price`.

### Ценовой потенциал

```text
MarketGap = (MedianTarget / CurrentPrice - 1) × 100%
```

Этот показатель **не включает дивиденды**.

### Полная ожидаемая доходность

Для сопоставимых целей Analytics использует backend `upside_percent`, включающий изменение цены и ещё не полученные дивиденды до прогнозного горизонта.

### Разброс и согласованность

```text
SpreadPercent = (MaxTarget - MinTarget) / MedianTarget × 100%
```

Категории:

- `≤ 10%` — высокая согласованность;
- `> 10%` и `≤ 25%` — средняя;
- `> 25%` — низкая.

При одной сопоставимой цели разброс не определяется.

## Active consensus

С v0.22.0 после выбора тикера Analytics дополнительно показывает отдельную карточку **Active consensus**:

```http
GET /api/analytics/active-consensus?ticker=SBER
```

Она не заменяет исходный analyst consensus block: source range/median остаются видимыми как baseline.

Возможные effective modes:

```text
MEDIAN
WEIGHTED CANARY
MEDIAN FALLBACK
```

`WEIGHTED CANARY` появляется только для тикера из активного canary allowlist и только при прохождении runtime safety guards. Если configured canary не проходит guard, UI показывает `MEDIAN FALLBACK` и конкретную причину.

Weighted expected return меняет только price-target layer; dividend contribution фиксируется на median baseline, как в Production Impact Simulator.

## Динамика consensus

Блок **«Динамика консенсуса»** восстанавливается из `forecast_revisions` без отдельной таблицы агрегатов.

После каждой ревизии система восстанавливает последнее известное состояние всех таблиц данного тикера, определяет базовый год основной таблицы и считает медиану/разброс только по сопоставимым целям этого года.

Дельты и линии графиков не продолжаются через смену прогнозного года. Историческая реконструкция ограничена максимумом API в 500 ревизий на тикер.

## История прогнозов

```http
GET /api/analytics/forecast-revisions
```

Фильтры: `ticker`, `table_id`, `since`, `limit`.

Рыночное обновление цены без изменения прогнозных входов не создаёт прогнозную ревизию. Фильтр аналитика влияет на chronology/fair-value chart, но не сужает consensus.

## Что изменилось сегодня

Daily revisions показывает сохранённые прогнозные изменения с начала текущего дня по локальному времени браузера и использует ту же `forecast_revisions` history.

## История запусков forecast sources

```http
GET /api/analytics/source-runs
```

`forecast_source_runs` отвечает на вопрос «как отработал источник», а `forecast_revisions` — «что изменилось в прогнозе».

## Точность источников

Backend сопоставляет historical forecast годовой ЧП с каноническим фактом `actual_net_profits` на фиксированной отсечке:

- `pre_year` — до 1 января финансового года;
- `mid_year` — до 1 июля;
- `year_end` — до 1 января следующего года.

Основная метрика — sMAPE. Дополнительно показываются MAE, bias, sign accuracy и покрытие.

```http
GET /api/analytics/source-accuracy
GET /api/analytics/source-accuracy/samples
```

По умолчанию rank требует минимум 5 наблюдений. Подробно: [`source-accuracy.md`](source-accuracy.md).

## Backtest консенсуса чистой прибыли

С v0.15.0 snapshot selector управляет backtest агрегирования прогнозов ЧП.

Сравниваются на одном наборе observations:

- медиана;
- арифметическое среднее;
- консервативный `Accuracy-weighted` вариант.

Публичная сводка:

```http
GET /api/analytics/consensus-backtest
```

Подробный local-only audit:

```http
GET /api/analytics/consensus-backtest/observations
```

Он содержит реальные source forecasts/weights, поэтому internet-клиент не имеет к нему доступа.

Accuracy-weighted training использует только более старые факты с известным `reported_at`, опубликованные до target cutoff. При отсутствии training history weighted совпадает с обычным средним.

## Robustness weighted backtest

С v0.16.0:

```http
GET /api/analytics/consensus-backtest/robustness
```

Проверяются:

1. результат по годам;
2. результат по тикерам;
3. evaluation leave-one-out по тикеру/году;
4. parameter sensitivity по 27 комбинациям.

Сетка:

```text
shrinkage_samples = 2, 5, 10
error_floor_percent = 2.5, 5, 10
relative_score_cap = 1.5, 2, 3
```

С v0.17.0 response также содержит `readiness`, поэтому robustness/readiness UI используют один тяжёлый backend-run.

## Shadow weighted consensus

С v0.17.0:

```http
GET /api/analytics/shadow-consensus?ticker=SBER
```

Shadow использует тот же target year, что production consensus.

Historical snapshot:

- будущий target year → `pre_year`;
- текущий год до 1 июля → `pre_year`;
- текущий год с 1 июля → `mid_year`;
- прошедший target year → `year_end`.

Training допускает только более старый fiscal year с `reported_at < as_of`. При отсутствии history веса равные.

Response не содержит source names, source-level forecasts или source-level weights.

## Forward shadow history и drift

С v0.18.0 worker сохраняет текущий shadow state по всем доступным тикерам основной таблицы. Historical training context строится один раз на batch capture.

```http
GET /api/analytics/shadow-consensus/history?ticker=SBER&days=90
GET /api/analytics/shadow-consensus/drift?ticker=SBER&days=30
```

Local-only manual capture:

```http
POST /api/analytics/shadow-consensus/capture
```

По умолчанию capture выполняется после startup sync и затем каждые 6 часов, retention 730 дней. History forward-only и не backfill-ится из старых revisions.

### Drift status

До классификации нужны минимум 3 snapshot и 24 часа history одного `target_year`.

- `insufficient` — history недостаточно;
- `stable` — threshold-признаков нет;
- `watch` — достигнут WATCH threshold;
- `alert` — достигнут ALERT threshold.

Контролируются baseline divergence, divergence step, max-weight concentration, relative movement gap и training-snapshot change. Это operational policy, не статистический тест и не торговый сигнал.

## Global shadow drift overview

С v0.19.0:

```http
GET /api/analytics/shadow-consensus/overview?days=30
```

Overview использует **тот же classifier и thresholds**, что `/shadow-consensus/drift`.

Universe берётся из основной таблицы. Тикер без history остаётся в response как `insufficient/no_history`, поэтому низкое coverage нельзя ошибочно принять за стабильный universe.

Backend batch-loads latest snapshots и monitoring window, затем классифицирует тикеры в памяти — N+1 query pattern отсутствует.

Сводка показывает universe size, history/classified coverage, `ALERT/WATCH/STABLE/insufficient` counts и `actionable = ALERT + WATCH`.

Сортировка:

```text
ALERT → WATCH → STABLE → insufficient
```

UI поддерживает окна 7/30/90/180 дней и status filters.

## Stateful drift notifications

С v0.20.0 global monitoring содержит блок **«Уведомления о переходах drift»**.

Notification engine запускается после каждого shadow capture и сравнивает текущий global drift с persisted per-ticker state.

Основные правила:

```text
bootstrap               → event only, без письма
STABLE → WATCH          → письмо с cooldown
STABLE → ALERT          → немедленное письмо
WATCH  → ALERT          → немедленная escalation
WATCH/ALERT → STABLE    → recovery, если incident реально был отправлен
ALERT → WATCH           → event only, это ещё не full recovery
same status             → без нового event/mail
* ↔ insufficient        → event only
смена target_year       → reset event, без письма
```

По умолчанию delivery выключен (`SHADOW_NOTIFICATIONS_ENABLED=false`), но state ledger продолжает обновляться. Это предотвращает deployment flood и ретроспективную отправку старых событий после будущего включения.

Public operational APIs:

```http
GET /api/analytics/shadow-consensus/notifications/status
GET /api/analytics/shadow-consensus/notifications/events?limit=50
```

Они не возвращают email recipient, SMTP credentials, SMTP error text или source identity.

Local-only test-email:

```http
POST /api/analytics/shadow-consensus/notifications/test
```

UI показывает enabled/configured state, cooldown, pending/failed count, last sent time и recent transition delivery history. Кнопка теста доступна только local admin при настроенном SMTP.

Failed delivery повторяется на следующем monitoring-cycle только пока event соответствует current target year/status. Иначе он становится `superseded` и не отправляется.

Подробная state-machine/SMTP/runbook документация: [`shadow-notifications.md`](shadow-notifications.md).

## Readiness к production weighting

```http
GET /api/analytics/consensus-readiness?snapshot=pre_year
```

Readiness — engineering policy из 11 gates, а не feature flag и не статистическая значимость. `READY` не меняет production consensus автоматически.

Подробно: [`shadow-consensus.md`](shadow-consensus.md).

## Production Impact Simulator и Promotion Decision Dashboard

С v0.21.0 Analytics содержит глобальный read-only блок, который отвечает на вопрос: **что изменилось бы при median→shadow-weighted promotion на текущем universe?**

```http
GET /api/analytics/production-impact?top_n=10&history_days=30
GET /api/analytics/promotion-dossier?top_n=10&history_days=30
```

Сравниваются:

- median и weighted target price;
- полная ожидаемая доходность;
- expected-return rank;
- Top-N membership/turnover;
- Spearman rank correlation;
- expected-return sign flips;
- гипотетическая median/weighted Watchlist score sensitivity.

Weighted scenario меняет только price-target layer. Dividend layer, уже содержащийся в median full return, сохраняется неизменным. Поэтому simulator изолирует влияние агрегатора и не подмешивает новую дивидендную модель.

Текущий `/watchlist/` использует primary table №1, а не median consensus. Поэтому simulated Watchlist score в этом блоке — **гипотетическая consensus-driven sensitivity**, не фактическая текущая Watchlist ranking. Ничего не записывается обратно в `stock_rows`.

Promotion dossier содержит 10 gates и три состояния:

```text
NOT_READY
OBSERVE
READY_FOR_MANUAL_PROMOTION
```

Он объединяет historical 11/11 readiness, comparable impact coverage, rank/Top-N stability и forward drift coverage/span.

## Controlled canary

С v0.22.0 в Production Impact Dashboard появляется control block:

```http
GET  /api/analytics/consensus-canary
PUT  /api/analytics/consensus-canary                  # local
POST /api/analytics/consensus-canary/rollback         # local
GET  /api/analytics/consensus-canary/events           # local
```

Canary выключен по умолчанию. Максимум — 5 тикеров.

Enable требует:

- `READY_FOR_MANUAL_PROMOTION`;
- ticker в primary universe;
- `shadow_available`;
- historical weights минимум по двум sources;
- live divergence `< 10%`;
- live concentration `< 1.5x` equal weight;
- forward drift `STABLE`.

Runtime повторяет эти guards. Любое нарушение приводит к `MEDIAN FALLBACK`, а не к продолжению weighted.

Rollback всегда доступен и просто выключает persisted canary state; source rows и forecast history не меняются.

Подробно: [`consensus-canary.md`](consensus-canary.md).

## Фактические результаты и MOEX CCI

```http
GET /api/analytics/actual-net-profits
PUT /api/analytics/actual-net-profits/{ticker}/{fiscal_year}
DELETE /api/analytics/actual-net-profits/{ticker}/{fiscal_year}
GET /api/analytics/actual-net-profits/sync-status
POST /api/analytics/actual-net-profits/sync
```

`PUT`, `DELETE` и manual sync требуют local scope. Manual fact имеет `source_key=manual` и защищён от автоматической CCI-перезаписи.

Подробнее: [`actual-result-sources.md`](actual-result-sources.md).

## Ограничения

- forecast history начинается только с реально сохранённых `forecast_revisions`;
- forward shadow history начинается с v0.18.0 и не backfill-ится;
- global overview universe следует основной таблице;
- разные target years не смешиваются в одной drift-series;
- training weight не использует факт без известного `reported_at`;
- leave-one-out в robustness является evaluation jackknife;
- exact `analyst_name` остаётся source identity для accuracy/weighting;
- drift thresholds являются operational policy, не статистическим тестом;
- notification state machine использует те же drift statuses, а не отдельный classifier;
- suppressed/failed/superseded notification events не меняют drift state;
- production-impact Watchlist score является simulation, потому что текущий Watchlist основан на primary table;
- promotion dossier является engineering policy, а не автоматическим feature flag;
- canary управляет только Active consensus и не переписывает primary/source rows;
- canary runtime fail-safe всегда направлен в median;
- текущий `/watchlist/` не переключается canary-механизмом.
