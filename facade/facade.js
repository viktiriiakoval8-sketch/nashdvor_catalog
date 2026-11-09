'use strict';
window.Facade = (() => {
  const eligible = new Set(['porcelain','polish-clinker','clinker-imitation']);
  const panels = CATALOG.sections.filter(s=>eligible.has(s.id)).flatMap(s=>s.items);
  const find = id => panels.find(p=>p.id===id);
  const dialog = document.createElement('dialog');
  dialog.className='facade-dialog';
  dialog.setAttribute('aria-labelledby','facade-title');
  dialog.innerHTML=`<div class="modal-header"><span class="label">NASH DVOR / ПРИМІРКА ФАСАДУ</span><button class="icon" type="button" id="facade-close" aria-label="Закрити примірку">×</button></div>
  <div class="facade-body"><h2 class="facade-heading" id="facade-title">Ваш дім. Новий характер.</h2>
  <p class="facade-intro">Завантажте фото стіни та порівняйте до трьох панелей. Перевірте автоматичну примірку: вікна, двері, цоколь і межі стіни можна уточнити вручну. Результат приблизний.</p>
  <div id="facade-status" class="facade-status" role="status" aria-live="polite"></div>
  <form id="facade-form">
  <section class="facade-photo-requirements" aria-labelledby="facade-photo-rules-title">
    <span class="facade-photo-eyebrow">ВАЖЛИВО ПЕРЕД ЗАВАНТАЖЕННЯМ</span>
    <h3 id="facade-photo-rules-title">Хороше фото — точніша примірка</h3>
    <div class="facade-photo-limits"><strong>Від 1200 px</strong><span>за довгою стороною</span><strong>До 10 МБ</strong><strong>JPG · PNG · HEIC</strong></div>
    <ol class="facade-photo-rules">
      <li><strong>Уся стіна в кадрі</strong><span>Відійдіть, щоб було видно обидва краї, верх під дахом і цоколь. Залиште невеликий запас; фасад має займати більшу частину фото.</span></li>
      <li><strong>Знімайте прямо</strong><span>Станьте навпроти середини однієї стіни. Тримайте телефон рівно, уникайте сильного ракурсу з кута.</span></li>
      <li><strong>Денне світло й різкість</strong><span>Без розмиття, сильного пересвіту та зйомки проти сонця. Вікна й двері мають бути видимі; оберіть місце з найменшою кількістю перешкод.</span></li>
      <li><strong>Оригінал із камери</strong><span>Без скриншотів, фільтрів і сильного стиснення в месенджерах. Завантажте початковий файл із телефона.</span></li>
    </ol>
    <p class="facade-photo-rules-note">Це поради для кращого результату. Відстань залежить від розміру будинку; фіксованої кількості метрів немає. Навіть якісне фото не гарантує точну автоматичну маску.</p>
  </section>
  <div class="facade-layout"><div><label class="facade-upload"><span class="label">01 / ФОТО ВАШОГО БУДИНКУ</span><strong>Оберіть фото фасаду</strong><input id="facade-photo" name="photo" type="file" accept="image/jpeg,image/png,image/heic,image/heif,.heic,.heif" required aria-label="Фото фасаду" aria-describedby="facade-photo-file-limits"><span class="facade-help" id="facade-photo-file-limits">JPG, PNG або HEIC · до 10 МБ · від 1200 px за довгою стороною</span><img id="facade-preview" alt="Вибране фото фасаду" hidden></label>
  <details class="facade-photo-guide"><summary>Як зробити фото для кращої примірки</summary><ul>
  <li><strong>Ракурс.</strong> Станьте навпроти середини однієї стіни, тримайте телефон рівно. Для широкого фасаду знімайте горизонтально. Сильний ракурс із кута ускладнює примірку.</li>
  <li><strong>Межі фасаду.</strong> Залиште видимими обидва краї стіни, її верх під дахом і низ біля цоколя. Фронтон, вікна та двері мають повністю потрапити в кадр.</li>
  <li><strong>Освітлення.</strong> Знімайте вдень, бажано при рівному світлі. Звичайні тіні допустимі; сильний пересвіт, сутінки та зйомка проти сонця заважають розпізнаванню.</li>
  <li><strong>Огляд.</strong> Оберіть місце, звідки більша частина стіни відкрита. Дерева, автомобілі, люди та риштування можуть закривати контур.</li>
  <li><strong>Камера.</strong> Протріть об’єктив, наведіть різкість на стіну й тримайте телефон нерухомо. Бажано знімати основною камерою у звичайному режимі, без панорами, надширокого кута та сильного цифрового зуму.</li>
  <li><strong>Оригінал.</strong> Завантажуйте початкове фото без фільтрів, скриншотів і сильного стиснення в месенджерах. Площа та точний масштаб плитки за фото не визначаються.</li>
  </ul><p>Це поради для кращого результату. Фіксованої відстані в метрах немає; автоматична примірка залишається приблизною.</p></details>
  <fieldset><legend>02 / Оберіть 1–3 панелі <span id="facade-count"></span></legend><div class="facade-choices" id="facade-choices"></div></fieldset></div>
  <div><fieldset><legend>03 / Основа та товщина</legend><div class="facade-variants" id="facade-variants"></div></fieldset>
  <div class="facade-fields"><label class="facade-wide">Населений пункт<input name="city" autocomplete="address-level2" maxlength="120" minlength="2" required></label>
  <label>Площа стіни, м²<input id="facade-area" name="area" type="number" inputmode="decimal" min="0.01" max="100000" step="0.01" placeholder="Наприклад, 80"></label>
  <label>Площа невідома<select id="facade-unknown" name="unknown"><option value="no">Вкажу площу</option><option value="yes" selected>Не знаю</option></select></label>
  <p class="facade-help facade-wide">За фото площу не визначаємо. Якщо не знаєте її, покажемо примірку без розрахунку.</p>
  <label>Ім’я<input name="name" autocomplete="given-name" minlength="2" maxlength="100" required></label>
  <label>Телефон<input name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="+380…" minlength="9" maxlength="24" required></label>
  <label class="facade-wide">Зручний спосіб зв’язку<select name="contact"><option value="phone">Телефон</option><option value="viber">Viber</option><option value="telegram">Telegram</option></select></label></div></div></div>
  <label class="facade-consent"><input name="consent" type="checkbox" required><span>Погоджуюся на обробку фото й контактних даних для примірки та зв’язку щодо замовлення. Зберігання — до 90 днів. Фото не публікуються та не використовуються для навчання моделей без окремої згоди. Посилання на результат доступне тим, кому я його передам.</span></label>
  <button class="primary" id="facade-submit" type="submit">Приміряти на моєму будинку →</button>
  <p class="facade-footnote">Попередня візуалізація. Підтвердження зразка та замір — перед замовленням, без оплати на цьому кроці.</p></form>
  <section id="facade-retake" hidden><p>Автоматична маска не вдалася. Ви можете обвести фасад і позначити проєми самостійно або завантажити інше фото.</p><button type="button" class="primary" id="facade-retake-edit">Виділити ділянки вручну</button><button type="button" class="facade-secondary" id="facade-retake-again">Інше фото</button></section>
  <section id="facade-result" hidden aria-label="Результат примірки"><div class="facade-result-top"><span class="facade-badge">ПОПЕРЕДНЄ УЯВЛЕННЯ</span><button type="button" class="facade-secondary" id="facade-edit">Уточнити ділянки</button><button type="button" class="facade-secondary" id="facade-again">Інше фото</button></div>
  <div class="facade-result-tabs" id="facade-result-tabs" aria-label="Порівняння панелей"></div>
  <h3 id="facade-result-name"></h3><p class="facade-help" id="facade-result-spec"></p>
  <div class="facade-viewer"><img id="facade-before" alt="Фасад до примірки"><div class="facade-after" id="facade-after-layer"><img id="facade-after" alt="Приблизний вигляд фасаду з панеллю"></div><span class="facade-divider" id="facade-divider"></span><span class="facade-image-label after">Після · приблизно</span><span class="facade-image-label before">До</span></div>
  <label class="facade-help">Порівняйте «до / після»<input class="facade-slider" id="facade-slider" type="range" min="0" max="100" value="50" aria-label="Частка зображення після примірки"></label>
  <p class="facade-disclaimer" id="facade-disclaimer"></p><p class="facade-warning" id="facade-warning"></p><p class="facade-help" id="facade-texture-note"></p>
  <div class="facade-quote" id="facade-quote"></div><div class="facade-actions"><button class="primary" type="button" data-facade-action="sample">Замовити зразок</button><button class="facade-secondary" type="button" data-facade-action="estimate">Уточнити кошторис</button><button class="facade-secondary" type="button" data-facade-action="discuss">Обговорити замовлення</button></div>
  <div class="facade-result-top" style="margin-top:18px"><button class="facade-secondary" type="button" id="facade-copy">Скопіювати особисте посилання</button><button class="facade-secondary" type="button" data-facade-action="complaint">Повідомити про невідповідність</button></div><p class="facade-footnote">Посилання та фото зберігаються до 90 днів. Кошторис попередній; комплектуючі, доставка й монтаж уточнюються після заміру.</p></section></div>`;
  document.body.append(dialog);
  const get=id=>document.getElementById('facade-'+id);
  const form=get('form');
  let selected=new Map(), activeJob=null, activeData=null, generation=0, previewUrl=null, focusBack=null, busy=false;
  const money=value=>value===null||value===undefined?'уточнюється':new Intl.NumberFormat('uk-UA',{maximumFractionDigits:2}).format(value)+' грн';
  function status(message,error=false){get('status').textContent=message;get('status').dataset.error=String(error);}
  async function api(path,options={}){
    let response;
    try{response=await fetch(path,{...options,headers:{Accept:'application/json',...options.headers},signal:options.signal||AbortSignal.timeout(30000)});}
    catch{throw new Error('Сервіс примірки недоступний. Спробуйте пізніше або зверніться за контактами внизу каталогу.');}
    const json=await response.json().catch(()=>null);
    if(!response.ok||!json){
      const error=new Error(typeof json?.detail==='string'?json.detail:Array.isArray(json?.detail)?'Не вдалося перевірити виділення. Перевірте точки контуру та спробуйте знову.':'Сервіс примірки недоступний. Спробуйте пізніше або зверніться за контактами внизу каталогу.');
      error.invalidElements=json?.invalidElements||[];throw error;
    }
    return json;
  }
  function displayRetake(data){
    activeData=data;activeJob=data.id;form.hidden=true;get('result').hidden=true;
    get('retake').hidden=false;editor.root.hidden=true;status(data.message,true);
  }
  const editor=window.createFacadeEditor({
    save:async body=>{
      const current=generation,job=activeJob;
      const data=await api(`/api/facade/jobs/${job}/correction`,{method:'PUT',
        headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(120000)});
      if(current!==generation||job!==activeJob)throw new Error('Зміни збережено. Відкрийте посилання на цю примірку, щоб побачити їх.');
      displayResult(data);status('Примірку оновлено. Перевірте всі краї та проєми.');
    },
    revoke:async()=>{await api(`/api/facade/jobs/${activeJob}/training-consent`,{method:'DELETE'});activeData.editing.trainingConsent=false;},
    close:()=>{if(activeData?.status==='ready')displayResult(activeData);else displayRetake(activeData);}
  });
  dialog.querySelector('.facade-body').append(editor.root);
  function edit(){
    if(!activeData)return;
    form.hidden=true;get('result').hidden=true;get('retake').hidden=true;status('');editor.open(activeData);
  }
  get('edit').onclick=edit;get('retake-edit').onclick=edit;
  function variants(){
    get('variants').replaceChildren();get('count').textContent=`(${selected.size}/3)`;
    for(const [id,variant] of selected){
      const p=find(id),box=el('div','facade-variant'),name=el('strong','',p.name),label=el('label','','Основа / товщина'),select=el('select');
      select.setAttribute('aria-label',`Основа та товщина: ${p.name}`);
      select.append(new Option('Уточнюється',''));
      for(const base of p.bases)for(const t of p.thicknesses)if((p.combinations||Object.keys(p.price)).includes(`${base.id}_${t.mm}`)){
        select.append(new Option(`${base.name} · ${t.label}`,`${base.id}|${t.mm}`));
      }
      select.value=variant.base===null?'':`${variant.base}|${variant.mm}`;
      select.onchange=()=>{const [base,mm]=select.value.split('|');selected.set(id,{id,base:base||null,mm:base?Number(mm):null});};
      label.append(select);box.append(name,label);get('variants').append(box);
    }
    for(const input of get('choices').querySelectorAll('input')){input.checked=selected.has(input.value);input.disabled=!input.checked&&selected.size>=3;}
  }
  for(const p of panels){
    const label=el('label','facade-choice'),check=el('input'),image=el('img');check.type='checkbox';check.value=p.id;image.src=p.image;image.alt='';image.loading='lazy';
    image.onerror=()=>image.hidden=true;
    check.onchange=()=>{if(check.checked&&selected.size<3)selected.set(p.id,{id:p.id,base:null,mm:null});else selected.delete(p.id);variants();};
    label.append(check,image,el('span','',p.name));get('choices').append(label);
  }
  function areaState(){const unknown=get('unknown').value==='yes';get('area').disabled=unknown;get('area').required=!unknown;}
  get('unknown').onchange=areaState;areaState();
  get('area').addEventListener('input',()=>{if(get('area').value){get('unknown').value='no';areaState();}});
  get('photo').onchange=async()=>{
    if(previewUrl)URL.revokeObjectURL(previewUrl);get('preview').hidden=true;
    const file=get('photo').files[0];get('photo').setCustomValidity('');if(!file)return;
    if(file.size>10*1024*1024){get('photo').setCustomValidity('Фото має бути не більше 10 МБ.');get('photo').reportValidity();return;}
    if(!/\.(jpe?g|png|heic|heif)$/i.test(file.name)){get('photo').setCustomValidity('Оберіть JPG, PNG або HEIC.');get('photo').reportValidity();return;}
    previewUrl=URL.createObjectURL(file);const img=get('preview');img.src=previewUrl;
    img.onload=()=>{img.hidden=false;if(Math.max(img.naturalWidth,img.naturalHeight)<1200){get('photo').setCustomValidity('Потрібне фото від 1200 px по довгій стороні.');get('photo').reportValidity();}};
    img.onerror=()=>{img.hidden=true;}; // HEIC may be decoded only by the server.
  };
  function showDialog(){focusBack=document.activeElement;if(!dialog.open)dialog.showModal();get('close').focus();}
  function closeDialog(){generation++;dialog.close();focusBack?.focus();}
  get('close').onclick=closeDialog;dialog.addEventListener('cancel',e=>{e.preventDefault();closeDialog();});
  async function open(panel,variant={}){
    if(busy){showDialog();return;}
    generation++;selected=new Map([[panel.id,{id:panel.id,base:variant.base||null,mm:variant.base?variant.mm:null}]]);variants();
    get('result').hidden=true;get('retake').hidden=true;editor.root.hidden=true;form.hidden=false;status('');showDialog();
    const current=generation;
    try{const health=await api('/api/facade/health');if(current!==generation)return;
      if(!health.ready)status(health.loading?'Сервіс завантажує модель. Спробуйте через кілька хвилин.':'Сервіс примірки тимчасово недоступний. Контакти — внизу каталогу.',true);
    }catch(error){if(current===generation)status(error.message,true);}
  }
  function renderQuote(q){
    const box=get('quote');box.replaceChildren(el('h3','','Попередній розрахунок'));
    const dl=el('dl');
    for(const [label,value] of [['Площа стіни',q.area===null?'не вказана':`${fmt(q.area)} м²`],['Панелі',money(q.panels)],['Комплектуючі','уточнюється'],['Доставка','уточнюється'],['Монтаж','уточнюється']])dl.append(el('dt','',label),el('dd','',value));
    box.append(dl);
    if(q.panelCount!==null)box.append(el('p','facade-help',`${q.panelCount} панелей × ${money(q.pricePerPanel)}; площа панелі ${fmt(q.panelArea)} м². Без запасу на підрізку.`));
    else if(q.unitPrice!==null)box.append(el('p','facade-help',`${fmt(q.area)} м² × ${money(q.unitPrice)}/м². Без запасу на підрізку.`));
    if(q.reason)box.append(el('p','facade-help',q.reason));
    box.append(el('p','facade-footnote',`Розраховано ${q.date}. Дійсний до ${q.validUntil}. Повна сума уточнюється після замірів.`));
  }
  function displayResult(data){
    activeData=data;activeJob=data.id;get('result').hidden=false;get('retake').hidden=true;editor.root.hidden=true;form.hidden=true;status('');
    get('before').src=data.before;get('disclaimer').textContent=data.disclaimer;get('warning').textContent=data.warning||'';get('texture-note').textContent=data.textureNote;
    get('result-tabs').replaceChildren();
    const select=(variant,button)=>{
      get('result-name').textContent=variant.name;
      get('result-spec').textContent=`${variant.base} · ${variant.thickness===null?'товщина уточнюється':variant.thickness===0?'без утеплювача':variant.thickness+' мм'}`;
      const size=find(variant.id)?.tileSize;
      get('result-spec').textContent+=size?` · Плитка ${size.width} × ${size.height} мм`:' · Розмір плитки уточнюється';
      get('after').src=variant.after;renderQuote(variant.quote);
      for(const b of get('result-tabs').children)b.setAttribute('aria-pressed',String(b===button));
    };
    for(const [index,variant] of data.variants.entries()){
      const button=el('button','facade-secondary',variant.name);button.type='button';button.onclick=()=>select(variant,button);get('result-tabs').append(button);if(!index)select(variant,button);
    }
    get('slider').value='50';get('slider').dispatchEvent(new Event('input'));
    for(const button of dialog.querySelectorAll('[data-facade-action]'))button.disabled=false;
    document.querySelector('meta[name="robots"]')?.remove();const robots=document.createElement('meta');robots.name='robots';robots.content='noindex,nofollow';document.head.append(robots);
  }
  async function poll(id,current){
    for(let attempts=0;attempts<180;attempts++){
      if(current!==generation)return;
      const data=await api(`/api/facade/jobs/${id}`);
      if(current!==generation)return;
      if(data.status==='ready'){displayResult(data);return;}
      if(data.status==='retake'){displayRetake(data);return;}
      if(data.status==='failed'){status(data.message,true);form.hidden=false;return;}
      status('Автоматично виділяємо стіну та переносимо фактуру. Це може зайняти кілька хвилин.');
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
    status('Обробка триває довше. Збережіть посилання на результат з адресного рядка та відкрийте його пізніше.',true);
  }
  form.onsubmit=async event=>{
    event.preventDefault();if(busy)return;
    if(!selected.size){status('Оберіть від 1 до 3 панелей.',true);return;}
    if(!form.reportValidity())return;
    const fields=new FormData(form),current=++generation;
    const source=new URLSearchParams(location.search).get('utm_source')||'catalog';
    const data={panels:[...selected.values()],city:fields.get('city'),area:get('unknown').value==='yes'?null:Number(fields.get('area')),name:fields.get('name'),phone:fields.get('phone'),contact:fields.get('contact'),consent:fields.has('consent'),source:source.slice(0,200)};
    const body=new FormData();body.append('photo',get('photo').files[0]);body.append('metadata',JSON.stringify(data));
    busy=true;get('submit').disabled=true;status('Перевіряємо фото…');
    try{const job=await api('/api/facade/jobs',{method:'POST',body});activeJob=job.id;
      history.replaceState(null,'',job.resultUrl);await poll(job.id,current);
    }catch(error){if(current===generation)status(error.message,true);}
    finally{busy=false;get('submit').disabled=false;}
  };
  get('slider').oninput=()=>{const value=Number(get('slider').value);get('after-layer').style.clipPath=`inset(0 ${100-value}% 0 0)`;get('divider').style.left=value+'%';};
  get('again').onclick=get('retake-again').onclick=()=>{generation++;busy=false;get('submit').disabled=false;get('result').hidden=true;get('retake').hidden=true;editor.root.hidden=true;form.hidden=false;history.replaceState(null,'','/lab');status('');};
  get('copy').onclick=async()=>{try{await navigator.clipboard.writeText(new URL(`/result/${activeJob}`,location.origin).href);status('Особисте посилання скопійовано.');}catch{status('Скопіюйте посилання з адресного рядка.');}};
  for(const button of dialog.querySelectorAll('[data-facade-action]'))button.onclick=async()=>{
    button.disabled=true;
    try{const result=await api(`/api/facade/jobs/${activeJob}/actions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:button.dataset.facadeAction})});status(button.dataset.facadeAction==='complaint'?'Дякуємо. Повідомлення про невідповідність збережено.':result.message);}
    catch(error){status(error.message,true);button.disabled=false;}
  };
  const match=location.pathname.match(/^\/result\/([a-f0-9-]{36})$/);
  if(match){showDialog();form.hidden=true;poll(match[1],++generation).catch(error=>status(error.message,true));}
  return {open,eligible};
})();
