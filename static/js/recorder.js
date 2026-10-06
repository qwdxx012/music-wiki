// Окно "Что играет?": индикатор отправки файла + запись с микрофона.
//
// Как работает запись:
//   1. По кнопке "Записать" просим доступ к микрофону (getUserMedia).
//   2. MediaRecorder пишет звук кусками (chunks) в течение SECONDS секунд.
//   3. Куски склеиваем в один Blob (двоичный "файл" в памяти браузера).
//   4. Blob кладём в FormData под именем "audio", как будто пользователь выбрал
//      файл в форме, и отправляем fetch-запросом на /recognize.
//   5. Сервер отвечает JSON: либо адрес страницы трека, либо текст ошибки.
// Это единственный AJAX-запрос в проекте, всё остальное - обычные формы.
(function () {
  // Обычная отправка файла: показываем прогресс-бар и блокируем кнопку,
  // чтобы нетерпеливый двойной клик не потратил два запроса AudD
  document.querySelectorAll("form[data-busy]").forEach(function (f) {
    f.addEventListener("submit", function () {
      var busy = document.getElementById(f.getAttribute("data-busy"));
      if (busy) busy.hidden = false;
      var submit = f.querySelector("button[type=submit]");
      if (submit) submit.disabled = true;
    });
  });

  var form = document.getElementById("recognize-form");
  var btn = document.getElementById("rec-btn");
  if (!form || !btn) return;

  var SECONDS = parseInt(form.getAttribute("data-rec-seconds"), 10) || 8;
  var status = document.getElementById("rec-status");
  var left = document.getElementById("rec-left");
  var bar = document.getElementById("rec-bar");
  var stopBtn = document.getElementById("rec-stop");
  var busy = document.getElementById(form.getAttribute("data-busy"));
  var dlg = document.getElementById("sys-dialog");
  var recorder = null, timer = null;

  // Кнопка "Записать" в HTML скрыта: без JS она бесполезна, остаётся загрузка файла
  btn.hidden = false;

  // ---------- системный диалог в стиле Windows ----------
  // kind: "error" | "warning" | "info". Путь к иконке берём из data-icon-*
  function showDialog(title, message, details, kind) {
    if (!dlg) { alert(title + "\n\n" + message); return; }
    document.getElementById("sys-dialog-title").textContent = title;
    document.getElementById("sys-dialog-message").textContent = message;
    document.getElementById("sys-dialog-details").textContent = details || "";
    document.getElementById("sys-dialog-icon").src =
      dlg.getAttribute("data-icon-" + (kind || "error")) || dlg.getAttribute("data-icon-error");
    dlg.hidden = false;
    dlg.querySelector("button.default").focus();
  }
  function closeDialog() { if (dlg) dlg.hidden = true; btn.focus(); }
  if (dlg) {
    dlg.querySelectorAll("[data-close]").forEach(function (b) { b.addEventListener("click", closeDialog); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !dlg.hidden) closeDialog();
    });
  }

  function setBusy(on) {
    if (busy) busy.hidden = !on;
    form.querySelectorAll("button, input").forEach(function (el) { el.disabled = on; });
  }

  // ---------- запись ----------
  // Браузеры умеют записывать в разные форматы: Chrome/Firefox - webm/ogg,
  // Safari - только mp4. Берём первый поддерживаемый из списка
  function pickType() {
    var types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
    if (!MediaRecorder.isTypeSupported) return "";
    for (var i = 0; i < types.length; i++) if (MediaRecorder.isTypeSupported(types[i])) return types[i];
    return "";
  }
  function extFor(type) {
    return type.indexOf("mp4") >= 0 ? "m4a" : type.indexOf("ogg") >= 0 ? "ogg" : "webm";
  }
  // Останавливаем все дорожки потока: без этого в браузере так и будет
  // гореть значок "микрофон используется"
  function stopStream(stream) { stream.getTracks().forEach(function (t) { t.stop(); }); }

  // getUserMedia не удался. По имени ошибки понимаем причину и объясняем её
  // человеческими словами, а не "NotAllowedError"
  function micError(err) {
    btn.disabled = false;
    var name = err && err.name;
    // NotAllowedError - пользователь нажал "Блокировать" (или запретил раньше);
    // PermissionDeniedError - то же самое в старых версиях Chrome
    if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") {
      showDialog("Доступ запрещён", "Нет доступа к микрофону.",
        "Разрешите доступ в настройках сайта (значок слева от адреса) и нажмите «Записать» ещё раз. Или загрузите файл.", "error");
    } else if (name === "NotFoundError" || name === "OverconstrainedError") {
      showDialog("Микрофон не найден", "Не найдено ни одного устройства записи.",
        "Подключите микрофон или загрузите аудиофайл.", "warning");
    } else if (name === "NotReadableError") {
      showDialog("Микрофон занят", "Микрофон используется другой программой.",
        "Закройте её и попробуйте снова.", "warning");
    } else {
      showDialog("Ошибка записи", "Не удалось начать запись.", String((err && err.message) || err), "error");
    }
  }

  function startRecording(stream) {
    var type = pickType(), chunks = [], started;
    try {
      recorder = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream);
    } catch (e) {
      stopStream(stream);
      recorder = null;
      btn.disabled = false;
      showDialog("Ошибка записи", "Браузер не смог начать запись.", String(e.message || e), "error");
      return;
    }
    // Браузер отдаёт записанный звук порциями, складываем их в массив
    recorder.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
    // onstop срабатывает и по кнопке "Стоп", и по истечении SECONDS секунд
    recorder.onstop = function () {
      clearInterval(timer);
      stopStream(stream);
      var mime = (recorder && recorder.mimeType) || type || "audio/webm";
      recorder = null;
      status.hidden = true;
      btn.disabled = false;
      var blob = new Blob(chunks, { type: mime });
      if (!blob.size) {
        showDialog("Ошибка записи", "Запись получилась пустой.", "Проверьте, что микрофон не выключен.", "warning");
        return;
      }
      // Расширение важно: по нему сервер проверяет, что это аудиофайл
      send(blob, "recording." + extFor(mime));
    };

    // Раз в 200 мс обновляем обратный отсчёт и полоску прогресса.
    // Время считаем по часам (Date.now), а не числом тиков: setInterval
    // в фоновой вкладке может замедляться, а часы - нет
    function tick() {
      var elapsed = (Date.now() - started) / 1000;
      left.textContent = Math.max(0, Math.ceil(SECONDS - elapsed));
      bar.style.width = Math.min(100, (elapsed / SECONDS) * 100) + "%";
      if (elapsed >= SECONDS && recorder && recorder.state === "recording") recorder.stop();
    }
    recorder.start();
    started = Date.now();
    status.hidden = false;
    tick();
    timer = setInterval(tick, 200);
  }

  function send(blob, filename) {
    // Имя поля "audio" такое же, как у <input type="file"> в форме,
    // поэтому сервер обрабатывает запись и загрузку файла одним кодом
    var data = new FormData();
    data.append("audio", blob, filename);
    setBusy(true);
    fetch(form.action, {
      method: "POST",
      body: data,
      credentials: "same-origin",
      // По этому заголовку сервер понимает, что отвечать нужно JSON, а не HTML
      headers: { "X-Requested-With": "fetch", "Accept": "application/json" }
    }).then(function (resp) {
      // Даже при ошибке (404, 422, 503) сервер присылает JSON с текстом.
      // Если пришло что-то другое (например, страница ошибки прокси), не падаем
      return resp.json().catch(function () {
        return { ok: false, title: "Ошибка", message: "Сервер вернул неожиданный ответ (HTTP " + resp.status + ")." };
      });
    }).then(function (res) {
      if (res.ok && res.redirect) { window.location.href = res.redirect; return; }
      setBusy(false);
      showDialog(res.title || "Ошибка", res.message || "Не удалось распознать запись.", res.details, res.kind || "error");
    }, function (err) {
      // Сюда попадаем, только если запрос вообще не дошёл до сервера
      setBusy(false);
      showDialog("Нет связи", "Не удалось отправить запись на сервер.", String((err && err.message) || err), "error");
    });
  }

  btn.addEventListener("click", function () {
    if (recorder) return; // запись уже идёт
    // Браузеры дают микрофон только на https:// или http://localhost.
    // Проверяем заранее, чтобы показать понятную причину, а не молчать
    if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showDialog("Микрофон недоступен", "Браузер не даёт доступ к микрофону на этой странице.",
        "Запись работает только по HTTPS или на localhost. Пока можно загрузить файл.", "warning");
      return;
    }
    if (typeof MediaRecorder === "undefined") {
      showDialog("Запись не поддерживается", "Этот браузер не умеет записывать звук.",
        "Обновите браузер или загрузите аудиофайл.", "warning");
      return;
    }
    btn.disabled = true;
    // Здесь браузер показывает запрос "Разрешить доступ к микрофону?".
    // Разрешили - startRecording, отказали или микрофона нет - micError
    navigator.mediaDevices.getUserMedia({ audio: true }).then(startRecording, micError);
  });

  if (stopBtn) stopBtn.addEventListener("click", function () {
    if (recorder && recorder.state === "recording") recorder.stop();
  });
})();
