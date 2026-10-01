window.LifeOSHouseStatusModules=window.LifeOSHouseStatusModules||{};
window.LifeOSHouseStatusModules.doorbell={
  async mount(host,hass){
    if(!host||!hass) return;
    try{
      if(typeof window.loadCardHelpers!=='function') throw new Error('Home Assistant card helpers unavailable');
      const helpers=await window.loadCardHelpers();
      const picture=await helpers.createCardElement({
        type:'picture-entity',
        entity:'camera.front_door_live_view',
        name:'Front Door',
        camera_view:'live',
        show_name:true,
        show_state:true,
        tap_action:{action:'none'},
        hold_action:{action:'none'}
      });
      picture.hass=hass;
      host.replaceChildren(picture);
    }catch(e){
      host.innerHTML='<div class="floor">CAMERA CARD ERROR</div>';
      console.error('House Status Doorbell native card mount failed',e);
    }
  },
  render(){
    return '<div class="panel"><div class="heading">Doorbell</div><div class="doorcam" data-doorbell-card></div></div>';
  }
};
