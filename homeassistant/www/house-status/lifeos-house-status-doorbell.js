window.LifeOSHouseStatusModules=window.LifeOSHouseStatusModules||{};
window.LifeOSHouseStatusModules.doorbell={
  _objectUrl:null,
  _loading:false,
  render(hass){
    const cam=hass?.states?.['camera.front_door_live_view'];
    const ok=cam&&cam.state!=='unavailable'&&cam.state!=='unknown';
    if(!ok) return '<div class="panel"><div class="heading">Doorbell</div><div class="floor">CAMERA UNAVAILABLE</div></div>';
    const image=this._objectUrl
      ? '<div class="doorcam"><img src="'+this._objectUrl+'" alt="Front Door" style="display:block;width:100%;max-height:70vh;object-fit:contain;border-radius:10px"></div>'
      : '<div class="doorcam"><div class="floor">LOADING CAMERA IMAGE…</div></div>';
    if(!this._loading) this._load(hass);
    return '<div class="panel"><div class="heading">Doorbell</div>'+image+'</div>';
  },
  async _load(hass){
    this._loading=true;
    try{
      const response=await hass.callApi('GET','camera_proxy/camera.front_door_live_view');
      let blob;
      if(response instanceof Blob) blob=response;
      else if(response instanceof ArrayBuffer) blob=new Blob([response]);
      else if(typeof response==='string'){
        const bytes=Uint8Array.from(atob(response),c=>c.charCodeAt(0)); blob=new Blob([bytes],{type:'image/jpeg'});
      }
      if(blob&&blob.size){
        if(this._objectUrl) URL.revokeObjectURL(this._objectUrl);
        this._objectUrl=URL.createObjectURL(blob);
      }
    }catch(_e){ this._objectUrl=null; }
    finally{ this._loading=false; document.querySelector('lifeos-house-status-v25')?.render?.(); }
  }
};
