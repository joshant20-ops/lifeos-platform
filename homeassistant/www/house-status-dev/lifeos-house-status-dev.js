try{ await import('/local/house-status-dev/lifeos-house-status-doorbell.js?dev='+Date.now()); } catch(error) { console.warn('House Status Doorbell module load failed',error); }
class LifeOSEnergyModule {
  static owns(mode){ return mode==='domestic'||mode==='flow'; }
}
class LifeOSHouseModule {
  static owns(mode){ return mode==='home'; }
}
class LifeOSDoorbellModule {
  static owns(mode){ return mode==='doorbell'; }
}
class LifeOSHouseStatusCard extends HTMLElement {
  static getStubConfig(){ return {mode:'domestic'}; }
  static getConfigElement(){ return document.createElement('lifeos-house-status-dev-editor-v2'); }
  setConfig(config){ this.config=config||{}; this.render(); }
  set hass(hass){ this._hass=hass; const mode=this._mode||this.config?.mode||'domestic'; const host=this._doorbellHost; if(mode==='doorbell'&&host?.isConnected){try{host.hass=hass;}catch(error){console.warn('House Status Doorbell update failed',error);}return;} this.render(); if(mode!=='doorbell')this._loadEnergyHistory(); }
  period(){return this._period||'today';}
  anchor(){return this._anchor||new Date();}
  londonParts(value){return Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(value).filter(p=>p.type!=='literal').map(p=>[p.type,Number(p.value)]));}
  londonDate(year,month,day){const wall=Date.UTC(year,month-1,day);let instant=wall;for(let i=0;i<4;i++){const p=this.londonParts(new Date(instant)),represented=Date.UTC(p.year,p.month-1,p.day,p.hour,p.minute,p.second),next=wall-(represented-instant);if(next===instant)break;instant=next;}return new Date(instant);}
  londonDay(value){const p=this.londonParts(value);return new Date(Date.UTC(p.year,p.month-1,p.day));}
  addLondonDays(value,days){const d=this.londonDay(value);d.setUTCDate(d.getUTCDate()+days);return this.londonDate(d.getUTCFullYear(),d.getUTCMonth()+1,d.getUTCDate());}
  addLondonMonths(value,months){const p=this.londonParts(value),d=new Date(Date.UTC(p.year,p.month-1,1));d.setUTCMonth(d.getUTCMonth()+months);const day=Math.min(p.day,new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,0)).getUTCDate());return this.londonDate(d.getUTCFullYear(),d.getUTCMonth()+1,day);}
  selectedLondonDay(){const p=this.londonParts(this.anchor());return this.londonDate(p.year,p.month,p.day);}
  periodStart(){const selected=this.selectedLondonDay();if(this.period()==='week')return this.addLondonDays(selected,-6);if(this.period()==='month')return this.addLondonMonths(selected,-1);if(this.period()==='year')return this.addLondonMonths(selected,-12);if(this.period()==='day')return this.addLondonDays(selected,-1);return selected;}
  periodEnd(){return this.addLondonDays(this.selectedLondonDay(),1);}
  periodWindow(){return [this.periodStart(),this.periodEnd()];}
  shiftPeriod(dir){this._energyHistoryKey=null;let a;if(this.period()==='week')a=this.addLondonDays(this.anchor(),7*dir);else if(this.period()==='month')a=this.addLondonMonths(this.anchor(),dir);else if(this.period()==='year')a=this.addLondonMonths(this.anchor(),12*dir);else a=this.addLondonDays(this.anchor(),dir);this._anchor=a;this._energyHistory=[];this._energyCoverage=null;this.render();this._loadEnergyHistory();}
  getCardSize(){ return 10; }
  val(id,def=0){ const s=this._hass?.states?.[id]; const n=Number(s?.state); return Number.isFinite(n)?n:def; }
  money(id){ return '£'+this.val(id).toFixed(2); }
  render(){
    if(!this._hass) return;
    const mode=this._mode||this.config?.mode||'domestic';
    const css=`<style>
      :host{display:block;border:2px solid #b568ff;--bg:#061720;--panel:#081c27;--line:#163747;--text:#f4f7f9;--muted:#b8c6ce;--blue:#a55cff}
      *{box-sizing:border-box}.app{background:linear-gradient(145deg,#061720,#031018);color:var(--text);border-radius:14px;padding:14px;font-family:var(--paper-font-body1_-_font-family,Arial,sans-serif)}
      .hanav{display:flex;align-items:center;height:48px;margin:-14px -14px 12px;padding:0 12px;border-bottom:1px solid var(--line);background:#101416}.hamb{font-size:23px;margin-right:18px;cursor:pointer;padding:8px;border-radius:50%}.haitem{height:48px;min-width:62px;padding:11px 18px;text-align:center;font-size:22px;color:var(--muted);cursor:pointer;position:relative}.haitem.active{background:transparent;color:white}.haitem.active:after{content:'';position:absolute;left:10px;right:10px;bottom:0;height:3px;background:#ddd}.top{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:18px;margin-bottom:8px}.controls{display:contents}.title{font-size:25px;font-weight:800;grid-column:1}.period{display:flex;grid-column:1;border:1px solid var(--line);border-radius:7px;overflow:hidden}.p{padding:7px 15px;color:var(--muted);border-right:1px solid var(--line);white-space:nowrap}.active{background:var(--blue);color:white}.datewrap{display:flex;grid-column:3;grid-row:1;align-items:center;gap:5px}.date,.arrow{border:1px solid var(--line);border-radius:7px;padding:7px 11px;color:var(--muted)}.date{position:relative;cursor:pointer;display:flex;align-items:center;gap:7px}.dateinput{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer;color-scheme:dark}
      .panel{border:1px solid var(--line);border-radius:10px;background:rgba(6,25,35,.82);padding:12px;margin-top:10px}.panelhead{display:grid;grid-template-columns:1fr auto;align-items:start}.panelcopy{min-width:0}.heading{font-size:20px;font-weight:750}.sub{color:var(--muted);margin:4px 0 8px}.chartslot{position:relative;border-top:1px solid rgba(255,255,255,.03);overflow:hidden}.chart{display:block;width:100%;height:auto;max-height:410px}.gridline{stroke:#47606c;stroke-dasharray:4 5;opacity:.65}.zeroline{stroke:#d8e1e6;stroke-width:1.5;opacity:.9}.axis{fill:#b8c6ce;font-size:11px}.axis-cost{fill:#1e9cf0}.axis-price{fill:#ffad18}.price{fill:none;stroke:#ffad18;stroke-width:3}.use{fill:none;stroke:#1e9cf0;stroke-width:4}.export{fill:none;stroke:#20b26b;stroke-width:4}.gas{fill:none;stroke:#ef5547;stroke-width:3}.bar-house{fill:#168cff}.bar-batt{fill:#8756d8}.bar-standing{fill:#a9b7c0}.bar-export{fill:#20a86b}.soc{fill:none;stroke:#a9b7c0;stroke-width:2;stroke-dasharray:5 4}.band-free{fill:#20b26b;opacity:.28}.band-powerdown{fill:#ef5547;fill-opacity:.32;stroke:#ef5547;stroke-width:1}.legendrow{display:flex;gap:10px;justify-content:center;align-items:center;flex-wrap:nowrap;color:var(--muted);font-size:10px;line-height:1;margin:0;padding:2px 0 0;white-space:nowrap}.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:4px}
      .cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:8px}.metric{border:1px solid var(--line);border-radius:9px;background:rgba(6,25,35,.9);padding:10px 12px;min-height:0}.metric b{display:block;font-size:13px}.big{font-size:23px;font-weight:800;margin:6px 0 3px}.small{color:var(--muted);font-size:12px;line-height:1.25}
      .doorcam{margin-top:10px;overflow:hidden;border-radius:10px}.doorcam > *{display:block}.floor{min-height:320px;display:flex;align-items:center;justify-content:center;border:1px dashed #31566a;border-radius:8px;color:var(--muted);background:#071923}.status{display:grid;grid-template-columns:1fr 1fr;gap:10px}.secure,.leave{padding:14px;border-radius:9px;font-size:18px;font-weight:750}.secure{border:1px solid #237d61;background:#0a3a31}.leave{border:1px solid #a43a4a;background:#501a25;text-align:center}.legend{display:flex;gap:22px;flex-wrap:wrap;color:var(--muted);font-size:13px}
      @media(max-width:850px){.app{padding:10px}.top{grid-template-columns:1fr auto}.controls{display:contents}.datewrap{grid-column:2;grid-row:1}.hanav{margin:-10px -10px 10px}.haitem{min-width:52px;padding:11px 12px}.top{flex-wrap:wrap}.title{font-size:22px}.period{grid-column:1 / -1;grid-row:2;width:auto;overflow:auto}.p{flex:0 0 auto;text-align:center;padding:7px 11px;font-size:12px}.datewrap{margin-left:auto}.date{width:auto;text-align:center}.cards{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.metric{padding:8px;min-height:0}.metric b{font-size:11px}.big{font-size:20px;margin:5px 0 2px}.small{font-size:10px;line-height:1.2}.chartslot{min-height:0}.status{grid-template-columns:1fr}.floor{min-height:240px}}
    </style>`;
    const moduleVersion=mode==='doorbell'?'Doorbell DEV':(mode==='home'?'House DEV':'Energy DEV');
    const anchorParts=this.londonParts(this.anchor());
    const nav=`<div class="hanav"><div class="hamb" role="button" tabindex="0" aria-label="Open Home Assistant menu">☰</div><div class="haitem ${mode==='domestic'?'active':''}" data-mode="domestic">⌂</div><div class="haitem ${mode==='flow'?'active':''}" data-mode="flow">⚡</div><div class="haitem ${mode==='home'?'active':''}" data-mode="home">▣</div><div class="haitem ${mode==='doorbell'?'active':''}" data-mode="doorbell">▥</div></div><div class="top"><div class="title">⌂ House Status DEV <span style="font-size:10px;opacity:.55;font-weight:400;margin-left:6px">${moduleVersion}</span></div><div class="controls">${mode!=='home'&&mode!=='doorbell'?'<div class="period"><div class="p '+(this.period()==='today'?'active':'')+'" data-period="today">Today</div><div class="p '+(this.period()==='day'?'active':'')+'" data-period="day">Day</div><div class="p '+(this.period()==='week'?'active':'')+'" data-period="week">Week</div><div class="p '+(this.period()==='month'?'active':'')+'" data-period="month">Month</div><div class="p '+(this.period()==='year'?'active':'')+'" data-period="year">Year</div><div class="p '+(this.period()==='range'?'active':'')+'" data-period="range">Date range</div></div>':''}<div class="datewrap"><div class="arrow" data-shift="-1">‹</div><label class="date">▣ ${this.anchor().toLocaleDateString('en-GB',{weekday:'short',day:'2-digit',month:'short',year:'numeric',timeZone:'Europe/London'})}<input class="dateinput" data-date-picker type="date" value="${anchorParts.year}-${String(anchorParts.month).padStart(2,'0')}-${String(anchorParts.day).padStart(2,'0')}"></label><div class="arrow" data-shift="1">›</div></div></div></div>`;
    if(mode==='doorbell'){
      this.dataset.module='doorbell';
      const doorbell=window.LifeOSHouseStatusDevModules?.doorbell;
      let body='<div class="panel"><div class="heading">Doorbell</div><div class="floor">DOORBELL MODULE UNAVAILABLE</div></div>';
      try{if(doorbell?.render)body=doorbell.render(this._hass);}catch(error){console.warn('House Status Doorbell render failed',error);}
      this.innerHTML=css+`<div class="app">${nav}${body}</div>`;
      this._doorbellHost=this.querySelector('[data-lifeos-doorbell-camera]');
      if(this._doorbellHost){
        this._doorbellHost.hass=this._hass;
        try{Promise.resolve(doorbell?.mount?.(this._doorbellHost,this._hass)).catch(error=>console.warn('House Status Doorbell mount failed',error));}catch(error){console.warn('House Status Doorbell mount failed',error);}
      }
      const menu=this.querySelector('.hamb');
      if(menu){const openMenu=()=>this.dispatchEvent(new CustomEvent('hass-toggle-menu',{bubbles:true,composed:true}));menu.onclick=openMenu;menu.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openMenu();}};}
      this.querySelectorAll('[data-mode]').forEach(el=>el.onclick=()=>{this._mode=el.dataset.mode;this.render();});
      return;
    }
    const moduleOwner=LifeOSEnergyModule.owns(mode)?'energy':LifeOSHouseModule.owns(mode)?'house':'energy';
    this.dataset.module=moduleOwner;
    const stamp=o=>new Date(o.valid_from||o.local_from||o.start||0).getTime();
    const liveReport=this._hass.states['sensor.lifeos_energy_report']?.attributes?.intervals||[];
    const historicalReport=this._energyHistory||[];
    const report=[...historicalReport,...liveReport].reduce((m,o)=>{const k=stamp(o);if(Number.isFinite(k))m.set(k,o);return m;},new Map()).values();
    const reportRows=[...report].sort((a,b)=>stamp(a)-stamp(b));
    const [selectedStart,selectedEnd]=this.periodWindow();
    const selectedRows=reportRows.filter(o=>stamp(o)>=selectedStart.getTime()&&stamp(o)<selectedEnd.getTime());
    const selectedUsage=selectedRows.reduce((n,o)=>n+(Number(o.domestic_import_kwh)||0),0);
    const pricedRows=selectedRows.filter(o=>o.domestic_import_cost_gbp!==null&&o.domestic_import_cost_gbp!==undefined&&Number.isFinite(Number(o.domestic_import_cost_gbp)));
    const selectedCost=pricedRows.reduce((n,o)=>n+Number(o.domestic_import_cost_gbp),0);
    const selectedAvgPrice=selectedUsage>0&&pricedRows.length===selectedRows.length&&this._energyCoverage>=99?selectedCost*100/selectedUsage:null;
    const fmtDate=d=>d.toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'Europe/London'}).replace(/\bSept\b/,'Sep');
    const selectedLabel=this.period()==='today'?fmtDate(selectedStart):
      this.period()==='day'?fmtDate(selectedStart)+' – '+fmtDate(this.addLondonDays(selectedEnd,-1)):
      ['week','month','year'].includes(this.period())?this.period()[0].toUpperCase()+this.period().slice(1)+' '+fmtDate(selectedStart)+' – '+fmtDate(this.addLondonDays(selectedEnd,-1)):
      fmtDate(selectedStart)+' – '+fmtDate(new Date(selectedEnd.getTime()-86400000));

    const standingChargeFor=r=>{const d=new Date(stamp(r));return .01+(d.getHours()===23&&d.getMinutes()===30?0.02:0)};
    const tariff=this._hass.states['sensor.lifeos_energy_tariff_horizon']?.attributes?.slots||[];
    const octopusTariff=this._hass.states['sensor.lifeos_energy_tariff_horizon'];
    const powerdownEntity='event.octopus_energy_a_8b23e5b8_octoplus_power_down_events';
    const rawPowerdownEvents=this._hass.states[powerdownEntity]?.attributes?.joined_events;
    const powerdownEvents=Array.isArray(rawPowerdownEvents)?rawPowerdownEvents:[];
    const powerdownHistory=this._history?.[powerdownEntity]||[];
    const svgChart=(flow=false)=>{
      const W=1000,H=360,padL=68,padR=68,padT=34,padB=30,iw=W-padL-padR,ih=H-padT-padB;
      const now=new Date(),[day0,day1]=this.periodWindow(),day2=this.addLondonDays(day1,1);
      const longRange=['week','month','year'].includes(this.period()),isToday=this.period()==='today',isRollingDay=this.period()==='day',t0=day0.getTime(),t1=day1.getTime(),t2=longRange?t1:day2.getTime(),tomorrowTariffRows=isToday?tariff.filter(o=>o.import_price_available===true&&o.import_p_per_kwh!==null&&Number.isFinite(Number(o.import_p_per_kwh))&&stamp(o)>=t1&&stamp(o)<t2):[],tomorrowPriceStamps=new Set(tomorrowTariffRows.map(stamp)),tomorrowPriceCount=tomorrowPriceStamps.size,expectedTomorrowPriceSlots=Math.round((t2-t1)/1800000),tomorrowPricingStatus=tomorrowPriceCount===0?'unavailable':tomorrowPriceCount<expectedTomorrowPriceSlots?'partial':'complete',tomorrowHasPrice=!longRange&&!isToday&&!isRollingDay&&tariff.some(o=>o.import_price_available===true&&o.import_p_per_kwh!==null&&stamp(o)>=t1&&stamp(o)<t2),tomorrowShare=isToday?(tomorrowPriceCount>0?0.5:0.15):isRollingDay?0.5:(tomorrowHasPrice?0.5:0.22),todayShare=1-tomorrowShare,x=t=>longRange?padL+((t-t0)/(t1-t0))*iw:(t<t1?padL+((t-t0)/(t1-t0))*iw*todayShare:padL+iw*todayShare+((t-t1)/(t2-t1))*iw*tomorrowShare);
      const todayReport=reportRows.filter(o=>{const t=stamp(o);return t>=t0&&t<(isToday?t1:t2);});
      const historicalPrice=reportRows.filter(o=>{const t=stamp(o);return t>=t0&&t<(isToday?t1:t2)&&Number.isFinite(Number(o.import_p_per_kwh));}).map(o=>({...o,import_price_available:true})); const tariffPrice=tariff.filter(o=>o.import_price_available===true&&o.import_p_per_kwh!==null).filter(o=>{const t=stamp(o);return t>=t0&&t<t2;}); const priceByStamp=new Map(historicalPrice.map(o=>[stamp(o),o])); tariffPrice.forEach(o=>priceByStamp.set(stamp(o),o)); const published=[...priceByStamp.values()].sort((a,b)=>stamp(a)-stamp(b));
      const aggregate=(arr,key,kind='avg')=>{
        if(!['week','month','year'].includes(this.period()))
          return arr.map(o=>{const t=stamp(o),raw=o[key],v=Number(raw);return raw!==null&&raw!==undefined&&Number.isFinite(t)&&Number.isFinite(v)?[x(t),v,t]:null;}).filter(Boolean);
        const buckets=new Map(),period=this.period(),zone='Europe/London',windowStart=this.londonDay(day0),startOrdinal=windowStart.getTime();
        const partsFor=t=>this.londonParts(t);
        arr.forEach(o=>{
          const t=stamp(o),raw=o[key],v=Number(raw);
          if(raw===null||raw===undefined||!Number.isFinite(t)||!Number.isFinite(v))return;
          const parts=partsFor(t),calendarOrdinal=Date.UTC(parts.year,parts.month-1,parts.day);let bucketStart;
          if(period==='week')bucketStart=this.londonDate(parts.year,parts.month,parts.day);
          else if(period==='month')bucketStart=this.addLondonDays(day0,Math.floor((calendarOrdinal-startOrdinal)/604800000)*7);
          else{
            let monthOffset=(parts.year-windowStart.getUTCFullYear())*12+parts.month-1-windowStart.getUTCMonth();
            bucketStart=this.addLondonMonths(day0,monthOffset);
            const bucketParts=this.londonParts(bucketStart);
            if(calendarOrdinal<Date.UTC(bucketParts.year,bucketParts.month-1,bucketParts.day))bucketStart=this.addLondonMonths(day0,--monthOffset);
          }
          const dateKey=bucketStart.toISOString();
          const b=buckets.get(dateKey)||{sum:0,n:0,weighted:0,weight:0,timestamp:t};
          b.sum+=v;b.n++;b.timestamp=Math.min(b.timestamp,t);
          const weight=Math.max(0,Number(o.domestic_import_kwh)||0);
          b.weighted+=v*weight;b.weight+=weight;
          buckets.set(dateKey,b);
        });
        return [...buckets.entries()].sort((a,b)=>Date.parse(a[0])-Date.parse(b[0])).map(([dateKey,b])=>[
          x(Date.parse(dateKey)),
          kind==='sum'?b.sum:kind==='weighted'?(b.weight?b.weighted/b.weight:b.sum/b.n):b.sum/b.n,
          b.timestamp
        ]);
      };
      const price=aggregate(published,'import_p_per_kwh','weighted'),cost=aggregate(todayReport,'domestic_import_cost_gbp','sum'),exp=aggregate(todayReport,'export_earnings_gbp','sum');
      // Gas is deliberately not fabricated: current HA gas telemetry is daily cumulative, not interval-resolved.
      const visibleX=p=>p[0]>=padL&&p[0]<=W-padR,flowPositive=aggregate(todayReport.map(r=>({...r,__flow_positive:Math.max(0,Number(r.domestic_import_cost_gbp)||0)+Math.max(0,Number(r.battery_charge_import_cost_gbp)||0)+standingChargeFor(r)})),'__flow_positive','sum').map(p=>p[1]),flowNegative=aggregate(todayReport.map(r=>({...r,__flow_negative:-Math.max(0,Number(r.export_earnings_gbp)||0)})),'__flow_negative','sum').map(p=>p[1]),vals=(flow?flowPositive:cost.filter(visibleX).map(p=>p[1])).filter(Number.isFinite),rawHi=vals.length?Math.max(...vals):0,rawLo=flow&&flowNegative.length?Math.min(...flowNegative):0,span=Math.max(.005,rawHi-rawLo),pad=Math.max(.0025,span*.10),lo=flow?Math.min(0,rawLo-pad):0,hi=flow?Math.max(.005,rawHi+pad):Math.max(.005,rawHi*1.10),pvals=price.filter(visibleX).map(p=>p[1]).filter(Number.isFinite),rawPlo=pvals.length?Math.min(...pvals):0,rawPhi=pvals.length?Math.max(...pvals):1,pPad=Math.max(1,(rawPhi-rawPlo)*.08),plo=rawPlo-pPad,phi=rawPhi+pPad;
      const y=v=>padT+ih-(v-lo)/(hi-lo||1)*ih,py=v=>padT+ih-(v-plo)/(phi-plo||1)*ih,path=(arr,fy)=>arr.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+fy(p[1]).toFixed(1)).join(' '),pathPrice=(arr,fy)=>arr.map((p,i)=>((i&&p[2]-arr[i-1][2]>2700000)?'M':i?'L':'M')+p[0].toFixed(1)+' '+fy(p[1]).toFixed(1)).join(' '),pricePath=longRange?path(price,py):pathPrice(price,py);
      let grid='',axes='';for(let i=0;i<5;i++){const yy=padT+i*ih/4,cv=hi-(hi-lo)*i/4,pv=phi-(phi-plo)*i/4;grid+='<line class="gridline" x1="'+padL+'" y1="'+yy+'" x2="'+(W-padR)+'" y2="'+yy+'"/>';axes+='<text class="axis axis-cost" x="'+(padL-8)+'" y="'+(yy+4)+'" text-anchor="end">£'+cv.toFixed(2)+'</text><text class="axis axis-price" x="'+(W-padR+8)+'" y="'+(yy+4)+'" text-anchor="start">'+pv.toFixed(1)+'p</text>';}
      if(flow){const zy=y(0);grid+='<line class="zeroline" data-zero-line x1="'+padL+'" y1="'+zy+'" x2="'+(W-padR)+'" y2="'+zy+'"/>';axes+='<text class="axis axis-cost" x="'+(padL-8)+'" y="'+(zy+4)+'" text-anchor="end">£0.00</text>';}
      const fmtAxis=d=>d.toLocaleDateString('en-GB',{day:'2-digit',month:'short',timeZone:'Europe/London'}).replace(/\bSept\b/,'Sep'),fmtDay=d=>d.toLocaleDateString('en-GB',{weekday:'short',day:'2-digit',month:'short',timeZone:'Europe/London'}).replace(/\bSept\b/,'Sep'),leftLabel=fmtAxis(day0),rightLabel=fmtAxis(this.addLondonDays(day1,-1)),midnight=x(t1);
      if(longRange){
        axes+='<text class="axis" data-rolling-window="'+this.period()+'" x="'+(padL+iw/2)+'" y="20" text-anchor="middle" style="font-weight:700;fill:#f4f7f9">'+leftLabel+' – '+rightLabel+'</text><text class="axis axis-cost" x="'+padL+'" y="16">Cost (£)</text><text class="axis axis-price" x="'+(W-padR)+'" y="16" text-anchor="end">Octopus price (p/kWh)</text>';
        const ticks=[];
        if(this.period()==='week')for(let i=0;i<7;i++){const d=this.addLondonDays(day0,i);ticks.push([d.getTime(),d.toLocaleDateString('en-GB',{weekday:'short',timeZone:'Europe/London'})]);}
        else if(this.period()==='month')for(let i=0,d=day0;d<day1;i++,d=this.addLondonDays(day0,i*7))ticks.push([d.getTime(),fmtAxis(d)]);
        else for(let i=0;i<12;i++){const d=this.addLondonMonths(day0,i);ticks.push([d.getTime(),fmtAxis(d)]);}
        ticks.forEach(([t,label])=>{axes+='<text class="axis" x="'+x(t)+'" y="'+(padT+ih+18)+'" text-anchor="middle">'+label+'</text>';});
      }else if(isToday){
        grid+='<line class="gridline" data-midnight-boundary x1="'+midnight+'" y1="'+padT+'" x2="'+midnight+'" y2="'+(padT+ih)+'"/>';
        axes+='<text class="axis" data-period-label="today" x="'+((padL+midnight)/2)+'" y="16" text-anchor="middle" style="font-weight:700;fill:#f4f7f9">Today</text><text class="axis" x="'+((padL+midnight)/2)+'" y="29" text-anchor="middle">'+fmtDay(day0)+'</text><text class="axis" data-period-label="tomorrow" x="'+((midnight+W-padR)/2)+'" y="16" text-anchor="middle" style="font-weight:700;fill:#f4f7f9">Tomorrow</text><text class="axis" x="'+((midnight+W-padR)/2)+'" y="29" text-anchor="middle">'+fmtDay(day1)+'</text><text class="axis axis-cost" x="'+padL+'" y="16">Cost (£)</text>'+(tomorrowPriceCount?'<text class="axis axis-price" x="'+(W-padR)+'" y="16" text-anchor="end">Octopus price (p/kWh)</text>':'');
        const todayTicks=[[day0,0],[day0,6],[day0,12],[day0,18],[day1,0]],tomorrowTicks=tomorrowPriceCount?[[day1,6],[day1,12],[day1,18],[day2,0]]:[[day2,0]];
        [...todayTicks,...tomorrowTicks].forEach(([day,hour])=>{const tick=new Date(day.getTime()+hour*3600000);axes+='<text class="axis" x="'+x(tick.getTime())+'" y="'+(padT+ih+18)+'" text-anchor="middle">'+(hour===0?'00:00':tick.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:'Europe/London'}))+'</text>';});
      }else{
        grid+='<line class="gridline" x1="'+midnight+'" y1="'+padT+'" x2="'+midnight+'" y2="'+(padT+ih)+'"/>';
        axes+='<text class="axis" x="'+((padL+midnight)/2)+'" y="16" text-anchor="middle" style="font-weight:700;fill:#f4f7f9">'+(this.period()==='day'?'Yesterday':'Selected day')+'</text><text class="axis" x="'+((padL+midnight)/2)+'" y="29" text-anchor="middle">'+fmtDay(day0)+'</text><text class="axis" x="'+((midnight+W-padR)/2)+'" y="16" text-anchor="middle" style="font-weight:700;fill:#f4f7f9">Selected day</text><text class="axis" x="'+((midnight+W-padR)/2)+'" y="29" text-anchor="middle">'+fmtDay(this.addLondonDays(day1,-1))+'</text><text class="axis axis-cost" x="'+padL+'" y="16">Cost (£)</text><text class="axis axis-price" x="'+(W-padR)+'" y="16" text-anchor="end">Octopus price (p/kWh)</text>';
        [[day0,0],[day0,6],[day0,12],[day0,18],[day1,0],[day1,6],[day1,12],[day1,18]].forEach(([day,hour])=>{const tick=new Date(day.getTime()+hour*3600000);axes+='<text class="axis" x="'+x(tick.getTime())+'" y="'+(padT+ih+18)+'" text-anchor="middle">'+(hour===0?'00:00':tick.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:'Europe/London'}))+'</text>';});
      }
      const slotEnd=o=>{const raw=o.valid_to||o.local_to||o.end;const parsed=raw?new Date(raw).getTime():NaN;return Number.isFinite(parsed)?parsed:stamp(o)+1800000;};
      const bandRect=(start,end,klass,label)=>{const a=Math.max(t0,start),b=Math.min(t2,end);if(!(b>a))return '';const x1=x(a),x2=x(b);return '<rect class="'+klass+'" data-energy-band="'+label+'" x="'+x1.toFixed(1)+'" y="'+padT+'" width="'+Math.max(0,x2-x1).toFixed(1)+'" height="'+ih+'"><title>'+label+' · '+new Date(a).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})+'–'+new Date(b).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})+'</title></rect>';};
      const prices=published.map(o=>Number(o.import_p_per_kwh)).filter(Number.isFinite),bestPrice=prices.length?Math.min(...prices):NaN,greenThreshold=Number.isFinite(bestPrice)?Math.min(0,bestPrice):0;
      const freeBands=published.filter(o=>{const p=Number(o.import_p_per_kwh);return Number.isFinite(p)&&p<=greenThreshold;}).map(o=>bandRect(stamp(o),slotEnd(o),'band-free',Number(o.import_p_per_kwh)<0?'Negative-price electricity':'Free electricity')).join('');
      const powerdownWindows=[...powerdownEvents,...powerdownHistory.flatMap(st=>Array.isArray(st?.attributes?.joined_events)?st.attributes.joined_events:[])];
      const seenPowerdown=new Set();
      const powerdownBands=this.period()==='year'?'':powerdownWindows.map(e=>{const a=new Date(e.start).getTime(),rawEnd=new Date(e.end).getTime(),b=isToday?Math.min(rawEnd,t1):rawEnd,key=a+'|'+b;if(isToday&&a>=t1)return '';if(seenPowerdown.has(key))return '';seenPowerdown.add(key);return Number.isFinite(a)&&Number.isFinite(b)?bandRect(a,b,'band-powerdown','Power down'):'';}).join('');
      const bands=powerdownBands+freeBands;
      const powerdownLegend=powerdownBands?'<span><i class="dot" style="background:#ef5547"></i>Power Down</span>':'';
      const tomorrowPublished=longRange||published.some(o=>stamp(o)>=t1),tomorrowMessage=tomorrowPricingStatus==='unavailable'?'Prices unavailable':tomorrowPricingStatus==='partial'?'Partial prices':'',blank=isToday&&tomorrowMessage?'<text class="axis" data-tomorrow-pricing="'+tomorrowPricingStatus+'" x="'+(midnight+iw*tomorrowShare/2)+'" y="'+(padT+ih/2)+'" text-anchor="middle">'+tomorrowMessage+'</text>':isRollingDay&&!published.length?'<text class="axis" x="'+((midnight+W-padR)/2)+'" y="'+(padT+ih/2)+'" text-anchor="middle">Prices not yet available</text>':!isToday&&!isRollingDay&&!tomorrowPublished?'<text class="axis" x="'+((midnight+W-padR)/2)+'" y="'+(padT+ih/2)+'" text-anchor="middle">Prices not yet available</text>':'';
      if(!flow)return '<svg class="chart" viewBox="0 0 '+W+' '+H+'">'+bands+grid+axes+blank+'<path class="price" d="'+pricePath+'"/><path class="use" d="'+path(cost,y)+'"/></svg><div class="legendrow"><span><i class="dot" style="background:#ffad18"></i>Electricity price</span><span><i class="dot" style="background:#1e9cf0"></i>Electricity used cost</span><span><i class="dot" style="background:#ef5547"></i>Gas cost</span>'+powerdownLegend+'</div>';
      let bars='';todayReport.forEach(o=>{if(['week','month','year'].includes(this.period()))return;const xx=x(stamp(o)),house=Math.max(0,Number(o.domestic_import_cost_gbp)||0),batt=Math.max(0,Number(o.battery_charge_import_cost_gbp)||0),standing=standingChargeFor(o),ex=Math.max(0,Number(o.export_earnings_gbp)||0),bw=Math.max(3,iw/(isToday?48:96)*.62),h1=Math.max(0,y(0)-y(house)),h2=Math.max(0,y(0)-y(batt)),he=Math.max(0,y(-ex)-y(0)),base=y(0);bars+='<rect class="bar-house" x="'+xx+'" y="'+(base-h1)+'" width="'+bw+'" height="'+h1+'"/><rect class="bar-batt" x="'+xx+'" y="'+(base-h1-h2)+'" width="'+bw+'" height="'+h2+'"/><rect class="bar-standing" x="'+xx+'" y="'+(base-h1-h2-Math.max(0,y(0)-y(standing)))+'" width="'+bw+'" height="'+Math.max(0,y(0)-y(standing))+'"/><rect class="bar-export" x="'+xx+'" y="'+base+'" width="'+bw+'" height="'+he+'"/>';});
      return '<svg class="chart" viewBox="0 0 '+W+' '+H+'">'+bands+grid+axes+blank+bars+'<path class="price" d="'+pricePath+'"/></svg><div class="legendrow"><span><i class="dot" style="background:#168cff"></i>House usage</span><span><i class="dot" style="background:#8756d8"></i>Battery charging</span><span><i class="dot" style="background:#20a86b"></i>Grid export</span><span><i class="dot"></i>Standing charge</span><span><i class="dot" style="background:#ffad18"></i>Electricity price</span></div>';
    };
    let body='';
    if(mode==='domestic'){
      const used=selectedUsage, exp=this.val('sensor.lifeos_export_energy');
      body=`<div class="panel"><div class="panelhead"><div class="panelcopy"><div class="heading">Domestic energy consumption</div><div class="sub">${this._energyHistoryError||("Electricity used, excluding battery and car charging · "+selectedLabel+(this._energyHistoryLoading?" · Loading history…":" · Available history "+(this._energyCoverage??0).toFixed(1)+"%"+(this._energyCoverage<99?" · Partial history":"")))}</div></div></div><div class="chartslot">${svgChart(false)}</div></div>
      <div class="cards"><div class="metric"><b>⌂ Electricity used</b><div class="big">${selectedRows.length&&pricedRows.length===selectedRows.length&&this._energyCoverage>=99?'£'+selectedCost.toFixed(2):'—'}</div><div class="small">${selectedRows.length?used.toFixed(2)+' kWh':'No history available'}<br>${selectedAvgPrice===null?'Price or interval coverage incomplete':selectedAvgPrice.toFixed(1)+' p/kWh avg'} · ${selectedLabel}</div></div>
      
      <div class="metric"><b>♨ Gas used (current)</b><div class="big">${this.money('sensor.octopus_energy_gas_e6e16309692443_2200667301_previous_accumulative_cost')}</div><div class="small">${this.val('sensor.octopus_energy_gas_e6e16309692443_2200667301_previous_accumulative_consumption_kwh').toFixed(2)} kWh</div></div>
      <div class="metric"><b>▤ Current total energy cost</b><div class="big">£${(this.val('sensor.lifeos_domestic_import_cost')+this.val('sensor.octopus_energy_gas_e6e16309692443_2200667301_previous_accumulative_cost')).toFixed(2)}</div><div class="small">Live sensor totals; electricity above follows the selected period.</div></div></div>`;
    } else if(mode==='flow'){
      const [chargeStart,chargeEnd]=this.periodWindow(),chargeStartParts=this.londonParts(chargeStart),chargeEndParts=this.londonParts(chargeEnd),standingDays=Math.max(1,(Date.UTC(chargeEndParts.year,chargeEndParts.month-1,chargeEndParts.day)-Date.UTC(chargeStartParts.year,chargeStartParts.month-1,chargeStartParts.day))/86400000),standingTotal=.50*standingDays; body=`<div class="panel"><div class="heading">Full energy flow</div><div class="sub">Grid import and export split by source. Includes house usage, battery charging/discharging and car charging.</div><div class="chartslot">${svgChart(true)}</div></div>
      <div class="cards"><div class="metric"><b>▤ Standing charge</b><div class="big">£${standingTotal.toFixed(2)}</div><div class="small">1p / half-hour · +2p at 23:30 · 50p/day</div></div><div class="metric"><b>⌂ House usage</b><div class="big">${this.money('sensor.lifeos_domestic_import_cost')}</div></div><div class="metric"><b>▣ Battery</b><div class="big">${this.val('sensor.lifeos_energy_battery_soc').toFixed(0)}%</div></div><div class="metric"><b>🚗 Car (EV)</b><div class="big">Not installed</div><div class="small">Charge only · £0 · 0 kWh</div></div><div class="metric"><b>↑ Export earnings</b><div class="big">-${this.money('sensor.lifeos_export_earnings')}</div></div></div>`;
    } else if(mode==='home'){
      body=`<div class="status"><div class="secure">⚪ Security sensors not installed</div><div class="leave">⌂ Leave House<br><span class="small">Automation pending</span></div></div><div class="panel"><div class="heading">Ground Floor</div><div class="floor">Replaceable ground-floor plan · overlays dormant until mapped</div></div><div class="panel"><div class="heading">First Floor</div><div class="floor">Replaceable first-floor plan · overlays dormant until mapped</div></div><div class="panel legend">🟩 Window open　🟥 Window closed　🟩 External door open　🟥 External door closed　🟢 Light off　🔴 Light on　🟩 TV on　🟥 TV off　⚪ ! unavailable</div>`;
    }
    else { const doorbell=window.LifeOSHouseStatusDevModules?.doorbell; body=doorbell?.render?doorbell.render(this._hass):'<div class="panel"><div class="heading">Doorbell</div><div class="floor">DOORBELL MODULE UNAVAILABLE</div></div>'; }
    this.innerHTML=css+`<div class="app">${nav}${body}</div>`; this._doorbellHost=null; if(mode==='doorbell'){const host=this.querySelector('[data-doorbell-card]');this._doorbellHost=host;if(host)host.__lifeosDoorbellHass=this._hass;const doorbell=window.LifeOSHouseStatusDevModules?.doorbell;doorbell?.mount?.(host,this._hass);}
    const menu=this.querySelector('.hamb');if(menu){const openMenu=()=>this.dispatchEvent(new CustomEvent('hass-toggle-menu',{bubbles:true,composed:true}));menu.onclick=openMenu;menu.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openMenu();}};}
    this.querySelectorAll('[data-mode]').forEach(el=>el.onclick=()=>{this._mode=el.dataset.mode;this.render();});
    this.querySelectorAll('[data-period]').forEach(el=>el.onclick=()=>{const p=el.dataset.period;this._energyHistoryKey=null;if(p==='range'){this._period='range';this.render();const picker=this.querySelector('[data-date-picker]');if(picker?.showPicker)picker.showPicker();else picker?.click();return;}this._period=p;this._energyHistory=[];this._energyCoverage=null;this.render();this._loadEnergyHistory();});
    this.querySelectorAll('[data-shift]').forEach(el=>el.onclick=()=>this.shiftPeriod(Number(el.dataset.shift)));
    const picker=this.querySelector('[data-date-picker]');if(picker)picker.onchange=()=>{if(!picker.value)return;const [y,m,d]=picker.value.split('-').map(Number);const chosen=this.londonDate(y,m,d);if(Number.isNaN(chosen.getTime()))return;this._anchor=chosen;this._energyHistoryKey=null;this._energyHistory=[];this._energyCoverage=null;this.render();this._loadEnergyHistory();};
  }
  async _loadEnergyHistory(){
    if(!this._hass)return;
    const period=this.period(),[start,end]=this.periodWindow();
    const now=Date.now(),effectiveEnd=Math.min(end.getTime(),now);
    if(effectiveEnd<=start.getTime()){this._energyHistory=[];this._energyHistoryError=null;this.render();return;}
    const useRollups=true;
    const key=period+'|'+start.toISOString()+'|'+effectiveEnd;
    if(this._energyHistoryKey===key||this._energyHistoryRequestedKey===key)return;
    this._energyHistoryController?.abort();
    const requestId=(this._energyHistoryRequestId||0)+1;
    this._energyHistoryRequestId=requestId;
    this._energyHistoryRequestedKey=key;
    this._energyHistoryController=new AbortController();
    this._energyHistory=[];
    this._energyCoverage=null;
    this._energyHistoryLoading=true;
    this.render();
    this._energyHistoryError=null;
    try{
      let url;
      if(useRollups){
        const apiOrigin=new URL(window.location.origin);
        apiOrigin.port='8110';
        url=new URL('/api/energy/rollups',apiOrigin).toString()+'?start='+Math.floor(start.getTime()/1000)+
          '&end='+Math.ceil(effectiveEnd/1000)+'&granularity=30m';
      }else{
        // The report endpoint is relative to now, so include the selected historical
        // day through now and filter its half-hour rows below.
        const hours=Math.max(1,Math.min(840,Math.ceil((now-start.getTime())/3600000)+2));
        const apiOrigin=new URL(window.location.origin);
        apiOrigin.port='8110';
        url=new URL('/api/energy/report',apiOrigin).toString()+'?hours='+hours;
      }
      const data=await fetch(url,{credentials:'omit',signal:this._energyHistoryController.signal}).then(r=>{
        if(!r.ok)throw new Error('energy history HTTP '+r.status);
        return r.json();
      });
      this._energyTimezone=data?.timezone||this._energyTimezone||'Europe/London';
      if(requestId!==this._energyHistoryRequestId)return;
      const reportedCoverage=Number(data?.coverage_percent);
      this._energyCoverage=Number.isFinite(reportedCoverage)?Math.max(0,Math.min(100,reportedCoverage)):0;
      const intervals=useRollups
        ?(Array.isArray(data?.points)?data.points:[]).map(o=>({
          valid_from:new Date(Number(o.timestamp)*1000).toISOString(),
          domestic_import_kwh:Number(o.domestic_import_kwh)||0,
          import_kwh:Number(o.grid_import_kwh)||0,
          export_kwh:Number(o.grid_export_kwh)||0,
          production_kwh:Number(o.production_kwh)||0,
          consumption_kwh:Number(o.consumption_kwh)||0,
          import_p_per_kwh:o.import_p_per_kwh,
          import_price_available:o.import_price_available,
          domestic_import_cost_gbp:o.domestic_import_cost_gbp,
          sample_count:o.sample_count,
          sample_coverage_percent:o.sample_coverage_percent
        }))
        :(Array.isArray(data?.intervals)?data.intervals:[]);
      this._energyHistory=intervals.filter(o=>{
        const t=new Date(o.valid_from||o.local_from||o.start||0).getTime();
        return Number.isFinite(t)&&t>=start.getTime()&&t<end.getTime();
      });
      this._energyHistoryKey=key;
      this._energyHistoryError=null;
    }catch(e){
      if(requestId!==this._energyHistoryRequestId)return;
      if(e?.name!=='AbortError'){
        console.warn('House Status DEV source-backed energy history load failed',e);
        this._energyHistory=[];
        this._energyHistoryError='Historical electricity data is temporarily unavailable.';
      }
    }finally{
      if(requestId===this._energyHistoryRequestId){
        this._energyHistoryLoading=false;
        this._energyHistoryRequestedKey=null;
        this._energyHistoryController=null;
        this.render();
      }
    }
  }

  async _loadPowerdownHistory(){
    if(!this._hass)return;
    const entity='event.octopus_energy_a_8b23e5b8_octoplus_power_down_events';
    try{
      const end=new Date(),start=new Date(end.getTime()-8*86400000);
      const rows=await this._hass.callApi('GET','history/period/'+start.toISOString()+'?filter_entity_id='+encodeURIComponent(entity)+'&end_time='+encodeURIComponent(end.toISOString())+'&minimal_response=0&no_attributes=0');
      this._history=this._history||{};this._history[entity]=Array.isArray(rows?.[0])?rows[0]:[];this.render();
    }catch(_e){}
  }

}
if(!customElements.get('lifeos-house-status-dev')) customElements.define('lifeos-house-status-dev',LifeOSHouseStatusCard);
window.customCards=window.customCards||[];window.customCards.push({type:'lifeos-house-status-dev',name:'LifeOS House Status Development v2',description:'Reference-locked House Status UI'});

class LifeOSHouseStatusEditor extends HTMLElement { setConfig(config){this.config=config;} set hass(hass){this._hass=hass;} }
if(!customElements.get('lifeos-house-status-dev-editor-v2')) customElements.define('lifeos-house-status-dev-editor-v2',LifeOSHouseStatusEditor);

