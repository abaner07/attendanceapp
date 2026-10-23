// Exercise the dashboard's real rendering and attendance calculations without a browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
function element(key) {
  if (!elements.has(key)) elements.set(key, {value:key==='#filter'?'all':'', hidden:false, textContent:'', innerHTML:'', addEventListener(){}});
  return elements.get(key);
}
const context = vm.createContext({document:{querySelector:element,activeElement:null},setInterval(){},fetch:async()=>({status:403}),Set,Date,console});
vm.runInContext(fs.readFileSync('static/app.js','utf8'),context);
vm.runInContext(`state={base_url:'http://localhost:8765',meetings:[
 {id:3,title:'Today',open:1,token:'current',created:'2026-10-23T12:00:00Z'},
 {id:2,title:'Second',open:0,created:'2026-10-22T12:00:00Z'},
 {id:1,title:'First',open:0,created:'2026-10-21T12:00:00Z'}],
 students:[{eid:'miss123',name:'Missing Student',since:1},{eid:'here123',name:'Here Student',since:1},{eid:'new123',name:'<script>unsafe</script>',since:3}],
 attendance:[{eid:'here123',meeting_id:1},{eid:'here123',meeting_id:2},{eid:'here123',meeting_id:3}]};render();`,context);
assert.equal(element('#risk').textContent,1);
assert.equal(element('#present').textContent,1);
assert.equal(element('#completed').textContent,2);
assert.ok(element('#students').innerHTML.indexOf('Missing Student') < element('#students').innerHTML.indexOf('Here Student'));
assert.ok(element('#students').innerHTML.includes('100%'));
assert.ok(element('#students').innerHTML.includes('No completed meetings'));
assert.ok(element('#students').innerHTML.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
assert.ok(!element('#students').innerHTML.includes('<script>unsafe'));
element('#filter').value='risk';vm.runInContext('render()',context);
assert.ok(element('#students').innerHTML.includes('Missing Student'));
assert.ok(!element('#students').innerHTML.includes('Here Student'));
element('#filter').value='absent';vm.runInContext('render()',context);
assert.ok(!element('#students').innerHTML.includes('Here Student'));
assert.ok(element('#students').innerHTML.includes('Missing Student'));
console.log('Dashboard calculations, ordering, filters, and HTML escaping passed.');
