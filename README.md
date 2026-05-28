# Личный бюджет по PDF

Локальное Streamlit-приложение для личного бюджета по PDF-выпискам банков. PDF обрабатываются на машине пользователя: в базу попадают операции, а исходные файлы по умолчанию не сохраняются.

## Что умеет MVP

- импортировать PDF-выписки накопительно, без обнуления истории;
- пропускать дубли операций через `duplicate_key`;
- вести профили и правила классификации;
- разделять доходы, расходы, компенсации, внутренние переводы и проектные обороты;
- строить план месяца и контроль бюджета;
- показывать финансовую оценку месяца с учётом качества данных.

## Поддерживаемые документы

В проекте есть адаптеры для Сбера, Т-Банка, Яндекс Банка, ВБ Банка, Альфа-Банка и Совкомбанка/Халвы. Нерелевантные PDF должны пропускаться без импорта операций.

## Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Локальный запуск

```bash
streamlit run app.py
```

Без env приложение запускается в локальном dev-режиме:

- авторизация выключена;
- debug-exports выключены;
- данные лежат в `data/`;
- debug/export директория по умолчанию `exports/`;
- лимит PDF-загрузки `100` МБ.

## Авторизация для закрытого теста

Временный вход можно включить через env:

```bash
APP_AUTH_ENABLED=1 APP_USERNAME=admin APP_PASSWORD=secret streamlit run app.py
```

Можно использовать hash вместо открытого пароля:

```bash
APP_AUTH_ENABLED=1 APP_USERNAME=admin APP_PASSWORD_HASH=<sha256> streamlit run app.py
```

Пароли не хранятся в SQLite и не должны попадать в репозиторий.

## Настройки через env

- `APP_ENV` — окружение, по умолчанию `local`.
- `APP_AUTH_ENABLED` — `1/true/yes/on`, чтобы включить закрытый вход.
- `APP_USERNAME` — логин, по умолчанию `admin`.
- `APP_PASSWORD` — пароль для закрытого теста.
- `APP_PASSWORD_HASH` — SHA-256 hash пароля.
- `APP_SECRET_KEY` — будущий секрет приложения, не хранить в коде.
- `BUDGET_DEBUG_EXPORTS` — debug-выгрузки, по умолчанию выключены.
- `DATA_DIR` — где хранить SQLite и профили.
- `EXPORTS_DIR` — где хранить debug/export-файлы при включённом debug.
- `MAX_UPLOAD_MB` — максимальный размер PDF, по умолчанию `100`.

Пример production-env лежит в `deploy/.env.example`.

## Данные и приватность

Локальные данные:

- SQLite-база: `data/budget.sqlite3` или путь из `DATA_DIR`;
- профили и правила: `data/profiles/`;
- debug/export-файлы: `exports/` или путь из `EXPORTS_DIR`.

PDF-файлы не должны сохраняться в репозитории. Debug-выгрузки выключены по умолчанию. Если включить `BUDGET_DEBUG_EXPORTS=1`, данные перед записью проходят через маскирование в `privacy.py`.

## Проверка

```bash
python3 -m compileall .
python3 -m unittest discover tests
python3 -W error::ResourceWarning -m unittest discover tests
```

Перед будущим деплоем смотрите `PRE_DEPLOY_CHECKLIST.md` и `DEPLOY.md`.
