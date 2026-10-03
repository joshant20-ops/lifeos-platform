const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const cards=[];
global.window = {
  async loadCardHelpers() {
    return {
      createCardElement(config) {
        const card={config,hass:null};
        cards.push(card);
        return card;
      }
    };
  }
};
global.document = {
  createElement(tag) { return {tag,className:'',textContent:'',}; }
};

require('./lifeos-house-status-doorbell.js');
const doorbell=window.LifeOSHouseStatusModules.doorbell;
const host={
  isConnected:true,
  innerHTML:'',
  children:[],
  replaceChildren(...children){this.children=children;}
};
const hass1={states:{'camera.front_door_live_view':{state:'idle'}}};
const hass2={states:{'camera.front_door_live_view':{state:'streaming'}}};

(async()=>{
  assert.match(doorbell.render(),/data-doorbell-card/,'Doorbell renders an in-page camera slot');
  await Promise.all([doorbell.mount(host,hass1),doorbell.mount(host,hass1)]);
  assert.equal(cards.length,1,'concurrent renders create only one live camera card');
  assert.deepEqual(cards[0].config,{type:'picture-entity',entity:'camera.front_door_live_view',name:'Front Door',camera_view:'live',show_name:true,show_state:true,tap_action:{action:'none'},hold_action:{action:'none'}});
  assert.equal(host.children[0],cards[0],'stock Home Assistant camera card mounts in the shell');
  await doorbell.mount(host,hass2);
  assert.equal(cards.length,1,'state updates reuse the mounted camera card');
  assert.equal(cards[0].hass,hass2,'latest Home Assistant state reaches the mounted card');

  const cardPath=path.join(__dirname,'lifeos-house-status-card.js');
  const legacyPath=path.join(__dirname,'lifeos-house-status-v27.js');
  const currentCard=fs.readFileSync(cardPath,'utf8');
  const legacyCard=fs.readFileSync(legacyPath,'utf8');
  assert.match(currentCard,/class="hanav"/,'normal House Status header stays in the shared shell');
  assert.match(currentCard,/this\._mode=el\.dataset\.mode;this\.render\(\)/,'Doorbell switches in-page without leaving the shell');
  assert.doesNotMatch(currentCard,/window\.location\.assign\('\/house-status-native\/doorbell'\)/,'Doorbell does not navigate to a separate page');
  assert.match(legacyCard,/customElements\.define\('lifeos-house-status-v27'/,'legacy panel registers its v27 element');
  assert.match(legacyCard,/type:'lifeos-house-status-v27'/,'legacy custom card metadata uses the v27 type');
  assert.doesNotMatch(legacyCard,/lifeos-house-status-v28/,'legacy asset does not leave v28 identifiers behind');
  assert.ok(legacyCard.startsWith("import './lifeos-house-status-doorbell.js?v=20261003-3';"),'v27 imports the current Doorbell module version');
  const normalizedLegacy=legacyCard
    .replace("import './lifeos-house-status-doorbell.js?v=20261003-3';", "import './lifeos-house-status-doorbell.js?v=20261003-3';")
    .replace('Doorbell v27','Doorbell v28')
    .replaceAll('lifeos-house-status-v27','lifeos-house-status-v28');
  assert.equal(normalizedLegacy,currentCard,'v27 remains a version-only mirror of the current shell');
  console.log('DOORBELL_EMBEDDED_CAMERA_CARD=PASS');
  console.log('DOORBELL_SHARED_HOUSE_STATUS_HEADER=PASS');
  console.log('DOORBELL_V27_SHELL_PARITY=PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
