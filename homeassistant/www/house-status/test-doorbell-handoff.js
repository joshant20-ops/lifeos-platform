const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const card = fs.readFileSync(path.join(__dirname, 'lifeos-house-status-card.js'), 'utf8');
const dashboard = JSON.parse(fs.readFileSync(path.join(__dirname, '../../house-status-dashboard.json'), 'utf8'));

assert.ok(
  card.includes("if(el.dataset.mode==='doorbell'){window.location.assign('/house-status-native/doorbell');return;}"),
  'the Doorbell tab must navigate directly to the native Lovelace route'
);
assert.doesNotMatch(card, /lifeos-house-status-doorbell|LifeOSHouseStatusModules|history\.pushState/,
  'the custom panel must not load a separate Doorbell renderer or SPA redirect shim');

const views = dashboard.data.config.views;
const doorbell = views.find(view => view.path === 'doorbell');
assert.ok(doorbell, 'the native Doorbell view must remain in the dashboard');
assert.equal(doorbell.type, 'panel');
assert.equal(doorbell.cards.length, 1, 'the native view must remain a single stock camera card');
assert.deepEqual(
  (({ type, entity, camera_view }) => ({ type, entity, camera_view }))(doorbell.cards[0]),
  { type: 'picture-entity', entity: 'camera.front_door_live_view', camera_view: 'live' }
);

console.log('DOORBELL_DIRECT_NATIVE_NAVIGATION=PASS');
console.log('DOORBELL_NATIVE_VIEW_CONFIG=PASS');
console.log('NOTE=Static routing/config checks only; browser image acceptance is not covered.');
