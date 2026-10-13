const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const here=__dirname;
const dev=fs.readFileSync(path.join(here,'lifeos-house-status-dev.js'),'utf8');
const devBell=fs.readFileSync(path.join(here,'lifeos-house-status-doorbell.js'),'utf8');
const loader=fs.readFileSync(path.join(here,'lifeos-house-status-dev-loader.js'),'utf8');
const live=fs.readFileSync(path.join(__dirname,'../../releases/house-status/live/lifeos-house-status-v28.js'),'utf8');
const deploy=fs.readFileSync(path.join(__dirname,'../../../scripts/lifeos-deploy-house-status-dev-dashboard.sh'),'utf8');
const liveWorkflow=fs.readFileSync(path.join(__dirname,'../../../.github/workflows/house-status-live-deploy.yml'),'utf8');
const liveDeploy=fs.readFileSync(path.join(__dirname,'../../../scripts/lifeos-deploy-house-status-dashboard.sh'),'utf8');
assert.match(dev,/customElements\.define\('lifeos-house-status-dev'/);
assert.match(dev,/type:'lifeos-house-status-dev'/);
assert.match(dev,/customElements\.define\('lifeos-house-status-dev-editor-v2'/);
assert.match(dev,/House Status DEV/);
assert.match(dev,/apiOrigin\.port='8110'/);
assert.match(dev,/new URL\('\/api\/energy\/rollups',apiOrigin\)/);
assert.match(dev,/fetch\(url,\{credentials:'omit',signal:this\._energyHistoryController\.signal\}\)/);
assert.match(dev,/this\._period=p;this\._energyHistory=\[\];this\._energyCoverage=null;this\.render\(\);this\._loadEnergyHistory\(\);/,'period selection must fetch selected-range history and discard prior totals');
assert.match(dev,/this\._energyHistoryRequestedKey===key/,'duplicate hass updates must not duplicate the active range request');
assert.match(dev,/this\._energyHistoryController\?\.abort\(\)/,'period changes must cancel an obsolete history request');
assert.match(dev,/if\(requestId!==this\._energyHistoryRequestId\)return;/,'late responses must not overwrite the selected period');
assert.match(dev,/Number\.isFinite\(reportedCoverage\)\?Math\.max\(0,Math\.min\(100,reportedCoverage\)\):0/,'coverage must come from the selected rollup response and stay bounded');
assert.match(dev,/domestic_import_kwh:Number\(o\.domestic_import_kwh\)\|\|0/);
assert.match(dev,/import_p_per_kwh:o\.import_p_per_kwh/);
assert.match(dev,/domestic_import_cost_gbp:o\.domestic_import_cost_gbp/);
assert.doesNotMatch(dev,/\/lifeos-energy-api\//);
assert.match(dev,/Doorbell DEV/);
assert.match(dev,/LifeOSHouseStatusDevModules/);
assert.doesNotMatch(dev,/LifeOSHouseStatusModules|lifeos-house-status-v28|lifeos-house-status-editor/);
assert.match(devBell,/camera\.front_door_live_view/);
assert.match(devBell,/camera_view:'live'/);
assert.match(loader,/Date\.now\(\)/);
assert.match(loader,/await import\(bundle\)/);
assert.ok(loader.trimStart().startsWith('const bundle='));
assert.ok(loader.includes('await import(bundle);'));
assert.ok(!loader.includes('(async()=>{'));
assert.ok(deploy.includes('--input-type=module --check < "$SOURCE_DIR/lifeos-house-status-dev-loader.js"'));
const haConfig=fs.readFileSync(path.join(__dirname,'../../../homelab/live/opt/stacks/homeassistant/config/configuration.yaml'),'utf8');
assert.ok(haConfig.includes('module_url: /local/house-status-dev/lifeos-house-status-dev-loader.js?v=dev-loader-3'));
assert.ok(deploy.includes("old_url='module_url: /local/house-status-dev/lifeos-house-status-dev-loader.js?v=dev-loader-2'"));
assert.ok(deploy.includes("new_url='module_url: /local/house-status-dev/lifeos-house-status-dev-loader.js?v=dev-loader-3'"));
assert.match(dev,/await import\('\/local\/house-status-dev\/lifeos-house-status-doorbell\.js\?dev='\+Date\.now\(\)\)/);
assert.match(devBell,/LifeOSHouseStatusDevModules/);
assert.doesNotMatch(devBell,/LifeOSHouseStatusModules/);
assert.match(live,/customElements\.define\('lifeos-house-status-v28'/);
assert.match(deploy,/TARGET_DIR="\$HA\/www\/house-status-dev"/);
assert.doesNotMatch(deploy,/install[^\n]*\$PROD_DIR|DASH_TARGET=.*=/);
assert.match(deploy,/HOUSE_STATUS_DEV_LIVE_ISOLATION=PASS/);
assert.doesNotMatch(liveWorkflow,/^  push:/m,'production deploy is not triggered by ordinary pushes');
assert.match(liveDeploy,/RELEASE_DIR=.*releases/);
(async()=>{
  class FakeElement {
    constructor(){this.dataset={};this.onclick=null;}
  }
  class FakeCardElement {
    constructor(){this.dataset={};this._html='';this.periodButtons=[];}
    set innerHTML(value){this._html=value;}
    get innerHTML(){return this._html;}
    querySelectorAll(selector){
      if(selector==='[data-period]'){
        this.periodButtons=[...this._html.matchAll(/data-period="([^"]+)"/g)].map(match=>{
          const element=new FakeElement();element.dataset.period=match[1];return element;
        });
        return this.periodButtons;
      }
      return [];
    }
    querySelector(){return null;}
  }
  const registry=new Map(),requests=[];
  const periodCoverage=[100,92.4,77.0,27.0];
  const periodUsage=[4.59,15.634,77.053,152.995];
  const context={
    HTMLElement:FakeCardElement,
    customElements:{get:name=>registry.get(name),define:(name,value)=>registry.set(name,value)},
    window:{location:{origin:'http://ha.local'},customCards:[]},
    document:{createElement:()=>new FakeElement()},
    URL,Date,Intl,AbortController,setTimeout,process,
    console:{warn(){},log(){},error:console.error},
    fetch:async input=>{
      const url=new URL(input);requests.push(url);
      const start=Number(url.searchParams.get('start'));
      const end=Number(url.searchParams.get('end'));
      const index=requests.length-1;
      return {ok:true,json:async()=>({
        timezone:'Europe/London',coverage_percent:periodCoverage[index]??0,
        points:[{timestamp:start,domestic_import_kwh:periodUsage[index]??0,
          grid_import_kwh:periodUsage[index]??0,grid_export_kwh:0,production_kwh:0,
          consumption_kwh:periodUsage[index]??0,import_p_per_kwh:24.5,
          import_price_available:true,domestic_import_cost_gbp:[1.09,3.86,16.96,34.82][index]??0,
          sample_count:30,sample_coverage_percent:92.4}],
        _requestedEnd:end
      })};
    }
  };
  vm.runInNewContext(dev.replace(/^await import\([^\n]+\);\n/,''),context);
  const Card=registry.get('lifeos-house-status-dev');
  const card=new Card();
  const anchor=new Date();anchor.setHours(12,0,0,0);
  card._anchor=anchor;card._mode='domestic';
  card.hass={states:{}};
  const pause=()=>new Promise(resolve=>setTimeout(resolve,0));
  await pause();
  assert.equal(requests.length,1,'initial view requests its one-day history');
  assert.match(card.innerHTML,/4\.59 kWh/);
  const select=async period=>{
    const button=card.periodButtons.find(item=>item.dataset.period===period);
    assert.ok(button,period+' tab exists');
    button.onclick();
    await pause();
    await pause();
  };
  await select('week');
  assert.equal(requests.length,2,'Week selection issues a fresh rollup request');
  assert.equal(requests[1].searchParams.get('granularity'),'30m');
  assert.ok(Number(requests[1].searchParams.get('end'))-Number(requests[1].searchParams.get('start'))>=6*86400);
  assert.match(card.innerHTML,/15\.63 kWh/,'Week uses its own response rows');
  await select('month');
  assert.equal(requests.length,3,'Month selection issues a fresh rollup request');
  assert.ok(Number(requests[2].searchParams.get('end'))-Number(requests[2].searchParams.get('start'))>=27*86400);
  assert.match(card.innerHTML,/77\.05 kWh/,'Month uses its own response rows');
  await select('year');
  assert.equal(requests.length,4,'Year selection issues a fresh rollup request');
  assert.equal(new Date(Number(requests[3].searchParams.get('start'))*1000).getMonth(),0);
  assert.match(card.innerHTML,/27\.0% · Partial history/,'Year shows API-reported partial coverage instead of stale 100%');
  assert.match(card.innerHTML,/24\.5p/,'historical Octopus price is plotted from the selected response');
  console.log('HOUSE_STATUS_DEV_PERIOD_SWITCH_RUNTIME_REGRESSION=PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});

console.log('HOUSE_STATUS_DEV_PERIOD_HISTORY_RELOAD=PASS');
console.log('HOUSE_STATUS_DEV_STALE_HISTORY_RESPONSE=PASS');
console.log('HOUSE_STATUS_DEV_HISTORY_COVERAGE=PASS');
console.log('HOUSE_STATUS_DEV_CUSTOM_ELEMENTS=PASS');
console.log('HOUSE_STATUS_DEV_CAMERA_NAMESPACE=PASS');
console.log('HOUSE_STATUS_DEV_DEPLOY_TARGET=PASS');
console.log('HOUSE_STATUS_LIVE_MANUAL_RELEASE_ONLY=PASS');
