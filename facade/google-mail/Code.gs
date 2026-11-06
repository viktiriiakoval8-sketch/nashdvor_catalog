/** NASH DVOR: manual visualization requests. Deploy as a Web app, execute as
 * the owner, access Anyone. Only MailApp permission is requested.
 * No passwords, recipient selection, inbox reading or public photo storage.
 */
const LEAD_RECIPIENT = 'nash.dvor.office@gmail.com';
const LEAD_SITE = 'https://catalog.nashdvor.com.ua/';
const MAX_PHOTO_BYTES = 10 * 1024 * 1024;

function leadText(value, max, label, required) {
  const s = typeof value === 'string' ? value.trim() : '';
  if ((required && !s) || s.length > max) throw new Error('Перевірте поле «' + label + '».');
  return s;
}

function leadPhoto(photo) {
  if (!photo || typeof photo.base64 !== 'string' || photo.base64.length > Math.ceil(MAX_PHOTO_BYTES / 3) * 4) {
    throw new Error('Оберіть фото розміром до 10 МБ.');
  }
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(photo.base64) || photo.base64.length % 4) throw new Error('Не вдалося прочитати фото. Оберіть файл повторно.');
  const bytes = Utilities.base64Decode(photo.base64);
  if (!bytes.length || bytes.length > MAX_PHOTO_BYTES) throw new Error('Оберіть фото розміром до 10 МБ.');
  const b = n => (bytes[n] + 256) % 256;
  const jpeg = bytes.length >= 3 && b(0) === 255 && b(1) === 216 && b(2) === 255;
  const png = bytes.length >= 8 && [137,80,78,71,13,10,26,10].every((v,n) => b(n) === v);
  const brand = bytes.length >= 12 ? String.fromCharCode.apply(null, bytes.slice(4,12)) : '';
  const heic = /^ftyp(?:heic|heix|hevc|hevx|mif1|msf1)$/.test(brand);
  if (!jpeg && !png && !heic) throw new Error('Потрібне фото у форматі JPG, PNG або HEIC.');
  const type = jpeg ? 'image/jpeg' : png ? 'image/png' : 'image/heic';
  const ext = jpeg ? '.jpg' : png ? '.png' : '.heic';
  return Utilities.newBlob(bytes, type, 'facade' + ext);
}

function validateLead(raw) {
  if (!raw || typeof raw !== 'object' || raw.website) throw new Error('Не вдалося перевірити заявку. Спробуйте ще раз.');
  const id = leadText(raw.id, 64, 'номер заявки', true);
  if (!/^[a-zA-Z0-9-]{16,64}$/.test(id)) throw new Error('Не вдалося перевірити номер заявки. Оновіть сторінку.');
  const name = leadText(raw.name, 100, 'Ім’я', true);
  const phone = leadText(raw.phone, 24, 'Телефон', true);
  const digits = phone.replace(/\D/g, '');
  if (!/^[+\d\s().-]+$/.test(phone) || digits.length < 9 || digits.length > 15) throw new Error('Перевірте номер телефону.');
  const city = leadText(raw.city, 120, 'Населений пункт', true);
  const selection = leadText(raw.selection, 12000, 'Обрані панелі', true);
  const note = leadText(raw.note, 3000, 'Побажання', false);
  const contact = leadText(raw.contact, 40, 'Спосіб зв’язку', false);
  const source = leadText(raw.source, 2000, 'Сторінка', true);
  if (source.indexOf(LEAD_SITE) !== 0) throw new Error('Надішліть заявку зі сторінки каталогу NASH DVOR.');
  if (raw.consent !== true) throw new Error('Підтвердьте згоду на обробку фото та контактів.');
  const area = raw.area === '' || raw.area === undefined ? null : Number(raw.area);
  if (area !== null && (!Number.isFinite(area) || area < 1 || area > 100000)) throw new Error('Перевірте площу фасаду.');
  return {id:id, name:name, phone:phone, city:city, area:area, note:note, contact:contact, source:source, selection:selection, photo:leadPhoto(raw.photo)};
}

function deliverLead(raw) {
  const lead = validateLead(raw);
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(15000)) throw new Error('Сервіс зайнятий. Спробуйте ще раз за хвилину.');
  try {
    const cache = CacheService.getScriptCache();
    if (cache.get('sent:' + lead.id)) return lead.id;
    if (MailApp.getRemainingDailyQuota() < 1) throw new Error('Надсилання тимчасово недоступне. Зателефонуйте нам або спробуйте пізніше.');
    const minute = 'minute:' + Math.floor(Date.now() / 60000);
    const count = Number(cache.get(minute) || '0');
    if (count >= 5) throw new Error('Забагато заявок одночасно. Спробуйте за хвилину.');
    const body = [
      'Нова заявка на ручну візуалізацію фасаду NASH DVOR',
      'Номер: ' + lead.id, 'Ім’я: ' + lead.name, 'Телефон: ' + lead.phone,
      'Населений пункт: ' + lead.city, 'Зручний зв’язок: ' + lead.contact,
      'Площа, м²: ' + (lead.area === null ? 'Не вказана' : lead.area),
      '', 'Обрані панелі:', lead.selection, '', 'Побажання:', lead.note,
      '', 'Сторінка каталогу: ' + lead.source, 'Згода на обробку даних: так',
      '', 'Фото фасаду прикріплене до листа. Обробка заявки — вручну.'
    ].join('\n');
    MailApp.sendEmail({to: LEAD_RECIPIENT, subject: 'NASH DVOR — візуалізація фасаду [' + lead.id + ']', body: body, attachments: [lead.photo], name: 'NASH DVOR — каталог'});
    cache.put('sent:' + lead.id, '1', 21600);
    cache.put(minute, String(count + 1), 120);
    return lead.id;
  } finally { lock.releaseLock(); }
}

function leadEscape(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function leadPage(success, message) {
  const title = success ? 'Заявку надіслано' : 'Заявку не надіслано';
  const content = '<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;background:#f5f1e8;color:#202020;font:16px/1.6 Arial,sans-serif;padding:24px"><main style="max-width:600px;margin:8vh auto;padding:28px;background:white;border-radius:12px"><p>NASH DVOR / ВІЗУАЛІЗАЦІЯ</p><h1>' + title + '</h1><p>' + leadEscape(message) + '</p><p>' + (success ? 'Наша команда підготує візуалізацію вручну та зв’яжеться з вами.' : 'Поверніться у попередню вкладку — фото й заповнені поля залишилися там. Повторіть спробу або зателефонуйте +380 98 578 87 87.') + '</p><a href="' + LEAD_SITE + '" target="_top">Повернутися до каталогу</a></main></body></html>';
  return HtmlService.createHtmlOutput(content).setTitle(title).addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function doPost(e) {
  try {
    const value = e && e.parameter && e.parameter.payload;
    if (typeof value !== 'string' || value.length > 15000000) throw new Error('Завеликий файл або пошкоджена заявка.');
    let raw;
    try { raw = JSON.parse(value); } catch (_) { throw new Error('Не вдалося прочитати заявку. Повторіть надсилання.'); }
    const id = deliverLead(raw);
    return leadPage(true, 'Фото та контакти надіслані команді NASH DVOR. Номер заявки: ' + id);
  } catch (error) {
    const known = /^(Перевірте|Потрібне|Оберіть|Не вдалося|Підтвердьте|Надішліть|Надсилання|Забагато|Сервіс|Завеликий)/.test(error.message || '');
    return leadPage(false, known ? error.message : 'Не вдалося передати заявку поштовій службі. Спробуйте пізніше.');
  }
}

function doGet() { return leadPage(false, 'Ця адреса приймає заявки лише з форми каталогу.'); }

/** Run once from the Apps Script editor to authorize and test the mail scope. */
function sendSetupTest() {
  const png = Utilities.newBlob(Utilities.base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jJXkAAAAASUVORK5CYII='), 'image/png', 'setup-test.png');
  MailApp.sendEmail({to:LEAD_RECIPIENT, subject:'NASH DVOR — тест нового обробника форми', body:'Технічна перевірка, не заявка клієнта. До листа прикріплено тестове PNG. Перевірте отримання вкладення перед увімкненням форми.', attachments:[png], name:'NASH DVOR — каталог'});
}
