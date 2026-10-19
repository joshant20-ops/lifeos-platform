const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const base=__dirname;
const sourcePath=process.env.HOUSE_STATUS_DOORBELL_ASSET||path.join(base,'lifeos-house-status-doorbell.js');
const source=fs.readFileSync(sourcePath,'utf8');
const app=fs.readFileSync(path.join(base,'lifeos-house-status-dev.js'),'utf8');
assert.doesNotMatch(source,/LifeOSEnergyModule|LifeOSHouseStatusCard|lifeos-house-status-dev\.js/,'Doorbell source has no Energy implementation dependency');
assert.match(app,/await import\('\/local\/house-status-dev\/lifeos-house-status-doorbell\.js\?dev='\+Date\.now\(\)\);/,'the app awaits its separate Doorbell module before registration');
assert.match(app,/host\.hass=hass/,'HA state updates are delivered to the isolated Doorbell element');

function environment({failCreate=false}={}){
  const window={};
  let routeLoads=0,panelFetches=0,helperCalls=0,createCalls=0,cardConfig=null,releaseCreate;
  const registry=new Map();
  class FakeCameraHost{constructor(){this.isConnected=true;this.innerHTML='';this.children=[];}replaceChildren(...items){this.children=items;}}
  class FakeHTMLElement{constructor(){this.isConnected=true;this.__cameraHost=new FakeCameraHost();}attachShadow(options){assert.equal(options.mode,'open');const host=this.__cameraHost;this.shadowRoot={_html:'',set innerHTML(value){this._html=value;},get innerHTML(){return this._html;},querySelector(selector){assert.equal(selector,'.doorcam');return host;}};return this.shadowRoot;}}
  const customElements={get(name){return registry.get(name);},define(name,value){registry.set(name,value);},async whenDefined(name){assert.ok(['partial-panel-resolver','ha-panel-lovelace'].includes(name),name);}};
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
        return {async createCardElement(config){
          createCalls++;cardConfig=config;
          if(failCreate)throw new Error('camera_card_create_failed');
          await new Promise(resolve=>{releaseCreate=resolve;});
          return {hass:null};
        }};
      };
    }};
    return {className:'',textContent:'',dataset:{}};
  }};
  const context={window,document,customElements,HTMLElement:FakeHTMLElement,setTimeout,console:{error(){}}};
  vm.runInNewContext(source,context,{filename:sourcePath});
  return {window,document,customElements,registry,get routeLoads(){return routeLoads;},get panelFetches(){return panelFetches;},get helperCalls(){return helperCalls;},get createCalls(){return createCalls;},get cardConfig(){return cardConfig;},release(){releaseCreate();}};
}

(async()=>{
  const env=environment();
  assert.equal(env.window.loadCardHelpers,undefined,'cold custom-panel start has no prior Lovelace helper');
  assert.equal(env.window.LifeOSEnergyModule,undefined,'Energy has not loaded or initialized');
  const doorbell=env.window.LifeOSHouseStatusDevModules?.doorbell;
  assert.equal(typeof doorbell?.render,'function','Doorbell module registration succeeds without Energy');
  assert.equal(typeof doorbell?.mount,'function');
  assert.match(doorbell.render(),/data-lifeos-doorbell-camera/,'Doorbell renders its independently registered element');
  const CameraElement=env.registry.get('lifeos-doorbell-camera-dev');
  assert.equal(typeof CameraElement,'function','Doorbell registers its own custom element without Energy');
  const host=new CameraElement();
  assert.match(host.shadowRoot.innerHTML,/<style>/,'Doorbell styles live inside its own Shadow DOM');
  assert.match(host.shadowRoot.innerHTML,/class="doorcam"/,'camera mount point is encapsulated inside the Doorbell element');
  const hass={states:{'camera.front_door_live_view':{state:'idle'}}};
  const mounting=doorbell.mount(host,hass);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(env.routeLoads,1,'Doorbell cold-start loads the Lovelace route');
  assert.equal(env.panelFetches,1,'Doorbell initializes card helpers in its own bootstrap');
  assert.equal(env.helperCalls,1);
  assert.equal(env.cardConfig.type,'picture-entity');
  assert.equal(env.cardConfig.entity,'camera.front_door_live_view');
  assert.equal(env.cardConfig.camera_view,'live');
  assert.equal(env.createCalls,1);
  assert.equal(host.__lifeosCameraHost.children.length,0,'the async card creation Promise is not mounted as an element');
  env.release();
  await mounting;
  assert.equal(host.__lifeosCameraHost.children.length,1);
  const card=host.__lifeosCameraHost.children[0];
  assert.equal(typeof card.then,'undefined');
  assert.equal(card.hass,hass,'the current HA camera state is assigned before mount');
  const updatedHass={states:{'camera.front_door_live_view':{state:'streaming'}}};
  await doorbell.mount(host,updatedHass);
  assert.equal(host.__lifeosCameraHost.children[0],card,'HA updates reuse the mounted native camera card');
  assert.equal(card.hass,updatedHass);
  assert.equal(env.routeLoads,1);
  assert.equal(env.createCalls,1);

  const failed=environment({failCreate:true});
  const failedHost={isConnected:true,innerHTML:'',children:[],replaceChildren(...items){this.children=items;}};
  await failed.window.LifeOSHouseStatusDevModules.doorbell.mount(failedHost,hass);
  assert.equal(failedHost.children[0].textContent,'Camera view could not load');
  assert.equal(failedHost.children[0].dataset.errorCode,'camera_card_create_failed');
  assert.equal(failed.window.LifeOSEnergyModule,undefined,'camera failure stays inside Doorbell');
  assert.equal(failed.window.LifeOSHouseStatusDevModules.doorbell!==undefined,true);
  console.log('HOUSE_STATUS_DOORBELL_SHADOW_DOM_ISOLATION=PASS');
  console.log('HOUSE_STATUS_DOORBELL_COLD_BOOTSTRAP=PASS');
  console.log('HOUSE_STATUS_DOORBELL_CARD_REGISTRATION=PASS');
  console.log('HOUSE_STATUS_DOORBELL_ASYNC_CARD_STATE_UPDATE=PASS');
  console.log('HOUSE_STATUS_DOORBELL_FAILURE_ISOLATION=PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
