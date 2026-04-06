# Приложение оценки справедливой цены акций MOEX

**Версия приложения:** `v6.0.0`

Приложение запускается как стек сервисов:
- `db` — PostgreSQL 16;
- `backend` — FastAPI + SQLAlchemy;
- `frontend` — статический UI на Nginx;
- `pgbackup` — автоматические бэкапы PostgreSQL;
- `prometheus` — сбор метрик;
- `grafana` — дашборды и визуализация;
- `loki` + `promtail` — сбор и просмотр логов;
- `node-exporter` — метрики хоста (CPU/RAM/Disk).
- Docker-образы backend/frontend собираются через multi-stage Dockerfile для уменьшения итогового размера.
- Для совместимости в контейнере включены базовые collectors `node-exporter` без `systemd`-collector (чтобы не требовался доступ к DBus на хосте).

## Функции
- Динамическая таблица: пользователь добавляет/удаляет строки.
- До 10 независимых копий таблицы по аналитикам (переключение активной таблицы и имя аналитика).
- Хранение текущего состояния таблицы в PostgreSQL.
- Автоподгрузка текущих цен по тикерам MOEX через ISS API (обновление раз в 10 минут).
- Для низколиквидных тикеров используется fallback на `PREVPRICE`, если нет текущей сделки.
- Фоновое обновление цен выполняется только backend-job каждые 10 минут.
- Явные сообщения об ошибках для невалидных тикеров.
- Авторасчёт:
  - капитализации (в млрд ₽): `цена * количество_акций_в_млрд`;
  - прогнозной цены (₽) для 4 календарных лет: `прогнозная_прибыль_в_млрд * P/E / количество_акций_в_млрд`;
  - upside (%) для 4 календарных лет: `(прогнозная_цена - текущая_цена) / текущая_цена * 100`.
- Интерфейс на русском с форматированием чисел до 2 знаков.
- Динамический сдвиг горизонта прогноза на год вперёд и назад с сохранением ЧП за календарным годом.
- Обновлённый UI: премиальный лаконичный стиль, sticky-header, визуальное выделение upside.
- Сортировка таблицы по тикеру и upside для каждого из 4 прогнозных лет по клику на заголовки столбцов (индикаторы `⇅/↑/↓`).
- Upside отображается целым числом процентов, а прогнозная цена — с точностью исходной текущей цены (до 10 знаков после запятой).
- Изменения в полях применяются на лету (в т.ч. при переходе в другое поле), при этом активный фокус ввода не сбрасывается.
- Подготовка к мониторингу: backend экспортирует `/metrics` в формате Prometheus.
- Мониторинг (Prometheus + Grafana) запускается вместе с приложением по умолчанию.
- Сбор и просмотр логов через Loki + Promtail в Grafana.
- Добавлены базовые alert-правила Prometheus (`monitoring/alerts.yml`).

## Запуск
```bash
docker compose up --build
```

После старта:
- Frontend: [http://localhost:8080](http://localhost:8080)
- Backend health: [http://localhost:8000/api/health](http://localhost:8000/api/health)
- Backend metrics (через frontend proxy): [http://localhost:8080/metrics](http://localhost:8080/metrics)
- Prometheus UI: [http://localhost:9090](http://localhost:9090)
- Grafana UI: [http://localhost:3000](http://localhost:3000)
- Loki readiness: [http://localhost:3100/ready](http://localhost:3100/ready)

## Kubernetes (Minikube)

В репозитории есть полный набор манифестов в `k8s/`:
- namespace, secret и PVC для PostgreSQL;
- deployment/service для `postgres`, `backend`, `frontend`;
- ingress и `kustomization.yaml`.

### Быстрый запуск одной командой
```bash
./scripts/minikube-up.sh
```

Скрипт сам:
- поднимет Minikube и включит ingress addon;
- соберёт образы backend/frontend внутри Docker Minikube;
- дождётся готовности ingress admission webhook;
- применит core-манифесты и затем ingress (отдельным шагом);
- дождётся готовности `postgres`, `backend`, `frontend`;
- покажет URL доступа.

### 1) Подготовка Minikube
```bash
minikube start
minikube addons enable ingress
kubectl version --client
kubectl get nodes
```

### 2) Сборка образов внутри Docker Minikube
```bash
eval $(minikube docker-env)
docker build -t krapa666/moex-backend:latest backend
docker build -t krapa666/moex-frontend:latest frontend
```

### 3) Применение манифестов
```bash
kubectl apply -k k8s
kubectl -n moex get pods,svc,ingress,pvc
```

### 4) Доступ к приложению
Доступ через Ingress (`http://junibox/`):
```bash
curl -I http://junibox/
```

Если Minikube запущен в отдельной VM/контейнере, чтобы `http://junibox/` работал так же как раньше
через системный Nginx, используй подготовленный конфиг:

```bash
minikube ip
# подставь IP в deploy/nginx/home-server-k8s.conf вместо MINIKUBE_IP
sudo cp deploy/nginx/home-server-k8s.conf /etc/nginx/conf.d/moex-k8s.conf
sudo nginx -t && sudo systemctl reload nginx
```

### 5) Проверка backend
```bash
kubectl -n moex get pods
kubectl -n moex logs deploy/backend --tail=100
kubectl -n moex port-forward svc/backend 8000:8000
curl http://127.0.0.1:8000/api/health
```

### 6) Обновление в Minikube
```bash
eval $(minikube docker-env)
docker build -t krapa666/moex-backend:latest backend
docker build -t krapa666/moex-frontend:latest frontend
kubectl -n moex rollout restart deploy/backend deploy/frontend
kubectl -n moex rollout status deploy/backend
kubectl -n moex rollout status deploy/frontend
```

### 7) Удаление
```bash
kubectl delete -k k8s
```

## Автовыгрузка после коммита (GitHub + GitLab)

В репозитории настроен локальный git-hook `.githooks/post-commit`, который после каждого `git commit` автоматически пытается выполнить:

- `git push github HEAD:main`
- `git push gitlab HEAD:main`

Используемые remote:

- `github` → `https://github.com/krapa666/moex.git`
- `gitlab` → `https://gitlab.com/krapa/moex.git`

Для token-based пуша хук поддерживает переменные окружения:

- `GITHUB_TOKEN`
- `GITLAB_TOKEN`

Ссылки на остальные микросервисы (внутри docker-сети):
- Promtail metrics: `http://promtail:9080/metrics`
- Node Exporter metrics: `http://node-exporter:9100/metrics`
- PgBackup health endpoint: `http://pgbackup:8080/`

## Примечания по мониторингу
Мониторинг запускается автоматически при обычном старте:
```bash
docker compose up --build
```

После запуска:
- Prometheus: [http://localhost:9090](http://localhost:9090)
- Grafana: [http://localhost:3000](http://localhost:3000)
- Loki readiness: [http://localhost:3100/ready](http://localhost:3100/ready)

## Миграции БД (Alembic)
- В контейнере backend миграции применяются автоматически при старте (`alembic upgrade head`).
- Локальный ручной запуск:
```bash
cd backend
alembic upgrade head
```

## GitLab CI/CD
- В корне добавлен `.gitlab-ci.yml` с этапами:
  - `lint`: запуск `ruff` для backend;
  - `test`: запуск `pytest` для backend;
  - `build`: сборка Docker-образов backend/frontend.
- Pipeline настроен под локальный GitLab Runner с **Docker executor** (tag: `home-docker`) и Docker-in-Docker для build job'ов.

### Настройка GitLab Runner (Docker executor) для этого проекта
1. Зарегистрируй runner на проект и укажи тег `home-docker`.
2. В `/etc/gitlab-runner/config.toml` для раннера проверь:
```toml
[[runners]]
  executor = "docker"
  request_concurrency = 4
  [runners.docker]
    privileged = true
    image = "docker:27.1.2"
    volumes = ["/cache"]
  environment = ["FF_USE_ADAPTIVE_REQUEST_CONCURRENCY=true"]
```
3. Перезапусти runner:
```bash
sudo systemctl restart gitlab-runner
```
4. Если на сервере несколько runner'ов — выставь `request_concurrency` в диапазон `2..4` у каждого, чтобы избежать bottleneck при long polling.

## Версионирование
- Текущая версия: `v6.0.0`
- Формат версий: `MAJOR.MINOR.PATCH`
  - `MAJOR` — несовместимые изменения API/модели данных,
  - `MINOR` — новые функции без поломки совместимости,
  - `PATCH` — исправления ошибок и мелкие улучшения.

## Разворачивание на домашнем сервере (junibox)

Ниже последовательность действий «с нуля» для Linux-сервера с уже установленным Nginx.

### 1) Установка зависимостей на сервере
```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin nginx
sudo usermod -aG docker $USER
newgrp docker
```

Проверь:
```bash
docker --version
docker compose version
nginx -v
```

### 2) Клонирование проекта
```bash
cd /opt
sudo git clone https://gitlab.com/krapa/moex.git
sudo chown -R $USER:$USER /opt/moex
cd /opt/moex
```

### 3) Запуск сервисов проекта (приложение + мониторинг одной командой)
```bash
docker compose up -d --build
```

Проверка контейнеров:
```bash
docker compose ps
```

### 4) Установка Nginx-конфига reverse proxy

В репозитории уже подготовлен конфиг:
- `deploy/nginx/home-server.conf`

Скопируй его в системный Nginx:
```bash
sudo cp /opt/moex/deploy/nginx/home-server.conf /etc/nginx/conf.d/moex.conf
```

Удалить дефолтный сайт (если мешает):
```bash
sudo rm -f /etc/nginx/sites-enabled/default
```

Проверить и перезапустить Nginx:
```bash
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx
```

### 5) Доступ к сервисам через веб

После запуска и настройки Nginx используй:
- Приложение (frontend): [http://junibox/](http://junibox/)
- Backend напрямую: [http://junibox/backend/api/health](http://junibox/backend/api/health)
- Prometheus: [http://junibox/prometheus/](http://junibox/prometheus/)
- Grafana: [http://junibox/grafana/](http://junibox/grafana/)
- Loki readiness: [http://junibox/loki/ready](http://junibox/loki/ready)
- Внутренние URL (доступны из docker-сети): `http://promtail:9080/metrics`, `http://node-exporter:9100/metrics`, `http://pgbackup:8080/`
- Сервис на домашнем сервере (порт 9091): [http://junibox/torrent/](http://junibox/torrent/)
  - Редирект вида `/transmission/web/` автоматически переписывается в `/torrent/transmission/web/`.

### 6) Базовая проверка после развёртывания
```bash
curl -I http://junibox/
curl http://junibox/backend/api/health
curl -I http://junibox/prometheus/
curl -I http://junibox/grafana/
curl -I http://junibox/loki/ready
curl -I http://junibox/torrent/
```

### 7) Обновление проекта
```bash
cd /opt/moex
git pull
docker compose up -d --build
```

### 8) Полезные команды эксплуатации
```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f prometheus
docker compose logs -f grafana
docker compose down
```

### 9) Сохранность данных при перезапусках и потере контейнеров
- Данные PostgreSQL сохраняются в Docker volume `postgres_data`, поэтому при обычном `docker compose down/up` данные не теряются.
- Добавлен сервис `pgbackup`, который делает автоматические бэкапы БД по расписанию в папку `./backups`.

Проверка наличия бэкапов:
```bash
ls -lah /opt/moex/backups
```

Ручной бэкап:
```bash
docker compose exec db pg_dump -U postgres -d fair_price > /opt/moex/backups/manual_$(date +%F_%H-%M-%S).sql
```

Восстановление из бэкапа:
```bash
cat /opt/moex/backups/<backup_file>.sql | docker compose exec -T db psql -U postgres -d fair_price
```

### 10) Если браузер показывает "не удалось загрузить данные"
Это обычно означает, что frontend уже открылся, а backend ещё стартует (миграции БД/инициализация).

Порядок проверки:
```bash
docker compose ps
docker compose logs -f backend
curl http://junibox/backend/api/health
```

Если backend в статусе `healthy` и `{"status":"ok"}`, просто обнови страницу через 10-20 секунд.

### 11) Логи в Grafana через Loki
Loki и Promtail запускаются вместе с приложением. Datasource'ы Prometheus и Loki подключаются в Grafana автоматически через provisioning.
Также автоматически создаётся дашборд **MOEX Home Server & App Overview** (папка `MOEX`) с:
- метриками домашнего сервера (CPU/RAM/Disk через Node Exporter),
- состоянием компонентов (`backend`, `prometheus`, `loki`, `promtail`, `node-exporter`),
- RPS/5xx backend,
- панелью логов Loki с фильтром только важных событий (`error/warn/critical/fatal/exception/failed/timeout`).

Проверка Loki:
```bash
curl -s http://junibox/loki/ready
```

Далее в Grafana:
1. Открой [http://junibox/grafana/](http://junibox/grafana/)
2. Explore → datasource `Loki`
3. Пример запросов:
   - `{container=\\\\"moex-backend\\\\"}`
   - `{container=~\\\\"moex-.*\\\\"}`
   - `{container=~\\\\"moex-(backend|db|frontend|prometheus|grafana|loki|promtail|pgbackup|node-exporter)\\\\"} |~ \\\\"(?i)(error|warn|critical|fatal|panic|exception|failed|timeout)\\\\"`
