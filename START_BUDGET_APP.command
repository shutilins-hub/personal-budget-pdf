#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Личный бюджет по PDF"
echo "Папка приложения: $(pwd)"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 не найден."
  echo "Установите Python 3 с https://www.python.org/downloads/ и запустите этот файл снова."
  read -p "Нажмите Enter, чтобы закрыть окно..."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Создаю виртуальное окружение..."
  python3 -m venv .venv
fi

echo "Проверяю зависимости..."
".venv/bin/python" -m pip install --upgrade pip
".venv/bin/python" -m pip install -r requirements.txt

mkdir -p "$HOME/.streamlit"
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
  printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

echo
echo "Запускаю приложение."
echo "Если браузер не открылся сам, откройте адрес: http://localhost:8501"
echo "Чтобы остановить приложение, закройте это окно или нажмите Ctrl+C."
echo

export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

".venv/bin/streamlit" run app.py \
  --server.port 8501 \
  --server.headless false \
  --server.showEmailPrompt false \
  --browser.gatherUsageStats false
