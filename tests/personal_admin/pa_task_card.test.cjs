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
test('outcome timeline exposes exact source navigation and honest unknown times',()=>{
 const card=new Card();card._config={};
 const html=card._projectTimelineMarkup({timeline:[{title:'<Dispatch>',event_kind:'information',evidence_only:true,observed_at:0,source_message_ids:['<dispatch@example.test>','<dispatch@example.test>','javascript:bad']} ]});
 assert.match(html,/&lt;Dispatch&gt;/);assert.match(html,/Observation time unknown/);
 assert.match(html,/no lifecycle inferred/);assert.match(html,/Supporting sources · 1/);
 assert.match(html,/rfc822msgid%3Adispatch%40example.test/);assert.doesNotMatch(html,/javascript:bad/);
 const dated=card._projectTimelineMarkup({timeline:[{title:'Receipt',observed_at:100,time_source:'email_date',source_message_ids:[]}]});
 assert.match(dated,/Email date:/);assert.match(dated,/GMT/);
 assert.match(card._projectTimelineMarkup({timeline:[]}),/No verified history/);
});
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
 for(const kind of ['marketing_offer','routine_delivery','optional_opportunity','optional_feedback','optional_change_window']){
  const html=card._taskCard({id:'reference',status:'OPEN',title:'Synthetic action',obligation_suppressed:kind});
  assert.doesNotMatch(html,/Renewal date/);assert.doesNotMatch(html,/Overdue/);assert.match(html,/Track this/);
 }
});

test('past event status asks about follow-up without asserting overdue or completion',()=>{
 const card=new Card();card._config={};
 const row={id:'event',status:'OPEN',title:'Review past event: Directions hearing',original_title:'Directions hearing',confirmation_required:'past_event_status',date_confirmation_required:true,due_date:null,extracted_date:'2026-09-23'};
 assert.equal(card._kind(row),'question');
 const tiles=card._overviewMarkup([row]);assert.match(tiles,/anything left to do after this event/);assert.doesNotMatch(tiles,/Overdue/);
 const detail=card._taskCard(row);assert.match(detail,/does not establish an overdue task or prove that it happened/);assert.match(detail,/Saved date · unverified/);assert.match(detail,/Yes, keep tracking/);assert.doesNotMatch(detail,/data-action="close"/);
 const warned=card._taskCard({...row,source_response_required:true,severity:'high'});assert.match(warned,/source needs checking for any required response or follow-up/);assert.match(warned,/saved date is unverified/);assert.match(warned,/severity-high/);
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

test('waiting matters expose missing context explicitly',()=>{
 const card=new Card();card._config={};card._overviewTab='waiting';
 const task={id:'synthetic-order',title:'Order TEST1042 placed',status:'WAITING'};
 const detail=card._taskCard(task,true);
 assert.match(detail,/At a glance/);
 assert.match(detail,/Sender not available/);
 assert.match(detail,/Message details have not been captured/);
 assert.match(detail,/No next step has been confirmed/);
 assert.match(card._overviewMarkup([task]),/Expected reply or next step not recorded/);
});

test('source-backed details show sender and contents without expanding evidence',()=>{
 const card=new Card();card._config={};
 const task={id:'synthetic-order',title:'Order placed',status:'WAITING',source_context:{sender:'Device Shop <orders@example.test>',subject:'Order TEST1042 confirmed',summary:'Two smart relays ordered for collection.',waiting_for:'Collection-ready email',next_step:'Bring the order reference when collecting.'}};
 const detail=card._taskCard(task,true);
 assert.match(detail,/Device Shop &lt;orders@example.test&gt;/);
 assert.match(detail,/Two smart relays ordered for collection/);
 assert.match(detail,/Collection-ready email/);
 assert.match(detail,/Bring the order reference/);
 assert.ok(detail.indexOf('At a glance')<detail.indexOf('The story so far'));
 assert.match(card._waitingSummary(task),/Two smart relays/);
});
test('projects and attention retain source controls and escape derived context',()=>{
 const card=new Card();card._config={};
 const p={id:'project-demo',name:'<unsafe>',intended_outcome:null,lifecycle:'candidate',attention:'WAITING',open_count:1,completed_count:0,next_action:[],waiting_on:['Vehicle assignment'],latest_update:null,matter_ids:['vehicle'],uncertainties:['Outcome unknown'],timeline:[],provenance:[{matter_id:'vehicle',rule:'accepted_matter',source_message_ids:['<demo@example.test>']}],buckets:{ACTION:[],WAITING:['vehicle'],WATCH:[],INFORMATION:[],COMPLETE:[]}};
 const row={id:'vehicle',title:'Collect vehicle',status:'WAITING',source_message_ids:['<demo@example.test>']};
 const view={projects:[p]};
 assert.match(card._projectsMarkup(view,[row]),/No current action/);
 assert.match(card._projectsMarkup(view,[row]),/Vehicle assignment/);
 assert.doesNotMatch(card._projectsMarkup(view,[row]),/<unsafe>/);
 card._selectedProjectId=p.id;
 const detail=card._projectsMarkup(view,[row]);
 for(const heading of ['Overview','Timeline','Actions','Waiting','Information','Complete','Evidence and grouping']) assert.match(detail,new RegExp(heading));
 assert.match(detail,/accepted_matter/);assert.match(detail,/data-action=/);
 card._productView='attention';
 assert.match(card._projectsMarkup(view,[row]),/Needs you/);
 assert.match(card._projectsMarkup(view,[row]),/Waiting on others/);
});
test('finite outcome uses existing overlay action without task completion',async()=>{
 const card=new Card();card._config={};const calls=[];
 const row={id:'vehicle',title:'Vehicle order',status:'WAITING'};
 card._items=()=>[row];
 card._hass={callService:async(...args)=>calls.push(args)};
 context.window.prompt=()=> 'Collect the synthetic vehicle';
 context.window.confirm=()=>true;
 await card._act({dataset:{action:'project_outcome',id:'vehicle'},disabled:false});
 assert.equal(calls[0][0],'shell_command');assert.equal(calls[0][1],'lifeos_pa_user_action');
 assert.equal(calls[0][2].action,'project_outcome');
 assert.equal(calls[0][2].note,'Collect the synthetic vehicle');
 assert.equal(calls.some(call=>call[2]?.action==='close'),false);
});
test('information inside a waiting matter is visible without an information task',()=>{
 const card=new Card();card._config={};
 const p={id:'project-demo',name:'Vehicle',intended_outcome:null,lifecycle:'candidate',attention:'WAITING',open_count:1,completed_count:0,next_action:[],waiting_on:['Vehicle assignment'],latest_update:null,anchor_matter_id:'vehicle',uncertainties:[],timeline:[{title:'Delivery estimate updated',event_kind:'information',observed_at:0,source_message_ids:['<info@example.test>']}],provenance:[],buckets:{ACTION:[],WAITING:['vehicle'],WATCH:[],INFORMATION:[],COMPLETE:[]}};
 const row={id:'vehicle',title:'Vehicle order',status:'WAITING'};
 card._selectedProjectId=p.id;
 const detail=card._projectsMarkup({projects:[p]},[row]);
 assert.match(detail,/<h3>Information<\/h3><p>Delivery estimate updated/);
 assert.match(detail,/Observation time unknown/);
 assert.doesNotMatch(detail,/1970/);
 assert.equal(p.buckets.ACTION.length,0);assert.equal(p.buckets.INFORMATION.length,0);
 card._productView='attention';
 assert.match(card._projectsMarkup({projects:[p]},[row]),/Delivery estimate updated/);
 assert.match(card._projectsMarkup({projects:[p]},[row]),/Information update, no new action/);
});
test('project detail explains next move without duplicate uncertainty or empty-section walls',()=>{
 const card=new Card();card._config={};
 const p={id:'project-demo',name:'Example Motors order',anchor_matter_id:'vehicle',intended_outcome:null,lifecycle:'candidate',attention:'WAITING',next_action:[],waiting_on:['Await vehicle assignment'],uncertainties:['Finite intended outcome not confirmed'],timeline:[],provenance:[],buckets:{ACTION:[],WAITING:['vehicle'],WATCH:[],INFORMATION:[],COMPLETE:[]}};
 const row={id:'vehicle',title:'Vehicle order',status:'WAITING'};card._selectedProjectId=p.id;
 const html=card._projectsMarkup({projects:[p]},[row]);
 assert.match(html,/No current action is recorded for you/);assert.match(html,/Await vehicle assignment/);
 assert.match(html,/Name project outcome/);assert.doesNotMatch(html,/Finite intended outcome not confirmed/);
 for(const label of ['Actions','Watching','Information','Complete']) assert.doesNotMatch(html,new RegExp('<h3>'+label+'</h3>'));
 assert.doesNotMatch(html,/0 updates|The story so far|No message updates/);
 assert.match(html,/No items in:/);
});
test('owner waiting is explicit and related items stay accessible without repeated panels',()=>{
 const card=new Card();card._config={};
 const a={id:'a',title:'First matter',status:'WAITING',user_waiting_for:'Vehicle and collection assignment',source_context:{sender:'Example Motors',subject:'Original request',next_step:'Upload identity now'}};
 const b={...a,id:'b',title:'Second matter'};
 const p={id:'owner-project',anchor_matter_id:'a',name:'Vehicle purchase',intended_outcome:'Collect vehicle',lifecycle:'active',attention:'WAITING',next_action:[],waiting_on:['Vehicle and collection assignment'],uncertainties:[],timeline:[],provenance:[],buckets:{ACTION:[],WAITING:['a','b'],WATCH:[],INFORMATION:[],COMPLETE:[]}};
 card._selectedProjectId=p.id;
 const html=card._projectsMarkup({projects:[p]},[a,b]);
 assert.match(html,/<details><summary>Related waiting items and sources · 2/);
 assert.match(html,/No current action is recorded for you/);
 assert.doesNotMatch(html,/Upload identity now/);
 assert.match(html,/No action currently required/);
 assert.match(card._waitingSummary(a),/Owner-confirmed waiting/);
});
test('attention renders one expandable project rather than a card per related item or bucket',()=>{
 const card=new Card();card._config={};card._productView='attention';
 const items=[{id:'a',title:'Action one',status:'OPEN'},{id:'b',title:'Unverified action',status:'OPEN',confirmation_required:'source_unavailable'},
  {id:'c',title:'Waiting one',status:'WAITING'},{id:'d',title:'Waiting two',status:'WAITING'},
  {id:'i',title:'Receipt',status:'OPEN',obligation_suppressed:'order_acknowledgement'},
  {id:'e',title:'Completed item',status:'DONE'}];
 const project={id:'project-owner',name:'Vehicle purchase',attention:'ACTION',matter_ids:items.map(item=>item.id),
  next_action:['Review an unverified item'],waiting_on:['Vehicle assignment'],timeline:[],
  buckets:{ACTION:['a','b'],WAITING:['c','d'],WATCH:[],INFORMATION:['i'],COMPLETE:['e']}};
 const other={id:'project-other',name:'Unrelated project',attention:'WAITING',matter_ids:['other'],next_action:[],waiting_on:['A reply'],timeline:[],
  buckets:{ACTION:[],WAITING:['other'],WATCH:[],INFORMATION:[],COMPLETE:[]}};
 const html=card._projectsMarkup({projects:[project,other],recently_completed_ids:['e']},[...items,{id:'other',title:'Other',status:'WAITING'}]);
 assert.equal((html.match(/data-attention-project="project-owner"/g)||[]).length,1);
 assert.equal((html.match(/data-attention-project="project-other"/g)||[]).length,1);
 assert.match(html,/<details class="attention-project" data-attention-project="project-owner"><summary/);
 assert.equal((html.match(/data-attention-item="project-owner:/g)||[]).length,6);
 assert.match(html,/1 recorded action · 1 question · 2 waiting/);
 assert.match(html,/Expand 6 related items and sources/);
 assert.match(html,/data-action="comment"/);assert.match(html,/Open project overview and timeline/);
 assert.doesNotMatch(html,/<button class="overview-tile" data-project="project-owner"/);
 card._attentionExpanded=new Set(['project-owner','project-owner:b']);
 const expanded=card._projectsMarkup({projects:[project]},items);
 assert.match(expanded,/data-attention-project="project-owner" open/);
 assert.match(expanded,/data-attention-item="project-owner:b" open/);
});
