window.LifeOSHouseStatusModules=window.LifeOSHouseStatusModules||{};
window.LifeOSHouseStatusModules.doorbell={
  mount(host,hass){
    const cam=hass?.states?.['camera.front_door_live_view'];
    if(!host) return;
    if(!cam||cam.state==='unavailable'||cam.state==='unknown'){
      host.innerHTML='<div class="floor">CAMERA UNAVAILABLE</div>';
      return;
    }
    try{
      const picture=document.createElement('hui-picture-entity-card');
      picture.setConfig({type:'picture-entity',entity:'camera.front_door_live_view',name:'Front Door',camera_view:'live',show_name:true,show_state:true,tap_action:{action:'none'},hold_action:{action:'none'}});
      picture.hass=hass;
      host.replaceChildren(picture);
    }catch(_e){
      host.innerHTML='<div class="floor">CAMERA UNAVAILABLE</div>';
    }
  },
  render(){
    return '<div class="panel"><div class="heading">Doorbell</div><div class="doorcam" data-doorbell-card></div></div>';
  }
};
