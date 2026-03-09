# 📚 Мои Курсы — Telegram Media Downloader

Веб-приложение для скачивания видео, аудио и документов из Telegram-каналов на ваш сервер (VDS).
Обходит ограничения на копирование/пересылку. Простой интерфейс для всей семьи.

---

## Что умеет

- Скачивает видео, аудио, документы и фото из любых Telegram-каналов и чатов
- Работает даже если в чате запрещено копирование и пересылка
- Воспроизведение видео и аудио прямо в браузере (перемотка, скорость 0.5x–2x)
- Превью изображений и видео (миниатюры из Telegram, без ffmpeg)
- Увеличенное превью при наведении мыши
- Чекбоксы для массовых операций (скачать, удалить)
- Скачивание файлов по одному (последовательно, без ZIP)
- Скачивание отдельных файлов из Telegram на сервер
- Докачка — скачивает только новые файлы, уже скачанные пропускает
- Мобильная версия (адаптивный интерфейс)
- Поддержка приватных каналов (ссылки `t.me/c/...`)

---

## Установка на VDS (5 минут)

### 1. Подготовка

```bash
# Обновляем систему
sudo apt update && sudo apt upgrade -y

# Устанавливаем Python (если ещё нет)
sudo apt install -y python3 python3-pip python3-venv git
```

### 2. Скачиваем проект

```bash
# Создаём папку и заходим в неё
mkdir -p ~/telegram-courses
cd ~/telegram-courses

# Скопируйте все файлы проекта сюда (через scp, git, или вручную)
```

### 3. Создаём виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Получаем Telegram API ключи

1. Откройте https://my.telegram.org
2. Войдите по номеру телефона
3. Перейдите в "API Development Tools"
4. Создайте приложение (название любое)
5. Скопируйте **api_id** и **api_hash**

### 5. Настраиваем конфигурацию

```bash
# Копируем шаблон
cp .env.example .env

# Редактируем
nano .env
```

Заполните:
```
API_ID=ваш_api_id
API_HASH=ваш_api_hash
PHONE=+7XXXXXXXXXX         # номер телефона аккаунта Telegram
APP_PASSWORD=вашпароль      # пароль для входа в веб-интерфейс
SECRET_KEY=любая-случайная-строка
```

### 6. Первый запуск

```bash
source venv/bin/activate
python app.py
```

Откройте в браузере: `http://ваш-ip:8080`

1. Войдите с паролем из `.env`
2. Перейдите в **Настройки** → нажмите **Подключить**
3. Введите код, который придёт в Telegram
4. Готово! Перейдите в **Курсы** → **Добавить курс**

### 7. Автозапуск (systemd)

Чтобы приложение работало постоянно:

```bash
sudo nano /etc/systemd/system/telegram-courses.service
```

Вставьте (замените `your_user` на имя пользователя):

```ini
[Unit]
Description=Telegram Courses Downloader
After=network.target

[Service]
User=your_user
WorkingDirectory=/home/your_user/telegram-courses
ExecStart=/home/your_user/telegram-courses/venv/bin/python app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-courses
sudo systemctl start telegram-courses

# Проверить статус:
sudo systemctl status telegram-courses
```

---

## Использование

### Для вас (администратор)

1. **Настройки** — подключение Telegram (один раз)
2. **Курсы → Добавить курс** — вставляете ссылку на канал/чат
3. Система сканирует чат и показывает список файлов
4. Нажимаете **Скачать всё из Telegram** — файлы качаются на VDS

### Для супруги

1. Открывает ссылку в браузере (пароль сохраняется)
2. Видит список файлов с превью
3. Нажимает **Скачать** на нужный файл
4. Или отмечает чекбоксами несколько файлов → **Скачать на компьютер**
5. Ненужные файлы можно удалить с сервера

---

## Форматы ссылок на чат

Все эти форматы работают:

- `https://t.me/channelname`
- `https://t.me/c/1234567890/1` — приватные каналы
- `https://t.me/+invitehash`
- `@channelname`
- Числовой ID: `-1001234567890`

---

## Безопасность

⚠️ Приложение открывает порт на VDS. Рекомендации:

- Используйте **надёжный пароль** в `APP_PASSWORD`
- Ограничьте доступ через **firewall** (ufw):
  ```bash
  sudo ufw allow from ваш_домашний_ip to any port 8080
  ```
- Для HTTPS можно поставить **nginx** как реверс-прокси с Let's Encrypt

---

## Устранение проблем

| Проблема | Решение |
|----------|---------|
| "Telegram не подключён" | Настройки → Подключить. Проверьте api_id/hash в .env |
| "Уже идёт загрузка" | Дождитесь завершения текущей загрузки |
| Файлы не качаются | Убедитесь, что аккаунт подписан на канал |
| Ошибка при добавлении курса | Проверьте формат ссылки. Попробуйте @username |
| Порт не открывается | `sudo ufw allow 8080` или проверьте настройки VDS |

---

## Структура проекта

```
telegram-courses/
├── app.py              # Веб-сервер (Flask)
├── downloader.py       # Telegram-клиент (Telethon)
├── config.py           # Конфигурация
├── .env                # Ваши настройки (не коммитить!)
├── .env.example        # Шаблон настроек
├── requirements.txt    # Зависимости Python
├── data.json           # Данные о курсах (создаётся автоматически)
├── session.session     # Сессия Telegram (создаётся автоматически)
├── downloads/          # Скачанные файлы
│   └── course_{id}/
│       └── .thumbs/    # Кэш миниатюр из Telegram
├── templates/          # HTML-шаблоны
│   ├── login.html
│   ├── main.html
│   └── admin.html
└── static/
    ├── css/style.css
    └── js/app.js
```
