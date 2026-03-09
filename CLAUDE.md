# Telegram Course Downloader

## Описание проекта

Веб-приложение для скачивания видео, аудио и документов из Telegram-каналов/чатов на VDS-сервер. Предназначено для сохранения купленных онлайн-курсов. Обходит клиентские ограничения на копирование/пересылку, работая напрямую через Telegram MTProto API.

**Сценарий использования:**
- Администратор (один раз): подключает Telegram-аккаунт, добавляет курс (ссылку на канал/чат)
- Пользователь: заходит по ссылке, видит список лекций, скачивает новые из Telegram на сервер, затем на свой компьютер, удаляет с сервера

## Технологический стек

- **Backend**: Python 3.11+, Flask 3.x
- **Telegram API**: Telethon (MTProto-клиент), запускается в фоновом asyncio-потоке
- **Frontend**: Vanilla HTML/CSS/JS, Jinja2
- **Данные**: JSON-файл `data.json`, файловая система
- **Деплой**: systemd + nginx reverse proxy (на том же домене что Songbook, путь `/tg/`)

## Структура проекта

```
├── CLAUDE.md                   # Этот файл
├── app.py                      # Flask-приложение: роуты, API
├── downloader.py               # Telethon-клиент: подключение, сканирование, скачивание
├── config.py                   # Загрузка конфигурации из .env
├── requirements.txt            # Python-зависимости
├── .env.example                # Шаблон конфигурации
├── .gitignore
├── templates/
│   ├── login.html              # Страница входа (пароль)
│   ├── main.html               # Основная страница: список файлов курса
│   └── admin.html              # Настройки: подключение TG, добавление курса
├── static/
│   ├── css/style.css           # Стили
│   └── js/app.js               # Клиентская логика
├── deploy.sh                   # Скрипт деплоя
├── telegram-courses.service    # Systemd unit
├── nginx.conf                  # Конфиг nginx (location block)
└── downloads/                  # Скачанные файлы (gitignored)
```

## Архитектурные решения

### Async в sync
Flask синхронный, Telethon асинхронный. Решение: asyncio event loop в отдельном daemon-потоке, вызовы через `asyncio.run_coroutine_threadsafe()`.

### URL Prefix
Приложение работает за nginx по пути `/tg/`. Flask WSGI middleware `PrefixMiddleware` устанавливает `SCRIPT_NAME`, чтобы `url_for()` генерировал правильные URL. Nginx в `proxy_pass` со слешем на конце (`http://127.0.0.1:8080/`) стрипает `/tg` перед проксированием.

### Один курс
MVP рассчитан на один курс. `get_course()` возвращает первый курс из `data.json`. URL не содержат course_id.

## Деплой

Сервер: `ssh wbcc` (тот же VDS что Songbook)
Домен: `abbsongs.duckdns.org/tg/`

```bash
# На сервере — первый раз:
cd /opt
git clone https://github.com/abb1303516/telegram_courses.git telegram-courses
cd telegram-courses
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить
sudo cp telegram-courses.service /etc/systemd/system/
sudo systemctl enable --now telegram-courses
# Добавить location block из nginx.conf в /etc/nginx/sites-enabled/songbook
sudo nginx -t && sudo systemctl reload nginx

# Обновление:
cd /opt/telegram-courses && ./deploy.sh
```

## API-эндпоинты

- `POST /api/telegram/connect` — подключение к Telegram
- `POST /api/telegram/verify` — подтверждение кода
- `GET  /api/telegram/status` — статус подключения
- `POST /api/course/add` — добавить курс `{link, title?}`
- `POST /api/course/rescan` — пересканировать файлы
- `POST /api/course/download` — скачать все новые из Telegram на сервер
- `GET  /api/progress` — прогресс скачивания
- `GET  /download/<filename>` — скачать файл на компьютер
- `POST /api/file/delete` — удалить файл с сервера

## Код-стайл

- Python: PEP 8, type hints
- JS: vanilla, без фреймворков, один файл
- CSS: CSS-переменные, один файл
- Интерфейс: русский
- Комментарии: английский
