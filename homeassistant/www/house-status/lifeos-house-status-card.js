class LifeOSHouseStatusCard extends HTMLElement {
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
      .panel{border:1px solid var(--line);border-radius:10px;background:rgba(6,25,35,.82);padding:12px;margin-top:10px}.heading{font-size:20px;font-weight:750}.sub{color:var(--muted);margin:4px 0 8px}.chartslot{min-height:360px;display:flex;align-items:center;justify-content:center;color:var(--muted);border-top:1px solid rgba(255,255,255,.03)}
      .cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:10px}.metric{border:1px solid var(--line);border-radius:9px;background:rgba(6,25,35,.9);padding:15px;min-height:132px}.metric b{display:block;font-size:16px}.big{font-size:29px;font-weight:800;margin:13px 0 6px}.small{color:var(--muted);line-height:1.5}
      .floor{min-height:320px;display:flex;align-items:center;justify-content:center;border:1px dashed #31566a;border-radius:8px;color:var(--muted);background:#071923}.status{display:grid;grid-template-columns:1fr 1fr;gap:10px}.secure,.leave{padding:14px;border-radius:9px;font-size:18px;font-weight:750}.secure{border:1px solid #237d61;background:#0a3a31}.leave{border:1px solid #a43a4a;background:#501a25;text-align:center}.legend{display:flex;gap:22px;flex-wrap:wrap;color:var(--muted);font-size:13px}
      @media(max-width:850px){.app{padding:10px}.top{flex-wrap:wrap}.title{flex-basis:100%}.tabs,.period{width:100%;overflow:auto}.tab,.p{flex:1;text-align:center;padding:8px 6px;font-size:12px}.date{width:100%;text-align:center}.cards{grid-template-columns:repeat(2,1fr)}.chartslot{min-height:300px}.status{grid-template-columns:1fr}.floor{min-height:240px}}
    </style>`;
    const nav=`<div class="top"><div class="title">⌂ House Status</div><div class="date">${new Date().toLocaleDateString('en-GB',{weekday:'short',day:'2-digit',month:'short',year:'numeric'})}</div></div>
      <div class="top"><div class="tabs"><div class="tab ${mode==='domestic'?'active':''}">Domestic Energy Consumption</div><div class="tab ${mode==='flow'?'active':''}">Full Energy Flow</div><div class="tab ${mode==='home'?'active':''}">Home Status</div></div>${mode!=='home'?'<div class="period"><div class="p active">Today</div><div class="p">Day</div><div class="p">Month</div><div class="p">Year</div><div class="p">Date range</div></div>':''}</div>`;
    let body='';
    if(mode==='domestic'){
      const used=this.val('sensor.lifeos_domestic_import_energy'), exp=this.val('sensor.lifeos_export_energy');
      body=`<div class="panel"><div class="heading">Domestic energy consumption</div><div class="sub">Electricity used (excluding battery and car charging), export and gas. Costs shown in £.</div><div class="chartslot">Energy chart is rendered by the paired ApexCharts card below this shell.</div></div>
      <div class="cards"><div class="metric"><b>⌂ Electricity used</b><div class="big">${this.money('sensor.lifeos_domestic_import_cost')}</div><div class="small">${used.toFixed(2)} kWh<br>${this.val('sensor.lifeos_average_import_price').toFixed(1)} p/kWh avg</div></div>
      <div class="metric"><b>↑ Export earnings</b><div class="big">-${this.money('sensor.lifeos_export_earnings')}</div><div class="small">${exp.toFixed(2)} kWh<br>${this.val('sensor.lifeos_average_export_price').toFixed(1)} p/kWh avg</div></div>
      <div class="metric"><b>♨ Gas used</b><div class="big">${this.money('sensor.octopus_energy_gas_e6e16309692443_2200667301_previous_accumulative_cost')}</div><div class="small">${this.val('sensor.octopus_energy_gas_e6e16309692443_2200667301_previous_accumulative_consumption_kwh').toFixed(2)} kWh</div></div>
      <div class="metric"><b>▤ Total energy cost</b><div class="big">£${(this.val('sensor.lifeos_domestic_import_cost')+this.val('sensor.octopus_energy_gas_e6e16309692443_2200667301_previous_accumulative_cost')-this.val('sensor.lifeos_export_earnings')).toFixed(2)}</div><div class="small">Electricity + gas − export</div></div></div>`;
    } else if(mode==='flow'){
      body=`<div class="panel"><div class="heading">Full energy flow</div><div class="sub">Grid import and export split by source. Includes house usage, battery charging/discharging and car charging.</div><div class="chartslot">Stacked energy-flow chart is rendered by the paired ApexCharts card below this shell.</div></div>
      <div class="cards"><div class="metric"><b>⌂ House usage</b><div class="big">${this.money('sensor.lifeos_domestic_import_cost')}</div></div><div class="metric"><b>▣ Battery</b><div class="big">${this.val('sensor.lifeos_energy_battery_soc').toFixed(0)}%</div></div><div class="metric"><b>🚗 Car (EV)</b><div class="big">Not installed</div><div class="small">Charge only · £0 · 0 kWh</div></div><div class="metric"><b>↑ Export earnings</b><div class="big">-${this.money('sensor.lifeos_export_earnings')}</div></div></div>`;
    } else {
      body=`<div class="status"><div class="secure">⚪ Security sensors not installed</div><div class="leave">⌂ Leave House<br><span class="small">Automation pending</span></div></div><div class="panel"><div class="heading">Ground Floor</div><div class="floor">Replaceable ground-floor plan · overlays dormant until mapped</div></div><div class="panel"><div class="heading">First Floor</div><div class="floor">Replaceable first-floor plan · overlays dormant until mapped</div></div><div class="panel legend">🟩 Window open　🟥 Window closed　🟩 External door open　🟥 External door closed　🟢 Light off　🔴 Light on　🟩 TV on　🟥 TV off　⚪ ! unavailable</div>`;
    }
    this.innerHTML=css+`<div class="app">${nav}${body}</div>`;
  }
}
customElements.define('lifeos-house-status',LifeOSHouseStatusCard);
window.customCards=window.customCards||[];window.customCards.push({type:'lifeos-house-status',name:'LifeOS House Status',description:'Reference-locked House Status UI'});
