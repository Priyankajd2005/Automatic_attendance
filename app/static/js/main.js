/**
 * FaceAttend - Main JavaScript
 * Handles photo dropzones, attendance verification interactivity,
 * multi-step forms, and general UI enhancements.
 */

// =====================================================
//  Photo Dropzone Handler
// =====================================================
function initDropzone(dropzoneId, inputId, previewId) {
  const dropzone = document.getElementById(dropzoneId);
  const input    = document.getElementById(inputId);
  const preview  = document.getElementById(previewId);

  if (!dropzone || !input) return;

  ['dragenter','dragover'].forEach(evt => {
    dropzone.addEventListener(evt, e => {
      e.preventDefault();
      dropzone.classList.add('drag-over');
    });
  });

  ['dragleave','drop'].forEach(evt => {
    dropzone.addEventListener(evt, e => {
      e.preventDefault();
      dropzone.classList.remove('drag-over');
    });
  });

  dropzone.addEventListener('drop', e => {
    const file = e.dataTransfer.files[0];
    if (file) showPreview(file, preview, dropzone);
  });

  input.addEventListener('change', () => {
    const file = input.files[0];
    if (file) showPreview(file, preview, dropzone);
  });
}

function showPreview(file, preview, dropzone) {
  if (!file.type.startsWith('image/')) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    if (preview) {
      preview.src = e.target.result;
      preview.style.display = 'block';
    }
    const uploadContent = dropzone.querySelector('.upload-content');
    if (uploadContent) uploadContent.style.display = 'none';
  };
  reader.readAsDataURL(file);
}

// =====================================================
//  Multi-Step Form
// =====================================================
let currentStep = 1;
const totalSteps = 3;

function showStep(step) {
  document.querySelectorAll('.form-step').forEach(el => el.classList.remove('active'));
  const el = document.querySelector(`[data-step="${step}"]`);
  if (el) el.classList.add('active');

  document.querySelectorAll('.step-item').forEach((item, idx) => {
    item.classList.remove('active', 'completed');
    if (idx + 1 < step) item.classList.add('completed');
    if (idx + 1 === step) item.classList.add('active');
  });

  updateNavButtons();
}

function nextStep() {
  if (currentStep < totalSteps) {
    if (validateStep(currentStep)) {
      currentStep++;
      showStep(currentStep);
      window.scrollTo(0, 0);
    }
  }
}

function prevStep() {
  if (currentStep > 1) {
    currentStep--;
    showStep(currentStep);
    window.scrollTo(0, 0);
  }
}

function validateStep(step) {
  if (step === 1) {
    const required = ['full_name', 'roll_number', 'college', 'department', 'semester'];
    for (const field of required) {
      const el = document.getElementById(field);
      if (el && !el.value.trim()) {
        el.classList.add('is-invalid');
        el.focus();
        showToast('Please fill in all required fields', 'warning');
        return false;
      } else if (el) {
        el.classList.remove('is-invalid');
      }
    }
  }
  if (step === 2) {
    const photo1 = document.getElementById('photo1');
    if (photo1 && photo1.files.length === 0) {
      showToast('Please upload at least one face photo (front photo is required)', 'warning');
      return false;
    }
  }
  return true;
}

function updateNavButtons() {
  const prevBtn = document.getElementById('prevBtn');
  const nextBtn = document.getElementById('nextBtn');
  const submitBtn = document.getElementById('submitBtn');

  if (prevBtn) prevBtn.style.display = currentStep === 1 ? 'none' : 'inline-block';
  if (nextBtn) nextBtn.style.display = currentStep === totalSteps ? 'none' : 'inline-block';
  if (submitBtn) submitBtn.style.display = currentStep === totalSteps ? 'inline-block' : 'none';
}

function populateConfirmation() {
  const fields = ['full_name', 'roll_number', 'college', 'department', 'semester', 'student_id', 'email', 'phone'];
  fields.forEach(field => {
    const input = document.getElementById(field);
    const display = document.getElementById('confirm_' + field);
    if (input && display) display.textContent = input.value || '-';
  });
}

// =====================================================
//  Attendance Verify Page - Face Box Interactivity
// =====================================================
function initFaceBoxes(recognitionData, imageNaturalWidth, imageNaturalHeight) {
  const wrapper = document.getElementById('faceCanvasWrapper');
  const img = document.getElementById('classroomPhoto');
  if (!wrapper || !img) return;

  function drawBoxes() {
    wrapper.querySelectorAll('.face-box').forEach(b => b.remove());

    const displayW = img.clientWidth;
    const displayH = img.clientHeight;
    const scaleX = displayW / imageNaturalWidth;
    const scaleY = displayH / imageNaturalHeight;

    recognitionData.forEach((face, idx) => {
      const [top, right, bottom, left] = face.location;

      const box = document.createElement('div');
      box.className = `face-box ${face.status === 'recognized' ? 'recognized' : 'unknown'}`;
      box.dataset.idx = idx;
      box.dataset.rollNumber = face.roll_number || '';
      box.style.top    = (top  * scaleY) + 'px';
      box.style.left   = (left * scaleX) + 'px';
      box.style.width  = ((right - left) * scaleX) + 'px';
      box.style.height = ((bottom - top) * scaleY) + 'px';

      const label = document.createElement('div');
      label.className = 'face-label';
      label.textContent = face.name || 'Unknown';
      box.appendChild(label);

      box.addEventListener('click', () => highlightStudent(face.roll_number));
      box.addEventListener('mouseenter', () => {
        if (face.roll_number) highlightStudent(face.roll_number, false);
      });

      wrapper.appendChild(box);
    });
  }

  img.addEventListener('load', drawBoxes);
  if (img.complete) drawBoxes();
  window.addEventListener('resize', drawBoxes);
}

function highlightStudent(rollNumber, scroll = true) {
  document.querySelectorAll('.attendance-row-highlighted').forEach(r => r.classList.remove('attendance-row-highlighted'));
  if (!rollNumber) return;
  const row = document.querySelector(`tr[data-roll="${rollNumber}"]`);
  if (row) {
    row.classList.add('attendance-row-highlighted');
    if (scroll) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

// =====================================================
//  Attendance Status Toggle
// =====================================================
function setAttendanceStatus(studentId, status) {
  const hiddenInput = document.querySelector(`input[name="status_${studentId}"]`);
  if (hiddenInput) hiddenInput.value = status;

  const row = document.querySelector(`tr[data-student-id="${studentId}"]`);
  if (row) {
    const presentBtn = row.querySelector('.btn-present');
    const absentBtn  = row.querySelector('.btn-absent');
    const badge      = row.querySelector('.status-badge');

    if (status === 'Present') {
      if (presentBtn) { presentBtn.classList.add('btn-success'); presentBtn.classList.remove('btn-outline-success'); }
      if (absentBtn)  { absentBtn.classList.remove('btn-danger'); absentBtn.classList.add('btn-outline-danger'); }
      if (badge) { badge.textContent = 'Present'; badge.className = 'status-badge badge-present'; }
    } else {
      if (absentBtn)  { absentBtn.classList.add('btn-danger'); absentBtn.classList.remove('btn-outline-danger'); }
      if (presentBtn) { presentBtn.classList.remove('btn-success'); presentBtn.classList.add('btn-outline-success'); }
      if (badge) { badge.textContent = 'Absent'; badge.className = 'status-badge badge-absent'; }
    }

    updateSummary();
  }
}

function updateSummary() {
  const presentCount = document.querySelectorAll('input[name^="status_"][value="Present"]').length;
  const absentCount  = document.querySelectorAll('input[name^="status_"][value="Absent"]').length;
  const totalCount   = presentCount + absentCount;

  const el = document.getElementById('summaryText');
  if (el) el.textContent = `${presentCount} Present, ${absentCount} Absent, ${totalCount} Total`;

  const pct = totalCount > 0 ? Math.round((presentCount / totalCount) * 100) : 0;
  const bar = document.getElementById('summaryBar');
  if (bar) { bar.style.width = pct + '%'; bar.textContent = pct + '%'; }
}

// =====================================================
//  Subject Load (Dynamic)
// =====================================================
function loadSubjects(dept, semester, targetSelect) {
  if (!dept || !semester) return;
  fetch(`/api/subjects?department=${encodeURIComponent(dept)}&semester=${encodeURIComponent(semester)}`)
    .then(r => r.json())
    .then(data => {
      const sel = document.getElementById(targetSelect);
      if (!sel) return;
      sel.innerHTML = '<option value="">-- Select Subject --</option>';
      data.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.id;
        opt.textContent = `${s.name} (${s.code})`;
        sel.appendChild(opt);
      });
    })
    .catch(err => console.error('Error loading subjects:', err));
}

// =====================================================
//  Toast Notifications
// =====================================================
function showToast(message, type = 'info') {
  const colors = { success: '#34a853', danger: '#ea4335', warning: '#f09300', info: '#1a73e8' };
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; top: 80px; right: 20px; z-index: 9999;
    background: ${colors[type] || colors.info}; color: white;
    padding: 12px 20px; border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    font-size: 0.9rem; font-weight: 500;
    animation: slideIn 0.3s ease; max-width: 350px;
  `;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// =====================================================
//  Processing Face Recognition
// =====================================================
async function processAttendance(sessionId) {
  const overlay = document.getElementById('loadingOverlay');
  if (overlay) overlay.style.display = 'flex';

  try {
    const response = await fetch(`/attendance/process/${sessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() }
    });
    const data = await response.json();

    if (data.success) {
      window.location.href = `/attendance/verify/${sessionId}`;
    } else {
      showToast('Error processing attendance: ' + (data.error || 'Unknown error'), 'danger');
      if (overlay) overlay.style.display = 'none';
    }
  } catch (err) {
    console.error(err);
    showToast('Network error. Please try again.', 'danger');
    if (overlay) overlay.style.display = 'none';
  }
}

// =====================================================
//  Utilities
// =====================================================
function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : '';
}

function confirmAction(message) {
  return confirm(message);
}

// Date picker default to today
document.addEventListener('DOMContentLoaded', () => {
  const dateInputs = document.querySelectorAll('input[type="date"]');
  dateInputs.forEach(input => {
    if (!input.value) {
      input.value = new Date().toISOString().split('T')[0];
    }
  });

  // Initialize sidebar active link
  const currentPath = window.location.pathname;
  document.querySelectorAll('.sidebar .nav-link').forEach(link => {
    if (link.getAttribute('href') === currentPath) {
      link.classList.add('active');
    }
  });

  // Auto-dismiss flash messages
  setTimeout(() => {
    document.querySelectorAll('.alert-dismissible').forEach(alert => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) bsAlert.close();
    });
  }, 5000);

  // Init any dropzones on page
  initDropzone('dropzone1', 'photo1', 'preview1');
  initDropzone('dropzone2', 'photo2', 'preview2');
  initDropzone('dropzone3', 'photo3', 'preview3');
  initDropzone('classroomDropzone', 'classroom_photo', 'classroomPreview');
});

// Slideshow animation keyframe
const style = document.createElement('style');
style.textContent = `
  @keyframes slideIn {
    from { opacity: 0; transform: translateX(20px); }
    to   { opacity: 1; transform: translateX(0); }
  }
`;
document.head.appendChild(style);
