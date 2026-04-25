/* static/js/drawer.js
   Shared drawer logic for dashboard.html and jobs.html
*/

const GOV_PLATFORMS = ['dpsa', 'sayouth', 'essa', 'govza'];

function scoreClass(s) {
  return s >= 70 ? 'high' : s >= 50 ? 'mid' : 'low';
}

function showToast(msg, ok = true) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + (ok ? 'ok' : 'err');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 3500);
}

function parseRequirements(desc) {
  if (!desc) return [];
  return desc.split('\n').map(l => l.trim()).filter(l =>
    l.length > 10 && (
      /require|must|experience|proficien|familiar|knowledge|skill|degree|qualif|certif|proven|ability|years/i.test(l)
      || /^[-•*·]\s/.test(l)
    )
  ).slice(0, 10);
}

function copyEmail(email) {
  navigator.clipboard.writeText(email).then(() => showToast(`Copied: ${email}`));
}

function closeDrawer() {
  document.getElementById('overlay').classList.remove('open');
  document.getElementById('drawer').classList.remove('open');
  if (window._activeDrawerRow) {
    window._activeDrawerRow.classList.remove('active');
    window._activeDrawerRow.style.background = '';
    window._activeDrawerRow = null;
  }
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

function openDrawer(jobId, row) {
  if (window._activeDrawerRow) {
    window._activeDrawerRow.classList.remove('active');
    window._activeDrawerRow.style.background = '';
  }
  window._activeDrawerRow = row;
  row.classList.add('active');

  document.getElementById('drawer-inner').innerHTML = `
    <div style="display:flex;align-items:center;justify-content:center;padding:3rem;
      color:var(--muted);font-family:'Space Mono',monospace;font-size:0.75rem;gap:0.5rem">
      <span class="pulse" style="background:var(--muted)"></span> Loading...
    </div>`;
  document.getElementById('overlay').classList.add('open');
  document.getElementById('drawer').classList.add('open');

  fetch(`/job/${jobId}/`)
    .then(r => r.json())
    .then(d => renderDrawer(d))
    .catch(() => {
      document.getElementById('drawer-inner').innerHTML =
        '<div style="padding:2rem;color:var(--danger);font-family:Space Mono,monospace;font-size:0.75rem">Failed to load.</div>';
    });
}

function renderDrawer(d) {
  const cls = scoreClass(d.match_score);
  const isGov = GOV_PLATFORMS.includes(d.platform);

  // Status row
  let statusHtml = '';
  if (d.applied) {
    statusHtml = `<span class="status-pill applied">✓ Applied</span><span class="status-time">${d.applied_at}</span>`;
  } else if (!d.apply_email) {
    statusHtml = `<span class="status-pill no-email">✗ No email</span><span class="status-time">Cannot auto-apply</span>`;
  } else {
    statusHtml = `<span class="status-pill pending">Pending</span><span class="status-time">Has email · not yet applied</span>`;
  }
  if (isGov && !d.apply_email) {
    statusHtml += `<span class="gov-warn-chip">⚠ May require Z83 form</span>`;
  }

  // Job info panel — salary / type / how to apply
  const rows = [
    d.salary      ? `<div class="info-row"><span class="info-label">💰 Salary</span><span class="info-val">${d.salary}</span></div>` : '',
    d.job_type    ? `<div class="info-row"><span class="info-label">📋 Type</span><span class="info-val">${d.job_type}</span></div>` : '',
    d.how_to_apply ? `<div class="info-row"><span class="info-label">📨 How to Apply</span><span class="info-val">${d.how_to_apply}</span></div>` : '',
  ].filter(Boolean).join('');

  const infoSection = rows ? `
    <div class="drawer-section">
      <div class="drawer-section-title">Job Info</div>
      <div class="info-grid">${rows}</div>
    </div>` : '';

  // Requirements
  const reqs = parseRequirements(d.description);
  const reqsHtml = reqs.length ? `
    <div class="drawer-section">
      <div class="drawer-section-title">Requirements</div>
      <ul class="req-list">
        ${reqs.map(r => `<li>${r.replace(/^[-•*·]\s*/, '')}</li>`).join('')}
      </ul>
    </div>` : '';

  // Cover letter (if already applied)
  const coverHtml = d.cover_letter ? `
    <div class="drawer-section">
      <div class="drawer-section-title">Cover Letter Sent</div>
      <div class="cover-letter-box">${d.cover_letter}</div>
    </div>` : '';

  // Gov notice
  const govNotice = isGov ? `
    <div class="gov-notice">
      <strong>🏛 Government Position</strong>
      Most SA government positions require a Z83 application form.
      Visit the posting link to confirm requirements.
    </div>` : '';

  // Action buttons
  const spiderBtn = (!d.applied && d.url && !d.apply_email)
    ? `<button class="btn btn-orange btn-sm" id="spider-btn" onclick="doSpider(${d.id})">🕷 Spider for Email</button>`
    : '';

  const applyBtn = (!d.applied && d.apply_email)
    ? `<div class="apply-btn-wrap"><button class="btn btn-green" id="apply-btn" onclick="doApply(${d.id})">✉ Apply Now</button></div>`
    : d.applied
    ? `<div class="apply-btn-wrap"><span class="applied-done-label">✓ APPLIED</span></div>`
    : '';

  const emailChip = d.apply_email
    ? `<div class="meta-chip">✉ <strong>${d.apply_email}</strong></div>`
    : '';

  document.getElementById('drawer-inner').innerHTML = `
    <div class="drawer-header">
      <div class="drawer-title-block">
        <div class="drawer-job-title">${d.title}</div>
        <div class="drawer-company">${d.company}${d.location ? ' · ' + d.location : ''}</div>
      </div>
      <button class="drawer-close" onclick="closeDrawer()">✕</button>
    </div>

    <div class="drawer-score-bar">
      <div>
        <div class="big-score ${cls}">${d.match_score}<span class="score-unit">%</span></div>
        <div class="score-label">Match Score</div>
      </div>
      <div class="score-bar-track">
        <div class="score-bar-fill ${cls}" style="width:${d.match_score}%"></div>
      </div>
    </div>

    <div class="drawer-meta-row">
      <span class="platform-badge ${isGov ? 'gov' : ''}">${d.platform}</span>
      <div class="meta-chip">📍 <strong>${d.location || 'Not specified'}</strong></div>
      <div class="meta-chip">🕐 ${d.scraped_at}</div>
      ${emailChip}
    </div>

    <div class="drawer-status-bar">${statusHtml}</div>
    <div class="spider-banner" id="spider-banner"></div>

    <div class="drawer-body">
      ${govNotice}
      <div id="email-chips-section"></div>
      ${infoSection}
      ${reqsHtml}
      <div class="drawer-section">
        <div class="drawer-section-title">Full Description</div>
        <div class="description-text">${d.description || 'No description available.'}</div>
      </div>
      ${coverHtml}
    </div>

    <div class="drawer-actions">
      ${spiderBtn}
      ${d.url ? `<a href="${d.url}" target="_blank" class="drawer-link">↗ View Posting</a>` : ''}
      ${applyBtn}
    </div>
  `;
}

function doSpider(jobId) {
  const btn = document.getElementById('spider-btn');
  const banner = document.getElementById('spider-banner');
  btn.disabled = true;
  btn.textContent = '🕷 Spidering...';
  banner.className = 'spider-banner running';
  banner.innerHTML = '<span class="pulse"></span> Fetching job page and following links...';

  fetch(`/job/${jobId}/spider/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
    .then(r => r.json())
    .then(d => {
      if (d.error) {
        banner.className = 'spider-banner fail';
        banner.textContent = '✗ ' + d.error;
        btn.disabled = false;
        btn.textContent = '🕷 Retry Spider';
        return;
      }
      if (d.apply_email) {
        banner.className = 'spider-banner success';
        banner.innerHTML = `✓ Email found: <strong>${d.apply_email}</strong>${d.followed_url ? ' (via contact page)' : ''}`;
        showToast(`Email found: ${d.apply_email}`);

        if (d.all_emails && d.all_emails.length > 1) {
          document.getElementById('email-chips-section').innerHTML = `
            <div class="drawer-section">
              <div class="drawer-section-title">All Emails Found</div>
              <div class="email-chips">
                ${d.all_emails.map(e => `<span class="email-chip" onclick="copyEmail('${e}')" title="Click to copy">${e}</span>`).join('')}
              </div>
            </div>`;
        }

        btn.outerHTML = `<div class="apply-btn-wrap"><button class="btn btn-green" id="apply-btn" onclick="doApply(${jobId})">✉ Apply Now</button></div>`;
        document.querySelector('.drawer-status-bar').innerHTML =
          `<span class="status-pill pending">Pending</span><span class="status-time">Email found · ready to apply</span>`;

        const dot = document.querySelector(`[data-id="${jobId}"] .no-email-dot`);
        if (dot) { dot.className = 'email-dot'; dot.title = d.apply_email; }
        const card = document.querySelector(`[data-id="${jobId}"]`);
        if (card) { card.dataset.email = '1'; card.classList.remove('no-email', 'gov-job'); card.classList.add('has-email'); if (typeof applyFilters === 'function') applyFilters(); }
      } else {
        banner.className = 'spider-banner fail';
        banner.textContent = '✗ No email found on this posting';
        btn.disabled = false;
        btn.textContent = '🕷 Retry Spider';
        showToast('No email found on this page.', false);
      }
    })
    .catch(err => {
      banner.className = 'spider-banner fail';
      banner.textContent = '✗ ' + (err.message || 'Network error');
      btn.disabled = false;
      btn.textContent = '🕷 Retry Spider';
    });
}

function doApply(jobId) {
  const btn = document.getElementById('apply-btn');
  btn.disabled = true;
  btn.textContent = 'Sending...';

  fetch(`/job/${jobId}/apply/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
    .then(r => {
      if (!r.ok && r.headers.get('content-type')?.includes('text/html')) {
        throw new Error(`Server error ${r.status} — check Gmail/Groq credentials`);
      }
      return r.json();
    })
    .then(d => {
      if (d.error) {
        showToast(d.error, false);
        btn.disabled = false;
        btn.textContent = '✉ Apply Now';
        return;
      }
      showToast('Application sent!');
      const now = new Date();
      const ts = now.toLocaleDateString('en-ZA', { day: '2-digit', month: 'short', year: 'numeric' })
        + ' · ' + now.toTimeString().slice(0, 5);
      document.querySelector('.drawer-status-bar').innerHTML =
        `<span class="status-pill applied">✓ Applied</span><span class="status-time">${ts}</span>`;
      btn.outerHTML = `<div class="apply-btn-wrap"><span class="applied-done-label">✓ APPLIED</span></div>`;
      if (d.cover_letter) {
        document.querySelector('.drawer-body').insertAdjacentHTML('beforeend', `
          <div class="drawer-section">
            <div class="drawer-section-title">Cover Letter Sent</div>
            <div class="cover-letter-box">${d.cover_letter}</div>
          </div>`);
      }
      const card = document.querySelector(`[data-id="${jobId}"]`);
      if (card) {
        card.dataset.applied = '1';
        card.classList.remove('has-email');
        card.classList.add('applied');
        const actionsEl = card.querySelector('.job-actions');
        if (actionsEl && !actionsEl.querySelector('.applied-tag')) {
          actionsEl.insertAdjacentHTML('afterbegin', '<span class="applied-tag">✓ sent</span>');
        }
        if (typeof applyFilters === 'function') applyFilters();
      }
    })
    .catch(err => {
      showToast(err.message || 'Network error', false);
      btn.disabled = false;
      btn.textContent = '✉ Apply Now';
    });
}

// jobs.html inline buttons
function doSpiderInline(jobId, btn) {
  btn.disabled = true;
  btn.textContent = '...';
  fetch(`/job/${jobId}/spider/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
    .then(r => r.json())
    .then(d => {
      if (d.apply_email) {
        showToast(`✓ ${d.apply_email}`);
        const card = document.querySelector(`[data-id="${jobId}"]`);
        if (card) { card.dataset.email = '1'; card.classList.remove('no-email', 'gov-job'); card.classList.add('has-email'); if (typeof applyFilters === 'function') applyFilters(); }
        btn.outerHTML = `<button class="apply-inline-btn" onclick="event.stopPropagation();doApplyInline(${jobId}, this)">✉ Apply</button>`;
      } else {
        showToast('No email.', false);
        btn.disabled = false;
        btn.textContent = '🕷';
      }
    })
    .catch(err => { showToast(err.message || 'Error', false); btn.disabled = false; btn.textContent = '🕷'; });
}

function doApplyInline(jobId, btn) {
  btn.disabled = true;
  btn.textContent = 'Sending...';
  fetch(`/job/${jobId}/apply/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
    .then(r => {
      if (!r.ok && r.headers.get('content-type')?.includes('text/html')) {
        throw new Error(`Server error ${r.status}`);
      }
      return r.json();
    })
    .then(d => {
      if (d.error) { showToast(d.error, false); btn.disabled = false; btn.textContent = '✉ Apply'; return; }
      showToast('Application sent!');
      btn.outerHTML = `<span style="font-family:'Space Mono',monospace;font-size:0.58rem;color:var(--accent)">✓ sent</span>`;
      const card = document.querySelector(`[data-id="${jobId}"]`);
      if (card) { card.dataset.applied = '1'; card.classList.remove('has-email'); card.classList.add('applied'); if (typeof applyFilters === 'function') applyFilters(); }
    })
    .catch(err => { showToast(err.message || 'Network error', false); btn.disabled = false; btn.textContent = '✉ Apply'; });
}
