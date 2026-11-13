/* Checklist template editor: sections → items → evidence fields, saved as JSON. */
(function () {
  'use strict';
  const { api, toast, esc, icons, confirmDialog } = window.Shiftcheck;
  const root = document.getElementById('editor');
  const raw = JSON.parse(document.getElementById('template-data').textContent);

  const state = {
    id: raw.id || null,
    name: raw.name || '',
    description: raw.description || '',
    is_active: raw.is_active === undefined ? true : !!raw.is_active,
    photo_min: raw.photo_min ?? 0,
    photo_max: raw.photo_max ?? 7,
    sections: (raw.sections || []).map((s) => ({
      title: s.title || '',
      items: (s.items || []).map((i) => ({ title: i.title || '', guidance: i.guidance || '', evidence_fields: (i.evidence_fields || []).map((f) => ({ ...f })) })),
    })),
  };
  let dirty = false;

  const meta = {
    name: document.getElementById('t-name'), description: document.getElementById('t-desc'),
    photo_min: document.getElementById('t-min'), photo_max: document.getElementById('t-max'), is_active: document.getElementById('t-active'),
  };
  meta.name.value = state.name; meta.description.value = state.description;
  meta.photo_min.value = state.photo_min; meta.photo_max.value = state.photo_max; meta.is_active.checked = state.is_active;

  const list = root.querySelector('[data-sections]');
  const blankItem = () => ({ title: '', guidance: '', evidence_fields: [] });

  function move(arr, i, d) { const j = i + d; if (j < 0 || j >= arr.length) return; [arr[i], arr[j]] = [arr[j], arr[i]]; }

  function tools(kind, si, ii) {
    const data = `data-kind="${kind}" data-s="${si}"${ii !== undefined ? ` data-i="${ii}"` : ''}`;
    return `<div class="editor-tools">
      <button class="icon-btn" type="button" data-act="up" ${data} aria-label="เลื่อนขึ้น"><i data-lucide="arrow-up"></i></button>
      <button class="icon-btn" type="button" data-act="down" ${data} aria-label="เลื่อนลง"><i data-lucide="arrow-down"></i></button>
      <button class="icon-btn" type="button" data-act="remove" ${data} aria-label="ลบ"><i data-lucide="trash-2"></i></button></div>`;
  }

  let counter = 0;
  function render(focusSel) {
    counter = 0;
    list.innerHTML = state.sections.map((s, si) => `
      <section class="editor-section">
        <div class="editor-section-head">
          <input class="input" value="${esc(s.title)}" placeholder="ชื่อหมวด เช่น ทางเข้าและกระจกหน้าร้าน" data-bind="section" data-s="${si}" aria-label="ชื่อหมวด">
          ${tools('section', si)}
        </div>
        ${s.items.map((it, ii) => `
          <div class="editor-item">
            <span class="no">${++counter}</span>
            <div>
              <input class="input" value="${esc(it.title)}" placeholder="ต้องตรวจอะไร?" data-bind="item" data-s="${si}" data-i="${ii}" aria-label="รายการที่ ${counter}">
              <input class="input input-sm" style="margin-top:6px" value="${esc(it.guidance)}" placeholder="คำแนะนำสำหรับผู้ตรวจ (ไม่บังคับ)" data-bind="guidance" data-s="${si}" data-i="${ii}" aria-label="คำแนะนำ">
              <div class="fields-list">
                ${it.evidence_fields.map((f, fi) => `
                  <div class="field-row">
                    <input class="input input-sm" value="${esc(f.label)}" placeholder="ชื่อช่องข้อมูลเมื่อไม่ผ่าน" data-bind="flabel" data-s="${si}" data-i="${ii}" data-f="${fi}" aria-label="ชื่อช่องข้อมูล">
                    <select class="select input-sm" data-bind="ftype" data-s="${si}" data-i="${ii}" data-f="${fi}" aria-label="ชนิดข้อมูล">
                      ${['text', 'number', 'date'].map((t) => `<option value="${t}" ${f.type === t ? 'selected' : ''}>${t === 'text' ? 'ข้อความ' : t === 'number' ? 'ตัวเลข' : 'วันที่'}</option>`).join('')}
                    </select>
                    <button class="icon-btn" type="button" data-act="rmfield" data-s="${si}" data-i="${ii}" data-f="${fi}" aria-label="ลบช่องข้อมูล"><i data-lucide="x"></i></button>
                  </div>`).join('')}
                ${it.evidence_fields.length < 5 ? `<button class="btn btn-sm btn-ghost" type="button" data-act="addfield" data-s="${si}" data-i="${ii}" style="justify-self:start"><i data-lucide="plus"></i>ช่องข้อมูลเมื่อไม่ผ่าน</button>` : ''}
              </div>
            </div>
            ${tools('item', si, ii)}
          </div>`).join('')}
        <div class="editor-add"><button class="btn btn-sm" type="button" data-act="additem" data-s="${si}"><i data-lucide="plus"></i>เพิ่มรายการ</button></div>
      </section>`).join('') || '<div class="panel"><div class="empty"><h3>ยังไม่มีหมวด</h3><p>เพิ่มหมวดเพื่อเริ่มสร้างเช็กลิสต์</p></div></div>';
    icons();
    summary();
    if (focusSel) list.querySelector(focusSel)?.focus();
  }

  function summary() {
    const items = state.sections.reduce((n, s) => n + s.items.length, 0);
    root.querySelector('[data-summary]').textContent = `${state.sections.length} หมวด ${items} รายการ${dirty ? ' · ยังไม่ได้บันทึก' : ''}`;
  }

  list.addEventListener('input', (e) => {
    const t = e.target; const b = t.dataset.bind; if (!b) return;
    const s = state.sections[t.dataset.s]; const it = s && s.items[t.dataset.i];
    if (b === 'section') s.title = t.value;
    if (b === 'item') it.title = t.value;
    if (b === 'guidance') it.guidance = t.value;
    if (b === 'flabel') it.evidence_fields[t.dataset.f].label = t.value;
    if (b === 'ftype') it.evidence_fields[t.dataset.f].type = t.value;
    dirty = true; summary();
  });

  list.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]'); if (!btn) return;
    const si = Number(btn.dataset.s), ii = Number(btn.dataset.i), fi = Number(btn.dataset.f);
    const act = btn.dataset.act, kind = btn.dataset.kind;
    let focus;
    if (act === 'additem') { state.sections[si].items.push(blankItem()); focus = `[data-bind=item][data-s="${si}"][data-i="${state.sections[si].items.length - 1}"]`; }
    if (act === 'addfield') { state.sections[si].items[ii].evidence_fields.push({ label: '', type: 'text' }); focus = `[data-bind=flabel][data-s="${si}"][data-i="${ii}"][data-f="${state.sections[si].items[ii].evidence_fields.length - 1}"]`; }
    if (act === 'rmfield') state.sections[si].items[ii].evidence_fields.splice(fi, 1);
    if (act === 'up' || act === 'down') {
      const d = act === 'up' ? -1 : 1;
      kind === 'section' ? move(state.sections, si, d) : move(state.sections[si].items, ii, d);
    }
    if (act === 'remove') {
      if (kind === 'section') {
        const s = state.sections[si];
        if (s.items.some((i) => i.title) && !(await confirmDialog('ลบหมวดนี้?', `หมวด “${s.title || 'ไม่มีชื่อ'}” และ ${s.items.length} รายการในหมวดจะถูกลบ`, 'ลบ', true))) return;
        state.sections.splice(si, 1);
      } else state.sections[si].items.splice(ii, 1);
    }
    dirty = true; render(focus);
  });

  root.querySelector('[data-add-section]').addEventListener('click', () => {
    state.sections.push({ title: '', items: [blankItem()] });
    dirty = true; render(`[data-bind=section][data-s="${state.sections.length - 1}"]`);
  });

  Object.entries(meta).forEach(([k, el]) => el.addEventListener('input', () => { dirty = true; summary(); }));

  async function save(e) {
    const btn = e.currentTarget;
    state.name = meta.name.value; state.description = meta.description.value;
    state.photo_min = Number(meta.photo_min.value || 0); state.photo_max = Number(meta.photo_max.value || 0);
    state.is_active = meta.is_active.checked;
    btn.classList.add('is-busy');
    try {
      const res = await api(root.dataset.saveUrl, state);
      dirty = false;
      window.location.href = res.url;
    } catch (err) {
      toast(err.message, 'error', 7000);
      btn.classList.remove('is-busy');
    }
  }
  document.querySelectorAll('[data-save]').forEach((b) => b.addEventListener('click', save));
  window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

  render();
})();
