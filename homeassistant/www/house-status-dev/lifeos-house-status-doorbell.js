window.LifeOSHouseStatusDevModules=window.LifeOSHouseStatusDevModules||{};

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

async function loadCardHelpersWithRetry(){
  let lastError;
  for(let attempt=0;attempt<8;attempt++){
    if(typeof window.loadCardHelpers==='function'){
      try{
        const helpers=await window.loadCardHelpers();
        if(helpers?.createCardElement)return helpers;
        lastError=new Error('card_helpers_incomplete');
      }catch(error){
        lastError=error;
      }
    }else{
      lastError=new Error('card_helpers_unavailable');
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
  host.innerHTML='<div class="floor">Loading live camera…</div>';
  host.__lifeosCameraMount=(async()=>{
    try{
      const helpers=await loadCardHelpersWithRetry();
      const card=helpers.createCardElement(cameraConfig);
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
      console.error('LifeOS Doorbell DEV camera card failed to mount',error?.name||'Error');
    }finally{
      host.__lifeosCameraMount=null;
    }
  })();
  return host.__lifeosCameraMount;
}

window.LifeOSHouseStatusDevModules.doorbell={
  mount:mountCamera,
  render(){
    return '<div class="panel"><div class="heading">Doorbell</div><div class="doorcam" data-doorbell-card><div class="floor">Loading live camera…</div></div></div>';
  }
};
