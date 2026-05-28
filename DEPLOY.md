# Подготовка к будущему закрытому онлайн-запуску

Фактический деплой сейчас не выполняется. Этот документ описывает безопасную схему для будущего VPS.

## Схема

Пользователь открывает домен, nginx принимает HTTPS-трафик и проксирует запросы в локальный Streamlit:

```text
пользователь -> домен -> nginx -> 127.0.0.1:8501 Streamlit -> SQLite/DATA_DIR
```

Streamlit-порт нельзя открывать напрямую наружу. Он должен слушать `127.0.0.1`, а внешний доступ должен идти через nginx и HTTPS.

## Обязательные env

Пример лежит в `deploy/.env.example`.

- `APP_ENV=production`
- `APP_AUTH_ENABLED=1`
- `APP_USERNAME=admin`
- `APP_PASSWORD` или `APP_PASSWORD_HASH`
- `APP_SECRET_KEY`
- `BUDGET_DEBUG_EXPORTS=0`
- `DATA_DIR=/var/lib/personal-budget-pdf/data`
- `EXPORTS_DIR=/var/lib/personal-budget-pdf/exports`
- `MAX_UPLOAD_MB=100`

Не храните реальные секреты в репозитории. На сервере env лучше положить в `/etc/personal-budget-pdf.env` с правами только для служебного пользователя.

## Что подготовить на сервере

1. Закрытый private-репозиторий.
2. Отдельного пользователя, например `personal-budget`.
3. Директории `DATA_DIR` и `EXPORTS_DIR` вне репозитория.
4. Python virtualenv и зависимости из `requirements.txt`.
5. systemd unit на основе `deploy/personal-budget-pdf.service.example`.
6. nginx config на основе `deploy/nginx.personal-budget-pdf.conf.example`.
7. HTTPS-сертификат.

## Почему репозиторий должен быть private

Приложение работает с финансовыми выписками. Даже при выключенных debug-exports риск случайных тестовых данных, профилей или локальных настроек выше нормы. До внешнего запуска репозиторий лучше держать private.

## Проверка перед запуском

Перед будущим деплоем пройдите `PRE_DEPLOY_CHECKLIST.md`.
