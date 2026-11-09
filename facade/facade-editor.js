'use strict';
window.createFacadeEditor = ({save, close, revoke}) => {
  const root=document.createElement('section');root.className='facade-editor';root.hidden=true;
  root.setAttribute('aria-label','Уточнення ділянок фасаду');
  root.innerHTML=`<h3>Уточніть ділянки</h3><p>Позначте вікна, двері та цоколь, щоб зберегти їхній вигляд. Якщо захоплено дах або сусідній будинок — обведіть фасад.</p>
  <div class="facade-editor-tools" role="group" aria-label="Інструменти виділення">
  <button type="button" data-tool="window">Вікно</button><button type="button" data-tool="door">Двері</button>
  <button type="button" data-tool="plinth">Цоколь</button><button type="button" data-tool="facade">Контур фасаду</button><button type="button" data-tool="exclude">Інша ділянка</button><button type="button" data-tool="select">Перемістити точки</button></div>
  <p class="facade-editor-hint" aria-live="polite"></p>
  <details class="facade-editor-suggestions" hidden><summary>Можливі пропущені проєми</summary><p>Це лише підказки. Перевірте рамку й натисніть «Додати», якщо вона відповідає вікну або дверям. Непідтверджені підказки не змінюють примірку.</p><div class="facade-editor-commands" data-suggestions></div></details>
  <div class="facade-editor-stage"><img class="facade-editor-photo" alt="Фото для уточнення маски" draggable="false">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" preserveAspectRatio="none" tabindex="0" role="img" aria-label="Поле виділення. Оберіть інструмент над фото. Стрілки переміщують вибрану точку, Delete видаляє область, Escape скасовує незавершене виділення."></svg></div>
  <div class="facade-editor-commands"><button type="button" data-command="zoom">Збільшити фото</button><button type="button" data-command="finish">Завершити контур</button><button type="button" data-command="cancel-draft">Скасувати контур</button><button type="button" data-command="undo">Скасувати дію</button><button type="button" data-command="clear">Очистити мої виділення</button></div>
  <ul class="facade-editor-list" aria-label="Мої виділення"></ul>
  <label class="facade-consent"><input type="checkbox" class="facade-editor-consent"><span class="facade-editor-consent-text"></span></label>
  <button type="button" data-command="revoke" hidden>Відкликати згоду без зміни примірки</button>
  <p class="facade-help">Виділення збережуться для цієї примірки навіть без згоди на навчання. Перед навчанням їх перевірять; модель не навчається автоматично після кожного виділення. Зберігання — до 90 днів разом із фото.</p>
  <p class="facade-editor-error" role="alert"></p>
  <div class="facade-editor-commands"><button type="button" class="primary" data-command="apply">Оновити примірку</button><button type="button" data-command="back">Назад без змін</button></div>`;
  const svg=root.querySelector('svg'), photo=root.querySelector('img'), list=root.querySelector('ul');
  const error=root.querySelector('.facade-editor-error'), hint=root.querySelector('.facade-editor-hint');
  const checkbox=root.querySelector('.facade-editor-consent');
  const stage=root.querySelector('.facade-editor-stage');
  photo.onload=()=>{stage.style.maxWidth=`min(780px, ${62*photo.naturalWidth/photo.naturalHeight}vh)`;};
  const command=name=>root.querySelector(`[data-command="${name}"]`);
  const labels={window:'Вікно',door:'Двері',plinth:'Цоколь',facade:'Контур фасаду',exclude:'Інша ділянка'};
  const colors={window:'#ef4157',door:'#f0a626',plinth:'#388bfd',facade:'#219d65',exclude:'#8b5cf6'};
  let elements=[], history=[], draft=[], tool='window', selected=-1, handle=-1, drag=null, revision=null, saving=false, invalid=[];
  let suggestions=[];
  const suggestionPanel=root.querySelector('.facade-editor-suggestions'), suggestionList=root.querySelector('[data-suggestions]');
  function pendingSuggestions(){
    const bounds=item=>[Math.min(...item.points.map(p=>p.x)),Math.min(...item.points.map(p=>p.y)),Math.max(...item.points.map(p=>p.x)),Math.max(...item.points.map(p=>p.y))];
    return suggestions.map((item,index)=>({item,index})).filter(({item})=>{
      const a=bounds(item);
      return !elements.some(element=>{
        if(!['window','door','exclude'].includes(element.kind))return false;
        const b=bounds(element), intersection=Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0]))*Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1]));
        return intersection/Math.max(1e-9,(a[2]-a[0])*(a[3]-a[1]))>.6;
      });
    });
  }
  function confirmSuggestion(index){
    if(saving)return;
    if(draft.length){error.textContent='Спочатку завершіть або скасуйте поточний контур.';return;}
    const item=suggestions[index];if(!item)return;
    if(add({kind:item.kind,points:clone(item.points)}))choose('select');
    render();
  }
  const clone=value=>JSON.parse(JSON.stringify(value));
  function checkpoint(){invalid=[];history.push(clone(elements));if(history.length>60)history.shift();}
  function point(event){const r=svg.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))};}
  function node(tag, attrs){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));return n;}
  function choose(value){if(saving)return;tool=value;draft=[];drag=null;handle=-1;error.textContent='';render();}
  function render(){
    svg.replaceChildren();
    const pending=pendingSuggestions();suggestionPanel.hidden=!pending.length;suggestionList.replaceChildren();
    for(const {item,index} of pending){
      const button=document.createElement('button');button.type='button';button.textContent=`Додати: ${labels[item.kind]} ${index+1}`;button.onclick=()=>confirmSuggestion(index);suggestionList.append(button);
      if(suggestionPanel.open)svg.append(node('polygon',{points:item.points.map(p=>`${p.x*1000},${p.y*1000}`).join(' '),fill:'#fff','fill-opacity':.06,stroke:'#f0a626','stroke-dasharray':'6 5','stroke-width':2,'vector-effect':'non-scaling-stroke','data-proposal':index}));
    }
    for(const [index,item] of elements.entries()){
      const points=item.points.map(p=>[p.x*1000,p.y*1000]);let shape;
      if(['window','door'].includes(item.kind)&&points.length===2){
        const [a,b]=points;shape=node('rect',{x:Math.min(a[0],b[0]),y:Math.min(a[1],b[1]),width:Math.abs(a[0]-b[0]),height:Math.abs(a[1]-b[1])});
      }else{
        const full=item.kind==='plinth'?[[0,points[0][1]],...points,[1000,points.at(-1)[1]],[1000,1000],[0,1000]]:points;
        shape=node('polygon',{points:full.map(p=>p.join(',')).join(' ')});
      }
      for(const [k,v] of Object.entries({fill:colors[item.kind],'fill-opacity':index===selected ? .28 : .16,stroke:invalid.includes(index)?'#b42318':colors[item.kind],'stroke-width':invalid.includes(index)?5:index===selected?3:2,'vector-effect':'non-scaling-stroke','data-index':index}))shape.setAttribute(k,String(v));
      svg.append(shape);
      if(index===selected&&tool==='select')for(const [i,p] of points.entries())svg.append(node('circle',{cx:p[0],cy:p[1],r:9,fill:'white',stroke:colors[item.kind],'stroke-width':3,'vector-effect':'non-scaling-stroke','data-index':index,'data-handle':i}));
    }
    if(draft.length){
      svg.append(node('polyline',{points:draft.map(p=>`${p.x*1000},${p.y*1000}`).join(' '),fill:'none',stroke:colors[tool]||'white','stroke-width':3,'vector-effect':'non-scaling-stroke'}));
      for(const p of draft)svg.append(node('circle',{cx:p.x*1000,cy:p.y*1000,r:5,fill:colors[tool]}));
    }
    for(const button of root.querySelectorAll('[data-tool]'))button.setAttribute('aria-pressed',String(button.dataset.tool===tool));
    hint.textContent=({window:'Клацайте по краю вікна разом із рамою та підвіконням. Потрібно щонайменше 3 точки. Потім натисніть «Завершити контур» або першу точку.',door:'Обведіть двері або гаражні ворота точками по периметру разом із рамою. Потім завершіть контур.',plinth:'Поставте точки по верхній межі цоколя в одному напрямку та завершіть контур. Усе нижче лінії в межах фасаду збережеться.',facade:'Обведіть лише поверхню стіни точками по периметру, включаючи фронтон, без даху. Потім завершіть контур.',exclude:'Обведіть точками будь-яку ділянку, яку потрібно зберегти: балкон, рослини, трубу або іншу перешкоду. Потім завершіть контур.',select:'Оберіть область у списку й перетягніть білі точки. Для точної поправки виберіть точку та натискайте стрілки.'})[tool];
    list.replaceChildren();
    elements.forEach((item,index)=>{
      const li=document.createElement('li'), pick=document.createElement('button'), del=document.createElement('button');
      if(invalid.includes(index))li.classList.add('facade-editor-invalid');
      pick.type=del.type='button';pick.textContent=`${index+1}. ${labels[item.kind]}`;pick.setAttribute('aria-pressed',String(index===selected));
      pick.onclick=()=>{selected=index;choose('select');};
      del.textContent='Видалити';del.setAttribute('aria-label',`Видалити ${labels[item.kind]} ${index+1}`);
      del.onclick=()=>{checkpoint();elements.splice(index,1);selected=-1;render();};li.append(pick,del);list.append(li);
    });
    command('finish').hidden=command('cancel-draft').hidden=tool==='select';
    command('finish').disabled=draft.length<(tool==='plinth'?2:3);
    command('cancel-draft').disabled=!draft.length;command('undo').disabled=!history.length&&!draft.length;
    command('clear').disabled=!elements.length;
    for(const control of root.querySelectorAll('button,input'))if(saving)control.disabled=true;
  }
  function add(item){
    if(elements.length>=64&&!['facade','plinth'].includes(item.kind)){error.textContent='Можна додати до 64 областей.';return false;}
    checkpoint();
    if(['facade','plinth'].includes(item.kind))elements=elements.filter(e=>e.kind!==item.kind);
    elements.push(item);selected=elements.length-1;return true;
  }
  svg.addEventListener('pointerdown',event=>{
    if(saving||event.button!==0)return;event.preventDefault();svg.focus();const p=point(event);
    const proposal=event.target.getAttribute('data-proposal');
    if(proposal!==null){confirmSuggestion(Number(proposal));return;}
    if(tool==='select'){
      const index=event.target.getAttribute('data-index'), h=event.target.getAttribute('data-handle');
      if(index!==null){selected=Number(index);if(h===null)handle=-1;}
      if(h!==null){handle=Number(h);checkpoint();drag={kind:'point',id:event.pointerId};svg.setPointerCapture(event.pointerId);}
      render();return;
    }
    {
      if(tool!=='plinth'&&draft.length>=3){
        const r=svg.getBoundingClientRect(),start=draft[0];
        if(Math.hypot((p.x-start.x)*r.width,(p.y-start.y)*r.height)<10){command('finish').click();return;}
      }
      if(draft.length>=(tool==='plinth'?16:32)){error.textContent='Завершіть поточний контур.';return;}
      if(tool==='plinth'&&draft.length){
        const delta=p.x-draft.at(-1).x, direction=draft.length>1?Math.sign(draft[1].x-draft[0].x):Math.sign(delta);
        if(Math.abs(delta)<=1e-6||Math.sign(delta)!==direction){error.textContent='Продовжуйте лінію в одному напрямку, без повернення назад.';return;}
      }
      draft.push(p);render();
    }
  });
  svg.addEventListener('pointermove',event=>{
    if(!drag||drag.id!==event.pointerId||saving)return;
    const p=point(event), item=elements[selected];if(!item)return;
    item.points[drag.kind==='rect'?1:handle]=p;render();
  });
  function release(event){
    if(!drag||drag.id!==event.pointerId)return;
    if(event.type==='pointercancel')elements=history.pop()||elements;
    else if(drag.kind==='rect'){
      const [a,b]=elements[selected].points;
      if(Math.abs(a.x-b.x)<.003||Math.abs(a.y-b.y)<.003){elements=history.pop()||[];selected=-1;}
    }
    drag=null;render();
  }
  svg.addEventListener('pointerup',release);svg.addEventListener('pointercancel',release);
  svg.addEventListener('keydown',event=>{
    if(saving)return;
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();draft=[];render();return;}
    if(event.key==='Delete'&&selected>=0){event.preventDefault();checkpoint();elements.splice(selected,1);selected=-1;render();return;}
    const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
    if(delta&&tool==='select'&&selected>=0&&handle>=0){event.preventDefault();checkpoint();const p=elements[selected].points[handle],step=event.shiftKey ? .01 : .002;p.x=Math.max(0,Math.min(1,p.x+delta[0]*step));p.y=Math.max(0,Math.min(1,p.y+delta[1]*step));render();}
  });
  for(const button of root.querySelectorAll('[data-tool]'))button.onclick=()=>choose(button.dataset.tool);
  suggestionPanel.addEventListener('toggle',render);
  command('finish').onclick=()=>{const points=clone(draft);if(tool==='plinth'&&points[0].x>points.at(-1).x)points.reverse();add({kind:tool,points});draft=[];choose('select');};
  command('cancel-draft').onclick=()=>{draft=[];render();};
  command('undo').onclick=()=>{if(draft.length){draft.pop();render();return;}elements=history.pop()||elements;selected=-1;render();};
  command('clear').onclick=()=>{checkpoint();elements=[];selected=-1;draft=[];render();};
  command('zoom').onclick=()=>{const zoomed=stage.classList.toggle('is-zoomed');command('zoom').textContent=zoomed?'Вмістити фото':'Збільшити фото';};
  command('back').onclick=()=>{root.hidden=true;close();};
  command('revoke').onclick=async()=>{
    if(saving)return;saving=true;render();
    try{await revoke();checkbox.checked=false;command('revoke').hidden=true;error.textContent='Згоду на навчання відкликано. Примірка збережена.';}
    catch(exc){error.textContent=exc.message;}
    finally{saving=false;for(const c of root.querySelectorAll('button,input'))c.disabled=false;render();}
  };
  command('apply').onclick=async()=>{
    if(saving)return;
    if(draft.length){error.textContent='Спочатку завершіть або скасуйте поточний контур.';return;}
    saving=true;error.textContent='Оновлюємо примірку…';render();
    try{await save({revision,elements:clone(elements),trainingConsent:checkbox.checked});root.hidden=true;}
    catch(exc){error.textContent=exc.message;invalid=exc.invalidElements||[];if(invalid.length){selected=invalid[0];tool='select';handle=-1;}}
    finally{saving=false;for(const c of root.querySelectorAll('button,input'))c.disabled=false;render();}
  };
  return {root, open(data){
    saving=false;elements=clone(data.editing?.elements||[]);revision=data.editing?.revision||null;
    suggestions=clone(data.openingSuggestions||[]);suggestionPanel.open=false;
    history=[];draft=[];selected=-1;handle=-1;drag=null;tool='window';invalid=[];
    stage.classList.remove('is-zoomed');command('zoom').textContent='Збільшити фото';
    photo.src=data.before;checkbox.checked=!!data.editing?.trainingConsent;
    command('revoke').hidden=!checkbox.checked;
    root.querySelector('.facade-editor-consent-text').textContent=data.editing?.consentText||'';
    error.textContent='';root.hidden=false;render();root.scrollIntoView({block:'start'});
  }};
};
