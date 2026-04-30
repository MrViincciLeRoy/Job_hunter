function submitAction(action) {
  document.getElementById('action-input').value = action;
  document.getElementById('running-badge').classList.add('show');
  document.getElementById('pipeline-form').submit();
}

function toggleDry(cb) {
  document.getElementById('dry-run-input').value = cb.checked ? '1' : '0';
}
