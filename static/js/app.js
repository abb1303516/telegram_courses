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
    const label = btn.textContent.trim();
    if (!confirm('Запустить скачивание из Telegram?\n\n' + label)) return;

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

/* -- Cancel running download -- */

async function cancelDownload() {
    const btn = document.getElementById('btnCancelDownload');
    if (btn) { btn.disabled = true; btn.textContent = 'Отменяю...'; }
    try {
        await api('./api/course/download/cancel');
        // pollProgress will pick up "cancelled" status and reload the page
    } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = 'Отменить загрузку'; }
    }
}

/* -- Progress Polling -- */

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 Б';
    var units = ['Б', 'КБ', 'МБ', 'ГБ'];
    var i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}

function pollProgress() {
    // Guard against multiple overlapping pollers (page reload + click race)
    if (pollProgress._timer) return;

    var section = document.getElementById('progressSection');
    if (section) section.style.display = 'block';
    var cancelBtn = document.getElementById('btnCancelDownload');
    if (cancelBtn) { cancelBtn.style.display = ''; cancelBtn.disabled = false; cancelBtn.textContent = 'Отменить загрузку'; }

    const interval = setInterval(async () => {
        try {
            const res = await fetch('./api/progress');
            const data = await res.json();

            if (data.status === 'idle') return;

            // Byte-level progress for current file
            var bytesPct = 0;
            var bytesText = '';
            if (data.bytes_total > 0) {
                bytesPct = data.bytes_done / data.bytes_total * 100;
                bytesText = formatBytes(data.bytes_done) + ' / ' + formatBytes(data.bytes_total);
            }

            // File-level progress (for bulk downloads)
            var fileText = '';
            if (data.total > 1) {
                fileText = 'Файл ' + (data.done + 1) + ' из ' + data.total + ': ';
            }

            document.getElementById('progressText').textContent =
                fileText + (bytesText || 'Скачивание...');
            document.getElementById('progressFile').textContent =
                data.current_file || '';

            // Progress bar: for single file use bytes, for bulk use file count
            var pct = data.total > 1
                ? ((data.done + bytesPct / 100) / data.total * 100)
                : bytesPct;
            document.getElementById('progressBar').style.width = pct + '%';

            if (data.status === 'cancelled') {
                clearInterval(interval);
                pollProgress._timer = null;
                var cb = document.getElementById('btnCancelDownload');
                if (cb) cb.style.display = 'none';
                document.getElementById('progressText').textContent =
                    'Загрузка отменена. Скачано ' + data.done + (data.total > 1 ? ' из ' + data.total : '') + '.';
                document.getElementById('progressFile').textContent = '';
                setTimeout(() => location.reload(), 1500);
                return;
            }

            if (data.status === 'completed') {
                clearInterval(interval);
                pollProgress._timer = null;
                var cb2 = document.getElementById('btnCancelDownload');
                if (cb2) cb2.style.display = 'none';
                document.getElementById('progressBar').style.width = '100%';
                document.getElementById('progressText').textContent =
                    'Готово! Скачано ' + data.done + (data.total > 1 ? ' файлов.' : ' файл.');
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
    }, 1000);
    pollProgress._timer = interval;
}

/* -- Download Single File from TG (main page) -- */

async function downloadSingle(filename, btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = 'Загрузка...';

    try {
        const data = await api('./api/file/download-tg', { filename });

        if (data.ok) {
            pollProgress();
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
            setTimeout(() => location.reload(), 400);
        } else {
            alert('Ошибка: ' + data.error);
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }

    btnEl.disabled = false;
}

/* ========== Checkbox Selection ========== */

function getChecked() {
    return Array.from(document.querySelectorAll('.file-check:checked')).map(c => c.value);
}

function updateSelection() {
    const checked = getChecked();
    const bulkBar = document.getElementById('bulkBar');
    const selText = document.getElementById('selectionText');
    const selectAll = document.getElementById('selectAll');

    if (!bulkBar) return;

    if (checked.length > 0) {
        bulkBar.classList.add('visible');
        if (selText) selText.textContent = 'Выбрано: ' + checked.length;
    } else {
        bulkBar.classList.remove('visible');
        if (selText) selText.textContent = 'Выбрано: 0';
    }

    // Update select all checkbox state
    const all = document.querySelectorAll('.file-check');
    if (all.length > 0 && checked.length === all.length) {
        selectAll.checked = true;
        selectAll.indeterminate = false;
    } else if (checked.length > 0) {
        selectAll.checked = false;
        selectAll.indeterminate = true;
    } else {
        selectAll.checked = false;
        selectAll.indeterminate = false;
    }

    // Highlight selected rows
    document.querySelectorAll('.file-row').forEach(row => {
        const cb = row.querySelector('.file-check');
        row.classList.toggle('selected', cb && cb.checked);
    });
}

function toggleSelectAll() {
    const selectAll = document.getElementById('selectAll');
    document.querySelectorAll('.file-check').forEach(cb => {
        cb.checked = selectAll.checked;
    });
    updateSelection();
}

/* -- Bulk Download to Computer (sequential) -- */

async function bulkDownload() {
    const checked = getChecked();
    // Filter to only files on server
    const onServer = checked.filter(name => {
        const row = document.querySelector('.file-row[data-filename="' + CSS.escape(name) + '"]');
        return row && row.dataset.onServer === 'true';
    });

    if (onServer.length === 0) {
        alert('Нет файлов на сервере для скачивания');
        return;
    }

    // Download files one by one with a delay
    for (let i = 0; i < onServer.length; i++) {
        const a = document.createElement('a');
        a.href = './download/' + encodeURIComponent(onServer[i]);
        a.download = onServer[i];
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        // Small delay between downloads so browser doesn't block them
        if (i < onServer.length - 1) {
            await new Promise(r => setTimeout(r, 500));
        }
    }
}

/* -- Bulk Download from TG -- */

async function bulkDownloadTG() {
    const checked = getChecked();
    const pending = checked.filter(name => {
        const row = document.querySelector('.file-row[data-filename="' + CSS.escape(name) + '"]');
        return row && row.dataset.onServer === 'false';
    });

    if (pending.length === 0) {
        alert('Все выбранные файлы уже на сервере');
        return;
    }

    if (!confirm('Скачать ' + pending.length + ' файлов из Telegram на сервер?')) return;

    for (const filename of pending) {
        const row = document.querySelector('.file-row[data-filename="' + CSS.escape(filename) + '"]');
        const btn = row ? row.querySelector('.file-actions .btn') : null;
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Загрузка...';
        }

        try {
            await api('./api/file/download-tg', { filename });
        } catch (e) {
            // continue with next file
        }
    }

    location.reload();
}

/* -- Bulk Delete -- */

async function bulkDelete() {
    const checked = getChecked();
    const onServer = checked.filter(name => {
        const row = document.querySelector('.file-row[data-filename="' + CSS.escape(name) + '"]');
        return row && row.dataset.onServer === 'true';
    });

    if (onServer.length === 0) {
        alert('Нет файлов на сервере для удаления');
        return;
    }

    if (!confirm('Удалить ' + onServer.length + ' файлов с сервера?')) return;

    for (const filename of onServer) {
        try {
            await api('./api/file/delete', { filename });
        } catch (e) {
            // continue
        }
    }

    location.reload();
}

/* -- Hover Preview -- */

function initHoverPreviews() {
    document.querySelectorAll('.file-preview').forEach(el => {
        const popup = el.querySelector('.hover-preview');
        if (!popup) return;

        el.addEventListener('mouseenter', (e) => {
            const rect = el.getBoundingClientRect();
            popup.style.display = 'block';
            // Position to the right of thumbnail
            let left = rect.right + 12;
            let top = rect.top + rect.height / 2 - popup.offsetHeight / 2;
            // Keep within viewport
            if (left + popup.offsetWidth > window.innerWidth - 16) {
                left = rect.left - popup.offsetWidth - 12;
            }
            if (top < 8) top = 8;
            if (top + popup.offsetHeight > window.innerHeight - 8) {
                top = window.innerHeight - popup.offsetHeight - 8;
            }
            popup.style.left = left + 'px';
            popup.style.top = top + 'px';
        });

        el.addEventListener('mouseleave', () => {
            popup.style.display = 'none';
        });
    });
}

/* -- Media Player -- */

function openPlayer(filename, type) {
    const overlay = document.getElementById('playerOverlay');
    const body = document.getElementById('playerBody');
    const title = document.getElementById('playerTitle');

    title.textContent = filename;

    const src = './stream/' + encodeURIComponent(filename);
    const tag = type === 'video' ? 'video' : 'audio';
    const cls = type === 'video' ? 'player-video' : 'player-audio';

    body.innerHTML =
        '<div class="player-controls-bar">' +
            '<button class="player-skip" onclick="playerSkip(-10)">-10s</button>' +
            '<button class="player-skip" onclick="playerSkip(-5)">-5s</button>' +
            '<span class="player-time" id="playerTime">0:00 / 0:00</span>' +
            '<button class="player-skip" onclick="playerSkip(5)">+5s</button>' +
            '<button class="player-skip" onclick="playerSkip(10)">+10s</button>' +
            '<select class="player-speed" onchange="playerSetSpeed(this.value)">' +
                '<option value="0.5">0.5x</option>' +
                '<option value="0.75">0.75x</option>' +
                '<option value="1" selected>1x</option>' +
                '<option value="1.25">1.25x</option>' +
                '<option value="1.5">1.5x</option>' +
                '<option value="2">2x</option>' +
            '</select>' +
        '</div>' +
        '<' + tag + ' controls autoplay class="' + cls + '" id="playerMedia">' +
            '<source src="' + src + '">' +
        '</' + tag + '>';

    var media = document.getElementById('playerMedia');
    media.addEventListener('timeupdate', updatePlayerTime);
    media.addEventListener('loadedmetadata', updatePlayerTime);

    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function playerSkip(sec) {
    var media = document.getElementById('playerMedia');
    if (media) media.currentTime = Math.max(0, media.currentTime + sec);
}

function playerSetSpeed(rate) {
    var media = document.getElementById('playerMedia');
    if (media) media.playbackRate = parseFloat(rate);
}

function formatTime(s) {
    if (isNaN(s)) return '0:00';
    var m = Math.floor(s / 60);
    var sec = Math.floor(s % 60);
    return m + ':' + (sec < 10 ? '0' : '') + sec;
}

function updatePlayerTime() {
    var media = document.getElementById('playerMedia');
    var el = document.getElementById('playerTime');
    if (media && el) {
        el.textContent = formatTime(media.currentTime) + ' / ' + formatTime(media.duration);
    }
}

function closePlayer(event) {
    if (event && event.target !== document.getElementById('playerOverlay')) return;

    const overlay = document.getElementById('playerOverlay');
    const body = document.getElementById('playerBody');

    // Stop playback
    const media = body.querySelector('video, audio');
    if (media) media.pause();

    overlay.classList.remove('active');
    body.innerHTML = '';
    document.body.style.overflow = '';
}

/* -- Sorting (persisted in localStorage) -- */

const SORT_KEY = 'tg_courses_sort';
const DEFAULT_SORT = { field: 'date', dir: 'desc' };  // newest first

function loadSortPref() {
    try {
        const raw = localStorage.getItem(SORT_KEY);
        if (raw) {
            const p = JSON.parse(raw);
            if (p.field && p.dir) return p;
        }
    } catch (e) {}
    return { ...DEFAULT_SORT };
}

function saveSortPref(field, dir) {
    try { localStorage.setItem(SORT_KEY, JSON.stringify({ field, dir })); } catch (e) {}
}

function applySort(field, dir) {
    const allBtns = document.querySelectorAll('.sort-btn');
    allBtns.forEach(b => {
        b.classList.remove('active');
        b.innerHTML = b.textContent.replace(/ [▲▼]/g, '').trim();
    });
    const btn = document.querySelector('.sort-btn[data-sort="' + field + '"]');
    if (btn) {
        btn.dataset.dir = dir;
        btn.classList.add('active');
        const label = btn.textContent.replace(/ [▲▼]/g, '').trim();
        btn.innerHTML = label + ' ' + (dir === 'asc' ? '&#9650;' : '&#9660;');
    }
    sortFiles(field, dir);
}

function toggleSort(field, btn) {
    const wasActive = btn.classList.contains('active');
    let dir = btn.dataset.dir || 'desc';
    if (wasActive) {
        dir = dir === 'asc' ? 'desc' : 'asc';
    } else {
        // Sensible defaults per field on first click
        dir = (field === 'date' || field === 'size') ? 'desc' : 'asc';
    }
    saveSortPref(field, dir);
    applySort(field, dir);
}

function sortFiles(field, dir) {
    const list = document.querySelector('.file-list');
    if (!list) return;
    const rows = Array.from(list.querySelectorAll('.file-row'));

    rows.sort((a, b) => {
        let va, vb;
        switch (field) {
            case 'date':
                va = a.dataset.date || '';
                vb = b.dataset.date || '';
                break;
            case 'name':
                va = a.dataset.filename.toLowerCase();
                vb = b.dataset.filename.toLowerCase();
                break;
            case 'size':
                va = parseInt(a.dataset.size) || 0;
                vb = parseInt(b.dataset.size) || 0;
                return dir === 'asc' ? va - vb : vb - va;
            case 'type':
                va = a.dataset.type || '';
                vb = b.dataset.type || '';
                break;
        }
        const cmp = va < vb ? -1 : va > vb ? 1 : 0;
        return dir === 'asc' ? cmp : -cmp;
    });

    rows.forEach(row => list.appendChild(row));
}

/* -- Text messages: show/hide toggle (persisted) + copy -- */

const TEXT_KEY = 'tg_courses_show_text';

function loadTextPref() {
    try {
        const v = localStorage.getItem(TEXT_KEY);
        return v === null ? true : v === '1';
    } catch (e) { return true; }
}

function applyTextVisibility(show) {
    const list = document.querySelector('.file-list');
    if (list) list.classList.toggle('hide-text', !show);
    const cb = document.getElementById('toggleText');
    if (cb) cb.checked = show;
}

function toggleTextMessages() {
    const cb = document.getElementById('toggleText');
    const show = cb ? cb.checked : true;
    try { localStorage.setItem(TEXT_KEY, show ? '1' : '0'); } catch (e) {}
    applyTextVisibility(show);
}

function flashBtn(btn, msg) {
    const orig = btn.dataset.orig || btn.textContent;
    btn.dataset.orig = orig;
    btn.textContent = msg;
    setTimeout(() => { btn.textContent = btn.dataset.orig; }, 1500);
}

function copyTextMsg(btn) {
    const row = btn.closest('.text-row');
    const content = row ? row.querySelector('.text-content') : null;
    if (!content) return;
    const text = content.textContent;

    // Modern API only works in a secure context (HTTPS/localhost).
    // Our app runs over plain HTTP on an IP, so fall back to execCommand.
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text)
            .then(() => flashBtn(btn, 'Скопировано'))
            .catch(() => legacyCopy(text, btn, content));
        return;
    }
    legacyCopy(text, btn, content);
}

function legacyCopy(text, btn, content) {
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.top = '-1000px';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        if (ok) { flashBtn(btn, 'Скопировано'); return; }
    } catch (e) {}
    // Last resort: select the text on the page so the user can Ctrl+C
    try {
        const range = document.createRange();
        range.selectNodeContents(content);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        flashBtn(btn, 'Выделено');
    } catch (e) {}
}

/* -- Init -- */

document.addEventListener('DOMContentLoaded', () => {
    // Enter to submit code on admin page
    const codeInput = document.getElementById('tgCode');
    if (codeInput) {
        codeInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') verifyCode();
        });
    }

    // Hover previews
    initHoverPreviews();

    // Apply saved sort preference (or default: date desc)
    if (document.querySelector('.sort-bar')) {
        const pref = loadSortPref();
        applySort(pref.field, pref.dir);
    }

    // Apply saved text-messages visibility (default: show)
    if (document.getElementById('toggleText')) {
        applyTextVisibility(loadTextPref());
    }

    // Reconcile selection UI with any checkboxes the browser restored
    // (Firefox / bfcache re-check boxes without firing onchange)
    if (document.querySelector('.file-check')) {
        updateSelection();
    }

    // Player keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        var media = document.getElementById('playerMedia');
        if (!media) return;

        if (e.key === 'Escape') { closePlayer(); return; }
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

        switch (e.key) {
            case 'ArrowLeft':  playerSkip(-5); e.preventDefault(); break;
            case 'ArrowRight': playerSkip(5);  e.preventDefault(); break;
            case ' ':
                if (media.paused) media.play(); else media.pause();
                e.preventDefault();
                break;
        }
    });
});
