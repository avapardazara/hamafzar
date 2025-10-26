(function(){
  // اینیت یک فیلد شمسی با altField و مقدار اولیه گِریگوریَن
  function initFaDate(faInput, altSelector, initialGregorian) {
    const $fa = $(faInput);
    if (!$fa.length) return;

    // اگر پلاگین در دسترس نبود، اجازه تایپ دستی بده و خارج شو
    if (!(window.$ && $.fn && $.fn.persianDatepicker)) {
      // Fallback: اجازه تایپ دستی و هیچ رفتاری نکن
      return;
    }

    // پلاگین در دسترس است؛ حالا readonly کن تا فقط از پیکر استفاده شود
    $fa.attr('readonly', 'readonly');

    // راه‌اندازی دیت‌پیکر
    $fa.persianDatepicker({
      format: 'YYYY/MM/DD',
      altField: altSelector,         // hidden ISO
      altFormat: 'YYYY-MM-DD',
      initialValue: !!initialGregorian,   // اگر مقدار اولیه ISO داری
      initialValueType: 'gregorian',      // مقدار اولیه از نوع میلادی است
      autoClose: true,                    // بعد انتخاب تاریخ بسته شود
      calendar: { persian: { locale: 'fa', leapYearMode: 'astronomical' } },
      toolbox: { calendarSwitch: { enabled: false } },
      navigator: { enabled: true, scroll: { enabled: false } }
    });

    // با کلیک یا فوکِس، پاپ‌آپ باز شود
    $fa.on('focus click', function(){
      try { $fa.persianDatepicker('show'); } catch(e) {}
    });
  }

  // اسکن خودکار تمام فیلدهایی که data-fa-date دارند
  window.__initAllFaDates = function(){
    document.querySelectorAll('[data-fa-date]').forEach(function(el){
      const alt = el.getAttribute('data-alt');        // سلکتور hidden
      const initial = el.getAttribute('data-initial'); // مقدار اولیه ISO (YYYY-MM-DD) یا ''
      if (alt) initFaDate(el, alt, initial || '');
    });
  };

  // اجرا پس از لود DOM
  document.addEventListener('DOMContentLoaded', window.__initAllFaDates);
})();
window.attachPDatepicker = function (visibleSel, hiddenSel, initialISO) {
  try {
    const vis = document.querySelector(visibleSel);
    const hid = document.querySelector(hiddenSel);
    if (!vis) return;

    // اگر از قبل type='text' بود، به date تغییرش می‌دهیم
    if (vis.type !== 'date') {
      try { vis.type = 'date'; } catch (_) {}
    }

    // مقدار اولیه
    if (initialISO) {
      vis.value = initialISO;
      if (hid) hid.value = initialISO;
    } else if (hid && hid.value && !vis.value) {
      vis.value = hid.value;
    }

    // سنکرون دوطرفه
    vis.addEventListener('change', () => { if (hid) hid.value = vis.value; });
    if (hid) {
      hid.addEventListener('change', () => {
        if (!vis.value) vis.value = hid.value;
      });
    }
  } catch (e) {
    console.warn('attachPDatepicker shim warning:', e);
  }
};