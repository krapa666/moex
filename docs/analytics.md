# Analytics

Страница `/analytics/` объединяет текущий consensus, историю прогнозных ревизий, динамику consensus, оценку исторической точности источников, backtest способов агрегирования прогнозов чистой прибыли, robustness-проверку weighted-метода, текущий shadow weighted consensus, readiness gate, forward shadow monitoring, глобальный drift overview и stateful notification history.

## Режим доступа

Analytics использует общий сетевой access scope приложения:

- local-клиент (`/api/auth/me` → `is_admin=true`) видит реальные `analyst_name` и локальные органы управления;
- internet-клиент работает read-only и видит нейтральные подписи `Аналитик 1`, `Аналитик 2` и т. д.;
- если scope определить не удалось, интерфейс безопасно трактует пользователя как guest.

Маскирование имён применяется к selector, текущему consensus, истории, графикам и рейтингу точности. Публичные backtest/robustness/shadow/readiness/history/drift/overview/notification сводки не содержат source-level имён изначально.

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

Failed delivery повторяется на следующем monitoring-cycle только пока event соответствует текущему target year/status. Иначе он становится `superseded` и не отправляется.

Подробная state-machine/SMTP/runbook документация: [`shadow-notifications.md`](shadow-notifications.md).

## Readiness к production weighting

```http
GET /api/analytics/consensus-readiness?snapshot=pre_year
```

Readiness — engineering policy из 11 gates, а не feature flag и не статистическая значимость. `READY` не меняет production consensus автоматически.

Подробно: [`shadow-consensus.md`](shadow-consensus.md).

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
- `READY` не меняет production mode автоматически;
- accuracy-weighted production consensus намеренно отключён.
