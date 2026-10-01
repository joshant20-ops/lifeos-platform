window.LifeOSHouseStatusModules=window.LifeOSHouseStatusModules||{};
window.LifeOSHouseStatusModules.doorbell={
  render(hass){
    const cam=hass?.states?.['camera.front_door_live_view'];
    const ok=cam&&cam.state!=='unavailable'&&cam.state!=='unknown';
    const src='/api/camera_proxy/camera.front_door_live_view?token='+encodeURIComponent(cam?.attributes?.access_token||'')+'&ts='+Date.now();
    return '<div class="panel"><div class="heading">Doorbell</div>'+(ok?'<div class="doorcam"><img data-doorbell-image src="'+src+'" alt="Front Door" style="display:block;width:100%;max-height:70vh;object-fit:contain;border-radius:10px" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'block\'"><div class="floor" style="display:none">CAMERA IMAGE UNAVAILABLE</div></div>':'<div class="floor">CAMERA UNAVAILABLE</div>')+'</div>';
  }
};
