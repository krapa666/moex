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

## 6.2 Остановка
```bash
./scripts/compose-down.sh
```

## 6.3 Доступ после старта
- Frontend: http://localhost:8080
- Backend health: http://localhost:8000/api/health
- Metrics (через proxy): http://localhost:8080/metrics
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000
- Loki readiness: http://localhost:3100/ready

---

## 7. Развёртывание в Minikube

## 7.1 One-step запуск
```bash
./scripts/minikube-up.sh
```

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

## 8. Развёртывание на домашнем сервере (junibox)

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
sudo cp deploy/nginx/home-server.conf /etc/nginx/conf.d/moex.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

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

## 13.3 После Minikube restart `502 Bad Gateway` через `junibox`
Перегенерируйте proxy-конфиг:
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
