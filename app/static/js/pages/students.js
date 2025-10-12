// app/static/js/pages/students.js

(function () {
  // پیش‌نمایش آواتار در فرم‌های create/edit
  function previewAvatar(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;

    // محدودیت ساده حجم (2MB) – با Config همخوان
    const MAX_BYTES = 2 * 1024 * 1024;
    if (file.size > MAX_BYTES) {
      alert("حجم تصویر نباید بیشتر از 2MB باشد.");
      e.target.value = "";
      return;
    }

    const reader = new FileReader();
    reader.onload = function (ev) {
      let preview = document.getElementById("avatarPreview");
      let placeholder = document.getElementById("avatarPlaceholder");
      if (!preview) {
        preview = document.createElement("img");
        preview.id = "avatarPreview";
        preview.style.width = "120px";
        preview.style.height = "120px";
        preview.style.borderRadius = "50%";
        preview.style.objectFit = "cover";
        preview.style.boxShadow = "var(--elev-1)";
        if (placeholder) {
          placeholder.replaceWith(preview);
        } else {
          // اگر قبلاً تصویر بوده، فقط سورس را عوض کن
          const container = document.querySelector(".avatar-upload");
          if (container) container.prepend(preview);
        }
      }
      preview.src = ev.target.result;
    };
    reader.readAsDataURL(file);
  }

  // اتصال هندلر
  document.addEventListener("DOMContentLoaded", function () {
    const input = document.getElementById("avatar");
    if (input) {
      input.addEventListener("change", previewAvatar);
    }
  });
})();
