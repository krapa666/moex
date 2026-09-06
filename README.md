# MOEX Fair Price

MOEX Fair Price — веб-приложение для сравнения прогнозов российских акций, расчёта модельной справедливой цены, полной ожидаемой доходности, анализа истории прогнозов и контроля аномальных объёмов торгов.

Каноническая версия приложения хранится в `VERSION`. Поддерживаемый production-путь — Docker Compose за хостовым Nginx.

## Возможности

### Оценки акций

- до 10 таблиц аналитиков/моделей;
- общий universe тикеров и общие параметры компании;
- календарные прогнозы чистой прибыли и дивидендов;
- fair value через исторический средний P/E;
- дивидендная и полная ожидаемая доходность;
- текущие цены и уже выплаченные дивиденды через MOEX ISS;
- автосохранение локальных изменений;
- JSON export/import редактируемых прогнозных данных.

Для года `Y`:

```text
ForecastPrice(Y) = NetProfit(Y) × P/E / Shares
```

`NetProfit` хранится в млрд ₽, `Shares` — в млрд акций, результат — ₽/акцию.

Полная доходность считается от текущей рыночной цены и включает ещё не полученные дивиденды до выбранного прогнозного года. Для текущего календарного года backend сам вычитает уже прошедшие фактические выплаты MOEX ISS из полного годового дивидендного прогноза.

### Источники прогнозов

Встроенный worker поддерживает:

- **Арсагера** — прогнозы чистой прибыли и дивидендов;
- **УК «ДОХОДЪ»** — дивидендные прогнозы; rolling-12m прибыль намеренно не используется как календарная ЧП;
- **fin-vista (модель)** — опциональный автоматический источник календарной ЧП и дивидендов, выключен по умолчанию;
- дополнительные опубликованные Google Sheets через конфигурацию.

Каждый запуск прогнозного источника сохраняется в `forecast_source_runs` с покрытием, числом обновлений и диагностикой ошибок.

Подробнее: [`docs/forecast-sources.md`](docs/forecast-sources.md).

### Analytics, история и evidence layer

Страница `/analytics/` показывает:

- текущий consensus по сопоставимому прогнозному году;
- медианную target price и разброс;
- ценовой потенциал и полную доходность;
- историю `forecast_revisions`;
- динамику consensus;
- изменения прогнозов за текущий день;
- рейтинг точности источников по фактической годовой ЧП;
- out-of-sample backtest способов агрегирования прогнозов ЧП;
- robustness-анализ weighted backtest по годам, тикерам, leave-one-out и параметрам;
- текущий shadow weighted consensus рядом с production median;
- readiness gate для будущего решения о production weighting;
- forward-only shadow history и drift monitoring;
- глобальный shadow drift overview по universe основной таблицы;
- stateful email-уведомления о значимых drift-переходах и историю их доставки.

Историческая точность строится на фиксированных срезах `pre_year`, `mid_year`, `year_end` и использует sMAPE, абсолютную ошибку, bias и точность знака результата.

С v0.15.0 backtest сравнивает медиану, арифметическое среднее и консервативный accuracy-weighted вариант с shrinkage/weight cap на одном и том же наборе наблюдений. Training использует только более ранние факты с известным `reported_at`, опубликованные до target cutoff.

С v0.16.0 robustness layer проверяет результат по финансовым годам и тикерам, leave-one-out и фиксированной сетке 27 комбинаций `shrinkage / error floor / weight cap`.

С v0.17.0 приложение рассчитывает текущий **shadow weighted consensus**. Historical snapshot для весов выбирается по фазе target year. Readiness policy содержит 11 gates; `READY` сам по себе ничего не переключает.

С v0.18.0 `arsagera-worker` сохраняет forward-only snapshot `median vs shadow weighted` по доступным бумагам основной таблицы. История не backfill-ится из старых ревизий, чтобы не вносить hindsight bias.

С v0.19.0 Analytics показывает **глобальный shadow drift overview**. Он использует тот же drift-policy, что детальная карточка тикера, сортирует `ALERT → WATCH → STABLE → insufficient` и явно показывает coverage истории/классификации. Бумага без history остаётся видимой как `insufficient`.

С v0.20.0 поверх этого monitoring layer работает **stateful notification engine**. Он хранит per-ticker state и transition ledger и не отправляет письмо при каждом шестичасовом snapshot. Письма создаются для значимых переходов (`STABLE→WATCH`, escalation в `ALERT`, полноценный recovery), одинаковое состояние дедуплицируется, повторный вход в WATCH защищён cooldown, а неудачная SMTP-доставка может быть повторена только пока событие ещё актуально. Рассылка выключена по умолчанию.

**Production consensus target price остаётся медианным; shadow/readiness/monitoring/notification layer не меняет fair value, Watchlist, expected return или ranking.**

Подробнее:

- [`docs/analytics.md`](docs/analytics.md)
- [`docs/source-accuracy.md`](docs/source-accuracy.md)
- [`docs/consensus-backtest.md`](docs/consensus-backtest.md)
- [`docs/shadow-consensus.md`](docs/shadow-consensus.md)
- [`docs/shadow-notifications.md`](docs/shadow-notifications.md)

### Фактические годовые результаты

Канонические факты ЧП хранятся отдельно от прогнозов в `actual_net_profits`.

- ручные факты имеют `source_key=manual`;
- автоматические факты MOEX CCI имеют `source_key=moex-cci`;
- автоматический источник не может перезаписать ручной факт;
- ручная правка импортированного CCI-факта переводит его под ручное владение.

Опциональный адаптер MOEX Corporate Information Center принимает только однозначные годовые МСФО-результаты в RUB с известным масштабом и owner/shareholder-attributable net profit. CCI является отдельным лицензируемым сервисом и выключен по умолчанию.

Подробнее: [`docs/actual-result-sources.md`](docs/actual-result-sources.md).

### Watchlist

Страница `/watchlist/` собирает рассчитанные оценки в отдельный обзор для быстрого поиска наиболее интересных бумаг. Она использует текущие данные приложения и не создаёт независимую модель прогнозов.

### Монитор объёмов

Страница `/volumes/` работает по всем активным обыкновенным и привилегированным акциям TQBR, исключая фонды и депозитарные расписки.

По умолчанию:

- baseline — 60 завершённых торговых сессий;
- сигнал — от `3.6×` до `6.5×` среднего оборота;
- `> 6.5×` помечается как «выше диапазона»;
- три плановых запуска по будням: **18:20, 18:35, 18:45 Europe/Moscow**;
- первый запуск обновляет историю, последующие используют сохранённую историю и обновляют текущий оборот;
- уведомления дедуплицируются по тикеру и торговой дате.

Расписание:

```dotenv
VOLUME_SCHEDULE_HOUR=18
VOLUME_SCHEDULE_MINUTES=20,35,45
VOLUME_SCHEDULE_TIMEZONE=Europe/Moscow
```

## Доступ и безопасность

Приложение использует сетевой scope, который вычисляет **хостовый Nginx**:

- `local` — изменение данных разрешено;
- `internet` или отсутствие доверенного scope — read-only.

Nginx передаёт backend заголовок `X-Moex-Access-Scope`. Backend не считает IP frontend-контейнера доказательством локального пользователя.

Логин/пароль приложения не используются. Реальные названия аналитиков в интернет-режиме Analytics маскируются как `Аналитик N`.

Frontend и backend публикуются Compose только на loopback:

```text
127.0.0.1:8080   frontend
127.0.0.1:18000  backend
```

Не публикуйте эти порты напрямую в интернет. Внешний доступ должен идти через хостовый Nginx на `80/443`.

Shadow notification status/event endpoints публично возвращают только operational metadata. Recipient, SMTP credentials, SMTP error text, analyst names, source-level forecasts и source-level weights наружу не выдаются. Test-email endpoint является local-only.

## Архитектура

```text
Host Nginx
   ├─ /              → frontend
   └─ /api/*         → backend

Docker Compose
   ├─ frontend         static SPA / Nginx
   ├─ backend          FastAPI + SQLAlchemy + Alembic
   ├─ arsagera-worker  Arsagera + DOHOD + optional fin-vista + Published Sheets
   │                   + optional MOEX CCI actual-result sync
   │                   + shadow history/drift state/notification cycle
   ├─ volume-worker    MOEX TQBR volume scheduler/collector
   ├─ db               PostgreSQL 16
   └─ pgbackup         scheduled PostgreSQL backups
```

Имя `arsagera-worker` сохранено для совместимости с существующим deployment/runbook, хотя процесс теперь планирует несколько независимых задач.

## Быстрый запуск

```bash
git clone https://github.com/krapa666/moex.git
cd moex
cp .env.example .env
# Задайте POSTGRES_PASSWORD в .env
./scripts/compose-up.sh
```

`compose-up.sh`:

1. запускает PostgreSQL;
2. безопасно восстанавливает sync-snapshot только когда это действительно нужно;
3. собирает и запускает сервисы;
4. переключает хостовый Nginx в Compose-режим.

Проверка:

```bash
cat VERSION
docker compose ps
curl http://127.0.0.1:18000/api/live
curl http://127.0.0.1:18000/api/health
```

Остановка:

```bash
./scripts/compose-down.sh
```

Перед остановкой создаётся `backups/mode-sync/latest.sql.gz`.

### Snapshot restore

По умолчанию:

```text
MOEX_RESTORE_SYNC_SNAPSHOT=auto
```

Snapshot автоматически импортируется только в пустую прикладную БД. Принудительное восстановление:

```bash
MOEX_RESTORE_SYNC_SNAPSHOT=force ./scripts/compose-up.sh
```

Используйте `force` только если действительно хотите заменить текущие данные snapshot-файлом.

## Хостовый Nginx и HTTPS

Обычная конфигурация:

```bash
sudo ./scripts/configure-nginx-compose-proxy.sh --reload
```

HTTPS:

```bash
sudo ./scripts/configure-nginx-compose-proxy.sh \
  --https \
  --server-name moex.junnylab.ru \
  --reload
```

Документированный production URL: `https://moex.junnylab.ru`.

## Важные переменные `.env`

Минимально необходим пароль PostgreSQL:

```dotenv
POSTGRES_DB=fair_price
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<local-secret>
```

Для MOEX CCI при наличии лицензии:

```dotenv
MOEX_CCI_ACTUALS_ENABLED=true
MOEX_CCI_USERNAME=<login>
MOEX_CCI_PASSWORD=<password>
MOEX_CCI_ACTUALS_SYNC_INTERVAL_HOURS=24
MOEX_CCI_ACTUALS_RUN_ON_STARTUP=false
MOEX_CCI_ACTUALS_YEARS_BACK=5
```

Forward shadow history можно переопределить, но это не обязательно:

```dotenv
SHADOW_HISTORY_ENABLED=true
SHADOW_HISTORY_INTERVAL_HOURS=6
SHADOW_HISTORY_RUN_ON_STARTUP=true
SHADOW_HISTORY_RETENTION_DAYS=730
```

Shadow emails по умолчанию выключены. Для их включения используется существующий SMTP transport volume monitor:

```dotenv
SHADOW_NOTIFICATIONS_ENABLED=true
SHADOW_NOTIFICATION_EMAIL=<recipient@example.com>
SHADOW_NOTIFICATION_COOLDOWN_HOURS=24
SHADOW_NOTIFICATION_HISTORY_DAYS=30
SHADOW_NOTIFICATION_MAX_ATTEMPTS=5

VOLUME_SMTP_ENABLED=true
VOLUME_SMTP_HOST=<smtp-host>
VOLUME_SMTP_PORT=587
VOLUME_SMTP_USERNAME=<smtp-user>
VOLUME_SMTP_PASSWORD=<smtp-secret>
VOLUME_SMTP_FROM=<verified-sender@example.com>
VOLUME_SMTP_STARTTLS=true
VOLUME_SMTP_SSL=false
VOLUME_PUBLIC_BASE_URL=https://moex.junnylab.ru
```

Если `SHADOW_NOTIFICATION_EMAIL` пуст, используется `VOLUME_NOTIFICATION_EMAIL`.

Реальные SMTP/CCI/PostgreSQL credentials и адреса получателей нельзя коммитить в Git. `.env.example` содержит только имена параметров и безопасные пустые/демонстрационные значения.

## Основные API

### Health/access

- `GET /api/live`
- `GET /api/health`
- `GET /api/auth/me`

### Таблицы и строки

- `GET/POST /api/tables`
- `PATCH/DELETE /api/tables/{id}`
- `POST /api/tables/{id}/make-primary`
- `GET /api/rows?table_id=...`
- `POST /api/rows`
- `PUT/DELETE /api/rows/{id}`
- `POST /api/rows/refresh?table_id=...`
- `GET /api/ticker-comparison?ticker=SBER`

### Analytics

- `GET /api/analytics/forecast-revisions`
- `GET /api/analytics/source-runs`
- `GET /api/analytics/source-accuracy`
- `GET /api/analytics/source-accuracy/samples`
- `GET /api/analytics/consensus-backtest`
- `GET /api/analytics/consensus-backtest/robustness` — включает readiness summary
- `GET /api/analytics/consensus-backtest/observations` — local
- `GET /api/analytics/shadow-consensus?ticker=SBER`
- `GET /api/analytics/shadow-consensus/history?ticker=SBER`
- `GET /api/analytics/shadow-consensus/drift?ticker=SBER`
- `GET /api/analytics/shadow-consensus/overview`
- `GET /api/analytics/shadow-consensus/notifications/status`
- `GET /api/analytics/shadow-consensus/notifications/events`
- `POST /api/analytics/shadow-consensus/notifications/test` — local
- `POST /api/analytics/shadow-consensus/capture` — local
- `GET /api/analytics/consensus-readiness`
- `GET /api/analytics/actual-net-profits`
- `PUT/DELETE /api/analytics/actual-net-profits/{ticker}/{fiscal_year}` — local
- `GET /api/analytics/actual-net-profits/sync-status`
- `POST /api/analytics/actual-net-profits/sync` — local, MOEX CCI

### Volume monitor

- `GET /api/volume/config`
- `GET /api/volume/overview`
- `GET /api/volume/securities/{ticker}/observations`
- `GET /api/volume/runs/latest`
- `GET/PUT /api/volume/settings`
- `POST /api/volume/notifications/test` — local
- `POST /api/volume/collect` — local

Все изменяющие endpoints требуют local scope. Observation-level backtest local-only, потому что содержит реальные имена/веса источников. Shadow/readiness/history/drift/overview/notification status/event endpoints содержат только безопасные агрегаты/operational metadata и доступны read-only internet mode.

## Миграции

Backend-контейнер перед стартом выполняет:

```bash
alembic upgrade head
```

Текущий schema head — `0022_shadow_drift_notifications`.

v0.20.0 добавляет:

- `shadow_drift_states` — текущее per-ticker operational state;
- `shadow_drift_notification_events` — transition/delivery ledger.

Последние ключевые изменения схемы также включают `actual_net_profits`, `source_key`, `forecast_source_runs`, `forecast_revisions` и `shadow_consensus_snapshots`.

Исторические migration-файлы являются источником истины: `backend/alembic/versions/`.

## Разработка и CI

Python 3.12:

```bash
python -m pip install -r backend/requirements-dev.txt
ruff check backend
PYTHONPATH=backend pytest -q backend/tests
bash -n scripts/*.sh
```

Frontend/browser:

```bash
npm ci
npx playwright install --with-deps chromium
npm run test:e2e
```

GitHub Actions проверяет Ruff, pytest, frontend JavaScript, shell/Nginx/Compose contracts, Playwright и сборку backend/frontend Docker images.

Основной CI — `.github/workflows/ci.yml`. Release flow описан в [`docs/release-process.md`](docs/release-process.md).

## Документация

- [`docs/forecast-editing.md`](docs/forecast-editing.md) — правила ручного редактирования прогнозов;
- [`docs/forecast-sources.md`](docs/forecast-sources.md) — автоматические источники прогнозов;
- [`docs/analytics.md`](docs/analytics.md) — consensus, history и evidence UI/API;
- [`docs/source-accuracy.md`](docs/source-accuracy.md) — методология оценки точности;
- [`docs/consensus-backtest.md`](docs/consensus-backtest.md) — no-lookahead backtest и robustness;
- [`docs/shadow-consensus.md`](docs/shadow-consensus.md) — shadow weighted consensus, readiness, forward drift monitoring и global overview;
- [`docs/shadow-notifications.md`](docs/shadow-notifications.md) — state machine, cooldown, retry, SMTP и runbook уведомлений;
- [`docs/actual-result-sources.md`](docs/actual-result-sources.md) — канонические факты и MOEX CCI;
- [`docs/release-process.md`](docs/release-process.md) — versioning и публикация релизов.

## Обновление production

Рабочая копия production по правилам проекта находится в `/home/krapa/moex`:

```bash
cd /home/krapa/moex
git switch main
git pull --ff-only
./scripts/compose-up.sh
```

После обновления:

```bash
cat VERSION
docker compose ps
curl http://127.0.0.1:18000/api/live
curl http://127.0.0.1:18000/api/health
```
