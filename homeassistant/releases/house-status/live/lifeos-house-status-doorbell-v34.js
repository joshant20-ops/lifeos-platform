const doorbellModules=window.LifeOSHouseStatusModules=window.LifeOSHouseStatusModules||{};

const cameraConfig={
  type:'picture-entity',
  entity:'camera.front_door_live_view',
  name:'Front Door',
  camera_view:'live',
  show_name:true,
  show_state:true,
  tap_action:{action:'none'},
  hold_action:{action:'none'}
};

async function bootstrapLovelaceCardHelpers(hass){
  if(typeof window.loadCardHelpers==='function')return;
  if(!window.__lifeosDoorbellLovelaceHelpers){
    window.__lifeosDoorbellLovelaceHelpers=(async()=>{
      await customElements.whenDefined('partial-panel-resolver');
      const resolver=document.createElement('partial-panel-resolver');
      if(typeof resolver._getRoutes!=='function')throw new Error('lovelace_route_loader_unavailable');
      const routeName='lifeos-doorbell-helper';
      const routes=resolver._getRoutes([{component_name:'lovelace',url_path:routeName}]);
      const loadPanel=routes?.routes?.[routeName]?.load;
      if(typeof loadPanel!=='function')throw new Error('lovelace_panel_route_unavailable');
      await loadPanel();
      await customElements.whenDefined('ha-panel-lovelace');
      const panel=document.createElement('ha-panel-lovelace');
      panel.hass=hass;
      panel.panel={config:{mode:'yaml'}};
      if(typeof panel._fetchConfig!=='function')throw new Error('lovelace_panel_config_loader_unavailable');
      await panel._fetchConfig(false);
      if(typeof window.loadCardHelpers!=='function')throw new Error('card_helpers_not_registered');
    })().finally(()=>{window.__lifeosDoorbellLovelaceHelpers=null;});
  }
  await window.__lifeosDoorbellLovelaceHelpers;
}

async function loadCardHelpersWithRetry(hass){
  let lastError;
  for(let attempt=0;attempt<8;attempt++){
    try{
      if(typeof window.loadCardHelpers!=='function')await bootstrapLovelaceCardHelpers(hass);
      const helpers=await window.loadCardHelpers();
      if(helpers?.createCardElement)return helpers;
      lastError=new Error('card_helpers_incomplete');
    }catch(error){
      lastError=error;
    }
    if(attempt<7)await new Promise(resolve=>setTimeout(resolve,250));
  }
  throw lastError||new Error('card_helpers_unavailable');
}

async function mountCamera(host,hass){
  if(!host)return;
  host.__lifeosDoorbellHass=hass;
  if(host.__lifeosCameraCard){
    host.__lifeosCameraCard.hass=hass;
    return;
  }
  if(host.__lifeosCameraMount)return host.__lifeosCameraMount;
  host.innerHTML='<div class="loading">Loading live camera…</div>';
  host.__lifeosCameraMount=(async()=>{
    try{
      const helpers=await loadCardHelpersWithRetry(host.__lifeosDoorbellHass||hass);
      const card=await helpers.createCardElement(cameraConfig);
      if(!card)throw new Error('picture_entity_card_unavailable');
      card.hass=host.__lifeosDoorbellHass||hass;
      if(!host.isConnected)return;
      host.replaceChildren(card);
      host.__lifeosCameraCard=card;
    }catch(error){
      host.__lifeosCameraCard=null;
      if(!host.isConnected)return;
      const fallback=document.createElement('div');
      fallback.className='error';
      fallback.textContent='Camera view could not load';
      const code=(typeof error?.message==='string'&&/^[a-z0-9_]+$/.test(error.message))?error.message:(error?.name||'unknown');
      fallback.dataset.errorCode=code;
      host.replaceChildren(fallback);
      console.error('LifeOS Doorbell v34 camera card failed to mount',code);
    }finally{
      host.__lifeosCameraMount=null;
    }
  })();
  return host.__lifeosCameraMount;
}

class LifeOSDoorbellCamera extends HTMLElement{
  constructor(){
    super();
    const root=this.attachShadow({mode:'open'});
    root.innerHTML=`<style>
      :host{display:block;min-width:0}
      .panel{border:1px solid #163747;border-radius:10px;background:rgba(6,25,35,.82);padding:12px;margin-top:10px;color:#f4f7f9;font-family:Arial,sans-serif}
      .heading{font-size:20px;font-weight:750}
      .doorcam{margin-top:10px;overflow:hidden;border-radius:10px}
      .doorcam > *{display:block}
      .loading,.error{min-height:320px;display:flex;align-items:center;justify-content:center;border:1px dashed #31566a;border-radius:8px;color:#b8c6ce;background:#071923}
      @media(max-width:850px){.loading,.error{min-height:240px}}
    </style><section class="panel"><div class="heading">Doorbell</div><div class="doorcam"><div class="loading">Loading live camera…</div></div></section>`;
    this.__lifeosCameraHost=root.querySelector('.doorcam');
  }
  set hass(hass){
    this._hass=hass;
    if(this.__lifeosCameraHost){
      this.__lifeosCameraHost.__lifeosDoorbellHass=hass;
      if(this.__lifeosCameraHost.__lifeosCameraCard){
        try{this.__lifeosCameraHost.__lifeosCameraCard.hass=hass;}
        catch(error){console.warn('LifeOS Doorbell camera update failed',error);}
      }else{
        mountCamera(this.__lifeosCameraHost,hass);
      }
    }
  }
  get hass(){return this._hass;}
}
window.LifeOSHouseStatusModules.doorbellV34={
  mount(host,hass){
    if(host&&'hass' in host){host.hass=hass;return host.__lifeosCameraHost?.__lifeosCameraMount;}
    return mountCamera(host,hass);
  },
  render(){return '<'+doorbellElementName+' data-lifeos-doorbell-camera></'+doorbellElementName+'>';}
};
const registeredDoorbellKey=doorbellModules.doorbell?'doorbell':Object.keys(doorbellModules).filter(key=>/^doorbellV\d+$/.test(key)).at(-1);
if(!registeredDoorbellKey)throw new Error('doorbell_module_identity_unavailable');
const doorbellElementName='lifeos-doorbell-camera-'+(registeredDoorbellKey==='doorbell'?'dev':registeredDoorbellKey.slice(8).toLowerCase());
if(!customElements.get(doorbellElementName))customElements.define(doorbellElementName,LifeOSDoorbellCamera);
