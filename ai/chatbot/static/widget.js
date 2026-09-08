(function() {
  // ⚙️ Backend URL — apne Ubuntu ka IP/domain daalo
  const API_URL = "http://192.168.0.216:8002/chat";

  let lastData = null;
  let history = [];   // pichhle 4 turns yaad rakho (user + bot)

  // ── Styles ──
  const style = document.createElement('style');
  style.textContent = `
    #floreto-fab { position:fixed; bottom:24px; right:24px; width:60px; height:60px; border-radius:50%;
      background:linear-gradient(135deg,#8b5cf6,#6366f1); box-shadow:0 4px 20px rgba(99,102,241,.5);
      cursor:pointer; z-index:99999; display:flex; align-items:center; justify-content:center;
      transition:transform .2s; border:none; }
    #floreto-fab:hover { transform:scale(1.08); }
    #floreto-fab svg { width:28px; height:28px; fill:#fff; }
    #floreto-panel { position:fixed; bottom:96px; right:24px; width:380px; max-width:calc(100vw - 32px);
      height:540px; max-height:calc(100vh - 130px); background:#1a1a1a; border-radius:16px;
      box-shadow:0 8px 40px rgba(0,0,0,.5); z-index:99999; display:none; flex-direction:column;
      overflow:hidden; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
    #floreto-panel.open { display:flex; }
    #floreto-head { padding:14px 18px; background:#252525; border-bottom:1px solid #333;
      display:flex; align-items:center; gap:8px; }
    #floreto-head .d { width:8px; height:8px; border-radius:50%; background:#4ade80; box-shadow:0 0 6px #4ade80; }
    #floreto-head h3 { font-size:15px; color:#fff; font-weight:600; margin:0; }
    #floreto-head .x { margin-left:auto; background:none; border:none; color:#888; cursor:pointer; font-size:20px; }
    #floreto-msgs { flex:1; overflow-y:auto; padding:16px; }
    .fm { margin-bottom:14px; }
    .fm .b { display:inline-block; padding:9px 13px; border-radius:12px; font-size:14px; line-height:1.5;
      max-width:85%; white-space:pre-wrap; word-wrap:break-word; }
    .fm.u { text-align:right; }
    .fm.u .b { background:#3b82f6; color:#fff; position:relative; }
    .fm.u { position:relative; }
       .fm.u .edit-btn { position:absolute; left:-4px; top:6px; background:none; border:none;
      color:#666; cursor:pointer; font-size:13px; opacity:0; transition:opacity .15s; padding:2px 6px; }
    .fm.u:hover .edit-btn { opacity:1; }
    .fm.u .edit-btn:hover { color:#8b5cf6; }
    .fm.a { position:relative; }
    .fm.a .copy-btn { background:none; border:none; color:#666; cursor:pointer; font-size:12px;
      opacity:0; transition:opacity .15s; padding:3px 8px; margin-top:4px; display:block; }
    .fm.a:hover .copy-btn { opacity:1; }
    .fm.a .copy-btn:hover { color:#8b5cf6; }
    .fm.a .b { background:#2a2a2a; color:#e8e8e8; }
    .fm table { border-collapse:collapse; margin-top:8px; font-size:11px; width:100%; }
    .fm th,.fm td { border:1px solid #3a3a3a; padding:4px 7px; text-align:left; color:#ddd; }
    .fm th { background:#252525; }
    .fm .dl { margin-top:8px; padding:5px 12px; background:#8b5cf6; color:#fff; border:none;
      border-radius:6px; cursor:pointer; font-size:12px; }
    .think { display:inline-flex; align-items:center; gap:7px; color:#8b5cf6; }
    .think .txt { background:linear-gradient(90deg,#666 25%,#c4b5fd 50%,#666 75%);
      background-size:200% 100%; -webkit-background-clip:text; background-clip:text;
      -webkit-text-fill-color:transparent; animation:shimmer 1.6s linear infinite; font-size:13px; }
    @keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }
    .think .dots span { display:inline-block; width:5px; height:5px; border-radius:50%;
      background:#8b5cf6; margin:0 1.5px; animation:bounce 1.2s infinite; }
    .think .dots span:nth-child(2){ animation-delay:.2s }
    .think .dots span:nth-child(3){ animation-delay:.4s }
    @keyframes bounce { 0%,60%,100%{transform:translateY(0);opacity:.4}
                        30%{transform:translateY(-5px);opacity:1} }
    #floreto-input { padding:12px; border-top:1px solid #333; display:flex; gap:8px; }
    #floreto-input input { flex:1; background:#252525; border:1px solid #3a3a3a; border-radius:8px;
      color:#fff; padding:9px 12px; font-size:14px; outline:none; }
    #floreto-input button { padding:9px 16px; background:#8b5cf6; color:#fff; border:none;
      border-radius:8px; cursor:pointer; font-weight:500; }
    #floreto-input button:disabled { opacity:.5; }
  `;
  document.head.appendChild(style);

  // ── FAB button ──
  const fab = document.createElement('button');
  fab.id = 'floreto-fab';
  // ✨ AI sparkle icon — dekhte hi lage AI hai
  fab.innerHTML = `<svg viewBox="0 0 24 24">
    <path d="M12 2l1.9 5.8L20 9.7l-5.1 3.7 1.9 5.8L12 15.9 7.2 19.2l1.9-5.8L4 9.7l6.1-1.9L12 2z"/>
    <circle cx="19" cy="5" r="1.6"/>
    <circle cx="5.5" cy="17.5" r="1.2"/>
  </svg>`;
  document.body.appendChild(fab);

  // ── Panel ──
  const panel = document.createElement('div');
  panel.id = 'floreto-panel';
  panel.innerHTML = `
    <div id="floreto-head">
      <span class="d"></span>
      <h3>Ustaad AI Investigator</h3>
      <button class="x" id="floreto-x">&times;</button>
    </div>
    <div id="floreto-msgs">
<div class="fm a">
<div class="b">Ustaad Ai ✨<br>Namaste! 👋 Aapka swagat hai. Bataiye, main aapki kya madad kar sakta hoon?</div></div>
    </div>
    <div id="floreto-input">
      <input id="floreto-q" placeholder="Ask..." autocomplete="off">
      <button id="floreto-send">➤</button>
    </div>
  `;
  document.body.appendChild(panel);

  const msgs = panel.querySelector('#floreto-msgs');
  const inp = panel.querySelector('#floreto-q');
  const sendBtn = panel.querySelector('#floreto-send');

  fab.onclick = () => { panel.classList.toggle('open'); if(panel.classList.contains('open')) inp.focus(); };
  panel.querySelector('#floreto-x').onclick = () => panel.classList.remove('open');

  function esc(s){ return String(s).replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

    // HTTP pe clipboard API block hoti hai — ye purana tareeka fallback hai
  function fallbackCopy(text, cb){
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); cb && cb(); } catch(e) {}
    document.body.removeChild(ta);
  }

  function addMsg(who, html, rawText){
    const d = document.createElement('div');
    d.className = 'fm ' + who;
    if(who === 'u'){
      d.innerHTML = `<button class="edit-btn" title="Edit">✎</button><div class="b">${html}</div>`;
      d.dataset.raw = rawText || '';
      d.querySelector('.edit-btn').onclick = () => {
        inp.value = d.dataset.raw;
        inp.focus();
        let n = d.nextSibling;
        while(n){ const nx = n.nextSibling; n.remove(); n = nx; }
        d.remove();
        // history bhi kaat do — is message ke baad ka sab hataao
        const idx = history.findIndex(h => h.role === 'user' && h.text === d.dataset.raw);
        if(idx >= 0) history = history.slice(0, idx);
      };
    } else {
      d.innerHTML = `<div class="b">${html}</div><button class="copy-btn" title="Copy">⧉ Copy</button>`;
      d.querySelector('.copy-btn').onclick = (e) => {
        const txt = d.querySelector('.b').innerText;
        const done = () => {
          e.target.textContent = '✓ Copied';
          setTimeout(() => e.target.textContent = '⧉ Copy', 1500);
        };
        // HTTPS pe clipboard API, HTTP pe purana tareeka (fallback)
        if (navigator.clipboard && window.isSecureContext) {
          navigator.clipboard.writeText(txt).then(done).catch(() => fallbackCopy(txt, done));
        } else {
          fallbackCopy(txt, done);
        }
      };
    }
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
    return d;
  }

  // sirf ye columns table me dikhao (kaam ke); CSV me poora raw jayega
  const NICE_COLS = ['createdAt','date','credit','debit','closing','fromUser','toUser','amount','method','remark',
                     'transactionType','actionType','clientname','agentname','marketName','betType','stake',
                     'profitLoss','status','availableBalance','exposure','bonus','utrNumber','fullName','AccountTypecheck'];

  function renderTable(data){
    if(!data || !data.rows || !data.rows.length) return '';
    const rows = data.rows;
    // NICE_COLS jo is data me actually hain, usi order me
    let keys = NICE_COLS.filter(k => k in rows[0]);
    if(!keys.length) keys = Object.keys(rows[0]).filter(k => !['_id','__v','userId','browser','browserDetails'].includes(k));
    let h = '<table><tr>' + keys.map(k=>`<th>${esc(k)}</th>`).join('') + '</tr>';
    rows.slice(0,20).forEach(r => {
      h += '<tr>' + keys.map(k=>{
        let v = r[k]; if(v===''||v==null) v='-';
        return `<td>${esc(v)}</td>`;
      }).join('') + '</tr>';
    });
    h += '</table>';
    if(rows.length>20) h += `<div style="color:#888;font-size:11px;margin-top:4px">+${rows.length-20} aur (CSV me poora)</div>`;
    h += '<button class="dl" onclick="__floretoDL()">⬇ CSV</button>';
    h += '<button class="dl" style="margin-left:6px;background:#ef4444" onclick="__floretoPDF()">⬇ PDF</button>';
    return h;
  }

  window.__floretoDL = function(){
    if(!lastData || !lastData.rows || !lastData.rows.length) return;
    const rows = lastData.rows;
    // SAARI rows se saare unique fields nikaalo (bet rows me alag, deposit rows me alag)
    const allKeys = new Set();
    rows.forEach(r => Object.keys(r).forEach(k => allKeys.add(k)));
    const keys = Array.from(allKeys);
    let csv = keys.join(',') + '\n';
    rows.forEach(r => csv += keys.map(k=>`"${String(r[k]??'').replace(/"/g,'""')}"`).join(',') + '\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
    a.download = `${lastData.user||'data'}_${lastData.collection||'export'}.csv`;
    a.click();
  };


   window.__floretoPDF = function(){
    if(!lastData || !lastData.rows || !lastData.rows.length) return;
    const rows = lastData.rows;

    // saare unique columns (CSV jaise)
    const allKeys = new Set();
    rows.forEach(r => Object.keys(r).forEach(k => allKeys.add(k)));
    const cols = Array.from(allKeys);

    const esc2 = v => {
      if (v === null || v === undefined || v === '') return '-';
      // nested object/array ko padhne layak banao ([object Object] ki jagah)
      if (typeof v === 'object') {
        try { v = JSON.stringify(v); } catch(e) { v = String(v); }
      }
      return String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    };
    const title = `${lastData.user || 'Data'} — ${lastData.collection || ''}`;

    // 8 se kam columns = normal TABLE, zyada = CARD layout (padhne me saaf)
    // 6 tak columns = table (statement/balance saaf table me), zyada = card
    const useTable = cols.length <= 6;

    let body = '';
    if (useTable) {
      body = `<table><thead><tr>${cols.map(c=>`<th>${esc2(c)}</th>`).join('')}</tr></thead><tbody>`;
      rows.forEach(r => {
        body += '<tr>' + cols.map(c => `<td>${esc2(r[c])}</td>`).join('') + '</tr>';
      });
      body += '</tbody></table>';
    } else {
      rows.forEach((r, i) => {
        body += `<div class="card"><div class="card-h">#${i+1}</div><div class="grid">`;
        cols.forEach(c => {
          const v = r[c];
          if (v === null || v === undefined || v === '') return;   // khali fields skip
          body += `<div class="k">${esc2(c)}</div><div class="v">${esc2(v)}</div>`;
        });
        body += '</div></div>';
      });
    }

    const html = `<html><head><meta charset="utf-8"><title>${esc2(title)}</title><style>
      *{box-sizing:border-box}
      body{font-family:Arial,Helvetica,sans-serif;padding:18px;font-size:12px;color:#000;line-height:1.45}
      h2{font-size:19px;margin:0 0 4px;color:#111}
      .sub{color:#555;font-size:11px;margin-bottom:16px}
      table{border-collapse:collapse;width:100%;font-size:11px}
      th,td{border:1px solid #999;padding:7px 9px;text-align:left;vertical-align:top;word-break:break-word}
      th{background:#e8e8e8;white-space:nowrap;font-weight:bold;font-size:11px}
      tr:nth-child(even) td{background:#f7f7f7}
      thead{display:table-header-group}
      tr{page-break-inside:avoid}
      .card{border:1.5px solid #bbb;border-radius:6px;margin-bottom:12px;padding:12px 14px;page-break-inside:avoid}
      .card-h{font-weight:bold;font-size:13px;color:#5b21b6;margin-bottom:9px;
              border-bottom:2px solid #ddd;padding-bottom:5px}
      .grid{display:grid;grid-template-columns:130px 1fr;gap:6px 12px}
      .k{color:#555;font-size:11px;text-align:right;font-weight:600;padding-top:1px}
      .v{font-size:12px;word-break:break-word;color:#000}
      @page{size:A4 portrait;margin:12mm}
      </style></head><body>
      <h2>${esc2(title)}</h2>
      <div class="sub">${rows.length} entries • ${new Date().toLocaleString()} • Ustaad AI Investigator</div>
      ${body}
      </body></html>`;

    const w = window.open('', '_blank');
    w.document.write(html);
    w.document.close();
    setTimeout(() => w.print(), 500);
  };


  async function send(){
    const q = inp.value.trim();
    if(!q) return;
    addMsg('u', esc(q), q);
    inp.value = '';
    sendBtn.disabled = true;
    const t = addMsg('a', '<span class="think"><span class="txt">Deep thinking</span>' +
      '<span class="dots"><span></span><span></span><span></span></span></span>');
     try {
      const res = await fetch(API_URL, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({message: q, history: history.slice(-8)})   // pichhle 4 turns
      });
      const data = await res.json();
      lastData = data.data;
      let html = esc(data.reply||'Kuch nahi mila.').replace(/\*\*(.*?)\*\*/g,'<b>$1</b>');
      // Table/CSV/PDF SIRF tab dikhao jab user ne saaf mange (download/csv/pdf/excel/table/list)
      const wantsDownload = /\b(csv|pdf|excel|download|downlod|table|list dikhao|list do)\b/i.test(q);
      if(data.data && wantsDownload) html += renderTable(data.data);
      t.querySelector('.b').innerHTML = html;
      // history me daalo (aage ke sawaal ke liye)
      history.push({role:'user', text:q});
      history.push({role:'bot', text:(data.reply||'').slice(0,300)});   // short rakho
    } catch(e) {
      t.querySelector('.b').innerHTML = '⚠️ ' + esc(e.message);
    }
    sendBtn.disabled = false;
    inp.focus();
    msgs.scrollTop = msgs.scrollHeight;
  }

  sendBtn.onclick = send;
  inp.onkeydown = (e) => { if(e.key==='Enter') send(); };
})();
