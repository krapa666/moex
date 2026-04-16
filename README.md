# MOEX Fair Price — полное руководство

> Полнофункциональное приложение для оценки справедливой цены акций MOEX с поддержкой нескольких таблиц аналитиков, автоматическим обновлением цен, мониторингом и развёртыванием через Docker Compose / Minikube.

---

## 1. Что умеет система

### 1.1 Бизнес-функции
- Ведение **таблиц аналитиков** (до 10 таблиц).
- Для каждой строки по тикеру:
  - текущая цена,
  - количество акций (млрд),
  - средний P/E,
  - прогнозная чистая прибыль на 4 года,
  - расчёт прогнозной цены и Upside на 4 года.
- Автоматический пересчёт производных полей при изменении входных данных.
- Автосинхронизация строк с одинаковыми тикерами между таблицами.
- Поддержка «основной» таблицы:
  - только в основной таблице редактируются `Кол-во акций` и `P/E`;
  - можно выбрать любую таблицу как основную.

### 1.2 Работа с ценами MOEX
- Backend получает цену по ISS API MOEX.
- При отсутствии сделок применяется fallback на `PREVPRICE`.
- Фоновое обновление цен раз в 10 минут.

### 1.3 UI-функции
- Русскоязычный интерфейс.
- Sticky-header, сортировки по тикеру/капитализации/upside.
- Автосохранение редактирования.
- Сравнение по тикеру: при наведении на тикер показываются дополнительные строки из других таблиц (внутри основной таблицы), с визуальным выделением группы.

---

## 2. Архитектура

## 2.1 Компоненты
- `frontend` (Nginx + static SPA):
  - отдаёт `index.html`, `app.js`, `styles.css`;
  - проксирует `/api` и `/metrics` в backend.
- `backend` (FastAPI + SQLAlchemy + Alembic):
  - API и бизнес-логика,
  - фоновая задача обновления цен,
  - экспорт метрик Prometheus.
- `db` (PostgreSQL 16):
  - хранение таблиц аналитиков и строк тикеров.
- `monitoring`:
  - `prometheus`, `grafana`, `loki`, `promtail`, `node-exporter`.
- `pgbackup`:
  - периодические бэкапы БД.

## 2.2 Поток данных (кратко)
1. Пользователь редактирует строку во frontend.
2. Frontend отправляет `PUT /api/rows/{id}`.
3. Backend сохраняет данные, пересчитывает производные поля, при необходимости синхронизирует данные в других таблицах.
4. Frontend обновляет отображение.

## 2.3 Структура проекта
- `backend/app/` — API, модели, сервисы.
- `backend/alembic/` — миграции.
- `backend/tests/` — unit-тесты.
- `frontend/` — статический клиент.
- `k8s/` — манифесты Kubernetes.
- `scripts/` — сценарии запуска/остановки.
- `monitoring/` — конфиги Prometheus/Grafana/Loki.
- `deploy/nginx/` — шаблоны reverse-proxy.

---

## 3. Модель данных

## 3.1 Основные сущности
- `analyst_tables`
  - `id`, `analyst_name`, `year_offset`, `sort_order`, `created_at`.
- `stock_rows`
  - `table_id`, `ticker`, `current_price`, `shares_billion`, `pe_avg_5y`,
  - `forecast_profit_year1..4_billion_rub`,
  - `forecast_price_year1..4`,
  - `upside_percent_year1..4`,
  - `net_profit_year_map`, `status_message`, timestamps.

## 3.2 Миграции
- Используется Alembic, миграции в `backend/alembic/versions`.
- Важно: revision-id в Alembic должен помещаться в `alembic_version.version_num` (`VARCHAR(32)`).

---

## 4. API (основное)

## 4.0 Режимы доступа (без авторизации)
- В системе больше нет логина/пароля.
- Права определяются по IP клиента:
  - **Локальная сеть** (`private/loopback` IP) → режим **администратора** (полный доступ).
  - **Внешняя сеть** (публичный IP) → режим **гостя** (только чтение).
- Backend определяет режим по `X-Forwarded-For` (через nginx proxy) и блокирует все mutating endpoint’ы для внешних клиентов.

## 4.1 Таблицы аналитиков
- `GET /api/tables` — список таблиц в текущем порядке (основная = №1).
- `POST /api/tables` — создать таблицу.
- `PATCH /api/tables/{table_id}` — изменить имя/сдвиг лет.
- `DELETE /api/tables/{table_id}` — удалить таблицу (нельзя удалить текущую основную).
- `POST /api/tables/{table_id}/make-primary` — сделать таблицу основной.

## 4.2 Строки
- `GET /api/rows?table_id=...`
- `POST /api/rows`
- `PUT /api/rows/{row_id}`
- `DELETE /api/rows/{row_id}`
- `POST /api/rows/refresh?table_id=...`

## 4.3 Сервисные endpoints
- `GET /api/health`
- `GET /metrics`
- `GET /api/ticker-comparison?ticker=...`
- `GET /api/access-mode` — текущий режим доступа (`admin`/`guest`) и IP клиента.

---

## 5. Правила редактирования и синхронизации

## 5.1 Ограничения по полям
- Поля `shares_billion` и `pe_avg_5y`:
  - редактируются **только в основной таблице (№1)**;
  - в остальных таблицах — readonly.

## 5.2 Автосинхронизация
- При создании/изменении строки тикер синхронизируется между таблицами.
- Изменения `shares_billion` и `pe_avg_5y` в основной таблице автоматически распространяются в остальные таблицы для того же тикера.

## 5.3 Сравнительные строки в UI
- При наведении на тикер:
  - в таблицу временно вставляются строки из других таблиц по этому же тикеру;
  - группа строк выделяется цветом.
- При уходе курсора/blur — таблица возвращается в исходный вид.

---

## 6. Быстрый старт (Docker Compose)

## 6.1 Запуск
```bash
./scripts/compose-up.sh
```
Скрипт также автоматически переключает хостовый Nginx reverse-proxy в compose-режим
(`scripts/configure-nginx-compose-proxy.sh --reload`), чтобы URL в домашней сети оставался тем же: `http://moex.ddns.net/`.

## 6.2 Остановка
```bash
./scripts/compose-down.sh
```
При остановке автоматически сохраняется актуальный snapshot БД в
`backups/mode-sync/latest.sql.gz` для последующего переноса между режимами.

## 6.3 Доступ после старта
- Frontend: http://localhost:8080
- Backend health: http://localhost:8000/api/health
- Metrics (через proxy): http://localhost:8080/metrics
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000
- Loki readiness: http://localhost:3100/ready

## 6.5 Определение прав по сети
- Права пользователя определяются автоматически:
  - локальная сеть → режим администратора;
  - внешняя сеть → режим гостя (read-only).
- Источник IP берётся из `X-Forwarded-For`, поэтому приложение должно работать за корректно настроенным nginx proxy.

## 6.4 Непрерывность данных между Compose и Minikube
- При `compose-down` и `minikube-down` выполняется экспорт snapshot БД.
- При `compose-up` и `minikube-up` выполняется импорт последнего snapshot (если он есть).
- Общий путь snapshot:
  - `backups/mode-sync/latest.sql.gz`
  - `backups/mode-sync/latest.meta`
- Это позволяет не терять актуальные данные при переключении способа развёртывания.

---

## 7. Развёртывание в Minikube

## 7.1 One-step запуск
```bash
./scripts/minikube-up.sh
```
Скрипт автоматически переключает тот же хостовый Nginx reverse-proxy в Minikube-режим
(`scripts/configure-nginx-k8s-proxy.sh --reload`), сохраняя единый внешний URL `http://moex.ddns.net/`.
Также скрипт поднимает `kubectl port-forward` для frontend на `127.0.0.1:30080`
и пишет PID/лог в:
- `/tmp/moex-k8s-port-forward.pid`
- `/tmp/moex-k8s-port-forward.log`
- `/tmp/moex-k8s-prometheus-port-forward.pid`
- `/tmp/moex-k8s-prometheus-port-forward.log`
- `/tmp/moex-k8s-grafana-port-forward.pid`
- `/tmp/moex-k8s-grafana-port-forward.log`
- `/tmp/moex-k8s-loki-port-forward.pid`
- `/tmp/moex-k8s-loki-port-forward.log`

В Minikube-режиме также поднимается мониторинг (`prometheus`, `grafana`, `loki`) и
он доступен через тот же внешний хост:
- `http://moex.ddns.net/prometheus/`
- `http://moex.ddns.net/grafana/`
- `http://moex.ddns.net/loki/`

Опции:
```bash
./scripts/minikube-up.sh --skip-nginx
```

## 7.2 One-step остановка
```bash
./scripts/minikube-down.sh
# или оставить кластер:
./scripts/minikube-down.sh --keep-minikube
```

## 7.3 Ручной контур (если нужно)
```bash
minikube start
minikube addons enable ingress
eval "$(minikube docker-env)"
docker build -t krapa666/moex-backend:latest backend
docker build -t krapa666/moex-frontend:latest frontend
kubectl apply -k k8s
```

---

## 8. Развёртывание на домашнем сервере (moex.ddns.net)

## 8.1 Базовые зависимости
```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin nginx
```

## 8.2 Клонирование и запуск
```bash
cd /opt
sudo git clone https://gitlab.com/krapa/moex.git
sudo chown -R $USER:$USER /opt/moex
cd /opt/moex
./scripts/compose-up.sh
```

## 8.3 Nginx-конфиг
```bash
# Compose-режим:
sudo ./scripts/configure-nginx-compose-proxy.sh --reload

# Minikube-режим:
sudo ./scripts/configure-nginx-k8s-proxy.sh --reload

# Ручная установка шаблона (fallback):
sudo cp deploy/nginx/home-server.conf /etc/nginx/conf.d/moex.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

## 8.4 Публикация в интернет (port-forward на роутере)
- Шаблоны `deploy/nginx/home-server.conf` и `deploy/nginx/home-server-k8s.conf` уже подготовлены для внешнего трафика:
  - `listen 80 default_server;` и `server_name ... _;` — принимают запросы по внешнему IP/домену, даже если Host не `moex.ddns.net`.
  - Добавлены корректные proxy-заголовки `X-Forwarded-*` и таймауты для стабильной работы через NAT.
  - `client_max_body_size 20m` — чтобы импорт JSON-файла БД не упирался в стандартный лимит Nginx.
- Для безопасности мониторинг и служебные endpoints ограничены только локальными/приватными сетями:
  - `/prometheus/`, `/grafana/`, `/loki/`, `/torrent/`.
  - Из интернета эти маршруты будут отдавать `403 Forbidden`.
- Рекомендация перед открытием портов:
  1. Настроить домен + TLS (Let's Encrypt).
  2. Пробрасывать наружу только `80/443`.
  3. Не публиковать backend напрямую (`:8000`) и внутренние сервисы (`:3000`, `:9090`, `:3100`, `:9091`).

### Переход на HTTPS (валидные сертификаты)
1. Получите сертификат Let's Encrypt для домена (webroot-mode):
```bash
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d your-domain.example
```
2. Сгенерируйте HTTPS-конфиг reverse-proxy:
```bash
# Compose
sudo ./scripts/configure-nginx-compose-proxy.sh --https --server-name your-domain.example --reload

# Minikube
sudo ./scripts/configure-nginx-k8s-proxy.sh --https --server-name your-domain.example --reload
```
Альтернатива: можно не передавать `--https`, если сертификаты уже лежат в
`/etc/letsencrypt/live/<domain>/fullchain.pem` и `privkey.pem` — скрипты
`configure-nginx-*.sh` автоматически переключатся на HTTPS-шаблон.

Переменные окружения (для `compose-up.sh` / `minikube-up.sh` и configure-скриптов):
- `MOEX_PUBLIC_DOMAIN` (или `MOEX_SERVER_NAME`) — домен для `server_name`.
- `MOEX_SSL_CERT_PATH` — путь к `fullchain.pem`.
- `MOEX_SSL_CERT_KEY_PATH` — путь к `privkey.pem`.

3. Проверка:
```bash
curl -I https://your-domain.example
```

Если HTTPS по-прежнему не открывается, проверьте:
1. Что активен именно `moex.conf`: `sudo nginx -T | rg -n 'moex|server_name|listen 443|ssl_certificate'`.
2. Что сертификат существует и читается nginx-процессом.
3. Что наружу проброшен порт `443` и открыт в firewall.
4. Что после генерации конфига выполнен reload (`--reload`) без ошибок `nginx -t`.

---

## 9. Мониторинг и логи

- Prometheus собирает метрики backend + инфраструктуры.
- Grafana datasource provisioning настраивается автоматически.
- Loki + Promtail собирают логи контейнеров.
- Готовые dashboard/alerts находятся в `monitoring/`.

Полезные проверки:
```bash
curl -s http://localhost:3100/ready
curl -s http://localhost:8000/api/health
curl -s http://localhost:8080/metrics | head
```

---

## 10. Бэкапы и восстановление

## 10.1 Где хранятся
- Бэкапы в `./backups`.
- Данные PostgreSQL в volume `postgres_data`.

## 10.2 Ручной бэкап
```bash
docker compose exec db pg_dump -U postgres -d fair_price > ./backups/manual_$(date +%F_%H-%M-%S).sql
```

## 10.3 Восстановление
```bash
cat ./backups/<backup_file>.sql | docker compose exec -T db psql -U postgres -d fair_price
```

---

## 11. Разработка

## 11.1 Локальные проверки
```bash
ruff check backend
PYTHONPATH=backend pytest -q backend/tests
```

## 11.2 Миграции
```bash
cd backend
alembic upgrade head
```

## 11.3 Важно про совместимость схемы
- При старте backend выполняется defensive-проверка `sort_order` для legacy БД.
- Рекомендуется всё равно поддерживать БД в актуальном состоянии через Alembic.

---

## 12. CI/CD

Файл `.gitlab-ci.yml`:
- `lint` — `ruff check backend`
- `test` — `pytest -q backend/tests`
- `build` — docker build backend/frontend

---

## 13. Troubleshooting

## 13.1 `Ошибка API 502`
Проверить backend:
```bash
docker compose ps
docker compose logs -f backend
curl http://localhost:8000/api/health
```

## 13.2 Ошибка Alembic `value too long for type character varying(32)`
Причина: слишком длинный `revision` ID.
Решение: использовать сокращённый revision (в проекте уже исправлено для миграции `0007`).

## 13.3 После Minikube restart `502 Bad Gateway` через `moex.ddns.net`
Перегенерируйте proxy-конфиг:
```bash
sudo ./scripts/configure-nginx-k8s-proxy.sh --reload
```
Если Minikube-профиль временно не поднят, но `127.0.0.1:30080` доступен,
`configure-nginx-k8s-proxy.sh` всё равно сгенерирует рабочий конфиг.

## 13.4 Принудительно переключить reverse-proxy между режимами
Compose-режим:
```bash
sudo ./scripts/configure-nginx-compose-proxy.sh --reload
```

Minikube-режим:
```bash
sudo ./scripts/configure-nginx-k8s-proxy.sh --reload
```

---

## 14. Безопасность и эксплуатационные замечания

- Не храните токены (`GITHUB_TOKEN`, `GITLAB_TOKEN`) в репозитории.
- Для production ограничьте CORS и доступ к служебным endpoint.
- Регулярно проверяйте алерты Prometheus и ротацию бэкапов.

---

## 15. Версионирование

- Формат: `MAJOR.MINOR.PATCH`.
- `MAJOR` — несовместимые изменения API/данных.
- `MINOR` — новый функционал без поломки обратной совместимости.
- `PATCH` — исправления.

---

## 16. Краткий чеклист первого запуска

1. `./scripts/compose-up.sh`
2. Открыть `http://localhost:8080`
3. Проверить `http://localhost:8000/api/health`
4. Проверить Grafana/Prometheus
5. Выполнить пробное добавление тикера и проверить авторасчёты
6. Проверить сравнение между таблицами

---

Если хотите, следующим шагом могу сделать отдельные разделы в README с примерами API-запросов (`curl`) для каждого endpoint и отдельный runbook для production-аварий (что проверять в каком порядке). 
