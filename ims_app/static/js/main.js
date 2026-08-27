// ── Sidebar Toggle ────────────────────────────────────────────────────────
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  if (sb) sb.classList.toggle('collapsed');
}

// ── Modal ─────────────────────────────────────────────────────────────────
function openModal(id) {
  const m = document.getElementById(id);
  if (m) { m.classList.add('open'); document.body.style.overflow = 'hidden'; }
}
function closeModal(id) {
  const m = document.getElementById(id);
  if (m) { m.classList.remove('open'); document.body.style.overflow = ''; }
}
// Close modal on backdrop click
document.addEventListener('click', function(e) {
  if (e.target.classList.contains('modal')) {
    e.target.classList.remove('open');
    document.body.style.overflow = '';
  }
});
// Close modal on Escape key
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal.open').forEach(m => {
      m.classList.remove('open');
      document.body.style.overflow = '';
    });
  }
});

// ── Password Toggle ───────────────────────────────────────────────────────
function togglePw(inputId, btn) {
  const inp = document.getElementById(inputId);
  if (!inp) return;
  const isText = inp.type === 'text';
  inp.type = isText ? 'password' : 'text';
  const icon = btn.querySelector('i');
  if (icon) {
    icon.className = isText ? 'fas fa-eye' : 'fas fa-eye-slash';
  }
}

// ── Auto-dismiss flash messages ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(function() {
    document.querySelectorAll('.flash').forEach(function(el) {
      el.style.transition = 'opacity .5s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 500);
    });
  }, 5000);

  // Highlight active nav item based on URL
  const path = window.location.pathname;
  document.querySelectorAll('.nav-item').forEach(function(link) {
    if (link.getAttribute('href') === path) {
      link.classList.add('active');
    }
  });

  // Set today's date on date inputs that are empty
  const today = new Date().toISOString().split('T')[0];
  document.querySelectorAll('input[type="date"]:not([value])').forEach(function(inp) {
    if (!inp.value) inp.setAttribute('placeholder', today);
  });
});

// ── Confirm Delete ────────────────────────────────────────────────────────
document.addEventListener('submit', function(e) {
  const form = e.target;
  if (form.dataset.confirm) {
    if (!confirm(form.dataset.confirm)) e.preventDefault();
  }
});

// ── Table search filter (client-side) ────────────────────────────────────
function filterTable(inputId, tableId) {
  const val = document.getElementById(inputId).value.toLowerCase();
  const rows = document.querySelectorAll('#' + tableId + ' tbody tr');
  rows.forEach(function(row) {
    row.style.display = row.textContent.toLowerCase().includes(val) ? '' : 'none';
  });
}
