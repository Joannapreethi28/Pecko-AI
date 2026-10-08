'use strict';

const icons = {
  wave:'<path d="M3 10v4m4-7v10m5-14v18m5-15v12m4-9v6"/>',
  chart:'<path d="M4 3v17h17M8 14v3m5-8v8m5-12v12"/>',
  layers:'<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
  folder:'<path d="M3 7V5h6l2 2h10v13H3V7Z"/>',
  leaf:'<path d="M20 3c1 11-4 17-10 16C1 17 4 7 11 7c3 0 6-1 9-4Z M4 22l10-12"/>',
  expand:'<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
  close:'<path d="m6 6 12 12M18 6 6 18"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 3M4 16l2 3a8 8 0 0 0 13-3"/>',
  route:'<circle cx="5" cy="6" r="2"/><circle cx="19" cy="18" r="2"/><path d="M7 6h9a4 4 0 0 1 0 8H8a4 4 0 0 0 0 8h5"/>',
  brain:'<path d="M12 5a3 3 0 0 0-5-2 4 4 0 0 0-3 6 4 4 0 0 0 0 7 4 4 0 0 0 5 5 3 3 0 0 0 3-3V5Zm0 0a3 3 0 0 1 5-2 4 4 0 0 1 3 6 4 4 0 0 1 0 7 4 4 0 0 1-5 5 3 3 0 0 1-3-3M7 8c3 0 3 4 0 4m10-4c-3 0-3 4 0 4M7 17h1m8 0h1"/>',
  volume:'<path d="m11 4-6 5H2v6h3l6 5V4Zm4 4a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
  mic:'<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/>',
  lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 4v3"/>',
  chip:'<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/>',
  'arrow-right':'<path d="M4 12h16m-6-6 6 6-6 6"/>',
  'arrow-up':'<path d="M12 20V4m-6 6 6-6 6 6"/>',
  external:'<path d="M14 3h7v7m0-7L10 14M10 3H4v17h17v-6"/>',
  play:'<path d="m9 5 11 7-11 7V5Z" fill="currentColor" stroke="none"/>',
  pause:'<path d="M8 5v14M16 5v14" stroke-width="4"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
  download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  file:'<path d="M14 2H5v20h14V7l-5-5Zm0 0v6h5M8 12h8m-8 4h6"/>',
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const svg = (name) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.file}</svg>`;
function applyIcons(root = document) { root.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = svg(el.dataset.icon); }); }
function node(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; }
const number = (value, digits = 1) => Number.isFinite(value) ? value.toLocaleString('en-US', {maximumFractionDigits: digits}) : 'Unavailable';
const sourceURL = path => '/source/' + String(path).split('/').map(encodeURIComponent).join('/');
let evidence = null;
let sending = false;
let replayTimers = [];

applyIcons();
const wave = $('#hero-wave');
const heights = [9,13,18,11,25,35,24,46,63,51,76,93,68,102,86,108,88,72,97,81,60,72,47,62,42,29,38,20,27,14,18,10];
heights.forEach((height, index) => {
  const bar = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  bar.setAttribute('x', 10 + index * 9.5); bar.setAttribute('y', (136 - height) / 2);
  bar.setAttribute('width', '4.5'); bar.setAttribute('height', height); bar.setAttribute('rx', '2.25');
  bar.setAttribute('fill', index < 7 || index > 25 ? '#a9bda3' : index < 12 || index > 21 ? '#6c9670' : '#2c674c');
  wave.append(bar);
});

const pageNames = {studio:'Demo studio', benchmarks:'Benchmarks', pipeline:'How it works', evidence:'Evidence library'};
function navigate() {
  const requested = location.hash.slice(1);
  const page = pageNames[requested] ? requested : 'studio';
  $$('.page').forEach(el => { el.hidden = el.id !== `page-${page}`; });
  $$('.nav-item').forEach(el => { const active = el.dataset.page === page; el.classList.toggle('active', active); if (active) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current'); });
  $('#breadcrumb-current').textContent = pageNames[page];
  document.title = `Pecko · ${pageNames[page]}`;
  if (page !== 'studio') $('#sample-audio').pause();
  if (page !== 'pipeline') stopReplay();
}
addEventListener('hashchange', () => { navigate(); window.scrollTo({top:0, behavior:'instant'}); $('#main').focus({preventScroll:true}); });
navigate();

function showError(message) {
  const banner = $('#connection-banner'); banner.replaceChildren(node('span', '', message));
  const retry = node('button', '', 'Retry'); retry.addEventListener('click', loadWorkspace); banner.append(retry); banner.hidden = false;
}
async function request(url, options = {}) {
  const response = await fetch(url, {...options, signal: AbortSignal.timeout(options.method ? 65000 : 5000)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || 'The local server could not complete this request.');
  return data;
}
async function refreshStatus() {
  const button = $('#refresh-status'); button.disabled = true;
  try {
    const status = await request('/api/status');
    $('#router-status').textContent = status.router.available ? `Ready · ${status.router.intents} intents` : 'Setup required';
    $('#router-status').classList.toggle('is-ready', status.router.available);
    $('#model-status').textContent = status.llm.available ? 'Connected locally' : 'Not connected';
    $('#model-status').classList.toggle('is-ready', status.llm.available);
    $('#prompt').maxLength = status.demo.max_text_length || 1000;
    $('#connection-banner').hidden = true;
    if (!status.router.available) showError(status.router.error || 'The intent router is unavailable. Check the frontend setup instructions.');
  } catch (error) {
    $('#router-status').textContent = 'Server unreachable'; $('#model-status').textContent = 'Unknown';
    $('#router-status').classList.remove('is-ready'); $('#model-status').classList.remove('is-ready');
    showError('The local server is unreachable. Start Pecko with python -m frontend, then retry.');
  } finally { button.disabled = false; }
}
$('#refresh-status').addEventListener('click', refreshStatus);

function appendMessage(role, text, metadata) {
  const message = node('article', `message ${role}`);
  if (role === 'assistant') { const label = node('div','message-label'); label.innerHTML = svg('wave'); label.append(node('span','','Pecko')); message.append(label); }
  message.append(node('p','',text));
  if (metadata) {
    const meta = node('div','message-meta');
    const names = {cached:'Cached intent', composed:'Composed locally', llm:'Local language model', unavailable:'Unavailable'};
    meta.append(node('span','tag neutral', metadata.available ? names[metadata.route] || metadata.route : 'Model / setup unavailable'));
    meta.append(node('span','',`${number(metadata.elapsed_ms,2)} ms · text response`));
    if (metadata.source) { const link=node('a','','Source'); link.href=sourceURL(metadata.source); link.target='_blank'; link.rel='noopener'; meta.append(link); }
    message.append(meta);
  }
  $('#messages').append(message); $('#conversation-body').scrollTop = $('#conversation-body').scrollHeight;
  return message;
}
async function sendMessage(text) {
  if (sending || !text.trim()) return;
  sending = true; $('#welcome').hidden = true;
  $('#prompt').value = ''; $('#send-button').disabled = true;
  $$('[data-prompt]').forEach(button => { button.disabled = true; });
  appendMessage('user', text.trim());
  const pending = appendMessage('assistant', 'Thinking locally'); pending.classList.add('pending');
  $('#composer-status').textContent = 'Working on your request…';
  try {
    const result = await request('/api/chat', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text.trim()})});
    pending.remove(); appendMessage('assistant', result.text, result);
    $('#composer-status').textContent = 'Typed input · no microphone';
  } catch (error) {
    pending.remove(); appendMessage('assistant', 'I couldn’t reach the local server. Check that Pecko is running, then try your message again.');
    $('#prompt').value = text; $('#composer-status').textContent = 'Message restored · try again';
  } finally {
    sending = false; $('#send-button').disabled = false; $$('[data-prompt]').forEach(button => { button.disabled = false; });
    $('#prompt').focus({preventScroll:true});
  }
}
$('#chat-form').addEventListener('submit', event => { event.preventDefault(); sendMessage($('#prompt').value); });
$$('[data-prompt]').forEach(button => button.addEventListener('click', () => sendMessage(button.dataset.prompt)));

const metricConfig = {
  ttft_p50_ms:{unit:'ms',description:'Milliseconds · lower is better',digits:1},
  peak_memory_mb:{unit:'MB',description:'Peak cgroup memory · lower is better',digits:1},
  decode_tps:{unit:'tok/s',description:'Tokens per second · higher is better',digits:1},
};
function renderChart(metric='ttft_p50_ms') {
  if (!evidence) return;
  const config = metricConfig[metric];
  $('#chart-unit').textContent = config.description;
  $$('[data-metric]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.metric === metric)));
  const chart = $('#model-chart'); chart.replaceChildren();
  const max = Math.max(...evidence.models.map(model => model[metric] || 0), 1);
  evidence.models.forEach(model => {
    const row=node('div',`chart-row${model.selected?' selected':''}`);
    const label=node('span','chart-label',model.name); if(model.selected) label.append(node('i'));
    const track=node('div','chart-track'); const fill=node('div','chart-fill'); fill.style.width=`${model[metric]/max*100}%`; track.append(fill);
    row.append(label,track,node('span','chart-value',`${number(model[metric],config.digits)} ${config.unit}`));chart.append(row);
  });
}
$$('[data-metric]').forEach(button => button.addEventListener('click',()=>renderChart(button.dataset.metric)));
function renderBenchmarks() {
  const tbody=$('#model-table');tbody.replaceChildren();
  evidence.models.forEach(model => {
    const row=node('tr');const name=node('td','',model.name);if(model.selected) name.append(node('span','tag','Provisional'));
    name.append(node('small','',`${model.quantization} · n = ${model.turns}`));row.append(name);
    [`${number(model.ttft_p50_ms)} ms`,`${number(model.ttft_p90_ms)} ms`,`${number(model.decode_tps)} tok/s`,`${number(model.peak_memory_mb)} MB`].forEach(value=>row.append(node('td','',value)));tbody.append(row);
  });
  renderChart();
  const grid=node('div','voice-grid');const cache=evidence.voice.cache;
  function comparison(title,rows,benefit) {
    const section=node('div');section.append(node('h3','',title));
    rows.forEach(([label,value])=>{const row=node('div','compare-row');row.append(node('span','',label),node('strong','',value));section.append(row);});
    section.append(node('p','compare-benefit',benefit));return section;
  }
  grid.append(comparison('Reuse a familiar answer',[
    ['Without cache',`${number(cache.baseline_cpu_ms_per_turn)} ms CPU / turn`],
    ['With cache',`${number(cache.cpu_ms_per_turn)} ms CPU / turn`],
    ['First PCM from cache',`${cache.first_pcm_from_cache} turns`],
  ],`${number(cache.cpu_reduction_percent)}% lower CPU time in this cache experiment.`));
  const sentence=evidence.voice.chunking.find(row=>row.policy==='sentence');const adaptive=evidence.voice.chunking.find(row=>row.policy==='adaptive');
  if(sentence && adaptive) grid.append(comparison('Speak in smaller clauses',[
    ['Whole sentence · p50',`${number(sentence.p50_ms,0)} ms`],['Adaptive chunks · p50',`${number(adaptive.p50_ms,0)} ms`],
    ['Adaptive chunks · p90',`${number(adaptive.p90_ms,0)} ms`],
  ],`${adaptive.turns} scripted turns · ${adaptive.turns_with_gaps} turns with gaps in this experiment.`));
  $('#voice-comparison').replaceChildren(grid);
}

const audio = $('#sample-audio');
function updateAudioButton() { const button=$('#audio-play');button.innerHTML=svg(audio.paused?'play':'pause');button.setAttribute('aria-label',audio.paused?'Play recorded voice sample':'Pause recorded voice sample'); }
function loadSample() {
  audio.pause();audio.src=$('#sample-select').value;$('#audio-progress-fill').style.width='0%';
  $('#audio-feedback').classList.add('sr-only');$('#audio-feedback').textContent='';
  $('#audio-play').disabled=false; updateAudioButton();
  const sample=evidence.samples.find(item=>item.url===audio.getAttribute('src'));
  $('#audio-play').title=sample ? `Recorded sample: ${sample.description}` : 'Play recorded sample';
}
$('#sample-select').addEventListener('change',loadSample);
$('#audio-play').addEventListener('click',async()=>{
  if (!audio.paused) { audio.pause();return; }
  try { await audio.play();$('#audio-feedback').classList.add('sr-only');$('#audio-feedback').textContent='Playing the selected recorded sample.'; }
  catch(error) { if(error.name==='AbortError')return;$('#audio-feedback').classList.remove('sr-only');$('#audio-feedback').textContent='Audio could not play. Check the server and select another sample.'; }
});
audio.addEventListener('play',updateAudioButton);audio.addEventListener('pause',updateAudioButton);audio.addEventListener('ended',updateAudioButton);
audio.addEventListener('timeupdate',()=>{ $('#audio-progress-fill').style.width=Number.isFinite(audio.duration)?`${audio.currentTime/audio.duration*100}%`:'0%'; });
audio.addEventListener('error',()=>{ if(!audio.getAttribute('src'))return;$('#audio-feedback').classList.remove('sr-only');$('#audio-feedback').textContent='This recorded sample is unavailable. Select another sample or restart the local server.';updateAudioButton(); });

function renderSources() {
  const term=$('#evidence-search').value.trim().toLowerCase();const list=$('#source-list');list.replaceChildren();
  const sources=evidence.sources.filter(item=>`${item.name} ${item.path} ${item.kind}`.toLowerCase().includes(term));
  const kinds={measured:'Measured',synthetic:'Synthetic',documentation:'Documentation',audio:'Recorded audio',implementation:'Source code'};
  sources.forEach(item=>{
    const link=node('a','source-row');link.href=sourceURL(item.path);link.target='_blank';link.rel='noopener';
    const icon=node('span');icon.innerHTML=svg(item.kind==='audio'?'volume':'file');
    const text=node('div');text.append(node('h3','',item.name),node('p','',item.path));
    const external=node('span');external.innerHTML=svg('external');
    link.append(icon,text,node('span',`tag ${item.kind==='synthetic'?'amber':'neutral'}`,kinds[item.kind]||item.kind),external);list.append(link);
  });
  $('#source-empty').hidden=sources.length>0;
}
$('#evidence-search').addEventListener('input',()=>{if(evidence)renderSources();});
function renderCapabilities() {
  const statuses={implemented:'Implemented','component-measured':'Measured component','synthetic-verified':'Synthetic verification',planned:'Specification',pending:'Pending'};
  const list=$('#capabilities');list.replaceChildren();
  evidence.capabilities.forEach(item=>{const row=node('div','capability-row');row.append(node('h3','',item.name),node('span',`tag ${['planned','pending'].includes(item.status)?'neutral':item.status==='synthetic-verified'?'amber':''}`,statuses[item.status]||item.status),node('p','',item.detail));list.append(row);});
}
$('#download-evidence').addEventListener('click',()=>{
  if(!evidence)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(evidence,null,2)],{type:'application/json'}));
  const link=node('a');link.href=url;link.download='pecko-evidence.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
});

function stopReplay() { replayTimers.forEach(clearTimeout);replayTimers=[];const button=$('#replay-button');button.disabled=!evidence;button.innerHTML=svg('play')+'Replay scenario'; }
function renderReplay() {
  const turn=evidence.replay.turns.find(item=>item.events.some(event=>event.type==='cancel'));
  const events=$('#replay-events');events.replaceChildren();
  if(!turn){events.append(node('p','muted small','No correction scenario is available in the recorded evidence.'));$('#replay-button').disabled=true;return;}
  const labels={partial:'Partial transcript',tentative_final:'Prepare privately',cancel:'Cancel previous work',final:'Final transcript'};
  turn.events.forEach(event=>{const row=node('div','replay-event muted');row.append(node('span','',`${number(event.at_s*1000,0)} ms`),node('span','',labels[event.type]||event.type));events.append(row);});
  const link=node('a','text-link','Inspect recorded events');link.href=sourceURL(evidence.replay.source);link.target='_blank';link.rel='noopener';events.append(link);
}
$('#replay-button').addEventListener('click',()=>{
  stopReplay();const turn=evidence?.replay.turns.find(item=>item.events.some(event=>event.type==='cancel'));if(!turn)return;
  $('#replay-button').disabled=true;$('#replay-button').textContent='Replaying recorded events…';
  const rows=$$('#replay-events .replay-event');rows.forEach(row=>row.classList.add('muted'));
  turn.events.forEach((event,index)=>{
    replayTimers.push(setTimeout(()=>{rows[index].classList.remove('muted');$('#replay-transcript').textContent=event.type==='cancel'?'Previous answer cancelled.':`“${event.text}”`;if(index===turn.events.length-1)stopReplay();},index*950));
  });
});
$('#present-button').addEventListener('click',async()=>{
  const presenting=document.body.classList.toggle('is-presenting');
  $('#present-button').innerHTML=svg(presenting?'close':'expand')+`<span>${presenting?'Exit presentation':'Present'}</span>`;
  $('#present-button').setAttribute('aria-pressed',String(presenting));
  try { if(presenting&&!document.fullscreenElement)await document.documentElement.requestFullscreen();else if(!presenting&&document.fullscreenElement)await document.exitFullscreen(); } catch(error) { /* Expanded layout works when the browser disallows fullscreen. */ }
});
document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement){document.body.classList.remove('is-presenting');$('#present-button').innerHTML=svg('expand')+'<span>Present</span>';$('#present-button').setAttribute('aria-pressed','false');}});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!document.fullscreenElement){document.body.classList.remove('is-presenting');$('#present-button').innerHTML=svg('expand')+'<span>Present</span>';$('#present-button').setAttribute('aria-pressed','false');}});

async function loadWorkspace() {
  $('#download-evidence').disabled=true;$('#replay-button').disabled=true;
  const results=await Promise.allSettled([refreshStatus(),request('/api/evidence')]);
  if(results[1].status==='fulfilled') {
    evidence=results[1].value;renderBenchmarks();renderSources();renderCapabilities();renderReplay();
    const select=$('#sample-select');select.replaceChildren();
    evidence.samples.forEach(sample=>{const option=node('option','',sample.name);option.value=sample.url;select.append(option);});
    if(evidence.samples.length)loadSample();
    $('#download-evidence').disabled=false;$('#replay-button').disabled=false;
  } else {
    showError('The evidence library could not load. Check that frontend/evidence.json exists, then retry.');
    $('#sample-select').replaceChildren(node('option','','Samples unavailable'));
  }
}
loadWorkspace();
