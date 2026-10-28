const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
let Card;
const context = {HTMLElement:class {}, customElements:{define:(_name, value)=>{Card=value;}}, window:{location:{protocol:'http:',hostname:'example.test'}}, Intl, Date, Set, Map};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../homeassistant/www/lifeos-pa-task-card.js'),'utf8'),context);
const event={id:'a'.repeat(64),source_message_id:'<alert@example.test>',email_received_at:1793187720};
const alert={id:'alert',title:'Review account security',status:'OPEN',source_message_ids:[event.source_message_id],sign_in_events:[event]};
test('overview starts with tiles and opens detail deliberately',()=>{
 const card=new Card();card._config={};
 assert.match(card._overviewMarkup([alert]),/data-matter="alert"/);
 assert.doesNotMatch(card._overviewMarkup([alert]),/data-action="signin_yes"/);
 card._selectedMatterId='alert';assert.match(card._overviewMarkup([alert]),/data-action="signin_yes"/);
});
test('confirmed alert cannot hide unrelated work or prevent ordinary completion',()=>{
 const card=new Card();card._config={};const mixed={...alert,source_message_ids:[...alert.source_message_ids,'<other@example.test>'],sign_in_events:[{...event,answer:'yes'}]};
 assert.equal(card._kind(mixed),'action');assert.equal(card._title(mixed),mixed.title);
 assert.match(card._taskCard(mixed),/data-action="close"/);
});
test('information stays in reference without completion or junk controls',()=>{
 const card=new Card();card._config={};const quote={id:'quote',title:'Renew policy',status:'OPEN',obligation_suppressed:'quote_only_no_verified_policy'};
 assert.doesNotMatch(card._overviewMarkup([quote]),/data-matter="quote"/);
 card._overviewTab='reference';assert.match(card._overviewMarkup([quote]),/data-matter="quote"/);
 assert.doesNotMatch(card._taskCard(quote),/data-action="(?:close|junk|reopen)"/);
 assert.match(card._taskCard(quote),/Renewal date: not confirmed/);
});
test('source context is escaped and does not infer location or sign-in time',()=>{
 const card=new Card();card._config={}; const html=card._taskCard(alert);
 assert.doesNotMatch(html,/<script>/);assert.match(html,/Alert email received/);
 assert.match(html,/Check the original alert/);assert.match(html,/does not approve or block a login/);
 assert.match(card._taskCard({id:'html',title:'<script>bad</script>',status:'OPEN'}),/&lt;script&gt;/);
});
test('answers send event-scoped overlay actions without generic completion',async()=>{
 const card=new Card();card._config={};const calls=[];
 card._hass={states:{'sensor.lifeos_pa_task_attention':{attributes:{items:[alert]}}},callService:async(...args)=>calls.push(args)};card._config={};
 await card._act({dataset:{action:'signin_no',id:'alert',event:event.id}});
 assert.equal(calls[0][2].action,'signin_no');assert.equal(calls[0][2].note,event.id);assert.equal(calls.length,2);
});
