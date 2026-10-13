'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const here=__dirname;
const read=name=>fs.readFileSync(path.join(here,'releases/house-status/live',name),'utf8').replace(/^import[^\n]*\n/gm,'');
const energy=fs.readFileSync(process.env.HOUSE_STATUS_LIVE_ASSET||path.join(here,'releases/house-status/live/lifeos-house-status-v29.js'),'utf8').replace(/^import[^\n]*\n/gm,'');
const frozen=read('lifeos-house-status-v28.js');
class FakeElement{constructor(){this.dataset={};this.onclick=null;}}
class FakeCardElement{
  constructor(){this.dataset={};this._html='';this.periodButtons=[];this.modeButtons=[];}
  set innerHTML(value){this._html=value;}
  get innerHTML(){return this._html;}
  querySelectorAll(selector){
    if(selector==='[data-period]'){
      this.periodButtons=[...this._html.matchAll(/data-period="([^"]+)"/g)].map(match=>{const el=new FakeElement();el.dataset.period=match[1];return el;});
      return this.periodButtons;
    }
    if(selector==='[data-mode]'){
      this.modeButtons=[...this._html.matchAll(/data-mode="([^"]+)"/g)].map(match=>{const el=new FakeElement();el.dataset.mode=match[1];return el;});
      return this.modeButtons;
    }
    return [];
  }
  querySelector(){return null;}
}
function create(source,mode='domestic'){
  const registry=new Map(),requests=[];
  let clockNow=new Date('2026-10-14T12:00:00+01:00');
  class TestDate extends Date{constructor(...args){if(args.length===0)super(clockNow.getTime());else super(...args);}static now(){return clockNow.getTime();}}
  const context={
    HTMLElement:FakeCardElement,
    customElements:{get:name=>registry.get(name),define:(name,value)=>registry.set(name,value)},
    window:{location:{origin:'http://ha.local'},customCards:[],LifeOSHouseStatusModules:{doorbellV28:{render:()=>'<div class="doorcam">Live Doorbell</div>',mount(){}}}},
    document:{createElement:()=>new FakeElement()},URL,Date:TestDate,Intl,AbortController,setTimeout,process,
    console:{warn(){},log(){},error:console.error},
    fetch:input=>{
      const url=new URL(input);requests.push(url);
      const start=Number(url.searchParams.get('start'));
      return Promise.resolve({ok:true,json:async()=>({timezone:'Europe/London',coverage_percent:100,points:[{
        timestamp:start,domestic_import_kwh:5.5,grid_import_kwh:5.5,grid_export_kwh:0,
        production_kwh:0,consumption_kwh:5.5,import_p_per_kwh:22.7,
        import_price_available:true,domestic_import_cost_gbp:1.25,sample_count:30,sample_coverage_percent:96
      }]})});
    }
  };
  vm.runInNewContext(source,context);
  const ctor=[...registry.entries()].find(([name])=>name.endsWith('v29')||name.endsWith('v28'))?.[1];
  const card=new ctor();card._mode=mode;card._anchor=new Date('2026-10-13T12:00:00+01:00');card.config={mode};
  return {card,requests,registry};
}
const pause=()=>new Promise(resolve=>setTimeout(resolve,0));
(async()=>{
  const {card,requests}=create(energy);
  const event='event.octopus_energy_a_8b23e5b8_octoplus_power_down_events';
  card.hass={states:{[event]:{attributes:{joined_events:[{start:'2026-10-13T08:00:00+01:00',end:'2026-10-13T08:30:00+01:00'}]}}}};
  await pause();await pause();
  const select=async period=>{const button=card.periodButtons.find(el=>el.dataset.period===period);assert.ok(button,period+' selector exists');button.onclick();await pause();await pause();};
  const expectedStart=value=>new Date(value).getTime()/1000;
  const checkRequest=(index,period,start,end,label)=>{
    assert.equal(requests[index].searchParams.get('granularity'),'30m',period+' uses API rollups');
    assert.equal(Number(requests[index].searchParams.get('start')),expectedStart(start),period+' API start');
    assert.equal(Number(requests[index].searchParams.get('end')),expectedStart(end),period+' API end');
    assert.ok(card.innerHTML.includes(label),period+' summary label');
  };
  await select('week');
  checkRequest(1,'Week','2026-10-07T00:00:00+01:00','2026-10-14T00:00:00+01:00','Week 07 Oct 2026 – 13 Oct 2026');
  assert.match(card.innerHTML,/data-rolling-window="week"[^>]*>07 Oct – 13 Oct/,'Week graph uses the same rolling window');
  const weekAxis=[...card.innerHTML.matchAll(/<text class="axis" x="[\d.]+" y="[\d.]+" text-anchor="middle">(Mon|Tue|Wed|Thu|Fri|Sat|Sun)<\/text>/g)].map(m=>m[1]);
  assert.deepEqual(weekAxis,['Wed','Thu','Fri','Sat','Sun','Mon','Tue'],'Week graph categories follow the rolling dates');
  assert.match(card.innerHTML,/5\.50 kWh/,'Week summary uses selected API data');
  assert.match(card.innerHTML,/data-energy-band="Power down"/,'Week retains Power Down graphics');
  assert.ok(card.innerHTML.includes('>Power Down</span>'),'Week retains the Power Down legend');
  await select('month');
  checkRequest(2,'Month','2026-09-13T00:00:00+01:00','2026-10-14T00:00:00+01:00','Month 13 Sep 2026 – 13 Oct 2026');
  assert.match(card.innerHTML,/data-rolling-window="month"[^>]*>13 Sep – 13 Oct/,'Month graph uses rolling dates');
  assert.match(card.innerHTML,/data-energy-band="Power down"/,'Month retains Power Down graphics');
  assert.ok(card.innerHTML.includes('>Power Down</span>'),'Month retains the Power Down legend');
  await select('year');
  checkRequest(3,'Year','2025-10-13T00:00:00+01:00','2026-10-14T00:00:00+01:00','Year 13 Oct 2025 – 13 Oct 2026');
  assert.match(card.innerHTML,/data-rolling-window="year"[^>]*>13 Oct – 13 Oct/,'Year graph uses rolling dates');
  assert.doesNotMatch(card.innerHTML,/data-energy-band="Power down"/,'Year graph hides Power Down graphics');
  assert.ok(!card.innerHTML.includes('>Power Down</span>'),'Year legend hides Power Down');
  console.log('YEAR_POWER_DOWN_RENDERING=HIDDEN');
  await select('month');
  assert.match(card.innerHTML,/data-energy-band="Power down"/,'Year to Month restores marker without reload');
  assert.ok(card.innerHTML.includes('>Power Down</span>'),'Year to Month restores legend without reload');
  await select('year');
  assert.doesNotMatch(card.innerHTML,/data-energy-band="Power down"/,'Month to Year hides marker again');
  await select('week');
  assert.match(card.innerHTML,/data-energy-band="Power down"/,'Year to Week restores marker without reload');
  assert.ok(card.innerHTML.includes('>Power Down</span>'),'Year to Week restores legend without reload');
  const rollingCard=card.innerHTML;
  const homeOld=create(frozen,'home').card,homeNew=create(energy,'home').card;
  homeOld.hass={states:{}};homeNew.hass={states:{}};
  assert.equal(homeNew.innerHTML,homeOld.innerHTML,'Home Status presentation is byte-identical to v28');
  const doorOld=create(frozen,'doorbell').card,doorNew=create(energy,'doorbell').card;
  doorOld.hass={states:{}};doorNew.hass={states:{}};
  assert.equal(doorNew.innerHTML,doorOld.innerHTML,'Doorbell presentation shell is byte-identical to v28');
  assert.ok(rollingCard.includes('Energy v2'),'Energy views identify the promoted version');
  console.log('LIVE_ENERGY_ROLLING_WINDOWS=PASS');
  console.log('LIVE_HOME_DOORBELL_UNCHANGED=PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
