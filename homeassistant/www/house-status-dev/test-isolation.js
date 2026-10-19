const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const here=__dirname;
const dev=fs.readFileSync(process.env.HOUSE_STATUS_DEV_ASSET||path.join(here,'lifeos-house-status-dev.js'),'utf8');
const devBell=fs.readFileSync(path.join(here,'lifeos-house-status-doorbell.js'),'utf8');
const loader=fs.readFileSync(path.join(here,'lifeos-house-status-dev-loader.js'),'utf8');
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'../../releases/house-status/live/approved-release.json'),'utf8'));
const live=fs.readFileSync(path.join(__dirname,'../../releases/house-status/live/lifeos-house-status-v28.js'),'utf8');
const deploy=fs.readFileSync(path.join(__dirname,'../../../scripts/lifeos-deploy-house-status-dev-dashboard.sh'),'utf8');
const devWorkflow=fs.readFileSync(path.join(__dirname,'../../../.github/workflows/house-status-dev-deploy.yml'),'utf8');
const liveWorkflow=fs.readFileSync(path.join(__dirname,'../../../.github/workflows/house-status-live-deploy.yml'),'utf8');
const liveDeploy=fs.readFileSync(path.join(__dirname,'../../../scripts/lifeos-deploy-house-status-dashboard.sh'),'utf8');
assert.match(dev,/customElements\.define\('lifeos-house-status-dev'/);
assert.match(dev,/type:'lifeos-house-status-dev'/);
assert.match(dev,/customElements\.define\('lifeos-house-status-dev-editor-v2'/);
assert.match(dev,/House Status DEV/);
assert.match(dev,/apiOrigin\.port='8110'/);
assert.match(dev,/new URL\('\/api\/energy\/rollups',apiOrigin\)/);
assert.match(dev,/tomorrowTariffRows=isToday\?tariff\.filter/,'tomorrow extension is driven only by available Octopus tariff slots');
assert.match(dev,/t<\(isToday\?t1:t2\)/,'Today consumption series is clipped at midnight');
assert.match(dev,/data-midnight-boundary/,'Today and Tomorrow have an explicit midnight boundary');
assert.match(dev,/data-tomorrow-pricing/,'partial and unavailable future pricing is identified');
assert.match(dev,/fetch\(url,\{credentials:'omit',signal:this\._energyHistoryController\.signal\}\)/);
assert.match(dev,/this\._period=p;this\._energyHistory=\[\];this\._energyCoverage=null;this\.render\(\);this\._loadEnergyHistory\(\);/,'period selection must fetch selected-range history and discard prior totals');
assert.match(dev,/this\._energyHistoryRequestedKey===key/,'duplicate hass updates must not duplicate the active range request');
assert.doesNotMatch(dev,/if\(this\.period\(\)==='today'\)this\._period='day'/,'date picking must preserve Today rather than silently changing tabs');
assert.match(dev,/periodWindow\(\)\{return \[this\.periodStart\(\),this\.periodEnd\(\)\];\}/,'all paths share one selected-period window');
assert.match(dev,/if\(this\.period\(\)==='day'\)return this\.addLondonDays\(selected,-1\)/,'Day fetch includes the prior calendar day');
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
assert.ok(deploy.includes("['approved_production']['release']")&&deploy.includes("['previous_production_release']"),'DEV deployment protects only the approved Live or rollback release');
assert.ok(deploy.includes('protected_live_panel_registration_invalid'),'DEV deployment fails closed on an unexpected Live panel');
const haConfig=fs.readFileSync(path.join(__dirname,'../../../homelab/live/opt/stacks/homeassistant/config/configuration.yaml'),'utf8');
const allowedLiveReleases=[manifest.approved_production.release,manifest.previous_production_release];
assert.ok(allowedLiveReleases.some(release=>haConfig.includes('name: lifeos-house-status-'+release)),'canonical configuration registers the approved or rollback Live release');
assert.ok(haConfig.includes('module_url: /local/house-status-dev/lifeos-house-status-dev-loader.js?v=dev-loader-4'));
assert.ok(deploy.includes("old_url='module_url: /local/house-status-dev/lifeos-house-status-dev-loader.js?v=dev-loader-3'"));
assert.ok(deploy.includes("new_url='module_url: /local/house-status-dev/lifeos-house-status-dev-loader.js?v=dev-loader-4'"));
assert.match(devWorkflow,/find \/opt\/actions-runner-lifeos\/externals/,'post-deploy runtime test must locate the Pi runner\'s bundled Node executable');
assert.match(dev,/await import\('\/local\/house-status-dev\/lifeos-house-status-doorbell\.js\?dev='\+Date\.now\(\)\)/);
assert.match(dev,/try\{ await import\([^\n]+\); \} catch\(error\) \{ console\.warn\('House Status Doorbell module load failed',error\); \}/,'Doorbell module load errors are contained');
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
  let clockNow=new Date(2026,9,14,12,0,0,0);
  class ControlledDate extends Date{
    constructor(...args){if(args.length===0)super(clockNow.getTime());else super(...args);}
    static now(){return clockNow.getTime();}
  }
  let holdNextDayResponse=false,heldDayResponse=null;
  const context={
    HTMLElement:FakeCardElement,
    customElements:{get:name=>registry.get(name),define:(name,value)=>registry.set(name,value)},
    window:{location:{origin:'http://ha.local'},customCards:[]},
    document:{createElement:()=>new FakeElement()},
    URL,Date:ControlledDate,Intl,AbortController,setTimeout,process,
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
  vm.runInNewContext(dev.replace(/^try\{ await import\([^\n]+\); \} catch\(error\) \{ console\.warn\([^\n]+\); \}\n/,''),context);
  const Card=registry.get('lifeos-house-status-dev');
  const card=new Card();
  const anchor=new Date(2026,9,13,12,0,0,0);
  const selectedDay=new Date(anchor);selectedDay.setHours(0,0,0,0);
  const previousDay=new Date(selectedDay);previousDay.setDate(previousDay.getDate()-1);
  const nextDay=new Date(selectedDay);nextDay.setDate(nextDay.getDate()+1);
  card._anchor=anchor;card._mode='domestic';
  card.hass={states:{}};
  const pause=()=>new Promise(resolve=>setTimeout(resolve,0));
  await pause();await pause();
  assert.equal(requests.length,1,'initial Today view requests its selected calendar day');
  assert.equal(Number(requests[0].searchParams.get('start')),Math.floor(selectedDay.getTime()/1000),'Today request starts at selected-day midnight');
  assert.equal(Number(requests[0].searchParams.get('end')),Math.floor(nextDay.getTime()/1000),'Today request ends at the next London midnight');
  assert.match(card.innerHTML,/4\.59 kWh/,'Today uses only its selected day total');
  assert.match(card.innerHTML,/class="axis axis-price"/,'Today chart renders price-scale labels');
assert.match(card.innerHTML,/class="price" d="M/,'Today chart renders the Octopus price series');
  assert.match(card.innerHTML,/class="use" d="M/,'Today chart renders the Enphase cost series');
  assert.match(card.innerHTML,/data-period-label="today"/,'Today section has a clear label');
  assert.match(card.innerHTML,/data-period-label="tomorrow"/,'Tomorrow section has a clear label');
  const midnightX=()=>Number(card.innerHTML.match(/data-midnight-boundary x1="([\d.]+)"/)?.[1]);
  const widthShare=()=>((midnightX()-68)/864);
  assert.ok(Math.abs(widthShare()-.85)<.001,'unavailable tomorrow prices reserve only 15% of the chart');
  assert.match(card.innerHTML,/data-tomorrow-pricing="unavailable"/,'unavailable future pricing is explicit');
  const makeTomorrowSlots=(count,basePrice=42)=>Array.from({length:count},(_,i)=>({
    valid_from:new Date(nextDay.getTime()+i*1800000).toISOString(),
    import_price_available:true,import_p_per_kwh:basePrice+i/10
  }));
  const pricePathX=()=>[...(card.innerHTML.match(/<path class="price" d="([^"]*)"/)||[])[1].matchAll(/[ML]([\d.]+) /g)].map(m=>Number(m[1]));
  const seriesXs=klass=>{const d=card.innerHTML.match(new RegExp('<path class="'+klass+'" d="([^"]*)"'))?.[1]||'';return [...d.matchAll(/[ML]([0-9.]+) /g)].map(m=>Number(m[1]));};
  const oldTodayMetric=()=>/4\.59 kWh/.test(card.innerHTML)&&/£1\.09/.test(card.innerHTML)&&/Available history 100\.0%/.test(card.innerHTML)&&seriesXs('use').every(x=>x<midnightX());
  const setTomorrowSlots=async slots=>{card.hass={states:{'sensor.lifeos_energy_tariff_horizon':{attributes:{slots}}}};await pause();await pause();};
  await setTomorrowSlots(makeTomorrowSlots(6));
  assert.equal(requests.length,1,'tariff updates redraw Today without refetching its measured energy');
  assert.ok(Math.abs(widthShare()-.5)<.001,'partial tomorrow pricing expands the chart to equal day widths');
  assert.match(card.innerHTML,/data-tomorrow-pricing="partial"/,'partially published prices are identified');
  assert.ok(pricePathX().some(x=>x>midnightX()),'partial Octopus prices plot in the tomorrow section');
  assert.ok(oldTodayMetric(),'future rates do not alter Today kWh or cost totals');
  await setTomorrowSlots(makeTomorrowSlots(48));
  assert.ok(Math.abs(widthShare()-.5)<.001,'complete tomorrow pricing retains equal day widths');
  assert.match(card.innerHTML,/Octopus price \(p\/kWh\)/,'published tomorrow prices are labeled with their tariff units');
  assert.ok(pricePathX().some(x=>x>midnightX()+300),'complete prices occupy tomorrow through the day');
  assert.ok(oldTodayMetric(),'complete future rates still do not alter Today totals');
  await setTomorrowSlots([]);
  assert.equal(requests.length,1,'prices becoming unavailable also redraw without refreshing the page');
  assert.ok(Math.abs(widthShare()-.85)<.001,'chart shrinks the empty tomorrow section back to 15%');
  assert.match(card.innerHTML,/data-tomorrow-pricing="unavailable"/,'missing tomorrow prices remain clearly marked');
  assert.ok(oldTodayMetric(),'unavailable future rates leave Today totals unchanged');
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
  card.hass={states:{'event.octopus_energy_a_8b23e5b8_octoplus_power_down_events':{attributes:{joined_events:[{start:'2026-10-13T08:00:00+01:00',end:'2026-10-13T08:30:00+01:00'}]}}}};
  await pause();
  await select('week');
  assert.equal(requests.length,6,'Week selection issues a fresh rollup request');
  assert.match(card.innerHTML,/data-energy-band="Power down"/,'Week renders the Power Down event marker');
  assert.ok(card.innerHTML.includes('>Power Down</span>'),'Week renders the Power Down legend');
  assert.equal(requests[5].searchParams.get('granularity'),'30m');
  const weekStart=new Date(Number(requests[5].searchParams.get('start'))*1000);
  assert.equal(weekStart.toISOString(),new Date(2026,9,7,0,0,0,0).toISOString(),'Week request starts six calendar days before the selected date');
  assert.equal(Number(requests[5].searchParams.get('end')),Math.floor(nextDay.getTime()/1000),'Week request includes the selected date through its next midnight');
  assert.ok(Number(requests[5].searchParams.get('end'))>Number(requests[5].searchParams.get('start')));
  assert.match(card.innerHTML,/Week 07 Oct 2026 – 13 Oct 2026/,'Week summary reports the exact rolling window');
  assert.match(card.innerHTML,/data-rolling-window="week"[^>]*>07 Oct – 13 Oct/,'Week graph labels the exact rolling window');
  const weekAxis=[...card.innerHTML.matchAll(/<text class="axis" x="[\d.]+" y="[\d.]+" text-anchor="middle">(Mon|Tue|Wed|Thu|Fri|Sat|Sun)<\/text>/g)].map(m=>m[1]);
  assert.deepEqual(weekAxis,['Wed','Thu','Fri','Sat','Sun','Mon','Tue'],'Week categories span Wed 7 Oct through Tue 13 Oct');
  assert.match(card.innerHTML,/15\.63 kWh/,'Week uses its own response rows');
  await select('month');
  assert.equal(requests.length,7,'Month selection issues a fresh rollup request');
  const monthStart=new Date(Number(requests[6].searchParams.get('start'))*1000);
  assert.equal(monthStart.toISOString(),new Date(2026,8,13,0,0,0,0).toISOString(),'Month request starts one calendar month before the selected date');
  assert.equal(Number(requests[6].searchParams.get('end')),Math.floor(nextDay.getTime()/1000),'Month request includes the selected date through its next midnight');
  assert.match(card.innerHTML,/Month 13 Sep 2026 – 13 Oct 2026/,'Month summary reports the exact rolling window');
  assert.match(card.innerHTML,/data-rolling-window="month"[^>]*>13 Sep – 13 Oct/,'Month graph labels the exact rolling window');
  assert.ok(Number(requests[6].searchParams.get('end'))>Number(requests[6].searchParams.get('start')));
  assert.match(card.innerHTML,/77\.05 kWh/,'Month uses its own response rows');
  await select('year');
  assert.equal(requests.length,8,'Year selection issues a fresh rollup request');
  assert.equal(new Date(Number(requests[7].searchParams.get('start'))*1000).toISOString(),new Date(2025,9,13,0,0,0,0).toISOString(),'Year request starts one calendar year before the selected date');
  assert.equal(Number(requests[7].searchParams.get('end')),Math.floor(nextDay.getTime()/1000),'Year request includes the selected date through its next midnight');
  assert.match(card.innerHTML,/Year 13 Oct 2025 – 13 Oct 2026/,'Year summary reports the exact rolling window');
  assert.match(card.innerHTML,/data-rolling-window="year"[^>]*>13 Oct – 13 Oct/,'Year graph labels the exact rolling window');
  assert.match(card.innerHTML,/27\.0% · Partial history/,'Year shows API-reported partial coverage instead of stale 100%');
  assert.match(card.innerHTML,/class="price" d="M/,'historical Octopus price is plotted from the selected response');
  assert.doesNotMatch(card.innerHTML,/data-energy-band="Power down"/,'Year graph suppresses Power Down event markers');
  assert.ok(!card.innerHTML.includes('>Power Down</span>'),'Year legend omits Power Down when no graphics are rendered');
  console.log('YEAR_POWER_DOWN_RENDERING=HIDDEN');
  await select('month');
  assert.match(card.innerHTML,/data-energy-band="Power down"/,'switching from Year to Month restores the Power Down marker without reloading');
  assert.ok(card.innerHTML.includes('>Power Down</span>'),'switching from Year to Month restores the Power Down legend without reloading');
  await select('year');
  assert.doesNotMatch(card.innerHTML,/data-energy-band="Power down"/,'switching back to Year hides Power Down again');
  await select('week');
  assert.match(card.innerHTML,/data-energy-band="Power down"/,'switching from Year to Week restores the Power Down marker without reloading');
  assert.ok(card.innerHTML.includes('>Power Down</span>'),'switching from Year to Week restores the Power Down legend without reloading');
  const londonDate=d=>d.toLocaleDateString('en-CA',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'});
  card._anchor=new Date(2026,2,31,12);card._period='week';
  const dstWeek=card.periodWindow();
  assert.equal(JSON.stringify(dstWeek.map(londonDate)),JSON.stringify(['2026-03-25','2026-04-01']),'rolling Week uses London calendar days across the spring DST change');
  assert.equal((dstWeek[1]-dstWeek[0])/3600000,167,'London DST week is seven calendar days rather than a fixed 168 hours');
  card._period='month';
  assert.equal(JSON.stringify(card.periodWindow().map(londonDate)),JSON.stringify(['2026-02-28','2026-04-01']),'one-month subtraction clamps to the last valid prior-month date');
  card._anchor=new Date(2024,1,29,12);card._period='year';
  assert.equal(JSON.stringify(card.periodWindow().map(londonDate)),JSON.stringify(['2023-02-28','2024-03-01']),'one-year subtraction clamps leap day to 28 February');
  const requestsBeforeRollover=requests.length;
  card._period='today';card._anchor=null;card._energyHistory=[];card._energyCoverage=null;card._energyHistoryKey=null;card._energyHistoryRequestedKey=null;
  clockNow=new Date(2026,9,13,23,59,0,0);card.hass={states:{}};
  await pause();await pause();
  const beforeMidnight=new Date(clockNow);beforeMidnight.setHours(0,0,0,0);
  assert.equal(Number(requests[requests.length-1].searchParams.get('start')),Math.floor(beforeMidnight.getTime()/1000),'Today uses the current calendar day before midnight');
  clockNow=new Date(2026,9,14,0,1,0,0);card.hass={states:{}};
  await pause();await pause();
  const afterMidnight=new Date(clockNow);afterMidnight.setHours(0,0,0,0);
  assert.equal(requests.length,requestsBeforeRollover+2,'midnight rollover issues a new Today request');
  assert.equal(Number(requests[requests.length-1].searchParams.get('start')),Math.floor(afterMidnight.getTime()/1000),'Today automatically rolls to the new calendar day at midnight');
  console.log('HOUSE_STATUS_DEV_TODAY_TOMORROW_PRICING=PASS');
  console.log('HOUSE_STATUS_DEV_TOMORROW_COMPLETE_PARTIAL_UNAVAILABLE=PASS');
  console.log('HOUSE_STATUS_DEV_TARIFF_LIVE_UPDATE=PASS');
  console.log('HOUSE_STATUS_DEV_MIDNIGHT_ROLLOVER=PASS');
  console.log('HOUSE_STATUS_DEV_TODAY_DAY_WINDOWS=PASS');
  console.log('HOUSE_STATUS_DEV_TODAY_DAY_SWITCH_RUNTIME_REGRESSION=PASS');
  console.log('HOUSE_STATUS_DEV_STALE_DAY_RESPONSE=PASS');
  console.log('HOUSE_STATUS_DEV_ROLLING_WEEK_MONTH_YEAR=PASS');
  console.log('ROLLING_PERIOD_RUNTIME_2026_10_13=PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});

console.log('HOUSE_STATUS_DEV_PERIOD_HISTORY_RELOAD=PASS');
console.log('HOUSE_STATUS_DEV_STALE_HISTORY_RESPONSE=PASS');
console.log('HOUSE_STATUS_DEV_HISTORY_COVERAGE=PASS');
console.log('HOUSE_STATUS_DEV_CUSTOM_ELEMENTS=PASS');
console.log('HOUSE_STATUS_DEV_CAMERA_NAMESPACE=PASS');
console.log('HOUSE_STATUS_DEV_DEPLOY_TARGET=PASS');
console.log('HOUSE_STATUS_LIVE_MANUAL_RELEASE_ONLY=PASS');


