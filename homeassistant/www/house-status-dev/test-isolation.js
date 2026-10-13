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
assert.doesNotMatch(dev,/if\(this\.period\(\)==='today'\)this\._period='day'/,'date picking must preserve Today rather than silently changing tabs');
assert.match(dev,/if\(period==='day'\)start\.setDate\(start\.getDate\(\)-1\)/,'Day fetch includes the prior calendar day');
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
  const registry=new Map();
    const requests=[];
  let holdNextDayResponse=false,heldDayResponse=null;
  const context={
    HTMLElement:FakeCardElement,
    customElements:{get:name=>registry.get(name),define:(name,value)=>registry.set(name,value)},
    window:{location:{origin:'http://ha.local'},customCards:[]},
    document:{createElement:()=>new FakeElement()},
    URL,Date,Intl,AbortController,setTimeout,process,
    console:{warn(){},log(){},error:console.error},
    fetch:input=>{
      const url=new URL(input);requests.push(url);
      const start=Number(url.searchParams.get('start'));
      const end=Number(url.searchParams.get('end'));
      const hours=(end-start)/3600;
      if(holdNextDayResponse&&hours>30&&hours<60){
        holdNextDayResponse=false;
        return new Promise(resolve=>{heldDayResponse=()=>resolve(makeResponse(start,end,99.99,9.99,100));});
      }
      return Promise.resolve(makeResponse(start,end));
    }
  };
  function makeResponse(start,end,override,overrideCost,overrideCoverage){
    const hours=(end-start)/3600;
    let rows,coverage;
    if(override!==undefined){
      rows=[{timestamp:start,usage:override,cost:overrideCost,price:49.9}];coverage=overrideCoverage;
    }else if(hours>30&&hours<60){
      rows=[{timestamp:start,usage:1.59,cost:.40,price:10.5},{timestamp:start+86400,usage:4.59,cost:1.09,price:24.5}];coverage=100;
    }else if(hours<30){
      rows=[{timestamp:start,usage:4.59,cost:1.09,price:24.5}];coverage=100;
    }else if(hours<200){
      rows=[{timestamp:start,usage:15.634,cost:3.86,price:24.5}];coverage=92.4;
    }else if(hours<1500){
      rows=[{timestamp:start,usage:77.053,cost:16.96,price:24.5}];coverage=77;
    }else{
      rows=[{timestamp:start,usage:152.995,cost:34.82,price:24.5}];coverage=27;
    }
    return {ok:true,json:async()=>({timezone:'Europe/London',coverage_percent:coverage,points:rows.map(r=>({
      timestamp:r.timestamp,domestic_import_kwh:r.usage,grid_import_kwh:r.usage,grid_export_kwh:0,
      production_kwh:0,consumption_kwh:r.usage,import_p_per_kwh:r.price,
      import_price_available:true,domestic_import_cost_gbp:r.cost,sample_count:30,
      sample_coverage_percent:coverage
    }))})};
  }
  vm.runInNewContext(dev.replace(/^await import\([^\n]+\);\n/,''),context);
  const Card=registry.get('lifeos-house-status-dev');
  const card=new Card();
  const anchor=new Date();anchor.setHours(12,0,0,0);anchor.setDate(anchor.getDate()-2);
  const selectedDay=new Date(anchor);selectedDay.setHours(0,0,0,0);
  const previousDay=new Date(selectedDay);previousDay.setDate(previousDay.getDate()-1);
  const nextDay=new Date(selectedDay);nextDay.setDate(nextDay.getDate()+1);
  card._anchor=anchor;card._mode='domestic';
  card.hass={states:{}};
  const pause=()=>new Promise(resolve=>setTimeout(resolve,0));
  await pause();await pause();
  assert.equal(requests.length,1,'initial Today view requests its selected calendar day');
  assert.equal(Number(requests[0].searchParams.get('start')),Math.floor(selectedDay.getTime()/1000),'Today request starts at selected-day midnight');
  assert.equal(Number(requests[0].searchParams.get('end')),Math.floor(nextDay.getTime()/1000),'Today request ends at next midnight');
  assert.match(card.innerHTML,/4\.59 kWh/,'Today uses only its selected day total');
  assert.match(card.innerHTML,/Octopus price \(p\/kWh\)/,'Today chart labels the price axis');
  assert.match(card.innerHTML,/class="price" d="M/,'Today chart renders the Octopus price series');
  assert.match(card.innerHTML,/class="use" d="M/,'Today chart renders the Enphase cost series');
  const select=async period=>{const button=card.periodButtons.find(item=>item.dataset.period===period);assert.ok(button,period+' tab exists');button.onclick();await pause();await pause();};
  await select('day');
  assert.equal(requests.length,2,'Day selection fetches its own rollup window');
  assert.equal(Number(requests[1].searchParams.get('start')),Math.floor(previousDay.getTime()/1000),'Day request starts at previous calendar-day midnight');
  assert.equal(Number(requests[1].searchParams.get('end')),Math.floor(nextDay.getTime()/1000),'Day request ends after the selected calendar day');
  assert.equal(Number(requests[1].searchParams.get('end'))-Number(requests[1].searchParams.get('start')),Math.floor((nextDay-previousDay)/1000),'Day request spans two local calendar days');
  assert.match(card.innerHTML,/6\.18 kWh/,'Day totals both days in its rolling history');
  assert.match(card.innerHTML,/1\.49/,'Day cost sums both days');
  assert.match(card.innerHTML,/Available history 100\.0%/,'Day shows coverage for its own 48-hour response');
  assert.ok(card.innerHTML.includes(previousDay.toLocaleDateString('en-GB',{weekday:'short',day:'2-digit',month:'short'})),'Day chart labels the previous calendar day');
  const todayButton=card.periodButtons.find(item=>item.dataset.period==='today');assert.ok(todayButton);todayButton.onclick();await pause();await pause();
  assert.equal(requests.length,3,'switching back to Today fetches its 24-hour response');
  assert.match(card.innerHTML,/4\.59 kWh/,'switching back replaces the 48-hour total');
  holdNextDayResponse=true;
  const delayedDay=card.periodButtons.find(item=>item.dataset.period==='day');delayedDay.onclick();await pause();
  assert.equal(requests.length,4,'rapid-switch scenario starts a Day request');
  const latestToday=card.periodButtons.find(item=>item.dataset.period==='today');latestToday.onclick();await pause();await pause();
  assert.equal(requests.length,5,'rapid switch starts a new Today request');
  heldDayResponse();await pause();await pause();
  assert.match(card.innerHTML,/4\.59 kWh/,'late Day response cannot overwrite the currently selected Today data');
  assert.doesNotMatch(card.innerHTML,/99\.99 kWh/,'stale-response sentinel is never shown');
  await select('week');
  assert.equal(requests.length,6,'Week selection issues a fresh rollup request');
  assert.equal(requests[5].searchParams.get('granularity'),'30m');
  const weekStart=new Date(Number(requests[5].searchParams.get('start'))*1000);
  assert.equal(weekStart.getDay(),1,'Week request starts Monday at local midnight');
  assert.ok(Number(requests[5].searchParams.get('end'))>Number(requests[5].searchParams.get('start')));
  assert.ok(Number(requests[5].searchParams.get('end'))-Number(requests[5].searchParams.get('start'))<=7*86400);
  assert.match(card.innerHTML,/15\.63 kWh/,'Week uses its own response rows');
  await select('month');
  assert.equal(requests.length,7,'Month selection issues a fresh rollup request');
  const monthStart=new Date(Number(requests[6].searchParams.get('start'))*1000);
  assert.equal(monthStart.getDate(),1,'Month request starts on day one');
  assert.ok(Number(requests[6].searchParams.get('end'))>Number(requests[6].searchParams.get('start')));
  assert.match(card.innerHTML,/77\.05 kWh/,'Month uses its own response rows');
  await select('year');
  assert.equal(requests.length,8,'Year selection issues a fresh rollup request');
  assert.equal(new Date(Number(requests[7].searchParams.get('start'))*1000).getMonth(),0);
  assert.match(card.innerHTML,/27\.0% · Partial history/,'Year shows API-reported partial coverage instead of stale 100%');
  assert.match(card.innerHTML,/class="price" d="M/,'historical Octopus price is plotted from the selected response');
  console.log('HOUSE_STATUS_DEV_TODAY_DAY_WINDOWS=PASS');
  console.log('HOUSE_STATUS_DEV_TODAY_DAY_SWITCH_RUNTIME_REGRESSION=PASS');
  console.log('HOUSE_STATUS_DEV_STALE_DAY_RESPONSE=PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});

console.log('HOUSE_STATUS_DEV_PERIOD_HISTORY_RELOAD=PASS');
console.log('HOUSE_STATUS_DEV_STALE_HISTORY_RESPONSE=PASS');
console.log('HOUSE_STATUS_DEV_HISTORY_COVERAGE=PASS');
console.log('HOUSE_STATUS_DEV_CUSTOM_ELEMENTS=PASS');
console.log('HOUSE_STATUS_DEV_CAMERA_NAMESPACE=PASS');
console.log('HOUSE_STATUS_DEV_DEPLOY_TARGET=PASS');
console.log('HOUSE_STATUS_LIVE_MANUAL_RELEASE_ONLY=PASS');
