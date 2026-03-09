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
├── app.py                      # Flask-приложение: роуты, API, файл-сервер
├── downloader.py               # Telethon-клиент: подключение, сканирование, скачивание, thumbnails
├── config.py                   # Загрузка конфигурации из .env
├── requirements.txt            # Python-зависимости
├── .env.example                # Шаблон конфигурации
├── .gitignore
├── templates/
│   ├── login.html              # Страница входа (пароль, с поддержкой сохранения в браузере)
│   ├── main.html               # Основная страница: список файлов курса с превью
│   └── admin.html              # Настройки: подключение TG, добавление курса
├── static/
│   ├── css/style.css           # Стили (CSS-переменные, адаптивный дизайн)
│   └── js/app.js               # Клиентская логика (AJAX, чекбоксы, hover-превью)
├── deploy.sh                   # Скрипт деплоя
├── telegram-courses.service    # Systemd unit
├── nginx.conf                  # Конфиг nginx (location block)
└── downloads/                  # Скачанные файлы (gitignored)
    └── course_{id}/
        ├── *.mp4, *.jpg, ...   # Медиафайлы
        └── .thumbs/            # Кэш миниатюр из Telegram (~5-20 КБ каждый)
```

## Архитектурные решения

### Async в sync
Flask синхронный, Telethon асинхронный. Решение: asyncio event loop в отдельном daemon-потоке, вызовы через `asyncio.run_coroutine_threadsafe()`.

### URL Prefix
Приложение работает за nginx по пути `/tg/`. Flask WSGI middleware `PrefixMiddleware` устанавливает `SCRIPT_NAME`, чтобы `url_for()` генерировал правильные URL. Nginx в `proxy_pass` со слешем на конце (`http://127.0.0.1:8080/`) стрипает `/tg` перед проксированием.

### Один курс
MVP рассчитан на один курс. `get_course()` возвращает первый курс из `data.json`. URL не содержат course_id.

### Превью файлов
- **Фото**: показывается оригинал если скачан, иначе Telegram-миниатюра
- **Видео**: показывается Telegram-миниатюра (встроенный thumb из метаданных)
- **Аудио/документы**: SVG-иконки по типу
- Миниатюры скачиваются из Telegram при сканировании (rescan/add), кэшируются в `.thumbs/`. Не требует ffmpeg.
- Hover-превью: position:fixed попап с JS-позиционированием (mouseenter/mouseleave)

### Медиа-плеер
- Модальное окно с затемнением для воспроизведения видео/аудио прямо в браузере
- Кнопки перемотки ±5с/±10с, выбор скорости (0.5x–2x), отображение времени
- Клавиши: стрелки ←→ ±5с, пробел пауза/play, Esc закрыть
- Flask `send_file(conditional=True)` для Range-запросов (перемотка)

### Чекбоксы и массовые операции
- Выбор файлов чекбоксами, "Выбрать все" с indeterminate-состоянием
- Массовое скачивание на компьютер (последовательно, по одному с задержкой 500мс)
- Массовое скачивание из TG на сервер
- Массовое удаление

### Приватные каналы
Ссылки формата `t.me/c/CHANNEL_ID/...` обрабатываются отдельно: ID конвертируется с префиксом `-100` для Telethon.

## Деплой

Сервер: `ssh wbcc` (IP `185.221.213.215`, root, тот же VDS что Songbook)
Домен: `https://abbsongs.duckdns.org/tg/`

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
ssh wbcc "cd /opt/telegram-courses && git pull && sudo systemctl restart telegram-courses"
```

## API-эндпоинты

- `POST /api/telegram/connect` — подключение к Telegram
- `POST /api/telegram/verify` — подтверждение кода `{code}`
- `GET  /api/telegram/status` — статус подключения
- `POST /api/course/add` — добавить курс `{link, title?}`
- `POST /api/course/rescan` — пересканировать файлы (+ фоновое скачивание thumbs)
- `POST /api/course/download` — скачать только НОВЫЕ файлы из Telegram на сервер
- `POST /api/file/download-tg` — скачать один файл из TG `{filename}`
- `POST /api/file/delete` — удалить файл с сервера `{filename}`
- `GET  /api/progress` — прогресс скачивания
- `GET  /download/<filename>` — скачать файл на компьютер
- `GET  /stream/<filename>` — стриминг видео/аудио (Range-запросы для перемотки)
- `GET  /preview/<filename>` — превью (оригинал для фото, thumb для видео)

## Код-стайл

- Python: PEP 8, type hints
- JS: vanilla, без фреймворков, один файл
- CSS: CSS-переменные, один файл
- Интерфейс: русский
- Комментарии: английский

## Ограничения сервера

- Мало места на диске — НЕ устанавливать тяжёлые пакеты (ffmpeg и т.п.)
- Один процесс скачивания одновременно (блокировка `downloader.downloading`)
