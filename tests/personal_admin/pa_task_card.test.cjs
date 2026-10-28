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
 assert.doesNotMatch(card._taskCard(quote),/data-action="(?:close|junk)"/);
 assert.match(card._taskCard(quote),/Renewal date: not confirmed/);
 assert.match(card._taskCard(quote),/Track this/);
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

test('new card reads separate reference channel and deduplicates rollout overlap',()=>{
 const card=new Card();card._config={};const quote={id:'quote',status:'OPEN',obligation_suppressed:'quote_only_no_verified_policy'};
 const rows=card._items({items:[alert],reference_items:[quote]});assert.equal(rows.length,2);
 card._overviewTab='reference';assert.match(card._overviewMarkup(rows),/data-matter="quote"/);
 assert.equal(card._items({items:[quote],reference_items:[quote]}).length,1);
});

test('non-quote references explain the correct category without renewal language',()=>{
 const card=new Card();card._config={};
 for(const kind of ['marketing_offer','routine_delivery','optional_opportunity']){
  const html=card._taskCard({id:'reference',status:'OPEN',title:'Synthetic action',obligation_suppressed:kind});
  assert.doesNotMatch(html,/Renewal date/);assert.doesNotMatch(html,/Overdue/);assert.match(html,/Track this/);
 }
});

test('unconfirmed commitments are questions with context, never overdue action cards',()=>{
 const card=new Card();card._config={};
 const row={id:'role',title:'Apply for a trustee position',status:'OPEN',due_date:'2026-07-20',confirmation_required:'optional_commitment'};
 assert.equal(card._kind(row),'question');assert.match(card._overviewMarkup([row]),/Do you want to pursue this/);
 assert.match(card._overviewMarkup([row]),/Apply for a trustee position/);assert.doesNotMatch(card._overviewMarkup([row]),/Overdue/);
 const detail=card._taskCard(row);assert.match(detail,/Saved date · unverified/);assert.match(detail,/Yes, track this/);assert.match(detail,/No, not something I need to do/);assert.doesNotMatch(detail,/data-action="close"/);
});
test('source-unavailable questions preserve the original matter and source link',()=>{
 const card=new Card();card._config={};const row={...alert,sign_in_events:[],confirmation_required:'source_unavailable'};
 assert.match(card._taskCard(row),/could not retrieve every original source/);
 assert.match(card._taskCard(row),/rfc822msgid/);
});
test('answering a commitment question dispatches the existing user overlay action',async()=>{
 const card=new Card();card._config={};const calls=[];
 const row={id:'role',status:'OPEN',confirmation_required:'optional_commitment'};
 card._hass={states:{'sensor.lifeos_pa_task_attention':{attributes:{items:[row]}}},callService:async(...args)=>calls.push(args)};
 await card._act({dataset:{id:'role',action:'dismiss'}});
 assert.equal(calls[0][2].action,'dismiss');assert.equal(calls[0][2].task_id,'role');
});
