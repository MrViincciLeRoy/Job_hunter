function buildPagination() {
  const bar = document.getElementById('pg-bar');
  if (!bar) return;
  const cur      = +bar.dataset.cur;
  const total    = +bar.dataset.total;
  const count    = +bar.dataset.count;
  const prev     = +bar.dataset.prev;
  const next     = +bar.dataset.next;
  const tab      = bar.dataset.tab;
  const plats    = bar.dataset.platforms ? bar.dataset.platforms.split(',').filter(Boolean) : [];
  const jobtype  = bar.dataset.jobtype;
  const search   = bar.dataset.search;
  const pagesize = bar.dataset.pagesize;

  function url(p) {
    let u = `?tab=${tab}&page=${p}&page_size=${pagesize}`;
    plats.forEach(pl => u += `&platform=${pl}`);
    if (jobtype) u += `&job_type=${encodeURIComponent(jobtype)}`;
    if (search)  u += `&q=${encodeURIComponent(search)}`;
    return u;
  }

  const hasPrev = cur > 1, hasNext = cur < total;
  let html = '';
  html += `<a class="pg nav${!hasPrev ? ' off' : ''}" href="${url(1)}">« First</a>`;
  html += `<a class="pg nav${!hasPrev ? ' off' : ''}" href="${url(prev)}">‹ Prev</a>`;

  const pages = new Set([1, total]);
  for (let i = Math.max(1, cur - 2); i <= Math.min(total, cur + 2); i++) pages.add(i);
  const sorted = [...pages].sort((a, b) => a - b);
  let last = 0;
  for (const p of sorted) {
    if (last && p - last > 1) html += `<span class="pg-dots">…</span>`;
    html += p === cur ? `<span class="pg cur">${p}</span>` : `<a class="pg" href="${url(p)}">${p}</a>`;
    last = p;
  }

  html += `<a class="pg nav${!hasNext ? ' off' : ''}" href="${url(next)}">Next ›</a>`;
  html += `<a class="pg nav${!hasNext ? ' off' : ''}" href="${url(total)}">Last »</a>`;
  html += `<span class="pg-info">Page ${cur} of ${total} · ${count} total</span>`;
  html += `<select class="pg-size" onchange="changeSize(this.value)">
    ${[25, 50, 100, 200].map(n => `<option value="${n}"${n == +pagesize ? ' selected' : ''}>${n}/page</option>`).join('')}
  </select>`;
  bar.innerHTML = html;
}

function changeSize(size) {
  const bar     = document.getElementById('pg-bar');
  const tab     = bar.dataset.tab;
  const plats   = bar.dataset.platforms ? bar.dataset.platforms.split(',').filter(Boolean) : [];
  const jobtype = bar.dataset.jobtype;
  const search  = bar.dataset.search;
  let u = `?tab=${tab}&page=1&page_size=${size}`;
  plats.forEach(pl => u += `&platform=${pl}`);
  if (jobtype) u += `&job_type=${encodeURIComponent(jobtype)}`;
  if (search)  u += `&q=${encodeURIComponent(search)}`;
  window.location.href = u;
}

function doSpiderInline(jobId, btn) {
  btn.disabled = true;
  btn.textContent = '...';
  fetch(`/job/${jobId}/spider/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
    .then(r => r.json())
    .then(d => {
      if (d.apply_email) {
        showToast(`✓ ${d.apply_email}`);
        const card = document.querySelector(`[data-id="${jobId}"]`);
        if (card) {
          card.dataset.email = '1';
          card.classList.remove('no-email', 'gov-job');
          card.classList.add('has-email');
          if (typeof applyFilters === 'function') applyFilters();
        }
        btn.outerHTML = `<button class="apply-inline-btn" onclick="event.stopPropagation();doApplyInline(${jobId},this)">✉ Apply</button>`;
      } else {
        showToast('No email.', false);
        btn.disabled = false;
        btn.textContent = '🕷';
      }
    })
    .catch(err => {
      showToast(err.message || 'Error', false);
      btn.disabled = false;
      btn.textContent = '🕷';
    });
}

function doApplyInline(jobId, btn) {
  btn.disabled = true;
  btn.textContent = 'Sending...';
  fetch(`/job/${jobId}/apply/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
    .then(r => {
      if (!r.ok && r.headers.get('content-type')?.includes('text/html')) throw new Error(`Server error ${r.status}`);
      return r.json();
    })
    .then(d => {
      if (d.error) {
        showToast(d.error, false);
        btn.disabled = false;
        btn.textContent = '✉ Apply';
        return;
      }
      showToast('Application sent!');
      btn.outerHTML = `<span style="font-family:'Space Mono',monospace;font-size:0.55rem;color:var(--accent)">✓ sent</span>`;
      const card = document.querySelector(`[data-id="${jobId}"]`);
      if (card) {
        card.dataset.applied = '1';
        card.classList.remove('has-email');
        card.classList.add('applied');
        if (typeof applyFilters === 'function') applyFilters();
      }
    })
    .catch(err => {
      showToast(err.message || 'Network error', false);
      btn.disabled = false;
      btn.textContent = '✉ Apply';
    });
}

buildPagination();
