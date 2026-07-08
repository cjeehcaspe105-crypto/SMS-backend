/* ==========================================================
   VMC Attendance System — script.js
   Villagers Montessori College
   Handles: Login, Dashboard, RFID Scanner, Attendance,
            Students, SMS Notifications, Settings
   ========================================================== */

// ── API base URL (no trailing slash, no sub-path) ──────────────────────────
// All fetch calls below append their own sub-paths (e.g. /students, /attendance).
// Previously this was set to '.../api/students' which caused every call to
// resolve to a doubly-nested path (.../api/students/students, etc.), breaking
// auth, RFID scanning, student CRUD, and cross-device sync simultaneously.
const API_BASE = 'https://sms-backend-ja4y.onrender.com/api';

/* ─────────────────────────────────────────────────────────
   UTILITY: Toast Notifications
───────────────────────────────────────────────────────── */
function showToast(message, type = 'info') {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${icons[type] || 'ℹ️'}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3600);
}

/* ─────────────────────────────────────────────────────────
   UTILITY: Toggle Modal Visibility
───────────────────────────────────────────────────────── */
function toggleModal(id, show) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle('show', show);
}

/* ─────────────────────────────────────────────────────────
   UTILITY: Live Clock
───────────────────────────────────────────────────────── */
function startClock() {
  const el = document.getElementById('liveClock');
  if (!el) return;
  function update() {
    const now = new Date();
    el.textContent = now.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
    });
  }
  update();
  setInterval(update, 1000);
}

/* ─────────────────────────────────────────────────────────
   UTILITY: Auth Guard — redirect if not logged in
───────────────────────────────────────────────────────── */
function guardAuth() {
  const page = document.body.dataset.page;
  if (page === 'login') return;
  const token = localStorage.getItem('vmc_token');
  const role = localStorage.getItem('vmc_role');
  if (!token) {
    window.location.href = 'index.html';
    return;
  }
  // Enforce access control
  if (role === 'parent' && page !== 'parent-portal') {
    window.location.href = 'parent-portal.html';
  } else if (role === 'admin' && page === 'parent-portal') {
    window.location.href = 'dashboard.html';
  }
}

function logout() {
  localStorage.removeItem('vmc_token');
  localStorage.removeItem('vmc_role');
  localStorage.removeItem('vmc_student_id');
  window.location.href = 'index.html';
}

/* ─────────────────────────────────────────────────────────
   LOGIN PAGE
   ───────────────────────────────────────────────────────── */
async function handleLogin(e) {
  e.preventDefault();
  const username = document.getElementById('loginUsername').value.trim();
  const password = document.getElementById('loginPassword').value.trim();
  const btn = document.getElementById('loginBtn');

  btn.disabled = true;
  btn.textContent = '🔄 Signing in...';

  try {
    const res = await fetch(`${API_BASE}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (data.success) {
      localStorage.setItem('vmc_token', data.token);
      localStorage.setItem('vmc_role', data.role);
      if (data.role === 'parent') {
        localStorage.setItem('vmc_student_id', data.studentId);
        window.location.href = 'parent-portal.html';
      } else {
        window.location.href = 'dashboard.html';
      }
    } else {
      showToast(data.message || 'Invalid credentials', 'error');
      btn.disabled = false;
      btn.innerHTML = '🔐 Sign In';
    }
  } catch (err) {
    showToast('Cannot connect to server. Make sure the server is running.', 'error');
    btn.disabled = false;
    btn.innerHTML = '🔐 Sign In';
  }
}

/* ─────────────────────────────────────────────────────────
   DASHBOARD PAGE
───────────────────────────────────────────────────────── */
let attendanceChart = null;

async function loadDashboard() {
  try {
    const [studRes, attRes, smsRes] = await Promise.all([
      fetch(`${API_BASE}/students`),
      fetch(`${API_BASE}/attendance`),
      fetch(`${API_BASE}/sms`)
    ]);
    const students = await studRes.json();
    const attendance = await attRes.json();
    const smsLogs = await smsRes.json();

    const today = new Date().toISOString().split('T')[0];

    const todayAtt = attendance.filter(a => a.date === today);
    const presentIds = new Set(todayAtt.filter(a => a.type === 'IN').map(a => a.studentId || a.student_id));
    const smsTodayCount = smsLogs.filter(s => s.date === today).length;

    setEl('statTotalStudents', students.length);
    setEl('statPresent', presentIds.size);
    setEl('statAbsent', Math.max(0, students.length - presentIds.size));
    setEl('statSmsSent', smsTodayCount);

    // Grade breakdown
    const gradeMap = {};
    students.forEach(s => { gradeMap[s.grade] = (gradeMap[s.grade] || 0) + 1; });

    const gradeCards = document.getElementById('gradeCards');
    if (gradeCards) {
      gradeCards.innerHTML = Object.entries(gradeMap).map(([g, n]) =>
        `<div class="grade-card"><div class="grade-num">${n}</div><div class="grade-lbl">${g}</div></div>`
      ).join('');
    }

    // Chart.js bar chart
    if (window.Chart) {
      const ctx = document.getElementById('attendanceChart');
      if (ctx) {
        const labels = Object.keys(gradeMap);
        const values = labels.map(g =>
          todayAtt.filter(a => a.grade === g && a.type === 'IN').length
        );
        if (attendanceChart) attendanceChart.destroy();
        attendanceChart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels,
            datasets: [{
              label: 'Present Today',
              data: values,
              backgroundColor: [
                'rgba(108,99,255,0.7)',
                'rgba(16,185,129,0.7)',
                'rgba(245,158,11,0.7)',
                'rgba(59,130,246,0.7)'
              ],
              borderRadius: 6,
              borderSkipped: false
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { ticks: { color: '#94a3b8' }, grid: { display: false } },
              y: { ticks: { color: '#94a3b8', stepSize: 1 }, grid: { color: 'rgba(255,255,255,0.06)' } }
            }
          }
        });
      }
    }

    // Recent activity feed
    const feed = document.getElementById('recentActivity');
    if (feed) {
      const recent = [...attendance]
        .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
        .slice(0, 10);
      feed.innerHTML = recent.length
        ? recent.map(a => `
            <li class="activity-item">
              <div class="activity-dot ${a.type === 'IN' ? 'in' : 'out'}"></div>
              <div>
                <div class="activity-text"><strong>${a.student_name || a.studentName}</strong> — ${a.type === 'IN' ? 'Time In' : 'Time Out'}</div>
                <div class="activity-time">${new Date(a.timestamp).toLocaleString()}</div>
              </div>
            </li>`).join('')
        : '<li class="activity-item"><div class="activity-text text-muted">No activity yet today.</div></li>';
    }

  } catch (err) {
    console.error('Dashboard load error:', err);
    showToast('Failed to load dashboard data.', 'error');
  }
}

function setEl(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

/* ─────────────────────────────────────────────────────────
   RFID SCANNER PAGE
───────────────────────────────────────────────────────── */
let students = [];
let settings = {};
let todayScans = [];
let scanCooldowns = {};   // rfid → last scan timestamp

async function loadRFID() {
  try {
    const [sRes, stRes] = await Promise.all([
      fetch(`${API_BASE}/settings`),
      fetch(`${API_BASE}/students`)
    ]);
    settings = await sRes.json();
    students = await stRes.json();

    const attRes = await fetch(`${API_BASE}/attendance`);
    const attendance = await attRes.json();
    const today = new Date().toISOString().split('T')[0];
    todayScans = attendance.filter(a => a.date === today);
    renderScanLog();
  } catch (err) {
    console.error('RFID load error:', err);
    showToast('Cannot connect to server.', 'error');
  }

  // Listen for keyboard-wedge RFID scanner input
  const rfidInput = document.getElementById('rfidInput');
  if (!rfidInput) return;

  rfidInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      const rfid = rfidInput.value.trim();
      rfidInput.value = '';
      if (rfid) processRFID(rfid);
    }
  });

  document.addEventListener('click', () => rfidInput.focus());
  rfidInput.focus();
}

async function processRFID(rfidCode) {
  const now = new Date();
  const cooldown = parseInt(settings.scanCooldown || 30) * 1000;

  if (scanCooldowns[rfidCode] && (now - scanCooldowns[rfidCode]) < cooldown) {
    showScanResult('error', '⏳', 'Cooldown Active', `Please wait before scanning again.`);
    return;
  }

  const student = students.find(s => s.rfid === rfidCode);
  if (!student) {
    showScanResult('error', '❓', 'Unknown RFID', `No student found for card: ${rfidCode}`);
    showToast('Unknown RFID card.', 'error');
    return;
  }

  const today = now.toISOString().split('T')[0];
  const todayIn = todayScans.find(s =>
    (s.rfid === rfidCode) && s.type === 'IN' && s.date === today
  );
  const todayOut = todayScans.find(s =>
    (s.rfid === rfidCode) && s.type === 'OUT' && s.date === today
  );

  // Prevent double OUT — student already scanned out today
  if (todayIn && todayOut) {
    showScanResult('error', '⚠️', 'Already Recorded', `${student.name} has already scanned IN and OUT today.`);
    showToast(`${student.name} already has Time In & Time Out recorded today.`, 'warning');
    return;
  }

  const type = todayIn ? 'OUT' : 'IN';
  const timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });

  // Determine late status
  let status = type === 'IN' ? 'On Time' : 'Departed';
  if (type === 'IN' && settings.lateThreshold) {
    const [lh, lm] = settings.lateThreshold.split(':').map(Number);
    if (now.getHours() > lh || (now.getHours() === lh && now.getMinutes() > lm)) {
      status = 'Late';
    }
  }

  // Build SMS message
  const template = type === 'IN'
    ? (settings.smsTemplateIn || 'Your child {name} has arrived at {time}.')
    : (settings.smsTemplateOut || 'Your child {name} has left at {time}.');
  const smsMessage = template.replace('{name}', student.name).replace('{time}', timeStr);

  const scanPayload = {
    id: 'ATT' + Date.now(),
    studentId: student.id,
    rfid: student.rfid,
    studentName: student.name,
    grade: student.grade,
    section: student.section,
    type,
    status,
    timestamp: now.toISOString(),
    date: today,
    parentContact: student.parentContact || student.parent_contact,
    smsMessage,
    smsStatus: 'Sent'
  };

  try {
    await fetch(`${API_BASE}/attendance/scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(scanPayload)
    });

    scanCooldowns[rfidCode] = now;
    todayScans.push({ ...scanPayload, student_name: student.name });
    renderScanLog();

    const icon = type === 'IN' ? '✅' : '🚪';
    showScanResult(
      type === 'IN' ? 'in' : 'out',
      icon,
      `${type === 'IN' ? 'Time In' : 'Time Out'} — ${student.name}`,
      `${student.grade} | ${student.section} | ${status} | ${timeStr}`
    );
    showToast(`${student.name} — ${type} recorded`, 'success');
  } catch (err) {
    console.error('Scan save error:', err);
    showToast('Failed to save scan. Check server connection.', 'error');
  }
}

function showScanResult(type, icon, title, sub) {
  const el = document.getElementById('scanResult');
  if (!el) return;
  el.className = `scan-result visible type-${type}`;
  el.innerHTML = `<div class="scan-result-inner">
    <div class="scan-result-icon">${icon}</div>
    <div class="scan-result-info">
      <h3>${title}</h3>
      <p>${sub}</p>
    </div>
  </div>`;
  setTimeout(() => { el.classList.remove('visible'); }, 5000);
}

function renderScanLog() {
  const tbody = document.getElementById('todayScansBody');
  const countEl = document.getElementById('scanCount');
  if (!tbody) return;
  if (countEl) countEl.textContent = `${todayScans.length} scans`;

  if (!todayScans.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted" style="padding:32px">No scans today.</td></tr>`;
    return;
  }
  tbody.innerHTML = [...todayScans].reverse().map(s => `
    <tr>
      <td>${s.rfid}</td>
      <td>${s.student_name || s.studentName}</td>
      <td>${s.grade}</td>
      <td>${new Date(s.timestamp).toLocaleTimeString()}</td>
      <td><span class="badge ${s.type === 'IN' ? 'badge-green' : 'badge-red'}">${s.type}</span></td>
      <td><span class="badge ${statusBadge(s.status)}">${s.status}</span></td>
    </tr>`).join('');
}

function simulateRFIDScan() {
  const available = students.filter(s => s.rfid);
  if (!available.length) { showToast('No students loaded.', 'warning'); return; }
  const pick = available[Math.floor(Math.random() * available.length)];
  processRFID(pick.rfid);
}

/* ─────────────────────────────────────────────────────────
   ATTENDANCE PAGE
───────────────────────────────────────────────────────── */
let allAttendance = [];

async function loadAttendance() {
  try {
    const res = await fetch(`${API_BASE}/attendance`);
    allAttendance = await res.json();
    // Group by student + date and show one row per student per day
    renderAttendance(allAttendance);
  } catch (err) {
    console.error('Attendance load error:', err);
    showToast('Failed to load attendance.', 'error');
  }
}

function renderAttendance(records) {
  const tbody = document.getElementById('attendanceBody');
  if (!tbody) return;

  // Group records: key = studentId + date
  const grouped = {};
  records.forEach(r => {
    const key = `${r.student_id || r.studentId}_${r.date}`;
    if (!grouped[key]) grouped[key] = { ...r, timeIn: null, timeOut: null, studentName: r.student_name || r.studentName };
    if (r.type === 'IN') grouped[key].timeIn = r.timestamp;
    if (r.type === 'OUT') grouped[key].timeOut = r.timestamp;
  });

  const rows = Object.values(grouped).sort((a, b) =>
    new Date(b.date) - new Date(a.date)
  );

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted" style="padding:32px">No attendance records found.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${r.rfid}</td>
      <td><strong>${r.studentName}</strong></td>
      <td>${r.grade}</td>
      <td>${r.date}</td>
      <td>${r.timeIn ? new Date(r.timeIn).toLocaleTimeString() : '—'}</td>
      <td>${r.timeOut ? new Date(r.timeOut).toLocaleTimeString() : '—'}</td>
      <td><span class="badge ${statusBadge(r.status)}">${r.status}</span></td>
    </tr>`).join('');
}

function filterAttendance() {
  const date = document.getElementById('filterDate')?.value;
  const grade = document.getElementById('filterGrade')?.value;
  const search = (document.getElementById('filterSearch')?.value || '').toLowerCase();

  let filtered = allAttendance;
  if (date) filtered = filtered.filter(r => r.date === date);
  if (grade) filtered = filtered.filter(r => r.grade === grade);
  if (search) filtered = filtered.filter(r =>
    (r.student_name || r.studentName || '').toLowerCase().includes(search) ||
    (r.rfid || '').toLowerCase().includes(search)
  );
  renderAttendance(filtered);
}

function exportAttendanceCSV() {
  const headers = ['RFID', 'Student Name', 'Grade', 'Date', 'Time In', 'Time Out', 'Status'];
  const grouped = {};
  allAttendance.forEach(r => {
    const key = `${r.student_id || r.studentId}_${r.date}`;
    if (!grouped[key]) grouped[key] = { ...r, timeIn: null, timeOut: null, studentName: r.student_name || r.studentName };
    if (r.type === 'IN') grouped[key].timeIn = r.timestamp;
    if (r.type === 'OUT') grouped[key].timeOut = r.timestamp;
  });
  const rows = Object.values(grouped).map(r => [
    r.rfid,
    r.studentName,
    r.grade,
    r.date,
    r.timeIn ? new Date(r.timeIn).toLocaleTimeString() : '',
    r.timeOut ? new Date(r.timeOut).toLocaleTimeString() : '',
    r.status
  ]);
  const csv = [headers, ...rows].map(r => r.join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `vmc-attendance-${Date.now()}.csv`; a.click();
  URL.revokeObjectURL(url);
  showToast('Attendance exported to CSV!', 'success');
}

/* ─────────────────────────────────────────────────────────
   STUDENTS PAGE
───────────────────────────────────────────────────────── */
let allStudents = [];

async function loadStudents() {
  try {
    const res = await fetch(`${API_BASE}/students`);
    allStudents = await res.json();
    renderStudents(allStudents);
  } catch (err) {
    console.error('Students load error:', err);
    showToast('Failed to load students.', 'error');
  }
}

function renderStudents(list) {
  const tbody = document.getElementById('studentBody');
  if (!tbody) return;
  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted" style="padding:32px">No students found.</td></tr>`;
    return;
  }
  tbody.innerHTML = list.map(s => `
    <tr>
      <td><code style="font-size:0.8rem;color:var(--accent-secondary)">${s.rfid}</code></td>
      <td><strong>${s.name}</strong></td>
      <td>${s.grade}</td>
      <td>${s.section}</td>
      <td>${s.parentName || s.parent_name}</td>
      <td>${s.parentContact || s.parent_contact}</td>
      <td>
        <div style="display:flex;gap:6px">
          <button class="btn btn-outline btn-sm" onclick="openEditStudentModal('${s.id}')">✏️ Edit</button>
          <button class="btn btn-danger btn-sm"  onclick="deleteStudent('${s.id}')">🗑️</button>
        </div>
      </td>
    </tr>`).join('');
}

function searchStudents() {
  const q = (document.getElementById('studentSearch')?.value || '').toLowerCase();
  renderStudents(q
    ? allStudents.filter(s =>
      s.name.toLowerCase().includes(q) ||
      s.rfid.toLowerCase().includes(q) ||
      s.grade.toLowerCase().includes(q) ||
      (s.parentContact || s.parent_contact || '').includes(q))
    : allStudents
  );
}

function openAddStudentModal() {
  document.getElementById('modalTitle').textContent = 'Add New Student';
  document.getElementById('studentForm').reset();
  document.getElementById('editStudentId').value = '';
  toggleModal('studentModal', true);
}

function openEditStudentModal(id) {
  const s = allStudents.find(x => x.id === id);
  if (!s) return;
  document.getElementById('modalTitle').textContent = 'Edit Student';
  document.getElementById('editStudentId').value = s.id;
  document.getElementById('inputName').value = s.name;
  document.getElementById('inputRfid').value = s.rfid;
  document.getElementById('inputGrade').value = s.grade;
  document.getElementById('inputSection').value = s.section;
  document.getElementById('inputParentName').value = s.parentName || s.parent_name;
  document.getElementById('inputParentContact').value = s.parentContact || s.parent_contact;
  toggleModal('studentModal', true);
}

async function saveStudent(e) {
  e.preventDefault();
  const editId = document.getElementById('editStudentId').value.trim();
  const payload = {
    id: editId || ('STU' + Date.now()),
    rfid: document.getElementById('inputRfid').value.trim(),
    name: document.getElementById('inputName').value.trim(),
    grade: document.getElementById('inputGrade').value,
    section: document.getElementById('inputSection').value.trim(),
    parentName: document.getElementById('inputParentName').value.trim(),
    parentContact: document.getElementById('inputParentContact').value.trim()
  };

  // FIX: use API_BASE (not the old API constant) so paths resolve correctly:
  //   ADD  → POST  /api/students
  //   EDIT → PUT   /api/students/{id}
  const url = editId ? `${API_BASE}/students/${editId}` : `${API_BASE}/students`;
  const method = editId ? 'PUT' : 'POST';

  try {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast(editId ? 'Student updated!' : 'Student added!', 'success');
      toggleModal('studentModal', false);
      loadStudents();
    } else {
      // FIX: show the actual error from the server, not a hardcoded message.
      const errMsg = data.error || 'Failed to save student. Check all fields and try again.';
      showToast(errMsg, 'error');
    }
  } catch (err) {
    console.error('Save student error:', err);
    showToast('Cannot reach server. Make sure the backend is running.', 'error');
  }
}

async function deleteStudent(id) {
  if (!confirm('Delete this student and all their records?')) return;
  try {
    const res = await fetch(`${API_BASE}/students/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      showToast('Student deleted.', 'success');
      loadStudents();
    } else {
      // Show real server error if available
      showToast(data.error || 'Delete failed. The student may have linked records.', 'error');
    }
  } catch (err) {
    console.error('Delete student error:', err);
    showToast('Cannot reach server. Make sure the backend is running.', 'error');
  }
}

async function loadSampleStudents() {
  const samples = [
    { id: 'DEMO001', rfid: 'DEMO-RF001', name: 'Maria Clara Santos', grade: 'Grade 7', section: 'St. Mark', parentName: 'Jose Santos', parentContact: '09171000001' },
    { id: 'DEMO002', rfid: 'DEMO-RF002', name: 'Jose Rizal Reyes', grade: 'Grade 8', section: 'St. Luke', parentName: 'Ana Reyes', parentContact: '09171000002' },
    { id: 'DEMO003', rfid: 'DEMO-RF003', name: 'Gabriela Luna', grade: 'Grade 9', section: 'St. John', parentName: 'Miguel Luna', parentContact: '09171000003' },
    { id: 'DEMO004', rfid: 'DEMO-RF004', name: 'Andres Bonifacio Cruz', grade: 'Grade 10', section: 'St. Matthew', parentName: 'Rosa Cruz', parentContact: '09171000004' },
    { id: 'DEMO005', rfid: 'DEMO-RF005', name: 'Melchora Aquino', grade: 'Grade 7', section: 'St. Peter', parentName: 'Carlos Aquino', parentContact: '09171000005' },
  ];
  try {
    const res = await fetch(`${API_BASE}/students/seed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(samples)
    });
    const data = await res.json();
    if (data.success) {
      showToast('Sample students loaded!', 'success');
      loadStudents();
    } else {
      showToast('Failed to load samples.', 'error');
    }
  } catch (err) {
    console.error('Load samples error:', err);
    showToast('Failed to load samples.', 'error');
  }
}

/* ─────────────────────────────────────────────────────────
   SMS PAGE
───────────────────────────────────────────────────────── */
let allSms = [];

async function loadSms() {
  try {
    const res = await fetch(`${API_BASE}/sms`);
    allSms = await res.json();
    renderSms(allSms);
  } catch (err) {
    console.error('SMS load error:', err);
    showToast('Failed to load SMS logs.', 'error');
  }
}

function renderSms(list) {
  const tbody = document.getElementById('smsBody');
  if (!tbody) return;
  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted" style="padding:32px">No SMS logs found.</td></tr>`;
    return;
  }
  tbody.innerHTML = list.map(s => `
    <tr>
      <td style="white-space:nowrap">${new Date(s.timestamp).toLocaleString()}</td>
      <td><strong>${s.student_name || s.studentName}</strong></td>
      <td>${s.parent_contact || s.parentContact}</td>
      <td style="max-width:200px;font-size:0.78rem;color:var(--text-muted)">${s.message}</td>
      <td><span class="badge ${s.type === 'IN' ? 'badge-green' : 'badge-red'}">${s.type}</span></td>
      <td><span class="badge ${s.status === 'Sent' ? 'badge-green' : 'badge-red'}">${s.status}</span></td>
      <td>
        <button class="btn btn-outline btn-sm" onclick="resendSms('${s.id}')">🔁 Resend</button>
      </td>
    </tr>`).join('');
}

function filterSms() {
  const date = document.getElementById('smsFilterDate')?.value;
  const status = document.getElementById('smsFilterStatus')?.value;
  const search = (document.getElementById('smsFilterSearch')?.value || '').toLowerCase();

  let f = allSms;
  if (date) f = f.filter(s => s.date === date);
  if (status) f = f.filter(s => s.status === status);
  if (search) f = f.filter(s =>
    (s.student_name || s.studentName || '').toLowerCase().includes(search) ||
    (s.parent_contact || s.parentContact || '').includes(search)
  );
  renderSms(f);
}

async function resendSms(id) {
  try {
    await fetch(`${API_BASE}/sms/${id}/resend`, { method: 'POST' });
    showToast('SMS resent successfully.', 'success');
    loadSms();
  } catch (err) {
    console.error('Resend SMS error:', err);
    showToast('Failed to resend.', 'error');
  }
}

/* ─────────────────────────────────────────────────────────
   SETTINGS PAGE
───────────────────────────────────────────────────────── */
async function loadSettings() {
  try {
    const res = await fetch(`${API_BASE}/settings`);
    const data = await res.json();

    setVal('settingAdminName', data.adminName);
    setVal('settingAdminEmail', data.adminEmail);
    setVal('settingSmsSender', data.smsSenderName);
    setVal('settingSmsTemplateIn', data.smsTemplateIn);
    setVal('settingSmsTemplateOut', data.smsTemplateOut);
    setVal('settingCooldown', data.scanCooldown);
    setVal('settingLateThreshold', data.lateThreshold);
    setVal('settingSchoolStart', data.schoolStart);
    setVal('settingSchoolEnd', data.schoolEnd);
  } catch (err) {
    console.error('Settings load error:', err);
    showToast('Failed to load settings.', 'error');
  }
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el && val !== undefined) el.value = val;
}

async function saveSettings(e) {
  e.preventDefault();
  const payload = {
    adminName: getVal('settingAdminName'),
    adminEmail: getVal('settingAdminEmail'),
    smsSenderName: getVal('settingSmsSender'),
    smsTemplateIn: getVal('settingSmsTemplateIn'),
    smsTemplateOut: getVal('settingSmsTemplateOut'),
    scanCooldown: getVal('settingCooldown'),
    lateThreshold: getVal('settingLateThreshold'),
    schoolStart: getVal('settingSchoolStart'),
    schoolEnd: getVal('settingSchoolEnd')
  };

  try {
    const res = await fetch(`${API_BASE}/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) showToast('Settings saved!', 'success');
  } catch (err) {
    console.error('Save settings error:', err);
    showToast('Failed to save settings.', 'error');
  }
}

function getVal(id) {
  return document.getElementById(id)?.value || '';
}

async function changePassword(e) {
  e.preventDefault();
  const current = document.getElementById('currentPassword').value;
  const newPwd = document.getElementById('newPassword').value;
  const confirm = document.getElementById('confirmPassword').value;

  if (newPwd !== confirm) { showToast('New passwords do not match.', 'error'); return; }
  if (newPwd.length < 4) { showToast('Password too short (min 4 chars).', 'warning'); return; }

  try {
    const res = await fetch(`${API_BASE}/settings/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current, new: newPwd })
    });
    const data = await res.json();
    if (data.success) {
      showToast('Password changed successfully.', 'success');
      e.target.reset();
    } else {
      showToast(data.message || 'Incorrect current password.', 'error');
    }
  } catch (err) {
    console.error('Change password error:', err);
    showToast('Server error.', 'error');
  }
}

async function clearAllData() {
  if (!confirm('⚠️ DELETE ALL students, attendance, and SMS logs? This cannot be undone.')) return;
  try {
    const res = await fetch(`${API_BASE}/clear`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast('All data cleared.', 'warning');
      // Redirect to dashboard after clearing
      setTimeout(() => { window.location.href = 'dashboard.html'; }, 1500);
    } else {
      showToast('Failed to clear data: ' + (data.error || 'Unknown error'), 'error');
    }
  } catch (err) {
    console.error('Clear data error:', err);
    showToast('Failed to clear data.', 'error');
  }
}

/* ─────────────────────────────────────────────────────────
   SHARED HELPER
───────────────────────────────────────────────────────── */
/* ─────────────────────────────────────────────────────────
   PARENT PORTAL PAGE
   ───────────────────────────────────────────────────────── */
async function loadParentPortal() {
  const studentId = localStorage.getItem('vmc_student_id');
  if (!studentId) {
    logout();
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/parent/portal/${studentId}`);
    const data = await res.json();
    if (!data.success) {
      showToast('Failed to load child data.', 'error');
      return;
    }

    const { student, attendance } = data;

    // Fill parent metadata
    const initials = student.parentName ? student.parentName.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase() : 'PC';
    const avatarEl = document.getElementById('parentPortalAvatar');
    if (avatarEl) avatarEl.textContent = initials;

    const nameEl = document.getElementById('parentPortalName');
    if (nameEl) nameEl.textContent = student.parentName || 'Parent / Guardian';

    const detailsEl = document.getElementById('parentPortalDetails');
    if (detailsEl) {
      detailsEl.textContent = `Contact: ${student.parentContact || '—'} • Student Linked: ${student.name} (${student.id})`;
    }

    // Render child card and attendance history
    const container = document.getElementById('childrenContainer');
    if (container) {
      if (!attendance || attendance.length === 0) {
        container.innerHTML = `
          <div class="child-card glass-card" style="padding: 24px;">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:12px; margin-bottom:16px;">
              <div>
                <h3 style="font-size:1.15rem; font-weight:700; margin:0; color:var(--text-main);">${student.name}</h3>
                <p style="font-size:0.85rem; color:var(--text-muted); margin:4px 0 0 0">${student.grade} | ${student.section} | RFID: ${student.rfid}</p>
              </div>
            </div>
            <p class="text-muted text-center" style="padding: 24px 0;">No attendance records found yet.</p>
          </div>
        `;
        return;
      }

      // Group attendance by date for this child
      const grouped = {};
      attendance.forEach(r => {
        if (!grouped[r.date]) {
          grouped[r.date] = { date: r.date, timeIn: null, timeOut: null, status: '—' };
        }
        if (r.type === 'IN') {
          grouped[r.date].timeIn = r.timestamp;
          grouped[r.date].status = r.status;
        }
        if (r.type === 'OUT') {
          grouped[r.date].timeOut = r.timestamp;
        }
      });

      const sortedHistory = Object.values(grouped).sort((a, b) => new Date(b.date) - new Date(a.date));

      const tableRows = sortedHistory.map(h => {
        const timeInStr = h.timeIn ? new Date(h.timeIn).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';
        const timeOutStr = h.timeOut ? new Date(h.timeOut).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';

        return `
          <tr>
            <td>${h.date}</td>
            <td>${timeInStr}</td>
            <td>${timeOutStr}</td>
            <td><span class="badge ${statusBadge(h.status)}">${h.status}</span></td>
          </tr>
        `;
      }).join('');

      container.innerHTML = `
        <div class="child-card glass-card" style="padding: 24px; overflow: hidden;">
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:12px; margin-bottom:16px;">
            <div>
              <h3 style="font-size:1.15rem; font-weight:700; margin:0; color:var(--text-main);">${student.name}</h3>
              <p style="font-size:0.85rem; color:var(--text-muted); margin:4px 0 0 0">${student.grade} | ${student.section} | RFID: ${student.rfid}</p>
            </div>
            <span class="badge badge-green" style="font-size:0.75rem">Enrolled</span>
          </div>
          
          <div style="overflow-x: auto;">
            <table class="data-table" style="margin-top: 8px;">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Time In</th>
                  <th>Time Out</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                ${tableRows}
              </tbody>
            </table>
          </div>
        </div>
      `;
    }
  } catch (err) {
    console.error('Parent portal load error:', err);
    showToast('Failed to connect to the server.', 'error');
  }
}

function statusBadge(status) {
  const map = {
    'On Time': 'badge-green',
    'Late': 'badge-orange',
    'Departed': 'badge-blue',
    'Sent': 'badge-green',
    'Failed': 'badge-red',
    'Absent': 'badge-red'
  };
  return map[status] || 'badge-neutral';
}

/* ─────────────────────────────────────────────────────────
   PAGE ROUTER — runs on DOMContentLoaded
───────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  guardAuth();
  startClock();

  const page = document.body.dataset.page;

  if (page === 'dashboard') loadDashboard();
  if (page === 'rfid') loadRFID();
  if (page === 'attendance') loadAttendance();
  if (page === 'students') loadStudents();
  if (page === 'sms') loadSms();
  if (page === 'settings') loadSettings();
  if (page === 'parent-portal') loadParentPortal();
});
