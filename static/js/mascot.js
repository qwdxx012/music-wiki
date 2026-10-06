// Маскот (анимированная SD-карта в правом нижнем углу).
// 1) Наведение: подсказка в стиле Windows с новой случайной цитатой о музыке.
// 2) Клик: плавно прокручивает к окну "Что играет?" и мигает его заголовком.
// Без JavaScript всё тоже работает: маскот - обычная ссылка на /recognize,
// а подсказка показывается через CSS :hover с цитатой, выбранной сервером.
(function () {
  var mascot = document.getElementById("mascot");
  if (!mascot) return;
  var tip = document.getElementById("mascot-tip");

  // Список цитат приходит из Python (services/quotes.py) через data-quotes.
  // Если JSON вдруг битый, просто остаётся цитата, которую вставил сервер
  var quotes = [];
  try {
    quotes = JSON.parse(mascot.getAttribute("data-quotes") || "[]");
  } catch (e) {
    quotes = [];
  }
  var lastIndex = -1;

  // Новая цитата при каждом наведении. Повтор той же подряд исключаем:
  // иначе при 13 цитатах примерно в каждом 13-м наведении ничего бы не менялось
  function showRandomQuote() {
    if (!tip || quotes.length === 0) return;
    var i = Math.floor(Math.random() * quotes.length);
    if (quotes.length > 1 && i === lastIndex) i = (i + 1) % quotes.length;
    lastIndex = i;
    tip.textContent = quotes[i];
  }
  // Меняем текст в момент наведения, а показывает подсказку CSS
  // с задержкой 0.4 с (как настоящая tooltip в Windows)
  mascot.addEventListener("mouseenter", showRandomQuote);
  mascot.addEventListener("focus", showRandomQuote);

  mascot.addEventListener("click", function (e) {
    var box = document.getElementById("recognize");
    // Окна "Что играет?" на этой странице нет (например, на странице артиста):
    // не мешаем ссылке, браузер откроет /recognize#recognize
    if (!box) return;
    e.preventDefault();
    box.scrollIntoView({ behavior: "smooth", block: "center" });
    // Класс flash запускает CSS-анимацию мигания. Чтобы она сработала и при
    // повторном клике, класс снимаем, заставляем браузер пересчитать
    // раскладку (чтение offsetWidth) и вешаем класс снова
    box.classList.remove("flash");
    void box.offsetWidth;
    box.classList.add("flash");
    // Фокус на выбор файла, чтобы можно было сразу нажать Enter/пробел.
    // preventScroll: иначе фокус дёрнет страницу и сломает плавную прокрутку
    var input = box.querySelector("input[type=file]");
    if (input) input.focus({ preventScroll: true });
  });
})();
