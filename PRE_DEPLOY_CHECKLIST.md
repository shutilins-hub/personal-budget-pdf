# Pre-deploy checklist

Перед покупкой VPS или закрытым онлайн-запуском проверьте:

- [ ] `python3 -m compileall .` проходит.
- [ ] `python3 -m unittest discover tests` проходит.
- [ ] `python3 -W error::ResourceWarning -m unittest discover tests` проходит.
- [ ] `BUDGET_DEBUG_EXPORTS=0` по умолчанию.
- [ ] Debug-файлы не создаются без явного `BUDGET_DEBUG_EXPORTS=1`.
- [ ] Авторизация включается через `APP_AUTH_ENABLED=1`.
- [ ] При `APP_AUTH_ENABLED=1` задан `APP_PASSWORD` или `APP_PASSWORD_HASH`.
- [ ] `MAX_UPLOAD_MB` блокирует слишком большие PDF.
- [ ] `DATA_DIR` и `EXPORTS_DIR` вынесены из репозитория.
- [ ] `data/`, `exports/`, `*.pdf`, `*.sqlite3`, `*.db`, `.env` не отслеживаются git.
- [ ] Локальный сценарий пройден: профиль -> загрузка -> очистка -> план -> контроль.
- [ ] Репозиторий переведён в private.
- [ ] Подготовлен домен или поддомен.
- [ ] Streamlit будет слушать только `127.0.0.1`, внешний доступ через nginx.
- [ ] На сервере включён HTTPS.
