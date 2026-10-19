const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const base=__dirname;
const sourcePath=process.env.HOUSE_STATUS_DEV_ASSET||path.join(base,'lifeos-house-status-dev.js');
const source=fs.readFileSync(sourcePath,'utf8').replace(/^await import\([^\n]+\);\n/,'');
assert.match(source,/if\(mode==='doorbell'\)\{[\s\S]*?return;\s*\}\s*const moduleOwner=/,'Doorbell returns through its dedicated shell path before Energy ownership or rendering');
assert.match(source,/const mode=this\._mode\|\|this\.config\?\.mode\|\|'domestic'; const host=this\._doorbellHost; if\(mode==='doorbell'&&host\?\.isConnected\)\{try\{host\.hass=hass/,'Doorbell mode is resolved from config and forwarded to its isolated element before Energy');

class FakeElement{constructor(){this.dataset={};this.isConnected=true;this.onclick=null;this.onkeydown=null;this.children=[];}set hass(value){this._hass=value;if(this.__lifeosCameraCard)this.__lifeosCameraCard.hass=value;}get hass(){return this._hass;}replaceChildren(...items){this.children=items;}}
class FakeCard extends FakeElement{constructor(){super();this._html='';this.doorbellHost=new FakeElement();this.menu=new FakeElement();this.modeButtons=['domestic','flow','home','doorbell'].map(mode=>{const item=new FakeElement();item.dataset.mode=mode;return item;});}
set innerHTML(value){this._html=value;}get innerHTML(){return this._html;}
querySelector(selector){if(selector==='[data-lifeos-doorbell-camera]')return this.doorbellHost;if(selector==='.hamb')return this.menu;return null;}
querySelectorAll(selector){if(selector==='[data-mode]')return this.modeButtons;return [];}}

(async()=>{
  const registry=new Map(),mountCalls=[],renderCalls=[];
  const camera={hass:null};
  const doorbell={render(hass){renderCalls.push(hass);return '<lifeos-doorbell-camera-dev data-lifeos-doorbell-camera>isolated camera host</lifeos-doorbell-camera-dev>';},mount(host,hass){mountCalls.push({host,hass});host.__lifeosCameraCard=camera;host.hass=hass;}};
  const states=new Proxy({}, {get(_target,key){throw new Error('Doorbell read unrelated HA state: '+String(key));}});
  class DoorbellBlockedEnergy{static owns(){throw new Error('Energy ownership code ran in Doorbell mode');}}
  const context={
    HTMLElement:FakeCard,
    customElements:{get:name=>registry.get(name),define:(name,value)=>registry.set(name,value)},
    window:{LifeOSHouseStatusDevModules:{doorbell},customCards:[],location:{origin:'http://ha.local'}},
    document:{createElement:()=>new FakeElement()},
    CustomEvent:class{constructor(type,options){this.type=type;this.options=options;}},
    LifeOSEnergyModule:DoorbellBlockedEnergy,
    URL,Date,Intl,AbortController,setTimeout,clearTimeout,fetch(){throw new Error('Energy fetch ran in Doorbell mode');},
    console:{warn(){},log(){},error:console.error},process
  };
  // Force the lexical Energy owner to fail too; Doorbell must return before it is consulted.
  const hardenedSource=source.replace('class LifeOSEnergyModule {','class LifeOSEnergyModule { static owns(){ throw new Error(\'Energy owner must not run for Doorbell\'); }');
  vm.runInNewContext(hardenedSource,context,{filename:sourcePath});
  const Card=registry.get('lifeos-house-status-dev');assert.equal(typeof Card,'function','shared card registration remains available');
  const card=new Card();card.setConfig({mode:'doorbell'});
  const hass={states};card.hass=hass;
  assert.equal(card.dataset.module,'doorbell');
  assert.ok(card.innerHTML.includes('data-lifeos-doorbell-camera'));
  assert.equal(renderCalls.length,1);assert.equal(renderCalls[0],hass);
  assert.equal(mountCalls.length,1);assert.equal(mountCalls[0].hass,hass);
  assert.equal(card.doorbellHost.hass,hass);
  card.hass={states};
  assert.equal(renderCalls.length,1,'HA updates do not rerender the shared Energy shell');
  assert.equal(mountCalls.length,1,'HA updates do not recreate the Doorbell card');
  assert.equal(card.doorbellHost.hass,card._hass,'the isolated Doorbell element receives each current HA state');
  assert.equal(camera.hass,card._hass,'HA updates reach the mounted camera card directly');
  console.log('HOUSE_STATUS_DOORBELL_SHARED_SHELL_ISOLATION=PASS');
  console.log('HOUSE_STATUS_DOORBELL_NO_ENERGY_STATE_OR_FETCH=PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
