// Offline contract tests: no browser, Google request, or email delivery.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../google-mail/transport.js'), 'utf8');
function setup(host = 'catalog.nashdvor.com.ua') {
  const listeners = {}, fields = {}, sent = [];
  let opened = 0, serial = 0, reads = 0, failRead = false;
  const form = {dataset: {requestType:'product'}, elements:{namedItem(name) {
    return fields[name] ||= {value: name, checked:true};
  }}, addEventListener(name, fn) { listeners[name] = fn; }, querySelector() {return null;}, reportValidity() {return true;}};
  const nodes = {'lead-form':form, 'lead-status':{scrollIntoView(){}}, 'lead-submit':{}, 'lead-photo':{files:[], addEventListener(){}}, 'lead-selection':{value:'panel A'}};
  const document = {getElementById:id=>nodes[id], head:{append(){}}, body:{append(){}}, createElement(tag) {
    return {append(child){this.child=child;}, remove(){}, submit(){sent.push(JSON.parse(this.child.value));}};
  }};
  class FileReader {
    readAsDataURL() { reads++; if (failRead) this.onerror(); else {this.result='data:image/jpeg;base64,aGVsbG8='; this.onload();} }
  }
  const window = {open(){opened++;return {close(){}};}};
  vm.runInNewContext(source, {window, document, FileReader, location:{protocol:'https:',hostname:host,port:'',href:'https://'+host+'/'}, crypto:{randomUUID:()=>`request-${++serial}`}});
  window.NashDvorGoogleMail.connect('https://script.google.com/macros/s/test/exec');
  return {form, nodes, fields, sent, get opened(){return opened;}, get reads(){return reads;}, fail(value){failRead=value;},
    submit:()=>listeners.submit({preventDefault(){},stopImmediatePropagation(){}})};
}
test('unchanged retries deduplicate; programmatic selection changes get a new ID', async()=>{
  const s=setup(); await s.submit(); await s.submit();
  assert.equal(s.sent[0].id,s.sent[1].id);
  s.nodes['lead-selection'].value='panel B'; await s.submit();
  assert.notEqual(s.sent[1].id,s.sent[2].id);
});
test('local preview does not open a Google receiver or submit contacts',async()=>{
  const s=setup('127.0.0.1'); await s.submit();
  assert.equal(s.opened,0); assert.equal(s.sent.length,0);
  assert.match(s.nodes['lead-status'].textContent,/локальний/);
});
test('photo preparation is reused and replacement creates a new request',async()=>{
  const s=setup(); s.form.dataset.requestType='visualization';
  s.nodes['lead-photo'].files=[{name:'one.jpg',size:100}];
  await s.submit(); await s.submit(); assert.equal(s.reads,1);
  assert.equal(s.sent[0].id,s.sent[1].id);
  s.nodes['lead-photo'].files=[{name:'two.jpg',size:100}]; await s.submit();
  assert.equal(s.reads,2); assert.notEqual(s.sent[1].id,s.sent[2].id);
});
test('a failed file read can be retried and double clicks cannot submit twice',async()=>{
  const s=setup(); s.form.dataset.requestType='visualization';
  s.nodes['lead-photo'].files=[{name:'one.jpg',size:100}];
  s.fail(true); await s.submit(); assert.equal(s.sent.length,0);
  assert.equal(s.nodes['lead-submit'].disabled,false);
  s.fail(false); await Promise.all([s.submit(),s.submit()]);
  assert.equal(s.sent.length,1); assert.equal(s.reads,2);
});
