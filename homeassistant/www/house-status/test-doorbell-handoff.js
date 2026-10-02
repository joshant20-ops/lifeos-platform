const assert = require('node:assert/strict');

const listeners = {};
global.document = {
  shellCards: [],
  querySelectorAll() { return this.shellCards; }
};
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
  'do not redirect again after reaching the native Doorbell view'
);

// The shell can push the target URL without actually replacing its own view.
// The fallback should reload only while a House Status card is still mounted.
document.shellCards = [{
  localName: 'hui-card',
  shadowRoot: {
    querySelectorAll() {
      return [{ localName: 'lifeos-house-status-v28', shadowRoot: null }];
    }
  }
}];
listeners['location-changed']();
assert.equal(
  window.location.redirectedTo,
  '/house-status-native/doorbell',
  'force native navigation if the custom shell remains after route change'
);

// A direct native Lovelace view has no mounted House Status card, so it stays put.
document.shellCards = [];
window.location.redirectedTo = null;
listeners['location-changed']();
assert.equal(
  window.location.redirectedTo,
  null,
  'do not reload the native Doorbell view after successful navigation'
);

console.log('DOORBELL_NULL_HOST_HANDOFF=PASS');
console.log('DOORBELL_NATIVE_ROUTE_IDEMPOTENT=PASS');
console.log('DOORBELL_SHELL_ROUTE_FALLBACK=PASS');
