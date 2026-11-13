/* Shiftcheck front-end behaviours. No framework: progressive enhancement on server-rendered pages. */
(function () {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const APP_ROOT = $('meta[name="app-root"]')?.content || '';
  const CSRF = $('meta[name="csrf-token"]')?.content || '';

  const icons = () => window.lucide && window.lucide.createIcons();
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  async function api(url, body) {
    const resp = await fetch(url.startsWith('/') ? APP_ROOT + url : url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF, 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await resp.json(); } catch (e) { /* non-JSON error page */ }
    if (!resp.ok || data.success === false) throw new Error(data.error || `คำขอล้มเหลว (${resp.status})`);
    return data;
  }

  // ------------------------------------------------------------ toasts & dialogs
  function toast(message, kind = 'success', timeout = 4200) {
    const box = $('#toasts');
    if (!box) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    el.innerHTML = `<span class="bar"></span><span>${esc(message)}</span><button type="button" aria-label="ปิด">×</button>`;
    el.querySelector('button').onclick = () => el.remove();
    box.appendChild(el);
    if (timeout) setTimeout(() => el.remove(), timeout);
  }

  function modal({ title, body, actions = [], wide = false, onOpen }) {
    return new Promise((resolve) => {
      const back = document.createElement('div');
      back.className = 'modal-backdrop';
      back.innerHTML = `<div class="modal${wide ? ' wide' : ''}" role="dialog" aria-modal="true" aria-labelledby="mdl-title">
        <div class="modal-head"><h3 id="mdl-title">${esc(title)}</h3><button class="icon-btn" type="button" data-close aria-label="ปิด"><i data-lucide="x"></i></button></div>
        <div class="modal-body"></div><div class="modal-foot"></div></div>`;
      const bodyEl = back.querySelector('.modal-body');
      typeof body === 'string' ? (bodyEl.innerHTML = body) : bodyEl.appendChild(body);
      const foot = back.querySelector('.modal-foot');
      const previous = document.activeElement;
      const close = (value) => { back.remove(); document.removeEventListener('keydown', onKey); previous?.focus?.(); resolve(value); };
      const onKey = (e) => { if (e.key === 'Escape') close(null); };
      actions.forEach((a) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = `btn ${a.className || ''}`;
        b.textContent = a.label;
        b.onclick = () => { const v = a.value; if (a.handler) { if (a.handler(close) === false) return; } close(v); };
        foot.appendChild(b);
      });
      if (!actions.length) foot.remove();
      back.querySelector('[data-close]').onclick = () => close(null);
      back.addEventListener('mousedown', (e) => { if (e.target === back) close(null); });
      document.addEventListener('keydown', onKey);
      document.body.appendChild(back);
      icons();
      onOpen?.(back, close);
      (foot.querySelector('.btn-primary, .btn-danger') || back.querySelector('[data-close]')).focus();
    });
  }

  const confirmDialog = (title, text, label = 'ยืนยัน', danger = false) => modal({
    title, body: `<p>${esc(text)}</p>`,
    actions: [{ label: 'ยกเลิก', value: false, className: 'btn-ghost' }, { label, value: true, className: danger ? 'btn-danger' : 'btn-primary' }],
  });

  window.Shiftcheck = { api, toast, modal, confirmDialog, esc, icons, APP_ROOT };

  // ------------------------------------------------------------ shell
  function initShell() {
    $('[data-nav-toggle]')?.addEventListener('click', () => document.body.classList.toggle('nav-open'));
    document.addEventListener('click', (e) => {
      if (document.body.classList.contains('nav-open') && !e.target.closest('#nav, [data-nav-toggle]')) document.body.classList.remove('nav-open');
    });

    $('[data-theme-toggle]')?.addEventListener('click', () => {
      const root = document.documentElement;
      const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
      root.dataset.theme = dark ? 'light' : 'dark';
      try { localStorage.setItem('shiftcheck-theme', root.dataset.theme); } catch (e) { /* private mode */ }
    });

    // Dropdown menus: <button data-dropdown> followed by <div class="dropdown" hidden>. One open at a time.
    // The menu is position: fixed and placed here, so a scrolling table wrapper can never clip it.
    let openMenu = null;
    const closeMenu = (refocus) => {
      if (!openMenu) return;
      openMenu.menu.hidden = true;
      openMenu.btn.setAttribute('aria-expanded', 'false');
      if (refocus) openMenu.btn.focus();
      openMenu = null;
    };
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-dropdown]');
      if (btn) {
        const menu = btn.nextElementSibling;
        const wasOpen = openMenu && openMenu.btn === btn;
        closeMenu();
        if (wasOpen || !menu) return;
        menu.hidden = false;
        btn.setAttribute('aria-expanded', 'true');
        const r = btn.getBoundingClientRect();
        const w = menu.offsetWidth, h = menu.offsetHeight;
        let top = r.bottom + 6;
        if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 6);
        menu.style.top = `${top}px`;
        menu.style.left = `${Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8))}px`;
        openMenu = { btn, menu };
        return;
      }
      // Choosing an item closes the menu after the click has done its work (submit, navigate, toggle).
      if (openMenu) (openMenu.menu.contains(e.target) ? setTimeout : (fn) => fn())(() => closeMenu());
    });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(true); });
    window.addEventListener('scroll', () => closeMenu(), true);
    window.addEventListener('resize', () => closeMenu());

    // Flash messages: success/info become toasts, problems stay inline where they are noticed.
    $$('[data-flashes] .notice').forEach((n) => {
      const cat = n.dataset.category;
      if (cat === 'success' || cat === 'info') { toast(n.textContent.trim(), 'success'); n.remove(); }
    });
    const fl = $('[data-flashes]');
    if (fl && !fl.children.length) fl.remove();

    document.addEventListener('click', (e) => {
      const opener = e.target.closest('[data-open-dialog]');
      if (opener) document.getElementById(opener.dataset.openDialog)?.showModal();
      const closer = e.target.closest('[data-close-dialog]');
      if (closer) closer.closest('dialog')?.close();
    });
    $$('dialog.dialog').forEach((d) => d.addEventListener('click', (e) => { if (e.target === d) d.close(); }));

    $$('select[data-autosubmit]').forEach((s) => s.addEventListener('change', () => s.form.submit()));

    // <form data-confirm="..."> asks before submitting.
    $$('form[data-confirm]').forEach((form) => form.addEventListener('submit', async (e) => {
      if (form.dataset.confirmed) return;
      e.preventDefault();
      const ok = await confirmDialog(form.dataset.confirmTitle || 'ยืนยันการทำรายการ?', form.dataset.confirm,
        form.dataset.confirmLabel || 'ดำเนินการต่อ', form.dataset.danger !== undefined);
      if (ok) { form.dataset.confirmed = '1'; (e.submitter && e.submitter.name) ? form.requestSubmit(e.submitter) : form.submit(); }
    }));

    // Prevent double submission
    $$('form[data-busy]').forEach((form) => form.addEventListener('submit', (e) => {
      if (e.defaultPrevented) return;
      const btn = e.submitter || form.querySelector('[type=submit]');
      setTimeout(() => btn?.classList.add('is-busy'), 0);
    }));
  }

  // ------------------------------------------------------------ repeatable note rows
  function initNotes() {
    $$('[data-notes]').forEach((wrap) => {
      const rows = $('.rows', wrap);
      wrap.addEventListener('click', (e) => {
        if (e.target.closest('[data-add-row]')) {
          const clone = rows.firstElementChild.cloneNode(true);
          $$('input, textarea', clone).forEach((i) => (i.value = ''));
          rows.appendChild(clone);
          icons();
          $('input', clone).focus();
        }
        const rm = e.target.closest('[data-remove-row]');
        if (rm) {
          const row = rm.closest('.note-row');
          if (rows.children.length > 1) row.remove(); else $$('input, textarea', row).forEach((i) => (i.value = ''));
        }
      });
    });
  }

  // ------------------------------------------------------------ signature pad
  function signaturePad(title) {
    const body = document.createElement('div');
    body.innerHTML = '<canvas class="sign-canvas" aria-label="พื้นที่เซ็นชื่อ"></canvas><p class="muted small" style="margin-top:8px">เซ็นด้วยนิ้ว ปากกา หรือเมาส์</p>';
    const canvas = body.querySelector('canvas');
    let drawn = false;
    return modal({
      title, body, wide: false,
      actions: [
        { label: 'ล้าง', className: 'btn-ghost', handler: () => { canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height); drawn = false; return false; } },
        { label: 'ยกเลิก', className: 'btn-ghost', value: null },
        { label: 'ใช้ลายเซ็นนี้', className: 'btn-primary', handler: (close) => { close(drawn ? canvas.toDataURL('image/png') : ''); return false; } },
      ],
      onOpen: () => {
        const ratio = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * ratio; canvas.height = rect.height * ratio;
        const ctx = canvas.getContext('2d');
        ctx.scale(ratio, ratio); ctx.lineWidth = 2.2; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#13201c';
        let drawing = false;
        const pos = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
        canvas.addEventListener('pointerdown', (e) => { drawing = true; canvas.setPointerCapture(e.pointerId); ctx.beginPath(); ctx.moveTo(...pos(e)); });
        canvas.addEventListener('pointermove', (e) => { if (!drawing) return; ctx.lineTo(...pos(e)); ctx.stroke(); drawn = true; });
        ['pointerup', 'pointercancel'].forEach((ev) => canvas.addEventListener(ev, () => { drawing = false; }));
      },
    });
  }

  function initSignatures() {
    $$('[data-signature-open]').forEach((btn) => btn.addEventListener('click', async () => {
      const input = btn.parentElement.querySelector('[data-signature-input]');
      const result = await signaturePad(btn.dataset.title || 'ลายเซ็น');
      if (result === null) return;
      input.value = result;
      btn.innerHTML = result ? `<img src="${result}" alt="ลายเซ็น">` : 'แตะเพื่อเซ็นชื่อ';
    }));
  }

  // ------------------------------------------------------------ lightbox
  function lightbox(sources, start = 0) {
    let index = start;
    const el = document.createElement('div');
    el.className = 'lightbox';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.innerHTML = `<div class="lightbox-bar"><span data-count></span><button class="icon-btn" data-x aria-label="ปิด"><i data-lucide="x"></i></button></div>
      <div class="lightbox-stage"><button class="icon-btn" data-prev aria-label="รูปก่อนหน้า"><i data-lucide="chevron-left"></i></button><img alt=""><button class="icon-btn" data-next aria-label="รูปถัดไป"><i data-lucide="chevron-right"></i></button></div>`;
    const img = $('img', el);
    const show = () => { img.src = sources[index]; img.alt = `รูปที่ ${index + 1}`; $('[data-count]', el).textContent = `รูปที่ ${index + 1} จาก ${sources.length}`; };
    const step = (d) => { index = (index + d + sources.length) % sources.length; show(); };
    const close = () => { el.remove(); document.removeEventListener('keydown', key); };
    const key = (e) => { if (e.key === 'Escape') close(); if (e.key === 'ArrowLeft') step(-1); if (e.key === 'ArrowRight') step(1); };
    $('[data-x]', el).onclick = close; $('[data-prev]', el).onclick = () => step(-1); $('[data-next]', el).onclick = () => step(1);
    el.addEventListener('click', (e) => { if (e.target.classList.contains('lightbox-stage')) close(); });
    document.addEventListener('keydown', key);
    document.body.appendChild(el); icons(); show();
    $('[data-x]', el).focus();
  }

  function initGalleries() {
    $$('[data-gallery]').forEach((g) => g.addEventListener('click', (e) => {
      const img = e.target.closest('img[data-lightbox]');
      if (img) lightbox($$('img[data-lightbox]', g).map((i) => i.src), Number(img.dataset.lightbox));
    }));
  }

  // ------------------------------------------------------------ photo capture
  function compress(src, maxDim = 1280, quality = 0.8) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
        const c = document.createElement('canvas');
        c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        let out = c.toDataURL('image/webp', quality);
        if (!out.startsWith('data:image/webp')) out = c.toDataURL('image/jpeg', quality);
        resolve(out);
      };
      img.onerror = () => reject(new Error('ไม่สามารถเปิดไฟล์นี้เป็นรูปภาพได้'));
      img.src = src;
    });
  }

  const readFile = (file) => new Promise((resolve, reject) => {
    const r = new FileReader(); r.onload = () => resolve(r.result); r.onerror = reject; r.readAsDataURL(file);
  });

  function cameraHelp(err) {
    if (!window.isSecureContext) return 'เบราว์เซอร์อนุญาตให้ใช้กล้องเฉพาะหน้าเว็บ HTTPS (หรือ localhost) กรุณาเปิดผ่าน HTTPS';
    const name = err && err.name;
    if (name === 'NotAllowedError' || name === 'SecurityError') return 'กล้องถูกบล็อก กรุณาอนุญาตการใช้กล้องในการตั้งค่าเว็บไซต์ของเบราว์เซอร์ แล้วลองใหม่';
    if (name === 'NotReadableError') return 'มีแอปอื่นใช้กล้องอยู่ กรุณาปิดแอปนั้นแล้วลองใหม่';
    if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'ไม่พบกล้องบนอุปกรณ์นี้';
    return 'ไม่สามารถเปิดกล้องบนอุปกรณ์นี้ได้';
  }

  function initPhotoCapture() {
    $$('[data-photo-capture]').forEach((root) => {
      const max = Number(root.dataset.max) || 7;
      const min = Number(root.dataset.min) || 0;
      const kind = root.closest('form')?.dataset.kind || 'photo';
      const grid = $('[data-photo-grid]', root);
      const input = $('[data-photo-input]', root);
      const counter = $('[data-photo-count]', root);
      const items = []; // { preview, value } value = stored path or data URL fallback

      function render() {
        grid.innerHTML = '';
        items.forEach((item, i) => {
          const tile = document.createElement('div');
          tile.className = 'photo-tile' + (item.uploading ? ' uploading' : '');
          tile.innerHTML = `<img src="${item.preview}" alt="รูปที่ ${i + 1}"><span class="badge">${i + 1}${i === 0 ? ' · รูปทีม' : ''}</span>
            <button type="button" class="remove" aria-label="ลบรูปที่ ${i + 1}"><i data-lucide="x"></i></button>`;
          $('img', tile).onclick = () => lightbox(items.map((x) => x.preview), i);
          $('.remove', tile).onclick = () => { items.splice(i, 1); render(); };
          grid.appendChild(tile);
        });
        for (let i = items.length; i < Math.max(min, Math.min(max, 3)); i++) {
          const slot = document.createElement('div');
          slot.className = 'photo-slot';
          slot.textContent = i === 0 ? 'รูปทีม' : (i < min ? 'จำเป็น' : 'ไม่บังคับ');
          grid.appendChild(slot);
        }
        input.value = JSON.stringify(items.filter((x) => !x.uploading).map((x) => x.value));
        counter.textContent = `${items.length} จาก ${max} รูป${min ? ` · ต้องมีอย่างน้อย ${min} รูป` : ''}`;
        icons();
        root.dispatchEvent(new CustomEvent('photos:change', { bubbles: true, detail: { count: items.length } }));
      }

      async function add(dataUrl) {
        if (items.length >= max) { toast(`แนบรูปได้สูงสุด ${max} รูป`, 'warning'); return; }
        const item = { preview: dataUrl, value: dataUrl, uploading: true };
        items.push(item); render();
        try {
          const res = await api('/uploads/photo', { photo: dataUrl, kind });
          item.value = res.path;
        } catch (e) {
          toast('บันทึกรูปไว้ในเครื่องแล้ว ระบบจะอัปโหลดพร้อมฟอร์ม', 'warning');
        }
        item.uploading = false; render();
      }

      root.closest('form')?.addEventListener('submit', (e) => {
        if (items.some((x) => x.uploading)) { e.preventDefault(); toast('กรุณารอให้อัปโหลดรูปเสร็จก่อน', 'warning'); return; }
        if (items.length < min) { e.preventDefault(); toast(`กรุณาแนบรูปอย่างน้อย ${min} รูปก่อนส่ง`, 'error'); root.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
      });

      $('[data-photo-file]', root)?.addEventListener('change', async (e) => {
        for (const file of Array.from(e.target.files || [])) {
          try { await add(await compress(await readFile(file))); } catch (err) { toast(err.message, 'error'); }
        }
        e.target.value = '';
      });

      $('[data-camera-open]', root).addEventListener('click', () => openCamera());

      async function openCamera() {
        if (!navigator.mediaDevices?.getUserMedia) { toast(cameraHelp(), 'error', 8000); return; }
        let facing = 'environment';
        let stream = null;
        const cam = document.createElement('div');
        cam.className = 'camera';
        cam.setAttribute('role', 'dialog');
        cam.setAttribute('aria-label', 'กล้อง');
        cam.innerHTML = `<video playsinline autoplay muted></video>
          <div class="camera-bar"><button class="btn" data-done type="button">เสร็จ</button>
          <button class="shutter" type="button" aria-label="ถ่ายรูป"></button>
          <div class="row"><span class="camera-count"></span><button class="btn" data-flip type="button" aria-label="สลับกล้อง"><i data-lucide="switch-camera"></i></button></div></div>
          <div class="camera-flash"></div>`;
        const video = $('video', cam);
        const shutter = $('.shutter', cam);
        const count = () => { $('.camera-count', cam).textContent = `${items.length}/${max}`; shutter.disabled = items.length >= max; };
        const stop = () => stream?.getTracks().forEach((t) => t.stop());
        const start = async () => {
          stop();
          try {
            stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: facing }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
          } catch (err) {
            try { stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false }); }
            catch (err2) { close(); toast(cameraHelp(err2), 'error', 9000); return; }
          }
          video.srcObject = stream;
          video.style.transform = facing === 'user' ? 'scaleX(-1)' : '';
        };
        const close = () => { stop(); cam.remove(); };
        $('[data-done]', cam).onclick = close;
        $('[data-flip]', cam).onclick = () => { facing = facing === 'user' ? 'environment' : 'user'; start(); };
        shutter.onclick = async () => {
          if (!video.videoWidth || items.length >= max) return;
          const flash = $('.camera-flash', cam); flash.classList.remove('on'); void flash.offsetWidth; flash.classList.add('on');
          const c = document.createElement('canvas');
          const scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight));
          c.width = Math.round(video.videoWidth * scale); c.height = Math.round(video.videoHeight * scale);
          const ctx = c.getContext('2d');
          if (facing === 'user') { ctx.translate(c.width, 0); ctx.scale(-1, 1); }
          ctx.drawImage(video, 0, 0, c.width, c.height);
          let data = c.toDataURL('image/webp', 0.8);
          if (!data.startsWith('data:image/webp')) data = c.toDataURL('image/jpeg', 0.8);
          await add(data); count();
        };
        document.body.appendChild(cam); icons(); count();
        await start();
      }

      render();
    });
  }

  // ------------------------------------------------------------ verify & AI photo check
  function initVerify() {
    $$('[data-verify]').forEach((panel) => {
      const url = panel.dataset.verify;
      $$('[data-verify-action]', panel).forEach((btn) => btn.addEventListener('click', async () => {
        const body = { is_verified: btn.dataset.verifyAction === '1' };
        $$('[data-verify-field]', panel).forEach((c) => (body[c.dataset.verifyField] = c.checked));
        btn.classList.add('is-busy');
        try {
          const res = await api(url, body);
          $('[data-verify-tag]', panel).innerHTML = res.is_verified ? '<span class="tag success">รับรองแล้ว</span>' : '<span class="tag">รอตรวจรับรอง</span>';
          $('[data-verify-meta]', panel).textContent = res.is_verified ? `รับรองโดย ${res.verified_by} เมื่อ ${res.verified_at}` : '';
          $('[data-verify-action="0"]', panel).hidden = !res.is_verified;
          toast(res.is_verified ? 'บันทึกการรับรองแล้ว' : 'ยกเลิกการรับรองแล้ว');
        } catch (e) { toast(e.message, 'error'); }
        btn.classList.remove('is-busy');
      }));
    });

    $$('[data-photo-check]').forEach((panel) => {
      const body = $('[data-photo-check-body]', panel);
      const tone = { PASS: 'success', WARN: 'warning', FAIL: 'danger', NO_STAFF: '' };
      const label = { PASS: 'ผ่าน', WARN: 'ควรตรวจสอบ', FAIL: 'ไม่ผ่าน', NO_STAFF: 'ไม่พบบุคคล' };
      const show = (r) => {
        if (!r || r.detected_count === undefined) return;
        body.innerHTML = `<ul class="check-list">
          <li><span>เป็นรูปถ่ายจริง (ไม่ใช่ถ่ายจากจอหรือภาพพิมพ์)</span><span class="tag ${r.is_screen_photo ? 'danger' : 'success'}">${r.is_screen_photo ? 'ไม่ใช่' : 'ใช่'}</span></li>
          <li><span>จำนวนคนที่พบ / ที่รายงาน</span><span class="tag ${r.count_matches ? 'success' : 'warning'}">${r.detected_count} / ${r.reported_count}</span></li>
          <li><span>เห็นเต็มตัว</span><span class="tag ${r.is_full_body ? 'success' : 'warning'}">${r.is_full_body ? 'ใช่' : 'ไม่ใช่'}</span></li>
          <li><span>การแต่งกาย</span><span class="tag ${tone[r.dress_code_status] || ''}">${label[r.dress_code_status] || r.dress_code_status}</span></li></ul>
          ${r.dress_code_summary ? `<p style="margin-top:12px">${esc(r.dress_code_summary)}</p>` : ''}
          ${(r.observations || []).length ? `<ul class="small muted">${r.observations.map((o) => `<li>${esc(o)}</li>`).join('')}</ul>` : ''}`;
      };
      try { show(JSON.parse(panel.dataset.cached || '{}')); } catch (e) { /* ignore */ }
      $('[data-photo-check-run]', panel).addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        btn.classList.add('is-busy');
        try { const res = await api(panel.dataset.photoCheck, { refresh: true }); show(res.result); toast('ตรวจรูปเสร็จแล้ว'); }
        catch (err) { toast(err.message, 'error'); }
        btn.classList.remove('is-busy');
      });
    });
  }

  // ------------------------------------------------------------ duplicate-submission check
  function initExistingCheck() {
    $$('form[data-check-url]').forEach((form) => {
      const notice = $('[data-existing-notice]', form);
      const run = async () => {
        const branch = form.elements.branch?.value; const date = form.elements.date?.value;
        if (!branch || !date || !notice) return;
        const url = `${APP_ROOT}${form.dataset.checkUrl}?branch=${encodeURIComponent(branch)}&date=${encodeURIComponent(date)}`;
        try {
          const res = await (await fetch(url, { headers: { Accept: 'application/json' } })).json();
          notice.hidden = !res.exists;
          if (res.exists) notice.querySelector('[data-existing-text]').innerHTML =
            `ส่งแล้วโดย <strong>${esc(res.submitted_by)}</strong> เวลา ${esc(res.time)} น. <a href="${res.url}">เปิดดู</a>`;
        } catch (e) { /* offline: the server checks again on submit */ }
      };
      ['branch', 'date'].forEach((n) => form.elements[n]?.addEventListener('change', run));
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    icons();
    initShell();
    initNotes();
    initSignatures();
    initGalleries();
    initPhotoCapture();
    initVerify();
    initExistingCheck();
  });
})();
