const assert = require('node:assert/strict');

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

console.log('DOORBELL_NULL_HOST_HANDOFF=PASS');
console.log('DOORBELL_NATIVE_ROUTE_IDEMPOTENT=PASS');
console.log('DOORBELL_FULL_DOCUMENT_HANDOFF=PASS');
console.log('DOORBELL_OTHER_ROUTES_UNCHANGED=PASS');
