// The Guide: pick a character, talk to them. Everything they say comes from Rabbid's PC.
const $ = s => document.querySelector(s);
let cast = [], current = null, busy = false;

async function api(path, body) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Guide': '42' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `The Guide's PC said ${r.status}`);
  return data;
}

const esc = s => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// Small markdown: code blocks, inline code, bold, italics, headings, lists, paragraphs
function md(text) {
  const blocks = [];
  let s = esc(text).replace(/```[a-z]*\n?([\s\S]*?)```/g, (_, code) => `\u0000${blocks.push(code) - 1}\u0000`);
  s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>')
       .replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>')
       .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>');
  const out = [];
  for (const para of s.split(/\n{2,}/)) {
    const lines = para.split('\n');
    if (lines.every(l => /^\s*([-*•]|\d+[.)])\s+/.test(l))) {
      const tag = /^\s*\d/.test(lines[0]) ? 'ol' : 'ul';
      out.push(`<${tag}>${lines.map(l => `<li>${l.replace(/^\s*([-*•]|\d+[.)])\s+/, '')}</li>`).join('')}</${tag}>`);
    } else if (/^#{1,4}\s/.test(para)) {
      out.push(`<h3>${para.replace(/^#{1,4}\s/, '')}</h3>`);
    } else {
      out.push(`<p>${lines.join('<br>')}</p>`);
    }
  }
  return out.join('').replace(/\u0000(\d+)\u0000/g, (_, i) => `<pre><code>${blocks[i]}</code></pre>`);
}

function face(ch, cls = 'face') {
  return `<span class="${cls}" style="--c:${ch.color}">${ch.emoji}</span>`;
}

async function loadCast() {
  try {
    const d = await api('/api/characters');
    cast = d.characters;
    const card = ch => `
      <button class="card" data-id="${ch.id}" style="--c:${ch.color}">
        ${face(ch)}<b>${esc(ch.name)}</b><span class="tag">${esc(ch.brain)}</span><span class="quip">${esc(ch.quip)}</span>
        ${ch.count ? `<span class="badge">💬 ${ch.count}</span>` : ''}
      </button>`;
    $('#cast').innerHTML = cast.filter(c => !c.crew).map(card).join('');
    $('#crew').innerHTML = cast.filter(c => c.crew).map(card).join('');
  } catch (e) {
    $('#cast').innerHTML = `<p class="msg error">Can't reach the PC: ${esc(e.message)}. Is Tailscale on?</p>`;
  }
}

function bubble(role, text) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.innerHTML = role === 'assistant' ? md(text) : esc(text).replace(/\n/g, '<br>');
  $('#log').appendChild(div);
  return div;
}
const toBottom = () => { const l = $('#log'); l.scrollTop = l.scrollHeight; };

async function open(id) {
  current = cast.find(c => c.id === id);
  if (!current) return;
  const head = $('.chat-head');
  head.style.setProperty('--c', current.color);
  $('#who').innerHTML = `${face(current)}<div><b>${esc(current.name)}</b><small>${esc(current.brain)} · ${esc(current.where)}</small></div>`;
  $('#log').innerHTML = '';
  $('#home').classList.remove('on'); $('#chat').classList.add('on');
  try {
    const d = await api(`/api/chat/${id}`);
    if (!d.messages.length) hello();
    d.messages.forEach(m => bubble(m.role, m.text));
  } catch (e) { bubble('error', e.message); }
  toBottom();
}

function hello() {
  const div = document.createElement('div');
  div.className = 'hello';
  div.innerHTML = `${face(current)}<div>${esc(current.quip)}</div><div style="margin-top:8px">Say hi to ${esc(current.name)}.</div>`;
  $('#log').appendChild(div);
}

function home() {
  $('#chat').classList.remove('on'); $('#home').classList.add('on');
  current = null; loadCast();
}

async function send(e) {
  e && e.preventDefault();
  const box = $('#text'), text = box.value.trim();
  if (!text || busy || !current) return;
  busy = true; $('#send').disabled = true;
  $('.hello')?.remove();
  bubble('user', text); box.value = ''; grow();
  const wait = document.createElement('div');
  wait.className = 'thinking'; wait.style.setProperty('--c', current.color);
  wait.innerHTML = `${esc(current.name)} is thinking <i></i><i></i><i></i>`;
  $('#log').appendChild(wait); toBottom();
  const who = current.id;
  try {
    const d = await api(`/api/chat/${who}`, { text });
    wait.remove();
    if (current && current.id === who) bubble('assistant', d.reply);
  } catch (err) {
    wait.remove(); bubble('error', err.message);
  }
  busy = false; $('#send').disabled = false; toBottom();
}

function grow() { const t = $('#text'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 200) + 'px'; }

// The status strip: how the PC is doing, at a glance. Red only when something needs Rabbid.
function ago(t, now) {
  const m = Math.round((now - t) / 60);
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h} hr ago` : `${Math.round(h / 24)} days ago`;
}
async function loadStatus() {
  try {
    const s = await api('/api/status');
    const b = s.backup;
    const stale = !b.when || s.now - b.when > 3 * 3600;
    const hot = (s.cpu_temp || 0) >= 85 || (s.gpu && s.gpu.temp >= 83);
    const stats = [
      [`🌡 CPU ${s.cpu_temp ?? '?'}°` + (s.gpu ? ` · GPU ${s.gpu.temp}°` : ''), hot ? 'bad' : ''],
      [`🧠 Memory ${s.ram.used}/${s.ram.total} GB`, s.ram.used / s.ram.total > .9 ? 'bad' : ''],
      [b.running ? '💾 Backing up…' : `💾 Backup ${b.when ? ago(b.when, s.now) : 'never'}`, !b.ok || stale ? 'bad' : 'good'],
      [s.seagate ? '🗄 Seagate on' : '🗄 Seagate unplugged', s.seagate ? '' : 'bad'],
      [s.internet ? '🌐 Internet OK' : '🌐 Internet DOWN', s.internet ? 'good' : 'bad'],
      [s.local_awake ? '🤖 Local AIs awake' : '🤖 Local AIs asleep', s.local_awake ? 'good' : ''],
    ];
    $('#status').innerHTML = stats.map(([t, c]) => `<span class="stat ${c}">${esc(t)}</span>`).join('');
  } catch (e) {
    $('#status').innerHTML = `<span class="stat bad">Can't reach the PC. Is Tailscale on?</span>`;
  }
}

let toastTimer;
function toast(text, bad) {
  const t = $('#toast');
  t.textContent = text; t.className = `toast on${bad ? ' bad' : ''}`;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.className = 'toast', 6000);
}

$('.controls').addEventListener('click', async e => {
  const b = e.target.closest('button');
  if (!b || b.disabled) return;
  let body = {};
  if (b.dataset.do === 'say') {
    const text = prompt('What should the PC say out loud?');
    if (!text || !text.trim()) return;
    body = { text };
  } else if (!confirm(b.dataset.ask)) return;
  b.disabled = true;
  try { toast((await api(`/api/do/${b.dataset.do}`, body)).done); }
  catch (err) { toast(err.message, true); }
  b.disabled = false;
  loadStatus();
});

$('#cast').addEventListener('click', e => { const c = e.target.closest('.card'); if (c) open(c.dataset.id); });
$('#crew').addEventListener('click', e => { const c = e.target.closest('.card'); if (c) open(c.dataset.id); });
$('#back').addEventListener('click', home);
$('#ask').addEventListener('submit', send);
$('#text').addEventListener('input', grow);
$('#text').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) send(e); });
$('#clear').addEventListener('click', async () => {
  if (!current || busy || !confirm(`Start a brand-new conversation with ${current.name}?`)) return;
  await api(`/api/chat/${current.id}/clear`, {}).catch(() => {});
  $('#log').innerHTML = ''; hello();
});

// A quiet star field drifting behind the Guide
(function stars() {
  const c = $('#stars'), x = c.getContext('2d');
  let w, h, pts;
  const size = () => {
    const r = devicePixelRatio || 1;
    w = c.width = innerWidth * r; h = c.height = innerHeight * r;
    pts = Array.from({ length: 160 }, () => ({ x: Math.random() * w, y: Math.random() * h, z: Math.random() * .8 + .2 }));
  };
  size(); addEventListener('resize', size);
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  (function frame() {
    x.fillStyle = '#05070a'; x.fillRect(0, 0, w, h);
    for (const p of pts) {
      if (!still) { p.x -= p.z * .35; if (p.x < 0) p.x = w; }
      x.fillStyle = `rgba(200,242,106,${p.z * .7})`;
      x.fillRect(p.x, p.y, p.z * 2.2, p.z * 2.2);
    }
    if (!document.hidden) requestAnimationFrame(frame); else setTimeout(frame, 1000);
  })();
})();

loadCast(); loadStatus();
setInterval(() => { if (!document.hidden && !current) loadStatus(); }, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden && !current) { loadCast(); loadStatus(); } });
