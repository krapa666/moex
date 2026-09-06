# Actual Results Corpus Worklist

Начиная с v0.28.0 локальная Analytics умеет строить операционный worklist недостающих фактических значений годовой чистой прибыли для текущего primary universe.

Worklist дополняет Historical Actual Results Backfill из v0.27.0: приложение само определяет, какие пары `ticker × fiscal_year` отсутствуют в `actual_net_profits`, и формирует CSV того же формата, который затем можно заполнить, проверить через preview и импортировать.

## Зачем это нужно

Production-БД может содержать десятки или сотни тикеров, а состав primary table меняется независимо от кода репозитория. Поэтому поддерживать ручной список тикеров в Git было бы ненадёжно.

Worklist строится непосредственно из текущей основной таблицы приложения:

```text
current primary universe
×
selected completed fiscal years
−
existing actual_net_profits
=
missing worklist
```

По умолчанию используется пять завершённых финансовых лет.

## Важная методологическая граница

Worklist — **не accuracy coverage** и не evidence gate.

Его знаменатель — текущий primary universe, умноженный на выбранные завершённые годы. Он отвечает только на операционный вопрос:

> Для каких текущих тикеров и лет у нас ещё нет канонического факта?

Он не доказывает, что каждый такой `ticker/year` исторически был листингован, сопоставим или должен участвовать в backtest.

Для недавно созданных компаний, реорганизаций, IPO и иных случаев часть строк может не иметь методологически сопоставимого исторического факта. В таких случаях нельзя придумывать значение или использовать несопоставимую отчётность только ради 100% fill rate.

Historical source accuracy по-прежнему использует только реальные прогнозные ревизии, существовавшие до соответствующего cutoff.

## API

Оба endpoint доступны только из `local` scope.

JSON summary:

```http
GET /api/analytics/actual-net-profits/backfill/worklist?years=5
```

Параметры:

```text
years     1..20, default 5
end_year  optional; default previous calendar year
```

Текущий или будущий финансовый год не допускается. Окно не может начинаться раньше 2000 года — это соответствует допустимому диапазону backfill importer.

Ответ содержит:

```text
primary_table_id
start_year
end_year
years
primary_tickers
expected_pairs
existing_pairs
missing_pairs
coverage_percent
by_year[]
missing[]
```

`coverage_percent` в этом endpoint означает только **fill rate операционного корпуса** текущего universe. Его нельзя смешивать с `/actual-net-profits/coverage`, где знаменатель формируется из реально существовавших исторических прогнозов.

CSV:

```http
GET /api/analytics/actual-net-profits/backfill/worklist.csv?years=5
```

CSV содержит только отсутствующие пары и использует тот же контракт, что v0.27 importer:

```text
ticker
fiscal_year
net_profit_billion_rub
source_name
source_url
reported_at
source_comment
```

Поля факта и provenance намеренно оставлены пустыми. Их нужно заполнить по первичному источнику; приложение не угадывает финансовый результат и не подставляет демонстрационные значения.

## UI workflow

В локальной `/analytics/` внутри секции Historical Actual Results Backfill появился блок **Worklist текущего primary universe**.

Порядок работы:

```text
1. выбрать глубину 3 / 5 / 7 / 10 лет
2. посмотреть current-universe fill rate
3. скачать worklist CSV
4. заполнить только подтверждённые факты и provenance
5. загрузить CSV обратно
6. выполнить preview
7. исправить INVALID строки
8. выполнить import
9. повторно проверить worklist и Actual Results Coverage
```

После импорта worklist автоматически уменьшается, потому что существующие `ticker/year` исключаются из следующей выгрузки.

## Что считать качественным источником

Правила v0.27 остаются обязательными:

- `source_name` должен явно описывать источник;
- `source_url` должен вести на реальный первичный источник;
- `reported_at` должен отражать дату публикации;
- значение должно быть годовой чистой прибылью в млрд ₽;
- методология должна быть сопоставима с owner/shareholder-attributable net profit, когда именно этот показатель используется в модели.

Если источник неоднозначен, строку лучше не импортировать.

## Console usage

Посмотреть summary из production host:

```bash
curl -sS \
  -H 'X-Moex-Access-Scope: local' \
  'http://127.0.0.1:18000/api/analytics/actual-net-profits/backfill/worklist?years=5' \
  | python3 -m json.tool
```

Скачать worklist:

```bash
curl -fsS \
  -H 'X-Moex-Access-Scope: local' \
  'http://127.0.0.1:18000/api/analytics/actual-net-profits/backfill/worklist.csv?years=5' \
  -o actual-results-worklist.csv
```

Проверить содержимое:

```bash
head -n 20 actual-results-worklist.csv
```

После заполнения использовать штатный preview/apply из `docs/actual-result-backfill.md`.

## Production boundary

v0.28.0 не меняет:

- production median consensus;
- source weights;
- controlled canary;
- auto-promotion;
- forecast source cadence/parsers;
- Watchlist;
- volume monitor;
- MOEX CCI configuration.

Новая migration не требуется. Новых обязательных `.env` параметров нет.
