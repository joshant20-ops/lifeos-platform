const assert = require('node:assert/strict');

global.window = {
  location: {
    pathname: '/house-status',
    redirectedTo: null,
    replace(path) { this.redirectedTo = path; }
  }
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
  'do not redirect again after reaching the native Doorbell view'
);

console.log('DOORBELL_NULL_HOST_HANDOFF=PASS');
console.log('DOORBELL_NATIVE_ROUTE_IDEMPOTENT=PASS');
