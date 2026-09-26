class LifeOSHouseStatusCard extends HTMLElement {
  static getStubConfig(){ return {mode:'domestic'}; }
  static getConfigElement(){ return document.createElement('lifeos-house-status-editor'); }
  setConfig(config){ this.config=config||{}; this.render(); }
  set hass(hass){ this._hass=hass; this.render(); }
  getCardSize(){ return 10; }
  val(id,def=0){ const s=this._hass?.states?.[id]; const n=Number(s?.state); return Number.isFinite(n)?n:def; }
  money(id){ return '£'+this.val(id).toFixed(2); }
  render(){
    if(!this._hass) return;
    const mode=this.config?.mode||'domestic';
    const css=`<style>
      :host{display:block;--bg:#061720;--panel:#081c27;--line:#163747;--text:#f4f7f9;--muted:#b8c6ce;--blue:#168cff}
      *{box-sizing:border-box}.app{background:linear-gradient(145deg,#061720,#031018);color:var(--text);border-radius:14px;padding:14px;font-family:var(--paper-font-body1_-_font-family,Arial,sans-serif)}
      .top{display:flex;align-items:center;gap:14px;margin-bottom:12px}.title{font-size:25px;font-weight:800;flex:1}.tabs,.period{display:flex;border:1px solid var(--line);border-radius:7px;overflow:hidden}.tab,.p{padding:10px 20px;color:var(--muted);border-right:1px solid var(--line);white-space:nowrap}.active{background:var(--blue);color:white}.date{border:1px solid var(--line);border-radius:7px;padding:9px 15px;color:var(--muted)}
      .panel{border:1px solid var(--line);border-radius:10px;background:rgba(6,25,35,.82);padding:12px;margin-top:10px}.heading{font-size:20px;font-weight:750}.sub{color:var(--muted);margin:4px 0 8px}.chartslot{min-height:360px;position:relative;border-top:1px solid rgba(255,255,255,.03);overflow:hidden}.chart{width:100%;height:300px}.gridline{stroke:#47606c;stroke-dasharray:4 5;opacity:.65}.axis{fill:#b8c6ce;font-size:11px}.priceaxis{fill:#ffbf45}.price{fill:none;stroke:#ffad18;stroke-width:3}.use{fill:none;stroke:#1e9cf0;stroke-width:4}.export{fill:none;stroke:#ef5547;stroke-width:4}.bar-house{fill:#168cff}.bar-batt{fill:#8756d8}.bar-export{fill:#20a86b}.soc{fill:none;stroke:#a9b7c0;stroke-width:2;stroke-dasharray:5 4}.legendrow{display:flex;gap:18px;justify-content:center;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:7px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}
      .cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:10px}.metric{border:1px solid var(--line);border-radius:9px;background:rgba(6,25,35,.9);padding:15px;min-height:132px}.metric b{display:block;font-size:16px}.big{font-size:29px;font-weight:800;margin:13px 0 6px}.small{color:var(--muted);line-height:1.5}
      .floor{min-height:320px;display:flex;align-items:center;justify-content:center;border:1px dashed #31566a;border-radius:8px;color:var(--muted);background:#071923}.status{display:grid;grid-template-columns:1fr 1fr;gap:10px}.secure,.leave{padding:14px;border-radius:9px;font-size:18px;font-weight:750}.secure{border:1px solid #237d61;background:#0a3a31}.leave{border:1px solid #a43a4a;background:#501a25;text-align:center}.legend{display:flex;gap:22px;flex-wrap:wrap;color:var(--muted);font-size:13px}
      @media(max-width:850px){.app{padding:10px}.top{flex-wrap:wrap}.title{flex-basis:100%}.tabs,.period{width:100%;overflow:auto}.tab,.p{flex:1;text-align:center;padding:8px 6px;font-size:12px}.date{width:100%;text-align:center}.cards{grid-template-columns:repeat(2,1fr)}.chartslot{min-height:300px}.status{grid-template-columns:1fr}.floor{min-height:240px}}
    </style>`;
    const nav=`<div class="top"><div class="title">⌂ House Status</div><div class="date">${new Date().toLocaleDateString('en-GB',{weekday:'short',day:'2-digit',month:'short',year:'numeric'})}</div></div>
      <div class="top"><div class="tabs"><div class="tab ${mode==='domestic'?'active':''}">Domestic Energy Consumption</div><div class="tab ${mode==='flow'?'active':''}">Full Energy Flow</div><div class="tab ${mode==='home'?'active':''}">Home Status</div></div>${mode!=='home'?'<div class="period"><div class="p active">Today</div><div class="p">Day</div><div class="p">Month</div><div class="p">Year</div><div class="p">Date range</div></div>':''}</div>`;
    const report=this._hass.states['sensor.lifeos_energy_report']?.attributes?.intervals||[];
    const tariff=this._hass.states['sensor.lifeos_energy_tariff_horizon']?.attributes?.slots||[];
    const octopusTariff=this._hass.states['sensor.lifeos_energy_tariff_horizon'];
    const svgChart=(flow=false)=>{
      const W=1000,H=350,pad=45, iw=W-pad*2, ih=H-pad*2;
      const pts=(arr,key,scale=1)=>arr.map((x,i)=>{const v=Number(x[key]);if(!Number.isFinite(v))return null;const xx=pad+(i/Math.max(1,arr.length-1))*iw;return [xx,v*scale]}).filter(Boolean);
      const price=pts(tariff.filter(x=>x.import_price_available===true && x.import_p_per_kwh!==null),'import_p_per_kwh');
      const cost=pts(report,'domestic_import_cost_gbp',1), exp=pts(report,'export_earnings_gbp',1);
      const all=[...cost,...exp].map(x=>x[1]); let lo=Math.min(0,...all),hi=Math.max(.01,...all); const y=v=>pad+ih-(v-lo)/(hi-lo||1)*ih; const pvals=price.map(x=>x[1]); const plo=Math.min(0,...pvals),phi=Math.max(1,...pvals); const py=v=>pad+ih-(v-plo)/(phi-plo||1)*ih;
      const path=(a,fy=y)=>a.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+fy(p[1]).toFixed(1)).join(' ');
      let grid='';for(let i=0;i<5;i++){const yy=pad+i*ih/4;grid+='<line class="gridline" x1="'+pad+'" y1="'+yy+'" x2="'+(W-pad)+'" y2="'+yy+'"/>';}
      const ylabels=[0,1,2,3,4].map(i=>{const yy=pad+i*ih/4;const cv=hi-(hi-lo)*i/4;const pv=phi-(phi-plo)*i/4;return '<text class="axis" x="'+(pad-8)+'" y="'+(yy+4)+'" text-anchor="end">£'+cv.toFixed(2)+'</text><text class="axis priceaxis" x="'+(W-pad+8)+'" y="'+(yy+4)+'">'+pv.toFixed(1)+'p</text>';}).join('');
      const labels=tariff.filter(x=>x.import_price_available===true&&x.import_p_per_kwh!==null);const xlabels=labels.filter((_,i)=>i%12===0||i===labels.length-1).map((x,i,a)=>{const idx=labels.indexOf(x);const xx=pad+(idx/Math.max(1,labels.length-1))*iw;const d=new Date(x.local_from);return '<text class="axis" x="'+xx+'" y="'+(H-12)+'" text-anchor="middle">'+d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})+'</text>';}).join('');
      if(!flow)return '<svg class="chart" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+grid+ylabels+xlabels+'<text class="axis" x="8" y="18">Cost (£)</text><text class="axis priceaxis" x="'+(W-8)+'" y="18" text-anchor="end">Octopus price (p/kWh)</text><path class="price" d="'+path(price,py)+'"/><path class="use" d="'+path(cost)+'"/><path class="export" d="'+path(exp)+'"/></svg><div class="legendrow"><span><i class="dot" style="background:#ffad18"></i>Electricity price</span><span><i class="dot" style="background:#1e9cf0"></i>Electricity used cost</span><span><i class="dot" style="background:#ef5547"></i>Export earnings</span></div>';
      const n=Math.max(1,report.length),bw=Math.max(3,iw/n*.62);let bars='';
      report.forEach((x,i)=>{const xx=pad+i/n*iw;const house=Math.max(0,Number(x.domestic_import_kwh)||0), batt=Math.max(0,Number(x.battery_charge_import_kwh)||0), ex=Math.max(0,Number(x.grid_export_kwh)||0);const k=ih/Math.max(.01,...report.map(r=>(Number(r.domestic_import_kwh)||0)+(Number(r.battery_charge_import_kwh)||0)+(Number(r.grid_export_kwh)||0)));const h1=house*k,h2=batt*k,he=ex*k;bars+='<rect class="bar-house" x="'+xx+'" y="'+(pad+ih-h1)+'" width="'+bw+'" height="'+h1+'"/><rect class="bar-batt" x="'+xx+'" y="'+(pad+ih-h1-h2)+'" width="'+bw+'" height="'+h2+'"/><rect class="bar-export" x="'+xx+'" y="'+(pad+ih)+'" width="'+bw+'" height="'+he+'"/>';});
      return '<svg class="chart" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+grid+bars+'<path class="price" d="'+path(price)+'"/></svg><div class="legendrow"><span><i class="dot" style="background:#168cff"></i>House usage</span><span><i class="dot" style="background:#8756d8"></i>Battery charging</span><span><i class="dot" style="background:#20a86b"></i>Grid export</span><span><i class="dot" style="background:#ffad18"></i>Electricity price</span></div>';
    };
    let body='';
    if(mode==='domestic'){
      const used=this.val('sensor.lifeos_domestic_import_energy'), exp=this.val('sensor.lifeos_export_energy');
      body=`<div class="panel"><div class="heading">Domestic energy consumption</div><div class="sub">Octopus tariff: ${octopusTariff?.attributes?.import_tariff||'unavailable'} · published half-hourly prices only</div><div class="chartslot">${svgChart(false)}</div></div>
      <div class="cards"><div class="metric"><b>⌂ Electricity used</b><div class="big">${this.money('sensor.lifeos_domestic_import_cost')}</div><div class="small">${used.toFixed(2)} kWh<br>${this.val('sensor.lifeos_average_import_price').toFixed(1)} p/kWh avg</div></div>
      <div class="metric"><b>↑ Export earnings</b><div class="big">${this.money('sensor.lifeos_export_earnings')}</div><div class="small">${exp.toFixed(2)} kWh<br>${this.val('sensor.lifeos_average_export_price').toFixed(1)} p/kWh avg</div></div>
      <div class="metric"><b>♨ Gas used</b><div class="big">${this.money('sensor.octopus_energy_gas_e6e16309692443_2200667301_previous_accumulative_cost')}</div><div class="small">${this.val('sensor.octopus_energy_gas_e6e16309692443_2200667301_previous_accumulative_consumption_kwh').toFixed(2)} kWh</div></div>
      <div class="metric"><b>▤ Total energy cost</b><div class="big">£${(this.val('sensor.lifeos_domestic_import_cost')+this.val('sensor.octopus_energy_gas_e6e16309692443_2200667301_previous_accumulative_cost')-this.val('sensor.lifeos_export_earnings')).toFixed(2)}</div><div class="small">Electricity + gas − export</div></div></div>`;
    } else if(mode==='flow'){
      body=`<div class="panel"><div class="heading">Full energy flow</div><div class="sub">Grid import and export split by source. Includes house usage, battery charging/discharging and car charging.</div><div class="chartslot">${svgChart(true)}</div></div>
      <div class="cards"><div class="metric"><b>⌂ House usage</b><div class="big">${this.money('sensor.lifeos_domestic_import_cost')}</div></div><div class="metric"><b>▣ Battery</b><div class="big">${this.val('sensor.lifeos_energy_battery_soc').toFixed(0)}%</div></div><div class="metric"><b>🚗 Car (EV)</b><div class="big">Not installed</div><div class="small">Charge only · £0 · 0 kWh</div></div><div class="metric"><b>↑ Export earnings</b><div class="big">-${this.money('sensor.lifeos_export_earnings')}</div></div></div>`;
    } else {
      body=`<div class="status"><div class="secure">⚪ Security sensors not installed</div><div class="leave">⌂ Leave House<br><span class="small">Automation pending</span></div></div><div class="panel"><div class="heading">Ground Floor</div><div class="floor">Replaceable ground-floor plan · overlays dormant until mapped</div></div><div class="panel"><div class="heading">First Floor</div><div class="floor">Replaceable first-floor plan · overlays dormant until mapped</div></div><div class="panel legend">🟩 Window open　🟥 Window closed　🟩 External door open　🟥 External door closed　🟢 Light off　🔴 Light on　🟩 TV on　🟥 TV off　⚪ ! unavailable</div>`;
    }
    this.innerHTML=css+`<div class="app">${nav}${body}</div>`;
  }
}
if(!customElements.get('lifeos-house-status')) customElements.define('lifeos-house-status',LifeOSHouseStatusCard);
window.customCards=window.customCards||[];window.customCards.push({type:'lifeos-house-status',name:'LifeOS House Status',description:'Reference-locked House Status UI'});

class LifeOSHouseStatusEditor extends HTMLElement { setConfig(config){this.config=config;} set hass(hass){this._hass=hass;} }
if(!customElements.get('lifeos-house-status-editor')) customElements.define('lifeos-house-status-editor',LifeOSHouseStatusEditor);
