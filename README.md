# MOEX Fair Price App (MVP)

MVP веб-приложения на Python для ввода тикера Московской биржи и автоматического получения текущей цены.

## Что реализовано

- Поле ввода тикера и авто-запрос текущей цены (с debounce) на фронтенде.
- Проверка, что тикер торгуется на Московской бирже (рынок акций TQBR).
- Сохранение истории запросов в PostgreSQL.
- Экспорт метрик Prometheus на `/metrics`.
- Запуск приложения и БД в Docker через `docker compose`.

## Быстрый старт

```bash
docker compose up --build
```

После старта:

- Приложение: http://localhost:8000
- Метрики Prometheus: http://localhost:8000/metrics

## Переменные окружения

- `DATABASE_URL` — URL подключения к PostgreSQL.
- `MOEX_TIMEOUT_SECONDS` — таймаут запросов к MOEX API.

## Примечание

В MVP используется публичный ISS API Московской биржи.
