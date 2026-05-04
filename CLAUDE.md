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
│   └── js/app.js               # Клиентская логика (AJAX, чекбоксы, hover-превью, медиа-плеер)
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

### Форумы с темами (topics)
Telegram-группы могут быть форумами с несколькими темами. `iter_messages(entity)` без `reply_to` возвращает сообщения из всех тем. Сканер корректно находит все медиа-файлы из всех тем.

### Дедупликация имён файлов
Telegram может давать разным файлам одинаковые имена (например, `record.mp4`). При сканировании `scan_chat()` обнаруживает дубликаты и добавляет суффикс `_msgID` (`record_35.mp4`, `record_43.mp4`). Суффикс стабилен — повторное сканирование даёт те же имена.

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

### Сортировка файлов
- Клиентская сортировка (JS) по дате поста, имени, размеру, типу
- По умолчанию: по дате поста, новые внизу (asc)
- Клик по активной кнопке переключает направление (▲/▼)
- Данные для сортировки в data-атрибутах `.file-row` (`data-date`, `data-size`, `data-type`)
- Дата поста отображается в `.file-meta` формате `дд.мм.гггг`

### Чекбоксы и массовые операции
- Выбор файлов чекбоксами, "Выбрать все" с indeterminate-состоянием
- Массовое скачивание на компьютер (последовательно, по одному с задержкой 500мс)
- Массовое скачивание из TG на сервер
- Массовое удаление

### Макет страницы (fixed toolbar + scrollable list)
- `body.main-page { height: 100vh; overflow: hidden }` — страница не прокручивается
- `.container` — flex column на всю высоту
- `.toolbar` (`flex-shrink: 0`) — заголовок, кнопки, алерты, bulk bar, прогресс — всегда видны
- `.file-list` (`flex: 1; overflow-y: auto; min-height: 0`) — единственная прокручиваемая область
- Bulk bar показывается/скрывается через `max-height/opacity` transition (не `display:none`, т.к. ломает layout)

### Хостинг приложения
Приложение перенесено с RU VDS на **NL VDS** (`188.208.103.65`, Hostkey B.v., Нидерланды). Причина: Telegram заблокирован в РФ с марта 2026 (DPI/ТСПУ), маршрут NL→RU зашейплен до 30 КБ/с. На NL — прямой быстрый доступ к Telegram (75 МБ/с) без прокси и туннелей.

**Архитектура NL VDS:**
- Python 3.10 + venv + systemd-сервис `telegram-courses` (без Docker)
- Flask слушает на `0.0.0.0:8181` (не за nginx)
- Пользователи заходят на `http://188.208.103.65:8181` через AmneziaVPN
- `URL_PREFIX=` пустой, `HOST=0.0.0.0`, `PROXY=` пустой (direct TG)
- Часы: `chrony` (NTP-синхронизация обязательна — Telethon отваливается при дрейфе >5с)

**Background tasks (Python 3.10 фикс):** функция `run_background()` в `app.py` сохраняет ссылки на futures от `asyncio.run_coroutine_threadsafe()` в `_background_futures`, чтобы Python 3.10 не собирал их GC посреди выполнения (в 3.11+ это не проявлялось из-за менее строгого GC, но best practice одинаковая).

**Прогресс скачивания:** `progress_callback` в Telethon отдаёт байты, JS поллит `/api/progress` раз в секунду.

### Резервная инфраструктура на RU VDS (для других проектов и на случай новых блокировок)
Приложение переехало на NL, но каналы на RU VDS оставлены — пригодятся при новых блокировках.
- **AmneziaWG туннель** (Docker `awg0`, образ `amneziavpn/amneziawg-go`) — маршрутизирует IP Telegram через `awg2` контейнер на NL (UDP 48588, обфусцированный WG).
- **SSH SOCKS5 туннель** (`ssh-tunnel-nl.service`) — порт 9150, SSH-ключ `id_ed25519` RU→NL.
- **SSH watchdog** (`ssh-tunnel-nl-watchdog.timer`) — раз в минуту проверяет туннель, перезапускает при обрыве.
- **Squid HTTP-прокси** на NL (`188.208.103.65:3128`) — используется kinescope-downloader, остаётся.

Каскад защиты: direct → Squid → SSH SOCKS5 → AmneziaWG. Код в `downloader.py:_parse_proxy()` поддерживает `PROXY=http://...` или `socks5://...` — если DPI опять станет агрессивным, в `.env` можно включить любой из каналов.

### Приватные каналы
Ссылки формата `t.me/c/CHANNEL_ID/...` обрабатываются отдельно: ID конвертируется с префиксом `-100` для Telethon.

## Деплой

Сервер: `ssh kinescope-vds` (IP `188.208.103.65`, root, голландский VDS Hostkey B.v.)
URL: `http://188.208.103.65:8181` (через AmneziaVPN пользователя)

Пользователи: администратор + 1 близкий пользователь. Без HTTPS/домена — трафик зашифрован AmneziaVPN пользователя.

```bash
# На сервере — первый раз:
cd /opt
git clone https://github.com/abb1303516/telegram_courses.git telegram-courses
cd telegram-courses
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить: HOST=0.0.0.0, PORT=8181, URL_PREFIX=, PROXY=
# Создать systemd-сервис /etc/systemd/system/telegram-courses.service
sudo systemctl enable --now telegram-courses

# Обновление:
ssh kinescope-vds "cd /opt/telegram-courses && git pull && systemctl restart telegram-courses"
```

**Важно:** часы на сервере должны быть синхронизированы (`apt install chrony`), иначе Telethon падает с "Security error: Too many messages had to be ignored consecutively".

## Резервный сервер (cold standby) — план

Когда появится второй VPS, развернуть на нём идентичную копию приложения, держать выключенной, периодически синхронизировать секреты. При падении основного — переключение за ~30 секунд.

**Что синхронизируется** (~170 КБ всего, sync почти мгновенный):
- `.env` — секреты, конфигурация
- `session.session` — авторизация Telethon
- `data.json` — метаданные курса

**Что НЕ синхронизируется:**
- Код приложения — берётся из git (`git pull`)
- Папка `downloads/` — временные файлы, не нужно дублировать (МБ-ГБ)

**Скрипт синхронизации** (запускать на резервном сервере вручную после понедельничного rescan, или cron раз в сутки):
```bash
#!/bin/bash
# /usr/local/bin/sync-from-primary.sh
PRIMARY=primary-server-alias
cd /opt/telegram-courses
git pull
rsync -a $PRIMARY:/opt/telegram-courses/.env .
rsync -a $PRIMARY:/opt/telegram-courses/session.session .
rsync -a $PRIMARY:/opt/telegram-courses/data.json .
```

**Сервис на резерве:** установлен через systemd, но `systemctl disable` (не запускается автоматически).

**При переключении** (основной упал):
1. SSH на резерв
2. Запустить `sync-from-primary.sh` (на случай если последняя синхронизация запоздала)
3. `systemctl start telegram-courses`
4. Открыть IP резервного сервера в браузере
5. Закладку браузера обновить на новый IP

**Почему cold standby, а не active-active:**
Telegram-сессия привязана к одному устройству. Два одновременных Telethon-клиента с одной сессией постоянно конфликтуют за авторизацию. Active-active возможен только с разными TG-сессиями, что сильно усложняет схему.

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
