"""One-time integration into the retained buildless catalog."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'index.html'
s = path.read_text(encoding='utf-8')
if 'facade/facade.css' not in s:
    s = s.replace('</head>', '<link rel="stylesheet" href="/facade/facade.css">\n</head>')
    s = s.replace('</body>', '<script src="/facade/facade.js"></script>\n</body>')
    s = s.replace('<button class="primary" id="share">', '<button class="primary" id="facade-detail" type="button">Приміряти фасад →</button><button class="primary" id="share">')
    old = "$('cards').append(c)}}"
    new = """if(['porcelain','polish-clinker','clinker-imitation'].includes(s.id)){const wrap=el('article','card-entry'),tryButton=el('button','facade-card-button','Приміряти фасад →');tryButton.type='button';tryButton.setAttribute('aria-label',`Приміряти фасад: ${i.name}`);tryButton.onclick=()=>window.Facade.open(i);wrap.append(c,tryButton);$('cards').append(wrap)}else $('cards').append(c)}}"""
    assert old in s
    s = s.replace(old, new)
    old = "function show(open=true){const i=item();if(!i)return;"
    new = old + "$('facade-detail').hidden=!['porcelain','polish-clinker','clinker-imitation'].includes(state.section);$('facade-detail').onclick=()=>window.Facade.open(i,{base:state.base,mm:state.mm});"
    assert old in s
    s = s.replace(old, new)
    path.write_text(s, encoding='utf-8')
print('Facade entry points integrated.')
