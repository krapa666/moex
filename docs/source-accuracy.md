# Точность источников прогнозов

## Назначение

Начиная с v0.13.0 MOEX Fair Price хранит отдельный канонический факт годовой чистой прибыли и сравнивает его с сохранёнными историческими ревизиями прогнозов.

Этот слой нужен для доказательной оценки качества источников. Сам рейтинг источников **не меняет текущие формулы consensus, fair value, Watchlist или доходности**.

С v0.15.0 поверх этого evidence layer появился отдельный no-lookahead backtest способов агрегирования прогнозов ЧП. Его методология описана в [`consensus-backtest.md`](consensus-backtest.md).

## Канонический факт

Фактическая чистая прибыль хранится отдельно от таблиц аналитиков в `actual_net_profits`.

Для каждой пары `ticker + fiscal_year` существует одна текущая каноническая запись:

- `net_profit_billion_rub` — фактическая ЧП в млрд ₽;
- `source_key` — владелец записи (`manual`, `moex-cci` и будущие источники);
- `source_name` — человекочитаемое название источника;
- `source_url` — необязательная ссылка;
- `source_comment` — необязательное пояснение;
- `reported_at` — дата публикации результата, если известна.

Ручная запись/правка получает `source_key=manual`. Автоматический источник может обновлять только собственную запись и не может перезаписать ручной факт.

С v0.14.0 опциональный адаптер MOEX CCI может автоматически наполнять этот ledger. Подробности и fail-closed правила: [`actual-result-sources.md`](actual-result-sources.md).

## Срезы прогноза

Для одного финансового года точность измеряется на трёх фиксированных отсечках:

| Срез | Отсечка | Смысл |
| --- | --- | --- |
| `pre_year` | 1 января финансового года | Что источник ожидал до начала года |
| `mid_year` | 1 июля финансового года | Насколько точен прогноз после первого полугодия |
| `year_end` | 1 января следующего года | Последняя оценка до завершения года |

Для каждого источника, тикера и года выбирается **последняя сохранённая ревизия строго раньше отсечки**, содержащая прогноз ЧП нужного года.

Ревизии после отсечки не используются. Поздний прогноз не может задним числом улучшить ранний исторический score.

## Метрики

Основная относительная метрика — symmetric mean absolute percentage error:

```text
sMAPE = 200 × |Forecast - Actual| / (|Forecast| + |Actual|)
```

Если прогноз и факт одновременно равны нулю, ошибка равна `0%`.

sMAPE используется вместо обычного MAPE, потому что в universe возможны убытки и значения около нуля.

Дополнительно рассчитываются:

- `median_smape_percent`;
- `mean_smape_percent`;
- `median_absolute_error_billion_rub`;
- `mean_absolute_error_billion_rub`;
- `mean_bias_billion_rub = Forecast - Actual`;
- `sign_accuracy_percent` — правильность знака прибыль/убыток/ноль;
- число наблюдений, уникальных тикеров и лет.

## Рейтинг

По умолчанию источник получает ранг только при наличии минимум **5 наблюдений** для выбранного среза.

Порядок среди допущенных источников:

1. меньшая медианная sMAPE;
2. меньшая средняя sMAPE;
3. большее число наблюдений;
4. имя источника как стабильный tie-breaker.

Источник с недостаточной историей остаётся видимым, но не получает ранг.

## API

Факты:

```http
GET /api/analytics/actual-net-profits
GET /api/analytics/actual-net-profits?ticker=SBER&fiscal_year=2025
```

Локальная ручная запись/рестейтмент:

```http
PUT /api/analytics/actual-net-profits/SBER/2025
Content-Type: application/json

{
  "net_profit_billion_rub": 1580.3,
  "source_name": "МСФО, отчёт эмитента",
  "source_url": "https://..."
}
```

Локальное удаление:

```http
DELETE /api/analytics/actual-net-profits/SBER/2025
```

Статус автоматического MOEX CCI:

```http
GET /api/analytics/actual-net-profits/sync-status
```

Локальный ручной запуск CCI sync:

```http
POST /api/analytics/actual-net-profits/sync
```

Агрегированная точность:

```http
GET /api/analytics/source-accuracy?snapshot=pre_year&min_samples=5
```

Детальные пары:

```http
GET /api/analytics/source-accuracy/samples?snapshot=pre_year
```

Детальный endpoint поддерживает фильтры `ticker`, `analyst_name`, `fiscal_year`, `limit`.

Backtest методов consensus ЧП:

```http
GET /api/analytics/consensus-backtest?snapshot=pre_year
```

Подробные observation-level веса и прогнозы доступны только локально:

```http
GET /api/analytics/consensus-backtest/observations?snapshot=pre_year
```

## Интерфейс

На `/analytics/` блок **«Точность источников»** содержит:

- выбор среза;
- рейтинг и метрики отдельных источников;
- backtest медианы, среднего и accuracy-weighted агрегирования ЧП на том же срезе;
- последние канонические факты;
- локальную форму ручного факта;
- для локального администратора — безопасный статус MOEX CCI и кнопку ручной синхронизации, когда интеграция включена и настроена.

В internet/read-only режиме реальные `analyst_name` маскируются как `Аналитик N`, а органы изменения фактов/синхронизации скрыты. Публичная backtest-сводка не содержит source names; подробные веса доступны только local scope.

## Почему production weighted consensus пока не включён

v0.15.0 впервые даёт out-of-sample backtest, но единичный успешный результат ещё не является основанием автоматически менять production consensus. Нужны достаточное покрытие несколькими годами и компаниями, устойчивость к параметрам shrinkage/cap и повторная проверка после роста factual history.

До отдельного решения текущий production consensus остаётся прежним. Подробные критерии описаны в [`consensus-backtest.md`](consensus-backtest.md).
