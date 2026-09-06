# Analytics

Страница `/analytics/` объединяет текущий consensus, историю прогнозных ревизий, динамику consensus, оценку исторической точности источников, backtest способов агрегирования прогнозов чистой прибыли, robustness-проверку weighted-метода, текущий shadow weighted consensus, readiness gate и forward shadow monitoring.

## Режим доступа

Analytics использует общий сетевой access scope приложения:

- local-клиент (`/api/auth/me` → `is_admin=true`) видит реальные `analyst_name` и локальные органы управления;
- internet-клиент работает read-only и видит нейтральные подписи `Аналитик 1`, `Аналитик 2` и т. д.;
- если scope определить не удалось, интерфейс безопасно трактует пользователя как guest.

Маскирование имён применяется к selector, текущему consensus, истории, графикам и рейтингу точности. Публичные backtest/robustness/shadow/readiness/history/drift сводки не содержат source-level имён изначально.

## Текущий consensus

Блок **«Консенсус аналитиков»** использует:

```http
GET /api/ticker-comparison?ticker=...
```

Базовый прогнозный год берётся из основной таблицы (`table_number=1`). В агрегаты попадают только оценки, которые относятся к этому же календарному году.

Правила:

- цели другого года не смешиваются;
- минимум/максимум считаются по сопоставимым `forecast_price`;
- медиана нечётного набора — центральное значение;
- медиана чётного набора — среднее двух центральных;
- показатель «Рынок» — медиана доступных `current_price` из ответа сравнения.

### Ценовой потенциал

```text
MarketGap = (MedianTarget / CurrentPrice - 1) × 100%
```

Этот показатель **не включает дивиденды**.

### Полная ожидаемая доходность

Для сопоставимых целей Analytics использует уже рассчитанный backend `upside_percent`, который включает изменение цены и ещё не полученные дивиденды до прогнозного горизонта.

Показываются:

- медианная полная доходность;
- число положительных прогнозов;
- доходность каждого аналитика рядом с target price.

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

В интерфейсе есть:

- график исторической медианной target price;
- график исторического `SpreadPercent`;
- последнее изменение медианы;
- последнее изменение разброса;
- число сопоставимых целей.

Дельты не считаются через смену прогнозного года. Линии графиков также не соединяются между разными горизонтами.

Историческая реконструкция ограничена максимумом API в 500 ревизий на тикер. Если достигнут лимит, интерфейс сообщает об этом явно.

## История прогнозов

История загружается через:

```http
GET /api/analytics/forecast-revisions
```

Фильтры API: `ticker`, `table_id`, `since`, `limit`.

Рыночное обновление цены без изменения прогнозных входных данных не создаёт прогнозную ревизию.

Фильтр аналитика влияет на обычную chronology/fair-value chart, но не сужает consensus: consensus по определению использует все доступные сопоставимые таблицы выбранного тикера.

## Что изменилось сегодня

Блок daily revisions показывает сохранённые прогнозные изменения с начала текущего дня по локальному времени браузера. Он основан на той же истории `forecast_revisions` и не создаёт отдельное хранилище.

## История запусков forecast sources

Операционная история автоматических источников доступна отдельно от истории самих прогнозов:

```http
GET /api/analytics/source-runs
```

Она хранит source key, имя источника/модели, время запуска, покрытие, число обновлённых/неизменившихся/пропущенных тикеров и ошибки.

`forecast_source_runs` отвечает на вопрос «как отработал источник», а `forecast_revisions` — «что изменилось в прогнозе».

## Точность источников

С v0.13.0 Analytics показывает блок **«Точность источников»**.

Backend сопоставляет сохранённый исторический прогноз годовой ЧП с каноническим фактом из `actual_net_profits` на фиксированной отсечке:

- `pre_year` — до 1 января финансового года;
- `mid_year` — до 1 июля;
- `year_end` — до 1 января следующего года.

Основная метрика — sMAPE. Дополнительно показываются MAE, bias, sign accuracy и покрытие.

API:

```http
GET /api/analytics/source-accuracy
GET /api/analytics/source-accuracy/samples
```

По умолчанию источник получает место в рейтинге только при минимум 5 наблюдениях.

Подробная методология: [`source-accuracy.md`](source-accuracy.md).

## Backtest консенсуса чистой прибыли

С v0.15.0 тот же snapshot selector дополнительно управляет backtest агрегирования прогнозов ЧП.

Сравниваются три метода на **одинаковом наборе** исторических наблюдений:

- медиана;
- арифметическое среднее;
- консервативный `Accuracy-weighted` вариант.

Публичная сводка:

```http
GET /api/analytics/consensus-backtest
```

Она содержит число наблюдений/тикеров/лет и метрики каждого метода: median/mean sMAPE, MAE, bias, sign accuracy и delta sMAPE к baseline-медиане.

Положительная delta означает меньшую ошибку относительно медианы.

Подробный audit endpoint:

```http
GET /api/analytics/consensus-backtest/observations
```

возвращает реальные source forecasts, веса и число training samples по источникам, поэтому доступен **только local scope**. Internet-клиент не может использовать его для обхода маскирования `analyst_name`.

Accuracy-weighted веса обучаются только на более старых фактах с известной датой публикации `reported_at`, которая была раньше целевой backtest-отсечки. Это исключает look-ahead bias. При отсутствии training history weighted-вариант совпадает с обычным средним.

## Robustness weighted backtest

С v0.16.0 Analytics дополнительно проверяет, насколько преимущество weighted-метода устойчиво.

Публичный endpoint:

```http
GET /api/analytics/consensus-backtest/robustness
```

Он использует тот же `snapshot` и возвращает только безопасные агрегаты, финансовые годы и публичные MOEX-тикеры.

Проверяются четыре аспекта:

1. **по годам** — weighted против медианы отдельно для каждого финансового года;
2. **по тикерам** — тот же расчёт отдельно для каждой бумаги;
3. **evaluation leave-one-out** — поочерёдное исключение одного тикера или одного года из scored set с повторным расчётом delta на оставшихся наблюдениях;
4. **parameter sensitivity** — 27 комбинаций `shrinkage_samples`, `error_floor_percent`, `relative_score_cap`.

Фиксированная сетка:

```text
shrinkage_samples = 2, 5, 10
error_floor_percent = 2.5, 5, 10
relative_score_cap = 1.5, 2, 3
```

Интерфейс показывает общий weighted delta, положительные ticker/year slices, leave-one-out preservation, параметрическую чувствительность и диапазон результата.

С v0.17.0 тот же response дополнительно содержит `readiness`, поэтому robustness и readiness UI строятся одним тяжёлым backend-прогоном, без повторного 27-case sweep.

Один snapshot selector управляет source accuracy, основным backtest, robustness и readiness, поэтому сравниваемые показатели относятся к одной временной отсечке.

## Shadow weighted consensus

С v0.17.0 после выбора тикера рядом с production consensus появляется отдельный **Shadow weighted consensus**.

API:

```http
GET /api/analytics/shadow-consensus?ticker=SBER
```

Shadow engine использует тот же target year, что и production consensus: `forecast_start_year` основной таблицы.

Historical snapshot для весов выбирается по текущей фазе target year:

- будущий target year → `pre_year`;
- текущий год до 1 июля → `pre_year`;
- текущий год с 1 июля → `mid_year`;
- уже прошедший target year → `year_end`.

Historical sample может участвовать в current weight только если его fiscal year старше target year и канонический факт имеет `reported_at` раньше текущего момента.

Если historical training history нет, веса становятся равными и shadow weighted совпадает с арифметическим средним.

Shadow response не содержит source names, source-level forecasts или source-level weights и безопасен для internet/read-only режима.

## Forward shadow history и drift

С v0.18.0 `arsagera-worker` сохраняет текущий shadow state по всем доступным тикерам основной таблицы. Для эффективности historical training context строится один раз на batch capture, а не отдельно для каждой бумаги.

Публичная история:

```http
GET /api/analytics/shadow-consensus/history?ticker=SBER&days=90
```

Публичный drift summary:

```http
GET /api/analytics/shadow-consensus/drift?ticker=SBER&days=30
```

Ручной capture является изменяющей операцией и требует local scope:

```http
POST /api/analytics/shadow-consensus/capture
```

По умолчанию worker снимает initial snapshot после startup sync и далее каждые 6 часов. Retention — 730 дней. Эти параметры можно переопределить через `SHADOW_HISTORY_*`, но существующий `.env` менять не обязательно.

History хранит только aggregate median/weighted values и диапазон веса без source identity. Реальные analyst names, source-level forecasts и source-level weights не сохраняются.

История является **forward-only**: старые `forecast_revisions` не backfill-ятся в shadow snapshots, потому что достоверная реконструкция тогдашних weights/source set создала бы риск hindsight bias.

### Drift status

Drift является operational policy, а не статистическим тестом и не торговым сигналом.

До классификации нужны минимум 3 snapshot и минимум 24 часа истории одного `target_year`.

Статусы:

- `insufficient` — history пока недостаточно;
- `stable` — threshold-признаков нет;
- `watch` — достигнут WATCH threshold;
- `alert` — достигнут ALERT threshold.

Контролируются:

- абсолютное расхождение weighted target с median baseline;
- изменение этого расхождения относительно предыдущего snapshot;
- концентрация max weight относительно равного веса;
- разница движения weighted и median внутри monitoring window;
- смена training snapshot (`pre_year/mid_year/year_end`).

Точные thresholds и rationale описаны в [`shadow-consensus.md`](shadow-consensus.md).

Analytics показывает forward chart `median vs weighted`, последние snapshots, длительность monitoring history и причины текущего drift status. Разные `target_year` на одном тренде не смешиваются.

## Readiness к production weighting

Readiness является explicit engineering policy, а не автоматическим feature flag и не тестом статистической значимости.

Публичный API:

```http
GET /api/analytics/consensus-readiness?snapshot=pre_year
```

Те же данные также вложены в `readiness` основного robustness response.

Readiness проверяет 11 gates: покрытие observations/tickers/years, median/mean improvement, ticker/year slices, оба leave-one-out, parameter sweep и худший parameter case.

Все gates должны пройти одновременно.

Статус `SHADOW` означает, что хотя бы один gate ещё не выполнен. `READY` означает только, что текущая evidence-policy выполнена; production consensus всё равно остаётся медианным до отдельного review и отдельного release.

Подробная методология: [`shadow-consensus.md`](shadow-consensus.md).

## Фактические результаты и MOEX CCI

С v0.14.0 канонические факты могут добавляться вручную или автоматически из опционального MOEX CCI.

API:

```http
GET /api/analytics/actual-net-profits
PUT /api/analytics/actual-net-profits/{ticker}/{fiscal_year}
DELETE /api/analytics/actual-net-profits/{ticker}/{fiscal_year}
GET /api/analytics/actual-net-profits/sync-status
POST /api/analytics/actual-net-profits/sync
```

`PUT`, `DELETE` и ручной `POST .../sync` требуют local scope.

В локальном интерфейсе доступна форма ручного факта и безопасный статус MOEX CCI. Manual fact получает `source_key=manual` и защищён от последующей автоматической перезаписи.

Подробнее: [`actual-result-sources.md`](actual-result-sources.md).

## Ограничения

- история прогнозов начинается только с реально сохранённых `forecast_revisions`;
- forward shadow history начинается только после установки v0.18.0 и не backfill-ится;
- разные прогнозные годы не смешиваются в одной consensus/drift точке;
- источник с малой выборкой остаётся видимым, но не получает надёжного rank;
- training weight не использует факт без известного `reported_at`;
- текущий canonical ledger не хранит полную историю рестейтментов, поэтому backtest в спорных временных случаях ведёт себя консервативно;
- leave-one-out в robustness является evaluation jackknife и не переобучает веса после исключения сегмента;
- exact `analyst_name` остаётся идентичностью source accuracy/weighting;
- drift thresholds являются operational policy, не статистическим тестом;
- `READY` не меняет production mode автоматически;
- accuracy-weighted production consensus пока намеренно отключён.
