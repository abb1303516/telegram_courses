/* -- Helpers -- */

function showStatus(el, msg, type) {
    el.textContent = msg;
    el.className = 'status-msg ' + type;
    el.style.display = 'block';
}

async function api(url, data) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    return res.json();
}

/* -- Telegram Connect (admin page) -- */

async function connectTelegram() {
    const btn = document.getElementById('connectBtn');
    const statusEl = document.getElementById('connectStatus');

    btn.disabled = true;
    btn.textContent = 'Подключаю...';
    showStatus(statusEl, 'Подключаюсь к Telegram...', 'loading');

    try {
        const data = await api('./api/telegram/connect');

        if (data.ok) {
            if (data.status === 'connected') {
                showStatus(statusEl, 'Telegram подключён!', 'ok');
                document.getElementById('tgStatus').textContent = 'Подключён';
                document.getElementById('tgStatus').className = 'badge badge-ok';
                setTimeout(() => location.reload(), 1000);
            } else if (data.status === 'code_sent') {
                showStatus(statusEl, 'Код отправлен в Telegram.', 'loading');
                document.getElementById('codeSection').style.display = 'block';
                document.getElementById('tgCode').focus();
            }
        } else {
            showStatus(statusEl, 'Ошибка: ' + data.error, 'error');
        }
    } catch (e) {
        showStatus(statusEl, 'Ошибка: ' + e.message, 'error');
    }

    btn.disabled = false;
    btn.textContent = 'Подключить';
}

async function verifyCode() {
    const code = document.getElementById('tgCode').value.trim();
    const statusEl = document.getElementById('connectStatus');
    if (!code) return;

    showStatus(statusEl, 'Проверяю код...', 'loading');

    try {
        const data = await api('./api/telegram/verify', { code });

        if (data.ok) {
            showStatus(statusEl, 'Telegram подключён!', 'ok');
            document.getElementById('tgStatus').textContent = 'Подключён';
            document.getElementById('tgStatus').className = 'badge badge-ok';
            document.getElementById('codeSection').style.display = 'none';
            setTimeout(() => location.reload(), 1000);
        } else {
            showStatus(statusEl, 'Ошибка: ' + data.error, 'error');
        }
    } catch (e) {
        showStatus(statusEl, 'Ошибка: ' + e.message, 'error');
    }
}

/* -- Add Course (admin page) -- */

async function addCourse() {
    const link = document.getElementById('chatLink').value.trim();
    const title = document.getElementById('courseTitle')?.value.trim() || '';
    const statusEl = document.getElementById('addStatus');
    const btn = document.getElementById('addCourseBtn');

    if (!link) {
        showStatus(statusEl, 'Введите ссылку на чат', 'error');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Добавляю...';
    showStatus(statusEl, 'Ищу чат и сканирую файлы...', 'loading');

    try {
        const data = await api('./api/course/add', { link, title });

        if (data.ok) {
            showStatus(statusEl, 'Готово! Найдено файлов: ' + data.total_files, 'ok');
            setTimeout(() => { window.location.href = './'; }, 1000);
        } else {
            showStatus(statusEl, 'Ошибка: ' + data.error, 'error');
        }
    } catch (e) {
        showStatus(statusEl, 'Ошибка: ' + e.message, 'error');
    }

    btn.disabled = false;
    btn.textContent = 'Добавить';
}

/* -- Rescan (main page) -- */

async function rescan() {
    const btn = document.getElementById('btnRescan');
    btn.disabled = true;
    btn.textContent = 'Обновляю...';

    try {
        const data = await api('./api/course/rescan');
        if (data.ok) {
            location.reload();
        } else {
            alert('Ошибка: ' + data.error);
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }

    btn.disabled = false;
    btn.textContent = 'Обновить список';
}

/* -- Download All from Telegram (main page) -- */

async function downloadAll() {
    const btn = document.getElementById('btnDownloadAll');
    btn.disabled = true;
    btn.textContent = 'Запускаю...';

    try {
        const data = await api('./api/course/download');
        if (data.ok) {
            document.getElementById('progressSection').style.display = 'block';
            pollProgress();
        } else {
            alert('Ошибка: ' + data.error);
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }

    btn.disabled = false;
    btn.textContent = 'Скачать из Telegram';
}

/* -- Progress Polling -- */

function pollProgress() {
    const interval = setInterval(async () => {
        try {
            const res = await fetch('./api/progress');
            const data = await res.json();
            const pct = data.total > 0 ? (data.done / data.total * 100) : 0;

            document.getElementById('progressText').textContent =
                'Скачивание: ' + data.done + ' / ' + data.total;
            document.getElementById('progressFile').textContent =
                data.current_file || '';
            document.getElementById('progressBar').style.width = pct + '%';

            if (data.status === 'completed') {
                clearInterval(interval);
                document.getElementById('progressText').textContent =
                    'Готово! Скачано ' + data.done + ' файлов.';
                document.getElementById('progressFile').textContent = '';

                if (data.errors && data.errors.length > 0) {
                    document.getElementById('progressText').textContent +=
                        ' (ошибок: ' + data.errors.length + ')';
                }

                setTimeout(() => location.reload(), 2000);
            }
        } catch (e) {
            // ignore polling errors
        }
    }, 2000);
}

/* -- Download Single File from TG (main page) -- */

async function downloadSingle(filename, btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = 'Загрузка...';

    try {
        const data = await api('./api/file/download-tg', { filename });

        if (data.ok) {
            // File is now on server — reload to show download/delete buttons
            location.reload();
        } else {
            alert('Ошибка: ' + data.error);
            btnEl.disabled = false;
            btnEl.textContent = 'Скачать из TG';
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
        btnEl.disabled = false;
        btnEl.textContent = 'Скачать из TG';
    }
}

/* -- Delete File (main page) -- */

async function deleteFile(filename, btnEl) {
    if (!confirm('Удалить "' + filename + '" с сервера?')) return;

    btnEl.disabled = true;

    try {
        const data = await api('./api/file/delete', { filename });

        if (data.ok) {
            const row = btnEl.closest('.file-row');
            row.classList.add('removing');
            setTimeout(() => {
                row.classList.remove('file-on-server');
                row.classList.add('file-pending');
                row.classList.remove('removing');
                const meta = row.querySelector('.file-meta');
                if (meta) {
                    meta.innerHTML = '<span class="badge-pending">в Telegram</span>';
                }
                const actions = row.querySelector('.file-actions');
                if (actions) actions.innerHTML = '';
            }, 300);
        } else {
            alert('Ошибка: ' + data.error);
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }

    btnEl.disabled = false;
}

/* -- Enter to submit code on admin page -- */

document.addEventListener('DOMContentLoaded', () => {
    const codeInput = document.getElementById('tgCode');
    if (codeInput) {
        codeInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') verifyCode();
        });
    }
});
