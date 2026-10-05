window.LifeOSHouseStatusModules=window.LifeOSHouseStatusModules||{};
const cameraConfig={type:'picture-entity',entity:'camera.front_door_live_view',name:'Front Door',camera_view:'live',show_name:true,show_state:true,tap_action:{action:'none'},hold_action:{action:'none'}};
async function bootstrapLovelaceCardHelpers(hass){
  if(typeof window.loadCardHelpers==='function')return;
  if(!window.__lifeosV28LovelaceHelpers){
    window.__lifeosV28LovelaceHelpers=(async()=>{
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
    })().finally(()=>{window.__lifeosV28LovelaceHelpers=null;});
  }
  await window.__lifeosV28LovelaceHelpers;
}
async function loadCardHelpersWithRetry(hass){
  let lastError;
  for(let attempt=0;attempt<8;attempt++){
    try{
      if(typeof window.loadCardHelpers!=='function')await bootstrapLovelaceCardHelpers(hass);
      const helpers=await window.loadCardHelpers();
      if(helpers?.createCardElement)return helpers;
      lastError=new Error('card_helpers_incomplete');
    }catch(error){lastError=error;}
    if(attempt<7)await new Promise(resolve=>setTimeout(resolve,250));
  }
  throw lastError||new Error('card_helpers_unavailable');
}
async function mountCamera(host,hass){
  if(!host)return;
  host.__lifeosDoorbellHass=hass;
  if(host.__lifeosCameraCard){host.__lifeosCameraCard.hass=hass;return;}
  if(host.__lifeosCameraMount)return host.__lifeosCameraMount;
  host.innerHTML='<div class="floor">Loading live camera…</div>';
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
      fallback.className='floor';
      fallback.textContent='Camera view could not load';
      host.replaceChildren(fallback);
      const code=(typeof error?.message==='string'&&/^[a-z0-9_]+$/.test(error.message))?error.message:(error?.name||'unknown');
      fallback.dataset.errorCode=code;
      console.error('LifeOS Doorbell v28 camera card failed to mount',code);
    }finally{host.__lifeosCameraMount=null;}
  })();
  return host.__lifeosCameraMount;
}
window.LifeOSHouseStatusModules.doorbellV28={mount:mountCamera,render(){return '<div class="panel"><div class="heading">Doorbell</div><div class="doorcam" data-doorbell-card><div class="floor">Loading live camera…</div></div></div>';}};
