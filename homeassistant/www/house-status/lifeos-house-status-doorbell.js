window.LifeOSHouseStatusModules=window.LifeOSHouseStatusModules||{};
const nativeDoorbellPath='/house-status-native/doorbell';
window.LifeOSHouseStatusModules.doorbell={
  mount(host){
    // Redirect before checking host: the custom shell currently calls mount with
    // [data-doorbell-card], which is absent from this native-view handoff.
    if(window.location.pathname!==nativeDoorbellPath){
      window.location.replace(nativeDoorbellPath);
      return;
    }
    if(!host) return;
    host.innerHTML='<div class="floor">Opening the native Doorbell view… <a href="/house-status-native/doorbell">Open Doorbell camera</a></div>';
  },
  render(){
    return '<div class="panel"><div class="heading">Doorbell</div><div class="floor"><a href="/house-status-native/doorbell">Open Doorbell camera</a></div></div>';
  }
};
