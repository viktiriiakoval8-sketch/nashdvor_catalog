/* Connect only after deploying and verifying Code.gs in the owner's account.
 * No no-cors fetch: the actual receiver displays success/failure in a new tab.
 * The original form keeps its fields and photo for a safe retry.
 */
window.NashDvorGoogleMail = {
  connect(endpoint) {
    if (!/^https:\/\/script\.google\.com\/macros\/s\/[A-Za-z0-9_-]+\/exec$/.test(endpoint)) throw new Error('Invalid Google receiver URL');
    const form = document.getElementById('lead-form');
    if (!form || form.dataset.googleConnected) return;
    form.dataset.googleConnected = 'true';
    const status = document.getElementById('lead-status');
    const submit = document.getElementById('lead-submit');
    let connectionPrepared = false;
    function prepareConnection() {
      if (connectionPrepared) return;
      connectionPrepared = true;
      for (const origin of ['https://script.google.com', 'https://script.googleusercontent.com']) {
        const link = document.createElement('link');
        link.rel = 'preconnect'; link.href = origin; document.head.append(link);
      }
    }
    form.addEventListener('focusin', prepareConnection, {once:true});
    form.addEventListener('pointerenter', prepareConnection, {once:true});
    let sending = false, requestId = null;
    const field = name => form.elements.namedItem(name)?.value || '';
    const readPhoto = file => new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1]);
      reader.onerror = () => reject(new Error('Не вдалося прочитати фото. Оберіть його повторно.'));
      reader.readAsDataURL(file);
    });
    // Prepare locally while the visitor fills in contacts; never upload before submit.
    let preparedFile = null, preparedPhoto = null;
    async function optimizePhoto(file) {
      if (file.size <= 512 * 1024 || /\.hei[cf]$/i.test(file.name)) return file;
      let image;
      try {
        image = await createImageBitmap(file);
        const scale = Math.min(1, 2048 / Math.max(image.width, image.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(image.width * scale));
        canvas.height = Math.max(1, Math.round(image.height * scale));
        const context = canvas.getContext('2d');
        context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        let blob;
        for (const quality of [0.85, 0.78, 0.7]) {
          blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
          if (!blob || blob.size <= 1024 * 1024) break;
        }
        return blob && blob.size < file.size ? blob : file;
      } catch (_) { return file; }
      finally { image?.close(); }
    }
    function preparePhoto(file) {
      if (preparedFile !== file || !preparedPhoto) {
        preparedFile = file;
        preparedPhoto = optimizePhoto(file).then(readPhoto);
        // Report read errors on submission, without an unhandled background rejection.
        preparedPhoto.catch(() => {});
      }
      return preparedPhoto;
    }
    document.getElementById('lead-photo').addEventListener('change', event => {
      const file = event.target.files[0];
      preparedFile = null; preparedPhoto = null;
      if (file && file.size <= 10 * 1024 * 1024) preparePhoto(file);
    });
    form.action = endpoint;
    const consent = form.querySelector('.lead-consent span');
    if (consent) consent.textContent = 'Погоджуюся на обробку фото й контактних даних для підготовки візуалізації та зв’язку щодо заявки. Фото та контакти надсилаються команді NASH DVOR через Google. Фото не публікуються.';
    form.addEventListener('input', () => { requestId = null; });
    form.addEventListener('submit', async event => {
      event.preventDefault(); event.stopImmediatePropagation();
      if (sending) return;
      const file = document.getElementById('lead-photo').files[0];
      const product = form.dataset.requestType === 'product';
      if (!product && (!file || file.size > 10 * 1024 * 1024)) { status.textContent = 'Оберіть фото розміром до 10 МБ.'; return; }
      const selection = document.getElementById('lead-selection').value;
      if (!selection) { status.textContent = 'Оберіть хоча б одну термопанель.'; status.scrollIntoView({block:'nearest'}); return; }
      requestId = requestId || crypto.randomUUID();
      const target = 'nd-lead-' + requestId;
      const result = window.open('', target);
      if (!result) { status.textContent = 'Дозвольте відкриття нової вкладки для надсилання заявки та натисніть кнопку ще раз. Фото й поля збережені.'; return; }
      sending = true; submit.disabled = true;
      status.textContent = 'Готуємо заявку до надсилання…';
      try {
        const data = {type:product ? 'product' : 'visualization', id:requestId, name:field('Ім’я'), email:field('Email'), phone:field('Телефон'), city:field('Населений пункт'), area:product ? '' : field('Площа фасаду, м²'), contact:field('Спосіб зв’язку'), note:field('Побажання'), selection, source:location.href, consent:form.elements.namedItem('Згода на обробку даних').checked, website:field('_honey'), photo:null};
        if (!product) data.photo = {base64:await preparePhoto(file)};
        const post = document.createElement('form'); post.method = 'POST'; post.action = endpoint; post.target = target; post.enctype = 'application/x-www-form-urlencoded'; post.hidden = true;
        const payload = document.createElement('input'); payload.type = 'hidden'; payload.name = 'payload'; payload.value = JSON.stringify(data); post.append(payload); document.body.append(post); post.submit(); post.remove();
        status.textContent = 'Перевірте результат надсилання у новій вкладці. Цю форму залишено відкритою разом із фото та контактами.';
      } catch (error) {
        result.close(); status.textContent = error.message || 'Не вдалося підготувати заявку. Спробуйте ще раз.';
      } finally { sending = false; submit.disabled = false; }
    }, true);
  }
};

