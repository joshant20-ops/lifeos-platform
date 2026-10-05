const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const base=__dirname;
const moduleSource=fs.readFileSync(path.join(base,'live','lifeos-house-status-doorbell-v28.js'),'utf8');
const legacyEntry=fs.readFileSync(path.join(base,'live','lifeos-house-status-v27.js'),'utf8');
const v28Entry=fs.readFileSync(path.join(base,'live','lifeos-house-status-v28.js'),'utf8');
assert.ok(legacyEntry.startsWith("import './lifeos-house-status-doorbell.js?v=20261004-1';"),'v27 stays on its existing shared module');
assert.doesNotMatch(legacyEntry,/doorbell-v28\.js|doorbellV28/,'v27 does not import the v28-only fix');
assert.ok(v28Entry.startsWith("import './lifeos-house-status-doorbell-v28.js?v=20261005-2';"),'v28 cache-busts the camera module fix');

let routeLoads=0,panelFetches=0,helperCalls=0,cardConfig=null;
const window={};
const customElements={async whenDefined(name){assert.ok(['partial-panel-resolver','ha-panel-lovelace'].includes(name));}};
const document={createElement(tag){
  if(tag==='partial-panel-resolver')return {_getRoutes(routes){
    assert.equal(routes[0].component_name,'lovelace');
    const name=routes[0].url_path;
    return {routes:{[name]:{async load(){routeLoads++;}}}};
  }};
  if(tag==='ha-panel-lovelace')return {panel:null,hass:null,async _fetchConfig(flag){
    assert.equal(flag,false);
    panelFetches++;
    window.loadCardHelpers=async()=>{
      helperCalls++;
      return {async createCardElement(config){cardConfig=config;await Promise.resolve();return {hass:null};}};
    };
  }};
  return {className:'',textContent:'',dataset:{},};
}};
const context={window,document,customElements,setTimeout,console};
vm.runInNewContext(moduleSource,context,{filename:'lifeos-house-status-doorbell-v28.js'});
const doorbell=window.LifeOSHouseStatusModules.doorbellV28;
const host={isConnected:true,innerHTML:'',children:[],replaceChildren(...items){this.children=items;}};
const hass={states:{'camera.front_door_live_view':{state:'idle'}}};
(async()=>{
  await doorbell.mount(host,hass);
  assert.equal(routeLoads,1,'the Lovelace panel bundle is loaded from the custom panel');
  assert.equal(panelFetches,1,'a Lovelace panel initializes loadCardHelpers in panel_custom');
  assert.equal(helperCalls,1,'the canonical card helper creates the card');
  assert.equal(cardConfig.type,'picture-entity');
  assert.equal(cardConfig.entity,'camera.front_door_live_view');
  assert.equal(cardConfig.camera_view,'live');
  assert.equal(host.children.length,1);
  assert.equal(typeof host.children[0].then,'undefined','the resolved camera card element is mounted, not its Promise');
  assert.equal(host.children[0].hass,hass);
  const nextHass={states:{'camera.front_door_live_view':{state:'streaming'}}};
  await doorbell.mount(host,nextHass);
  assert.equal(host.children[0].hass,nextHass,'state updates reuse the native camera card');
  assert.equal(routeLoads,1,'the helper bootstrap runs only once');
  console.log('V28_PANEL_LOVELACE_CARD_HELPERS=PASS');
  console.log('V27_CAMERA_MODULE_ISOLATION=PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
