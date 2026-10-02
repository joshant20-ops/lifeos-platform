const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const listeners = {};
global.window = {
  location: {
    pathname: '/house-status',
    redirectedTo: null,
    replace(path) { this.redirectedTo = path; }
  },
  addEventListener(name, callback) { listeners[name] = callback; }
};

require('./lifeos-house-status-doorbell.js');
const doorbell = window.LifeOSHouseStatusModules.doorbell;

doorbell.mount(null);
assert.equal(
  window.location.redirectedTo,
  '/house-status-native/doorbell',
  'redirect must run even when the custom shell passes a null host'
);

assert.match(doorbell.render(), /href="\/house-status-native\/doorbell"/);

window.location.pathname = '/house-status-native/doorbell';
window.location.redirectedTo = null;
doorbell.mount(null);
assert.equal(
  window.location.redirectedTo,
  null,
  'mount must leave the native route alone'
);

// The location-changed event is dispatched by the custom panel after its
// history.pushState transition. The panel may be hidden behind a closed shadow
// root, so navigation must not depend on discovering its DOM element.
listeners['location-changed']();
assert.equal(
  window.location.redirectedTo,
  '/house-status-native/doorbell',
  'promote the custom panel route change to a full document navigation'
);

// The handler is inert on every route except the native Doorbell target.
window.location.pathname = '/house-status';
window.location.redirectedTo = null;
listeners['location-changed']();
assert.equal(
  window.location.redirectedTo,
  null,
  'leave non-Doorbell routes unchanged'
);

const cardPath=path.join(__dirname,'lifeos-house-status-card.js');
const legacyPath=path.join(__dirname,'lifeos-house-status-v27.js');
const currentCard=fs.readFileSync(cardPath,'utf8');
const legacyCard=fs.readFileSync(legacyPath,'utf8');
const oldDoorbellHandler="this.querySelectorAll('[data-mode]').forEach(el=>el.onclick=()=>{this._mode=el.dataset.mode;this.render();});";
const fullNavigationHandler="this.querySelectorAll('[data-mode]').forEach(el=>el.onclick=()=>{if(el.dataset.mode==='doorbell'){window.location.assign('/house-status-native/doorbell');return;}this._mode=el.dataset.mode;this.render();});";
assert.ok(legacyCard.includes(fullNavigationHandler),'legacy v27 Doorbell uses a full native-page navigation');
const normalizedLegacy=legacyCard
  .replace('Doorbell v27','Doorbell v28')
  .replace(fullNavigationHandler,currentCard.match(/this\.querySelectorAll\('\[data-mode\]'\)[^\n]+/)[0])
  .replaceAll('lifeos-house-status-v27','lifeos-house-status-v28');
assert.equal(normalizedLegacy,currentCard,'v27 compatibility keeps the current Energy and House shell code');
console.log('DOORBELL_V27_FULL_NAVIGATION=PASS');
console.log('DOORBELL_V27_ENERGY_HOUSE_PRESERVED=PASS');

console.log('DOORBELL_NULL_HOST_HANDOFF=PASS');
console.log('DOORBELL_NATIVE_ROUTE_IDEMPOTENT=PASS');
console.log('DOORBELL_FULL_DOCUMENT_HANDOFF=PASS');
console.log('DOORBELL_OTHER_ROUTES_UNCHANGED=PASS');
