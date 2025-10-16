(function(){
  // اینیت یک فیلد شمسی با altField و مقدار اولیه گِریگوریَن
  function initFaDate(faInput, altSelector, initialGregorian) {
    const $fa = $(faInput);
    if (!$fa.length) return;

    // برای جلوگیری از تایپ دستی و مجبور کردن به استفاده از پیکر
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

    // با کلیک و فوکِس، پاپ‌آپ باز شود
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