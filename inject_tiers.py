import sys

with open('dashboard/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Add CSS
css_inject = """
.tier-blurred {
    filter: blur(4px);
    opacity: 0.5;
    pointer-events: none;
    user-select: none;
}
.tier-overlay {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: var(--gold);
    font-weight: bold;
    font-size: 11px;
    text-align: center;
    background: rgba(0,0,0,0.85);
    padding: 8px 12px;
    border-radius: 4px;
    border: 1px solid var(--gold);
    z-index: 10;
    width: max-content;
}
.opt-rec { position: relative; }
</style>
"""
html = html.replace('</style>', css_inject)

# 2. Add Header Toggle
header_find = """  <div class="status">"""
header_inject = """  <div style="display:flex; gap:15px; align-items:center;">
    <select id="tierSelect" style="background:#111; color:var(--gold); border:1px solid var(--border); padding:4px 8px; border-radius:4px; font-size:11px; font-weight:bold; cursor:pointer; outline:none;">
        <option value="elite">ELITE TIER</option>
        <option value="pro">PRO TIER</option>
        <option value="free">FREE TIER</option>
    </select>
    <div class="status">"""
html = html.replace(header_find, header_inject)
html = html.replace('    <span id="statusText" style="font-size:12px;color:var(--text2)">Connecting...</span>\n    <span style="font-size:10px;color:var(--text2);margin-left:8px">ScriptMasterLabs™</span>\n  </div>\n</div>', 
                    '    <span id="statusText" style="font-size:12px;color:var(--text2)">Connecting...</span>\n    <span style="font-size:10px;color:var(--text2);margin-left:8px">ScriptMasterLabs™</span>\n    </div>\n  </div>\n</div>')

# 3. JS listeners
js_init_find = "const allSignals = {};"
js_init_inject = """const tierSelect = document.getElementById('tierSelect');
tierSelect.addEventListener('change', () => { renderAllSignals(); pollFlow(); });
function getTier() { return tierSelect.value; }
"""
html = html.replace("let allSignals = {};", js_init_inject + "let allSignals = {};")

# 4. JS options logic
options_find = """    optEl.innerHTML = allOptions.map((o,i) => {
      const emoji = i===0?'🥇':i===1?'🥈':i===2?'🥉':'▪️';
      return '<div class="opt-rec" style="margin-bottom:6px">' +
        '<div style="display:flex;justify-content:space-between;align-items:center">' +
        '<span class="strike">' + emoji + ' ' + o.parent_symbol + ' ' + o.direction + ' $' + o.strike.toFixed(2) + '</span>' +
        '<span class="badge ' + badgeClass(o.confidence) + '">' + o.confidence + '</span></div>' +
        '<div style="color:var(--gold);font-weight:600;margin-top:2px">' + o.expiration + ' (' + o.dte + ' DTE)</div>' +
        '<div class="details">Δ ' + o.delta.toFixed(2) + ' | $' + o.bid.toFixed(2) + '/$' + o.ask.toFixed(2) +
        ' | Vol ' + o.volume.toLocaleString() + ' | OI ' + o.open_interest.toLocaleString() +
        ' | IV ' + (o.iv*100).toFixed(0) + '% | Score ' + o.score.toFixed(0) + '</div></div>';
    }).join('');"""
options_inject = """    optEl.innerHTML = allOptions.map((o,i) => {
      const emoji = i===0?'🥇':i===1?'🥈':i===2?'🥉':'▪️';
      const tier = getTier();
      let blurClass = '';
      let overlay = '';
      if (tier === 'free') {
          blurClass = 'tier-blurred';
          overlay = '<div class="tier-overlay">UPGRADE TO PRO/ELITE<br><span style="font-size:9px;color:var(--text2);font-weight:normal">To Unlock Options Recs</span></div>';
      } else if (tier === 'pro' && i > 0) {
          blurClass = 'tier-blurred';
          overlay = '<div class="tier-overlay">UPGRADE TO ELITE<br><span style="font-size:9px;color:var(--text2);font-weight:normal">To Unlock Full Chain</span></div>';
      }
      return '<div class="opt-rec" style="margin-bottom:6px">' + overlay +
        '<div class="' + blurClass + '">' +
        '<div style="display:flex;justify-content:space-between;align-items:center">' +
        '<span class="strike">' + emoji + ' ' + o.parent_symbol + ' ' + o.direction + ' $' + o.strike.toFixed(2) + '</span>' +
        '<span class="badge ' + badgeClass(o.confidence) + '">' + o.confidence + '</span></div>' +
        '<div style="color:var(--gold);font-weight:600;margin-top:2px">' + o.expiration + ' (' + o.dte + ' DTE)</div>' +
        '<div class="details">Δ ' + o.delta.toFixed(2) + ' | $' + o.bid.toFixed(2) + '/$' + o.ask.toFixed(2) +
        ' | Vol ' + o.volume.toLocaleString() + ' | OI ' + o.open_interest.toLocaleString() +
        ' | IV ' + (o.iv*100).toFixed(0) + '% | Score ' + o.score.toFixed(0) + '</div></div></div>';
    }).join('');"""
html = html.replace(options_find, options_inject)

# 5. JS flow logic
flow_find = """    flowEl.innerHTML = entries.slice(0,50).map(([sym, f]) => {"""
flow_inject = """    const tier = getTier();
    if (tier === 'free') {
      const dummy = entries.slice(0,6).map(([sym, f]) => {
          const bp = f.metrics?.buy_pct||50;
          return '<div class="flow-row"><span class="sym">???</span>' +
            '<span style="color:var(--text2);font-size:11px;min-width:50px">????</span>' +
            '<div class="bar-wrap"><div class="bar-inner" style="width:50%;background:var(--text2)"></div></div>' +
            '<span style="min-width:40px;text-align:right">--</span></div>';
      }).join('');
      flowEl.innerHTML = '<div style="position:relative;height:100%;"><div class="tier-overlay" style="position:absolute;top:50px;">UPGRADE TO PRO/ELITE<br><span style="font-size:9px;color:var(--text2);font-weight:normal">To Unlock Real-Time Flow</span></div><div class="tier-blurred">' + dummy + '</div></div>';
      return;
    }
    flowEl.innerHTML = entries.slice(0,50).map(([sym, f]) => {"""
html = html.replace(flow_find, flow_inject)

with open('dashboard/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Injected UI tier logic successfully.")
