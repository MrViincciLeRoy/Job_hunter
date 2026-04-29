const allChip   = document.querySelector('.type-chip[data-type="all"]');
const typeChips = document.querySelectorAll('.type-chip:not([data-type="all"])');

function toggleChip(el) {
  if (el.dataset.type === 'all') {
    typeChips.forEach(c => c.classList.remove('active'));
    allChip.classList.add('active-all');
  } else {
    allChip.classList.remove('active-all');
    el.classList.toggle('active');
    if (!Array.from(typeChips).some(c => c.classList.contains('active'))) {
      allChip.classList.add('active-all');
    }
  }
  syncTypeInputs();
}

function syncTypeInputs() {
  const container = document.getElementById('job-type-inputs');
  container.innerHTML = '';
  const active = Array.from(typeChips).filter(c => c.classList.contains('active'));
  const values = active.length ? active.map(c => c.dataset.type) : ['all'];
  values.forEach(v => {
    const inp = document.createElement('input');
    inp.type = 'hidden';
    inp.name = 'job_types';
    inp.value = v;
    container.appendChild(inp);
  });
}

function submitAction(action) {
  document.getElementById('action-input').value = action;
  document.getElementById('running-badge').classList.add('show');
  document.getElementById('pipeline-form').submit();
}

function toggleDry(cb) {
  document.getElementById('dry-run-input').value = cb.checked ? '1' : '0';
}

syncTypeInputs();
