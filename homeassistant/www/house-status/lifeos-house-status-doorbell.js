window.LifeOSHouseStatusModules=window.LifeOSHouseStatusModules||{};
const nativeDoorbellPath='/house-status-native/doorbell';
window.LifeOSHouseStatusModules.doorbell={
  mount(host){
    if(!host) return;
    host.innerHTML='<div class="floor">Opening the native Doorbell view… <a href="/house-status-native/doorbell">Open Doorbell camera</a></div>';
    if(window.location.pathname!==nativeDoorbellPath){
      window.location.replace('/house-status-native/doorbell');
    }
  },
  render(){
    return '<div class="panel"><div class="heading">Doorbell</div><div class="floor"><a href="/house-status-native/doorbell">Open Doorbell camera</a></div></div>';
  }
};
