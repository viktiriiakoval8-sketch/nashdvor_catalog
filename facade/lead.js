'use strict';
window.Facade = (() => {
  const sections = new Set(['porcelain', 'polish-clinker', 'clinker-imitation']);
  const panels = CATALOG.sections.filter(s => sections.has(s.id)).flatMap(s => s.items);
  const dialog = document.createElement('dialog');
  dialog.className = 'lead-dialog';
  dialog.setAttribute('aria-labelledby', 'lead-title');
  dialog.innerHTML = `<div class="modal-header"><span class="label">NASH DVOR / ВІЗУАЛІЗАЦІЯ</span><button type="button" class="icon" id="lead-close" aria-label="Закрити заявку">×</button></div>
  <div class="lead-body"><h2 id="lead-title">Побачте новий фасад вашого дому</h2>
  <p class="lead-intro">Завантажте фото та залиште контакти. Наша команда вручну підготує візуалізацію з обраними термопанелями й зв’яжеться з вами.</p>
  <form id="lead-form" method="POST" action="https://formsubmit.co/nash.dvor.office@gmail.com" enctype="multipart/form-data">
    <input type="hidden" name="_subject" value="NASH DVOR — заявка на візуалізацію фасаду">
    <input type="hidden" name="_template" value="table">
    <input type="hidden" name="_next" value="https://catalog.nashdvor.com.ua/thanks.html">
    <input type="text" name="_honey" tabindex="-1" autocomplete="off" class="lead-trap" aria-hidden="true">
    <input type="hidden" name="Обрані панелі" id="lead-selection">
    <input type="hidden" name="Сторінка каталогу" id="lead-source">
    <div class="lead-layout"><div>
      <label class="lead-upload"><span class="label">01 / ФОТО БУДИНКУ</span><strong>Оберіть фото фасаду</strong>
        <input type="file" name="attachment" id="lead-photo" accept="image/jpeg,image/png,image/heic,image/heif,.jpg,.jpeg,.png,.heic,.heif" required aria-label="Фото фасаду">
        <span class="lead-help">JPG, PNG або HEIC · до 10 МБ</span><img id="lead-preview" alt="Ваше фото фасаду" hidden>
      </label>
      <p class="lead-help">Зніміть стіну цілком при денному світлі. Бажано, щоб було видно дах, цоколь, вікна та двері. Надішліть оригінал фото без фільтрів.</p>
      <fieldset><legend>02 / Оберіть до трьох термопанелей</legend><div id="lead-choices" class="lead-choices"></div></fieldset>
    </div><div>
      <div id="lead-variants" class="lead-variants"></div>
      <fieldset><legend>03 / Як із вами зв’язатися</legend><div class="lead-fields">
        <label>Ім’я<input name="Ім’я" autocomplete="given-name" minlength="2" maxlength="100" required></label>
        <label>Телефон<input name="Телефон" type="tel" inputmode="tel" autocomplete="tel" placeholder="+380…" minlength="9" maxlength="24" required></label>
        <label class="lead-wide">Населений пункт<input name="Населений пункт" autocomplete="address-level2" minlength="2" maxlength="120" required></label>
        <label>Площа фасаду, м²<input name="Площа фасаду, м²" type="number" inputmode="decimal" min="1" max="100000" step="0.01" placeholder="Якщо відома"></label>
        <label>Зручний зв’язок<select name="Спосіб зв’язку"><option>Телефон</option><option>Viber</option><option>Telegram</option></select></label>
        <label class="lead-wide">Побажання<textarea name="Побажання" rows="3" maxlength="3000" placeholder="Наприклад, колір, частина фасаду або питання до менеджера"></textarea></label>
      </div></fieldset>
    </div></div>
    <label class="lead-consent"><input type="checkbox" name="Згода на обробку даних" value="Так" required><span>Погоджуюся на обробку фото й контактних даних для підготовки візуалізації та зв’язку щодо заявки. Дані надсилаються команді NASH DVOR через сервіс FormSubmit. Фото не публікуються.</span></label>
    <p id="lead-status" class="lead-status" role="status" aria-live="polite"></p>
    <button class="primary" type="submit" id="lead-submit">Надіслати фото та заявку →</button>
    <p class="lead-help">Якщо форма не надсилається, <a id="lead-email" href="mailto:nash.dvor.office@gmail.com">надішліть заявку зі своєї пошти</a> та додайте фото до листа.</p>
    <p class="lead-help">Візуалізацію готує наша команда вручну. Після надсилання менеджер зв’яжеться з вами та узгодить деталі. Без оплати на цьому кроці.</p>
  </form></div>`;
  document.body.append(dialog);
  const get = id => document.getElementById('lead-' + id);
  const form = get('form');
  let selected = new Map(), previewURL = null, focusBack = null;
  const node = (tag, className, value) => { const n = document.createElement(tag); if (className) n.className = className; if (value !== undefined) n.textContent = value; return n; };
  const pairs = p => p.bases.flatMap(b => p.thicknesses.filter(t => (p.combinations || Object.keys(p.price)).includes(`${b.id}_${t.mm}`)).map(t => ({base: b.id, mm: t.mm})));
  function serialize() {
    get('selection').value = [...selected].map(([id, v]) => {
      const p = panels.find(p => p.id === id);
      const key = `${v.base}_${v.mm}`;
      const price = p.price[key];
      return [p.name, 'Артикул: ' + (p.variantSkus?.[key] || p.sku), p.bases.find(b => b.id === v.base)?.name, p.thicknesses.find(t => t.mm === v.mm)?.label, Number.isFinite(price) ? `${price} ${p.currency}` : 'Без опублікованої ціни', p.source].filter(Boolean).join(' · ');
    }).join('\n\n');
    get('source').value = location.href;
    const body = ['Заявка на візуалізацію фасаду NASH DVOR', ...['Ім’я', 'Телефон', 'Населений пункт', 'Площа фасаду, м²', 'Спосіб зв’язку', 'Побажання'].map(name => name + ': ' + form.elements.namedItem(name).value), '', get('selection').value, '', 'Сторінка: ' + location.href, '', 'Додайте фото фасаду до цього листа.'].join('\n');
    get('email').href = 'mailto:nash.dvor.office@gmail.com?subject=' + encodeURIComponent('NASH DVOR — заявка на візуалізацію') + '&body=' + encodeURIComponent(body);
  }
  function render() {
    get('choices').replaceChildren(); get('variants').replaceChildren();
    for (const p of panels) {
      const label = node('label', 'lead-choice');
      const check = node('input'); check.type = 'checkbox'; check.checked = selected.has(p.id); check.disabled = !check.checked && selected.size >= 3;
      const image = node('img'); image.src = p.image; image.alt = ''; image.loading = 'lazy'; image.onerror = () => image.remove();
      label.append(check, image, node('span', '', p.name));
      check.onchange = () => { if (check.checked) { const v = pairs(p)[0]; if (v) selected.set(p.id, v); } else selected.delete(p.id); get('status').textContent = ''; render(); };
      get('choices').append(label);
    }
    for (const [id, v] of selected) {
      const p = panels.find(p => p.id === id), group = node('div', 'lead-variant'); group.append(node('strong', '', p.name));
      const baseLabel = node('label', '', 'Основа'), base = node('select'); base.setAttribute('aria-label', `Основа: ${p.name}`);
      for (const b of p.bases.filter(b => pairs(p).some(v => v.base === b.id))) { const o = node('option', '', b.name); o.value = b.id; o.selected = b.id === v.base; base.append(o); }
      base.onchange = () => { selected.set(id, pairs(p).find(x => x.base === base.value)); render(); };
      const thicknessLabel = node('label', '', 'Товщина'), thickness = node('select'); thickness.setAttribute('aria-label', `Товщина: ${p.name}`);
      for (const t of p.thicknesses.filter(t => pairs(p).some(x => x.base === v.base && x.mm === t.mm))) { const o = node('option', '', t.label); o.value = String(t.mm); o.selected = t.mm === v.mm; thickness.append(o); }
      thickness.onchange = () => { selected.set(id, {base: v.base, mm: Number(thickness.value)}); serialize(); };
      baseLabel.append(base); thicknessLabel.append(thickness); group.append(baseLabel, thicknessLabel); get('variants').append(group);
    }
    serialize();
  }
  get('photo').onchange = () => {
    const input = get('photo'), file = input.files[0]; input.setCustomValidity(''); get('status').textContent = '';
    if (previewURL) URL.revokeObjectURL(previewURL); previewURL = null; get('preview').hidden = true;
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { input.value = ''; input.setCustomValidity('Оберіть фото розміром до 10 МБ.'); input.reportValidity(); return; }
    if (!/\.(jpe?g|png|heic|heif)$/i.test(file.name)) { input.value = ''; input.setCustomValidity('Потрібне фото у форматі JPG, PNG або HEIC.'); input.reportValidity(); return; }
    if (!/\.hei[cf]$/i.test(file.name)) { previewURL = URL.createObjectURL(file); get('preview').src = previewURL; get('preview').hidden = false; }
  };
  form.addEventListener('input', serialize);
  form.addEventListener('submit', event => {
    if (!selected.size) { event.preventDefault(); get('status').textContent = 'Оберіть хоча б одну термопанель.'; return; }
    serialize();
    // Native multipart submission preserves the photo attachment. The provider
    // redirects to thanks.html only after handling the submitted form.
    get('status').textContent = 'Надсилаємо фото та заявку…';
  });
  function close() { dialog.close(); focusBack?.focus(); }
  get('close').onclick = close;
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  function open(panel = null, variant = {}) {
    const p = panel ? panels.find(p => p.id === panel.id) : null; if (panel && !p) return;
    focusBack = document.activeElement;
    const all = p ? pairs(p) : []; const choice = all.find(v => v.base === variant.base && v.mm === variant.mm) || all[0];
    selected = new Map(choice ? [[p.id, choice]] : []); get('status').textContent = ''; render();
    document.getElementById('detail')?.close(); dialog.showModal(); get('close').focus();
  }
  document.getElementById('lead-open')?.addEventListener('click', () => open());
  return {open};
})();
