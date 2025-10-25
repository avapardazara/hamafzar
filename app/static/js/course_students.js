(function(){
  function $(sel, root){ return (root||document).querySelector(sel); }
  function $all(sel, root){ return Array.from((root||document).querySelectorAll(sel)); }

  async function fetchJSON(url){
    const res = await fetch(url, {credentials:'same-origin'});
    if (!res.ok) throw new Error('HTTP '+res.status);
    return res.json();
  }
  async function postForm(url, data){
    const fd = new FormData();
    Object.entries(data||{}).forEach(([k,v])=>fd.append(k, v));
    const res = await fetch(url, {method:'POST', body: fd, credentials:'same-origin'});
    const ct = res.headers.get('content-type')||'';
    if (ct.includes('application/json')) return res.json();
    return {ok: res.ok};
  }

  function renderList(container, items, type){
    // نوع: 'available' یا 'enrolled'
    const ul = container.querySelector('ul');
    ul.innerHTML = '';
    if (!items || !items.length){
      ul.innerHTML = '<li class="muted">موردی یافت نشد.</li>';
      return;
    }
    items.forEach(s=>{
      const li = document.createElement('li');
      li.className = 'row';
      li.innerHTML = `
        <div class="info">
          <div class="name ellipsis" title="${s.name || '—'}">${s.name || '—'}</div>
          <div class="meta ellipsis">${s.email || '—'}${s.phone ? ' · '+s.phone : ''}</div>
        </div>
        <div class="act">
          ${type==='available'
            ? `<button class="btn btn-small btn-primary" data-enroll="${s.id}">افزودن</button>`
            : `<button class="btn btn-small" data-unenroll="${s.id}">حذف</button>`}
        </div>
      `;
      ul.appendChild(li);
    });
  }

  async function refreshLists(root){
    const courseId = root.getAttribute('data-course-id');
    const q = ($('#studentSearch', root).value||'').trim();
    root.classList.add('loading');
    try{
      const data = await fetchJSON(`/courses/${courseId}/students/json?q=${encodeURIComponent(q)}`);
      renderList($('#availableBox', root), data.available, 'available');
      renderList($('#enrolledBox', root), data.enrolled, 'enrolled');
      $('#availableCount', root).textContent = data.count.available;
      $('#enrolledCount', root).textContent = data.count.enrolled;
    }catch(e){
      console.error(e);
      alert('خطا در دریافت فهرست دانشجوها');
    }finally{
      root.classList.remove('loading');
    }
  }

  async function onClick(root, e){
    const enrollBtn = e.target.closest('[data-enroll]');
    const unenrollBtn = e.target.closest('[data-unenroll]');
    if (enrollBtn){
      const studentId = enrollBtn.getAttribute('data-enroll');
      const cid = root.getAttribute('data-course-id');
      enrollBtn.disabled = true;
      const res = await postForm(`/courses/${cid}/students/enroll`, {student_id: studentId});
      if (!res || res.ok !== true) alert('افزودن ناموفق بود');
      await refreshLists(root);
    }
    if (unenrollBtn){
      const studentId = unenrollBtn.getAttribute('data-unenroll');
      const cid = root.getAttribute('data-course-id');
      unenrollBtn.disabled = true;
      const res = await postForm(`/courses/${cid}/students/unenroll`, {student_id: studentId});
      if (!res || res.ok !== true) alert('حذف ناموفق بود');
      await refreshLists(root);
    }
  }

  function init(){
    const root = document.getElementById('course-students');
    if (!root) return;

    // رویدادها
    root.addEventListener('click', e => onClick(root, e));
    const search = document.getElementById('studentSearch');
    if (search){
      let t=null;
      search.addEventListener('input', ()=>{
        clearTimeout(t); t=setTimeout(()=>refreshLists(root), 300);
      });
    }

    refreshLists(root);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
