'use strict';
(() => {
  const panels = CATALOG.sections.flatMap(section => section.items);
  const select = document.getElementById('lab-panel');
  for (const panel of panels) select.append(new Option(panel.name, panel.id));
  document.getElementById('lab-open').onclick = () => {
    const panel = panels.find(item => item.id === select.value);
    if (panel) window.Facade.open(panel);
  };
})();
