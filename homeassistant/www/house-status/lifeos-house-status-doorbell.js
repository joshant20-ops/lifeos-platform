window.LifeOSHouseStatusModules=window.LifeOSHouseStatusModules||{};
const nativeDoorbellPath='/house-status-native/doorbell';

// HA's location-changed event can leave the custom card mounted after the shell
// updates history. If that happens, force a full navigation to native Lovelace.
function houseStatusShellMounted(){
  const pending=[document];
  while(pending.length){
    const root=pending.pop();
    if(!root||typeof root.querySelectorAll!=='function') continue;
    for(const element of root.querySelectorAll('*')){
      if(/^lifeos-house-status-v\\d+$/.test(element.localName)) return true;
      if(element.shadowRoot) pending.push(element.shadowRoot);
    }
  }
  return false;
}
function enforceNativeDoorbellRoute(){
  if(window.location.pathname===nativeDoorbellPath&&houseStatusShellMounted()){
    window.location.replace(nativeDoorbellPath);
  }
}
window.addEventListener?.('location-changed',enforceNativeDoorbellRoute);

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
