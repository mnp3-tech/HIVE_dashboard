const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const demoMode = new URLSearchParams(location.search).get('demo') === '1';
const PREFS_KEY = 'hive.dashboard.preferences.v1';
function loadPrefs(){
  const raw = localStorage.getItem(PREFS_KEY);
  if(raw === 'reduced') return {density:'reduced', mode:'observe'};
  if(raw === 'full' || !raw) return {density:'full', mode:'observe'};
  try { const parsed = JSON.parse(raw); return {density: parsed.density || 'full', mode: parsed.mode || 'observe'}; }
  catch(_error) { return {density:'full', mode:'observe'}; }
}
const DENSITY_CYCLE = ['full', 'reduced', 'minimal'];
const prefs = loadPrefs();
const state = {memory:null, system:null, snapshot:null, workerPolicy:null, capabilities:null, cliWorkers:{items:[],evidence:null,error:null}, chat:{sessions:[],history:[],selected:null,evidence:null,error:null}, view:'overview', density:prefs.density, mode:prefs.mode, error:null};
function savePrefs(){ localStorage.setItem(PREFS_KEY, JSON.stringify({density:state.density, mode:state.mode})); }

const TASK_BUCKETS = ['queued', 'active', 'completed', 'blocked', 'unknown'];
const BUCKET_LABELS = {queued:'Queued', active:'Active', completed:'Completed', blocked:'Blocked', unknown:'Unknown status'};

function now(){ return Date.now(); }
function isoTime(value){ const date = new Date(value || 0); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); }
function age(value){ if(!value) return '—'; const timestamp=new Date(value).getTime(); if(!Number.isFinite(timestamp)) return '—'; const seconds = Math.max(0, Math.round((now() - timestamp) / 1000)); if(seconds < 60) return `${seconds}s`; if(seconds < 3600) return `${Math.round(seconds/60)}m`; return `${Math.round(seconds/3600)}h`; }
function tone(status){ const normalized = String(status || 'unknown').toLowerCase(); return ['working','running','active','ok','healthy','valid','alive','ready'].includes(normalized) ? 'ok' : ['blocked','offline','failed','critical','unavailable'].includes(normalized) ? 'fail' : ['waiting','degraded','stale','queued','auth_required'].includes(normalized) ? 'warn' : 'unknown'; }
function stateLabel(status){ return String(status || 'unknown').replaceAll('_',' ').toUpperCase(); }
function valueWithUnit(metric, fallback = '—'){ if(metric == null || metric.value == null) return fallback; return `${Number(metric.value).toFixed(metric.unit === '%' ? 0 : 1)}${metric.unit || ''}`; }
function metricDetail(metric){ if(!metric) return 'unavailable'; if(metric.validity === 'stale') return `stale · observed ${age(metric.observed_at)} ago`; if(metric.validity === 'unavailable') return metric.reason || 'unavailable'; return metric.source ? `${metric.source} · observed ${age(metric.observed_at)} ago` : `observed ${age(metric.observed_at)} ago`; }
function evidenceLine(evidence){ if(!evidence) return 'No evidence received from the adapter.'; const parts=[`source ${evidence.source || 'unknown'}`, `validity ${evidence.validity || 'unknown'}`]; if(evidence.observed_at) parts.push(`observed ${age(evidence.observed_at)} ago`); if(evidence.reason) parts.push(evidence.reason); return parts.join(' · '); }

function normalize(raw){
  const source = raw || {};
  const metrics = source.metrics || {};
  const events = source.events && Array.isArray(source.events.items) ? source.events.items : [];
  const eventsEvidence = source.events && source.events.evidence ? source.events.evidence : null;
  const projects = source.projects && Array.isArray(source.projects.items) ? source.projects.items : [];
  const projectsEvidence = source.projects && source.projects.evidence ? source.projects.evidence : null;
  const projectRegistry = source.project_registry && Array.isArray(source.project_registry.items) ? source.project_registry.items : [];
  const projectRegistryEvidence = source.project_registry && source.project_registry.evidence ? source.project_registry.evidence : null;
  const selfEvolution = source.self_evolution || {item:null,evidence:null};
  const tasks = source.tasks && Array.isArray(source.tasks.items) ? source.tasks.items : [];
  const tasksEvidence = source.tasks && source.tasks.evidence ? source.tasks.evidence : null;
  const workers = source.workers && Array.isArray(source.workers.items) ? source.workers.items : [];
  const workersEvidence = source.workers && source.workers.evidence ? source.workers.evidence : null;
  const localWorkers = source.local_workers && Array.isArray(source.local_workers.items) ? source.local_workers.items : [];
  const localWorkersEvidence = source.local_workers && source.local_workers.evidence ? source.local_workers.evidence : null;
  const adapters = source.adapters || {};
  const topology = source.topology || {status:'deferred', reason:'Topology visualization is deferred for this MVP.'};
  const readiness = source.readiness || {aggregate:'unknown', items:[], evidence:null};
  return {
    received_at: source.received_at || null,
    environment: source.environment || 'LOCAL / UNVERIFIED',
    core: source.core || {status:'unknown', reason:'No application health payload'},
    metrics,
    model_limits: source.model_limits && Array.isArray(source.model_limits.items) ? source.model_limits : null,
    events, eventsEvidence,
    projects, projectsEvidence,
    projectRegistry, projectRegistryEvidence, selfEvolution,
    tasks, tasksEvidence,
    workers, workersEvidence, localWorkers, localWorkersEvidence,
    adapters,
    topology,
    readiness,
  };
}

async function load(){
  $('#refresh-button').disabled = true;
  state.error = null;
  if(demoMode){ state.snapshot = normalize(demoSnapshot()); state.workerPolicy = demoWorkerPolicy(); state.capabilities = demoCapabilities(); state.chat = demoChat(); $('#demo-banner').hidden = false; }
  else {
    try { const response = await fetch('/api/dashboard/snapshot', {headers:{Accept:'application/json'}, cache:'no-store'}); if(!response.ok) throw new Error(`adapter returned HTTP ${response.status}`); state.snapshot = normalize(await response.json()); }
    catch(error){ state.error = error; state.snapshot = normalize(null); }
    try { const response = await fetch('/api/control/worker-policy', {headers:{Accept:'application/json'}, cache:'no-store'}); state.workerPolicy = response.ok ? await response.json() : null; }
    catch(_error){ state.workerPolicy = null; }
    try { const response = await fetch('/api/control/capabilities', {headers:{Accept:'application/json'}, cache:'no-store'}); state.capabilities = response.ok ? await response.json() : null; }
    catch(_error){ state.capabilities = null; }
    try { const response = await fetch('/api/local-workers/cli-status', {headers:{Accept:'application/json'}, cache:'no-store'}); state.cliWorkers = response.ok ? await response.json() : {items:[],evidence:{validity:'unavailable',reason:`CLI probe returned HTTP ${response.status}`}}; }
    catch(error){ state.cliWorkers = {items:[],evidence:{validity:'unavailable',reason:`CLI probe unavailable: ${error.message}`}}; }
    try { const response = await fetch('/api/memory/status', {headers:{Accept:'application/json'}, cache:'no-store', signal: AbortSignal.timeout(6000)}); state.memory = response.ok ? await response.json() : {error:`HTTP ${response.status}`}; }
    catch(error){ state.memory = {error:String(error.message||error)}; }
    try { const response = await fetch('/api/system/resources', {headers:{Accept:'application/json'}, cache:'no-store', signal: AbortSignal.timeout(6000)}); state.system = response.ok ? await response.json() : {error:`HTTP ${response.status}`}; }
    catch(error){ state.system = {error:String(error.message||error)}; }
    await loadChat();
  }
  render(); $('#refresh-button').disabled = false;
}

function safeChatText(value){
  const text=String(value||'').replace(/Bearer\s+[A-Za-z0-9._=-]+/gi,'[redacted]').replace(/(?:sk|gho|AKIA)[A-Za-z0-9._=-]{8,}/gi,'[redacted]').replace(/\s+/g,' ').trim();
  return text.length>240 ? `${text.slice(0,237)}…` : text;
}

async function loadChat(){
  state.chat={sessions:[],history:[],selected:null,evidence:null,error:null};
  try{
    const response=await fetch('/api/ao/sessions',{headers:{Accept:'application/json'},cache:'no-store'});
    if(!response.ok) throw new Error(`AO sessions HTTP ${response.status}`);
    const data=await response.json();
    const raw=Array.isArray(data.items) ? data.items : Array.isArray(data) ? data : [];
    state.chat.sessions=raw.map(item=>({id:item.id||'',name:item.displayName||item.name||item.id||'Unnamed session',status:item.status||item.activity||'unknown',harness:item.harness||'unknown'})).filter(item=>item.id);
    state.chat.evidence=data.evidence||null;
    const selected=state.chat.sessions.find(item=>item.id===state.chat.selected)||state.chat.sessions[0];
    if(!selected) return;
    state.chat.selected=selected.id;
    const history=await fetch(`/api/ao/sessions/${encodeURIComponent(selected.id)}/history`,{headers:{Accept:'application/json'},cache:'no-store'});
    if(!history.ok) throw new Error(`AO history HTTP ${history.status}`);
    const payload=await history.json();
    const items=Array.isArray(payload.items) ? payload.items : Array.isArray(payload) ? payload : [];
    state.chat.history=items.slice(-8).map(item=>({role:item.role||item.author||'event',text:safeChatText(item.text||item.content||item.message||''),timestamp:item.timestamp||item.created_at||null})).filter(item=>item.text);
    state.chat.evidence=payload.evidence||state.chat.evidence;
  }catch(error){ state.chat.error=error; }
}

const evidenceByKey = {};
function setText(id, text){ const element = $(`#${id}`); if(element) element.textContent = text; }
function render(){
  const snapshot = state.snapshot || normalize(null);
  document.body.classList.toggle('reduced-motion', state.density !== 'full');
  document.body.classList.toggle('density-minimal', state.density === 'minimal');
  document.body.classList.remove('mode-command','mode-observe','mode-focus'); document.body.classList.add(`mode-${state.mode}`);
  $$('.mode-button').forEach(button=>button.classList.toggle('active', button.dataset.mode === state.mode));
  const densityButton = $('#density-toggle'); if(densityButton){ densityButton.setAttribute('aria-pressed', String(state.density !== 'full')); densityButton.textContent = state.density === 'full' ? '◌' : state.density === 'reduced' ? '◍' : '●'; }
  setText('rail-mode', state.mode.toUpperCase()); setText('rail-density', state.density.toUpperCase());
  setText('view-name', state.view[0].toUpperCase()+state.view.slice(1));
  setText('environment-tag', snapshot.environment);
  setText('freshness-tag', state.error ? 'ADAPTER OFFLINE' : `DATA AGE ${age(snapshot.received_at)}`);
  $('#connection-dot').className = state.error ? 'fail' : snapshot.received_at ? 'live' : '';
  setText('connection-label', state.error ? 'Adapter offline' : `Snapshot received ${age(snapshot.received_at)} ago`);
  evidenceByKey.projects = snapshot.projectsEvidence; evidenceByKey.projectRegistry = snapshot.projectRegistryEvidence; evidenceByKey.evolution = snapshot.selfEvolution && snapshot.selfEvolution.evidence; evidenceByKey.tasks = snapshot.tasksEvidence; evidenceByKey.events = snapshot.eventsEvidence; evidenceByKey.workerPolicy = state.workerPolicy ? state.workerPolicy.evidence : null; evidenceByKey.localWorkers = snapshot.localWorkersEvidence; evidenceByKey.cliWorkers = state.cliWorkers.evidence;
  renderSummary(snapshot); renderHiveOrbit(snapshot); renderProjects(snapshot); renderEvolution(snapshot); renderTasks(snapshot); renderAdapters(snapshot); renderWorkerPolicy(); renderLocalWorkers(snapshot); renderCliWorkers(); renderHandoff(snapshot); renderEvents(snapshot); renderChat(); renderTargets(snapshot); renderShell(snapshot); renderCards(snapshot); renderShellTail(snapshot); renderView();
}

function renderWorkerPolicy(){
  const policy = state.workerPolicy;
  const workers = policy && Array.isArray(policy.workers) ? policy.workers : [];
  const validity = workers.length ? 'valid' : (demoMode ? 'valid' : 'unavailable');
  const badge = $('#worker-policy-validity'); if(badge){ badge.textContent = stateLabel(validity); badge.className = `panel-status ${tone(validity)}`; }
  setText('worker-policy-evidence', policy && policy.evidence ? evidenceLine(policy.evidence) : (policy ? `local-first routing enforced · accepted cost modes: ${(policy.accepted_cost_modes||[]).join(', ')}` : 'Worker policy adapter unavailable.'));
  const container = $('#worker-policy-cards'); if(!container) return;
  if(!workers.length){ container.innerHTML = '<div class="empty-state compact"><span>⚙</span><strong>No worker policy received</strong><small>GET /api/control/worker-policy has not returned evidence yet.</small></div>'; return; }
  container.innerHTML = workers.map(worker => {
    const local = worker.execution_mode === 'local';
    const trustClass = worker.execution_mode === 'unknown' ? 'unknown' : local ? 'local' : 'remote';
    const costClass = worker.cost_mode_allowed ? 'ok' : 'fail';
    return `<div class="worker-card">
      <div class="worker-card-heading"><strong>${esc(worker.canonical_worker_id || worker.worker_id)}</strong><span class="trust-badge ${trustClass}">${esc(local ? 'LOCAL' : worker.execution_mode === 'unknown' ? 'UNKNOWN' : 'EXTERNAL / SUBSCRIPTION')}</span></div>
      <div class="worker-field"><span>Capability</span><strong>${esc(worker.capability || 'UNKNOWN')}</strong></div>
      <div class="worker-field"><span>Cost mode</span><strong><span class="cost-badge ${costClass}">${esc(stateLabel(worker.cost_mode))}</span></strong></div>
      <div class="worker-field"><span>Network</span><strong>${esc(stateLabel(worker.network_requirement))}</strong></div>
      <div class="worker-field"><span>Endpoint</span><strong>${esc(worker.endpoint || (local ? 'No local endpoint declared' : 'Remote — no endpoint declared'))}</strong></div>
      <div class="worker-field"><span>Fallback policy</span><strong>${esc(stateLabel(worker.fallback_policy))}</strong></div>
      ${!worker.cost_mode_allowed ? `<div class="worker-reason">BLOCKED: cost_mode '${esc(worker.cost_mode)}' is outside the free/subscription allowlist.</div>` : ''}
    </div>`;
  }).join('');
}

function renderLocalWorkers(snapshot){
  const container=$('#local-worker-cards'); if(!container) return;
  const workers=snapshot.localWorkers||[];
  if(!workers.length){ container.innerHTML='<div class="empty-state compact"><span>⌁</span><strong>No local worker probe evidence</strong><small>Only allowlisted loopback endpoints are probed; workers are never auto-started.</small></div>'; return; }
  container.innerHTML=workers.map(worker=>`<div class="local-worker-card"><div class="adapter-card-heading"><strong>${esc(worker.name)}</strong><span class="source-state ${tone(worker.status)}">${esc(stateLabel(worker.status))}</span></div><div class="adapter-field"><span>Endpoint</span><strong>${esc(worker.endpoint)}</strong></div><div class="adapter-field"><span>Models</span><strong>${esc((worker.models||[]).length)}</strong></div><div class="adapter-reason">${esc(worker.reason||'No probe result')}</div></div>`).join('');
}

function renderCliWorkers(){
  const payload=state.cliWorkers||{}, items=Array.isArray(payload.items)?payload.items:[], evidence=payload.evidence;
  const badge=$('#cli-worker-validity'); if(badge){ const validity=evidence&&evidence.validity?evidence.validity:'unknown'; badge.textContent=stateLabel(validity); badge.className=`panel-status ${tone(validity)}`; }
  setText('cli-worker-evidence', evidence ? evidenceLine(evidence) : 'Version probe evidence unavailable.');
  const container=$('#cli-worker-cards'); if(!container) return;
  if(!items.length){ container.innerHTML='<div class="empty-state compact"><span>⌁</span><strong>No CLI worker probe evidence</strong><small>OpenCode and Freebuff are not treated as execution-ready.</small></div>'; return; }
  container.innerHTML=items.map(worker=>`<div class="local-worker-card cli-worker-card"><div class="adapter-card-heading"><strong>${esc(worker.name||worker.id)}</strong><span class="source-state ${tone(worker.status)}">${esc(stateLabel(worker.status))}</span></div><div class="adapter-field"><span>Mode</span><strong>VERSION PROBE ONLY</strong></div><div class="adapter-field"><span>Version</span><strong>${esc(worker.version||'UNKNOWN')}</strong></div><div class="adapter-reason">${esc(worker.reason||'No probe result')}</div></div>`).join('');
}

function renderHandoff(snapshot){
  const handoff=state.capabilities&&state.capabilities.handoff;
  const routing=state.capabilities&&state.capabilities.routing;
  const valid=Boolean(handoff&&handoff.route&&handoff.proposal_only===true&&handoff.delivery===false&&handoff.retry===false);
  const badge=$('#handoff-validity'); if(badge){ badge.textContent=valid?'PROPOSAL ONLY':'UNKNOWN'; badge.className=`panel-status ${valid?'warn':'unknown'}`; }
  setText('handoff-evidence', valid ? `source ${handoff.route} · proposal-only · no delivery or retry` : 'Handoff capability evidence unavailable.');
  setText('handoff-summary', valid ? 'Bounded attempt/idempotency metadata supports resume-from-checkpoint. Uncertain or delivered attempts require recovery; no resend is allowed.' : 'No delivery, retry, provider launch, or canonical state change is performed by this route.');
  const readiness=snapshot&&snapshot.readiness||{aggregate:'unknown',items:[]};
  setText('provider-readiness', routing && routing.provider_execution === false && routing.attestation_shape_only === true ? `SYSTEM READINESS ${stateLabel(readiness.aggregate)} · PROVIDER EXECUTION BLOCKED · attestation is shape-only; verified HIVE/provider identity and protected routes are required.` : `SYSTEM READINESS ${stateLabel(readiness.aggregate)}`);
  const grid=$('#readiness-grid'); if(!grid) return;
  const items=Array.isArray(readiness.items)?readiness.items:[];
  grid.innerHTML=items.length ? items.map(item=>`<div class="local-worker-card"><div class="adapter-card-heading"><strong>${esc(item.component||'unknown')}</strong><span class="source-state ${tone(item.status)}">${esc(stateLabel(item.status))}</span></div><div class="adapter-field"><span>Validity</span><strong>${esc(stateLabel(item.validity))}</strong></div><div class="adapter-field"><span>Source</span><strong>${esc(item.source||'unknown')}</strong></div><div class="adapter-reason">${esc(item.reason||'No reason supplied.')}<br><span>${esc(item.next_safe_action||'No next safe action supplied.')}</span></div></div>`).join('') : '<div class="empty-state compact"><span>⌁</span><strong>Readiness evidence unavailable</strong><small>No component availability model was returned.</small></div>';
}

function openEvidenceDrawer(key, title){
  const evidence = evidenceByKey[key];
  const dialog = $('#evidence-drawer'); if(!dialog) return;
  setText('evidence-drawer-title', title || key);
  setText('evidence-drawer-source', evidence && evidence.source ? evidence.source : 'UNKNOWN');
  setText('evidence-drawer-validity', evidence && evidence.validity ? stateLabel(evidence.validity) : 'UNKNOWN');
  setText('evidence-drawer-observed', evidence && evidence.observed_at ? `${age(evidence.observed_at)} ago` : 'STALE / UNOBSERVED');
  setText('evidence-drawer-reason', evidence && evidence.reason ? evidence.reason : 'No reason supplied.');
  if(typeof dialog.showModal === 'function') dialog.showModal();
}

function renderSummary(snapshot){
  const cpu=snapshot.metrics.cpu, memory=snapshot.metrics.memory, disk=snapshot.metrics.disk;
  setText('metric-core', stateLabel(snapshot.core.status)); setText('metric-core-detail', snapshot.core.reason || `health evidence · ${age(snapshot.core.observed_at)} ago`); setText('metric-cpu', valueWithUnit(cpu)); setText('metric-cpu-detail', metricDetail(cpu)); setText('metric-memory', valueWithUnit(memory)); setText('metric-memory-detail', metricDetail(memory)); setText('metric-disk', valueWithUnit(disk)); setText('metric-disk-detail', metricDetail(disk)); setText('core-state', stateLabel(snapshot.core.status)); setText('core-state-detail', snapshot.core.reason || 'Application health evidence received'); const dot=$('#core-dot'); dot.className=`status-dot ${tone(snapshot.core.status)}`;
}

function renderHiveOrbit(snapshot){
  const svg=$('#hive-orbit'), empty=$('#orbit-empty'); if(!svg) return;
  const workers=(snapshot.workers||[]).filter(item=>item && item.id).slice(0,8);
  const tasks=(snapshot.tasks||[]).filter(item=>item && item.id && item.worker).slice(0,8);
  const events=(snapshot.events||[]).filter(item=>item && item.timestamp).slice(0,6);
  const verified=Boolean(snapshot.core && snapshot.core.observed_at);
  const badge=$('#orbit-validity'); if(badge){ const validity=verified?'valid':'unknown'; badge.textContent=stateLabel(validity); badge.className=`panel-status ${tone(validity)}`; }
  setText('orbit-evidence', snapshot.workersEvidence ? evidenceLine(snapshot.workersEvidence) : (verified ? `Core observed ${age(snapshot.core.observed_at)} ago · ${workers.length} worker records` : 'No timestamped HIVE topology evidence'));
  if(empty) empty.hidden=Boolean(workers.length||tasks.length||events.length);
  const cx=380, cy=210, radius=132;
  const escText=value=>esc(String(value||'').slice(0,28));
  const workerPoint=(index,total)=>{ const angle=(-Math.PI/2)+(index/Math.max(total,1))*Math.PI*2; return {x:cx+Math.cos(angle)*radius,y:cy+Math.sin(angle)*radius}; };
  const nodes=[];
  workers.forEach((worker,index)=>{ const point=workerPoint(index,workers.length); nodes.push({id:worker.id,x:point.x,y:point.y,label:worker.name||worker.provider||worker.id,status:worker.status||'unknown',kind:'worker'}); });
  const workerById=new Map(nodes.map(node=>[node.id,node]));
  const taskNodes=tasks.slice(0,Math.max(0,6-workers.length)).map((task,index)=>{ const angle=(index+workers.length)*Math.PI/Math.max(workers.length+tasks.length,1)*2; return {id:task.id,x:cx+Math.cos(angle)*(radius+45),y:cy+Math.sin(angle)*(radius+45),label:task.title||task.id,status:task.status||'unknown',kind:'task',worker:task.worker}; });
  nodes.push(...taskNodes);
  const lines=nodes.map(node=>`<line class="orbit-edge ${node.kind}" x1="${cx}" y1="${cy}" x2="${node.x.toFixed(1)}" y2="${node.y.toFixed(1)}"></line>`).join('');
  const taskLinks=taskNodes.map(node=>{ const target=workerById.get(node.worker); return target?`<line class="orbit-edge task-link" x1="${node.x.toFixed(1)}" y1="${node.y.toFixed(1)}" x2="${target.x.toFixed(1)}" y2="${target.y.toFixed(1)}"></line>`:''; }).join('');
  const nodeMarkup=nodes.map(node=>`<g class="orbit-node ${node.kind} ${tone(node.status)}" transform="translate(${node.x.toFixed(1)} ${node.y.toFixed(1)})"><circle r="${node.kind==='task'?14:23}"></circle><text class="orbit-node-label" y="${node.kind==='task'?31:38}" text-anchor="middle">${escText(node.label)}</text><text class="orbit-node-state" y="${node.kind==='task'?43:51}" text-anchor="middle">${escText(stateLabel(node.status))}</text></g>`).join('');
  const eventMarks=events.map((event,index)=>{ const angle=(index/events.length)*Math.PI*2; return `<circle class="orbit-event ${tone(event.severity)}" cx="${(cx+Math.cos(angle)*190).toFixed(1)}" cy="${(cy+Math.sin(angle)*190).toFixed(1)}" r="4"><title>${escText(event.title||event.kind||'Observed event')}</title></circle>`; }).join('');
  svg.innerHTML=`<circle class="orbit-ring outer" cx="${cx}" cy="${cy}" r="190"></circle><circle class="orbit-ring inner" cx="${cx}" cy="${cy}" r="90"></circle>${lines}${taskLinks}<g class="orbit-core ${tone(snapshot.core.status)}" transform="translate(${cx} ${cy})"><circle r="48"></circle><circle class="orbit-core-glow" r="62"></circle><text y="-3" text-anchor="middle">HIVE</text><text y="14" text-anchor="middle">CORE</text><text class="orbit-node-state" y="78" text-anchor="middle">${escText(stateLabel(snapshot.core.status))}</text></g>${nodeMarkup}${eventMarks}`;
}

function renderChat(){
  const chat=state.chat||{}; const label=$('#chat-session-label'); const badge=$('#chat-validity'); const dot=$('#chat-dot');
  const selected=(chat.sessions||[]).find(item=>item.id===chat.selected); const validity=selected?'valid':chat.error?'unavailable':'unknown';
  if(label) label.textContent=selected ? `${selected.name} · ${selected.harness} · ${selected.status}` : chat.error ? 'AO chat adapter unavailable' : 'No provider session selected';
  if(badge){ badge.textContent=stateLabel(validity); badge.className=`panel-status ${tone(validity)}`; }
  if(dot) dot.className=`status-dot ${tone(validity)}`;
  const transcript=$('#chat-transcript'); if(!transcript) return;
  const history=chat.history||[];
  transcript.innerHTML=history.length ? history.map(item=>`<div class="chat-message ${item.role==='assistant'?'agent':'user'}"><span>${esc(item.role==='assistant'?'HIVE':'YOU')}</span><p>${esc(item.text)}</p>${item.timestamp?`<small>${esc(age(item.timestamp))} ago</small>`:''}</div>`).join('') : `<div class="empty-state compact"><span>◌</span><strong>${chat.error?'AO chat adapter unavailable':'No chat evidence received'}</strong><small>${chat.error?esc(chat.error.message):'Session history will appear here when the documented local adapter returns it.'}</small></div>`;
}

function renderProjects(snapshot){
  const evidence = snapshot.projectsEvidence;
  const registryEvidence = snapshot.projectRegistryEvidence;
  const validity = evidence && evidence.validity === 'valid' ? 'valid' : (registryEvidence ? registryEvidence.validity : (evidence ? evidence.validity : 'unknown'));
  const badge = $('#projects-validity'); badge.textContent = stateLabel(validity); badge.className = `panel-status ${tone(validity)}`;
  setText('projects-evidence', `${evidenceLine(evidence)} · registry ${evidenceLine(registryEvidence)}`);
  const list = $('#project-list');
  const merged = new Map();
  (snapshot.projectRegistry || []).forEach(project => merged.set(project.id, {...project, source:'registry'}));
  (snapshot.projects || []).forEach(project => merged.set(project.id, {...project, source:'hive'}));
  const projects = [...merged.values()];
  if(!projects.length && (validity === 'unavailable' || validity === 'unknown' || validity === 'auth_required')){
    list.innerHTML = `<div class="empty-state compact"><span>⌁</span><strong>Project catalog ${esc(validity)}</strong><small>${esc(evidence && evidence.reason ? evidence.reason : 'No evidence received from HIVE Core.')}</small></div>`;
    return;
  }
  if(!projects.length){
    list.innerHTML = '<div class="empty-state compact"><span>▱</span><strong>No projects registered</strong><small>HIVE Core returned a valid, empty project catalog.</small></div>';
    return;
  }
  list.innerHTML = projects.map(project => {
    const detail = project.source === 'registry' ? `${project.id} · ${project.registration || 'unknown'} · ${project.workspace_present ? 'workspace present' : 'workspace not verified'}` : `${project.id} · HIVE Core`;
    const label = project.source === 'registry' ? (project.registration || project.status) : project.status;
    return `<div class="catalog-row"><i class="component-state ${tone(project.status)}"></i><div class="component-main"><strong>${esc(project.name)}</strong><small>${esc(detail)}</small></div><span class="component-badge">${esc(stateLabel(label))}${project.protected ? ' · PROTECTED' : ''}</span></div>`;
  }).join('');
}

function renderEvolution(snapshot){
  const evolution = snapshot.selfEvolution || {};
  const evidence = evolution.evidence;
  const item = evolution.item;
  const validity = evidence ? evidence.validity : 'unknown';
  const badge = $('#evolution-validity'); if(badge){ badge.textContent = stateLabel(validity); badge.className = `panel-status ${tone(validity)}`; }
  setText('evolution-evidence', evidenceLine(evidence));
  const summary = $('#evolution-summary'); if(!summary) return;
  if(!item){ summary.innerHTML = '<div class="empty-state compact"><span>✎</span><strong>Self-evolution checkpoint unavailable</strong><small>No proposal-only lifecycle evidence received.</small></div>'; return; }
  const hive=evolution.hive||{}; const hiveStatuses=hive.statuses&&typeof hive.statuses==='object' ? Object.entries(hive.statuses).map(([status,count])=>`${status}: ${count}`).join(' · ') : '';
  summary.innerHTML = `<div class="evolution-card"><div class="evolution-card-heading"><strong>${esc(item.id)} · ${esc(item.name)}</strong><span class="component-badge">${esc(stateLabel(item.status))}</span></div><small>${esc(item.completed_steps)} completed · ${esc(item.open_steps)} open · proposal-only ${item.proposal_only ? 'YES' : 'UNKNOWN'}</small>${item.next_action ? `<p>${esc(item.next_action)}</p>` : ''}${item.blocker ? `<div class="adapter-reason">${esc(item.blocker)}</div>` : ''}${hiveStatuses ? `<div class="evolution-hive-status"><span>HIVE /evolution</span><strong>${esc(hiveStatuses)}</strong></div>` : ''}</div>`;
}

function renderTasks(snapshot){
  const evidence = snapshot.tasksEvidence;
  const validity = evidence ? evidence.validity : 'unknown';
  const badge = $('#tasks-validity'); badge.textContent = stateLabel(validity); badge.className = `panel-status ${tone(validity)}`;
  setText('tasks-evidence', evidenceLine(evidence));
  const container = $('#task-buckets');
  if(validity === 'unavailable' || validity === 'unknown' || validity === 'auth_required'){
    container.innerHTML = `<div class="empty-state compact"><span>⌁</span><strong>Task queue ${esc(validity)}</strong><small>${esc(evidence && evidence.reason ? evidence.reason : 'No evidence received from HIVE Core.')}</small></div>`;
    return;
  }
  container.innerHTML = TASK_BUCKETS.map(bucket => {
    const items = snapshot.tasks.filter(task => task.status === bucket);
    const rows = items.length
      ? items.map(task => `<div class="task-row"><strong>${esc(task.title)}</strong><small>${esc(task.id)} · ${esc(task.project_id || 'unassigned')} · ${esc(task.worker || 'auto')} · ${esc(task.raw_status || task.status)}</small></div>`).join('')
      : `<div class="task-row empty">No ${esc(BUCKET_LABELS[bucket].toLowerCase())} tasks.</div>`;
    return `<div class="bucket-column"><div class="bucket-heading">${esc(BUCKET_LABELS[bucket])} <b>${items.length}</b></div>${rows}</div>`;
  }).join('');
}

function renderAdapters(snapshot){
  const adapters = snapshot.adapters || {};
  const ids = Object.keys(adapters);
  const container = $('#adapter-cards');
  if(!ids.length){ container.innerHTML = '<div class="empty-state compact"><span>⌁</span><strong>No adapter evidence</strong><small>The adapter has not reported any adapter health records.</small></div>'; return; }
  container.innerHTML = ids.map(id => {
    const info = adapters[id] || {};
    return `<div class="adapter-card"><div class="adapter-card-heading"><strong>${esc(id.toUpperCase())}</strong><span class="source-state ${tone(info.validity)}">${esc(stateLabel(info.validity))}</span></div>
      <div class="adapter-field"><span>Configured</span><strong>${info.configured ? 'YES' : 'NO'}</strong></div>
      <div class="adapter-field"><span>Token configured</span><strong>${info.token_configured ? 'YES' : 'NO'}</strong></div>
      <div class="adapter-field"><span>Authenticated (verified)</span><strong>${info.authenticated ? 'YES' : stateLabel(info.authentication_validity || 'unknown')}</strong></div>
      <div class="adapter-field"><span>Reachable</span><strong>${info.reachable ? 'YES' : 'NO'}</strong></div>
      <div class="adapter-field"><span>Last observed</span><strong>${info.last_observed_at ? age(info.last_observed_at) + ' ago' : '—'}</strong></div>
      <div class="adapter-reason">${esc(info.reason || 'No reason supplied.')}</div>
      ${info.authentication_reason ? `<div class="adapter-reason">${esc(info.authentication_reason)}</div>` : ''}
    </div>`;
  }).join('');
}

function renderEvents(snapshot){
  setText('events-evidence', evidenceLine(snapshot.eventsEvidence));
  $('#event-list').innerHTML=snapshot.events.length ? snapshot.events.slice(0,8).map(event=>`<div class="event-row"><time>${event.timestamp ? isoTime(event.timestamp) : '—'}</time><i class="event-marker ${tone(event.severity)}"></i><div class="event-copy"><strong>${esc(event.title||event.kind||'Observed event')}</strong><small>${esc(event.source||'unknown source')} · ${esc(event.component_id||event.project_id||'unscoped')} · ${event.timestamp ? age(event.timestamp) + ' ago' : 'timestamp unknown'}</small></div></div>`).join('') : '<div class="empty-state compact"><span>≋</span><strong>Nothing observed</strong><small>Events are rendered only from a timestamped source.</small></div>';
}

function renderTargets(snapshot){
  const project=$('#delegate-project'), worker=$('#delegate-worker'); if(!project||!worker)return;
  const projects = (snapshot.projects && snapshot.projects.length) ? snapshot.projects : [];
  const oldProject=project.value;
  project.innerHTML = '<option value="">Unassigned / Core</option>' + projects.map(item=>`<option value="${esc(item.id||'')}">${esc(item.name||item.id||'Unnamed project')}</option>`).join('');
  if([...project.options].some(option=>option.value===oldProject)) project.value=oldProject;
  const workers = snapshot.workers.filter(item=>item.id);
  const oldWorker=worker.value;
  worker.innerHTML = '<option value="">AUTO · Governor decides</option>' + workers.map(item=>`<option value="${esc(item.id)}">${esc(item.name||item.provider||item.id)}${item.model?' · '+esc(item.model):''}</option>`).join('');
  if([...worker.options].some(option=>option.value===oldWorker)) worker.value=oldWorker;
  setText('delegate-worker-evidence', evidenceLine(snapshot.workersEvidence));
}


// ---- P0.1 cockpit shell: every value below comes from the snapshot or reads UNKNOWN / NOT PROVIDED ----
const SHELL_ROLES = ['FURY','SHURI','THOR','VISION','FALCON','UATU'];
const ROLE_COLORS = {FURY:'#ffd36b',SHURI:'#b58cff',THOR:'#5aa8ff',VISION:'#ff9a5c',FALCON:'#6fe0ff',UATU:'#8f9bff'};
const PROVIDER_ACCENT = {gpt:'#6fa8ff',codex:'#b58cff',claude:'#f08cd8',local:'#8ad8ff'}; // identity colours: deliberately NOT the status hues (ok/warn/fail)
const PROJECT_COLORS = ['#4fe3a1','#ffb347','#ff6f7d','#5aa8ff','#b58cff','#6fd0ff'];
const roleIcon=(role)=>`<span class="role-ava" style="--role:${ROLE_COLORS[role]||'#6fb4ff'}"><svg aria-hidden="true"><use href="#ico-${role.toLowerCase()}"/></svg></span>`;
const SHELL_PROVIDERS = [['gpt','GPT'],['codex','CODEX'],['claude','CLAUDE']];
function providerObservation(snapshot, key){
  const hit=(snapshot.workers||[]).filter(item=>item && String(item.provider||item.name||item.id||'').toLowerCase().includes(key));
  if(!hit.length) return {tone:'unknown', label:'UNKNOWN'};
  const status=hit[0].status||'unknown'; return {tone:tone(status), label:stateLabel(status)};
}
function gaugeMarkup(v){
  const pct=v.known&&v.pct!==null?Math.max(0,Math.min(100,v.pct)):0; const c=2*Math.PI*40;
  const inner=v.known?v.text:'?';
  const compact=!v.known&&COMPACT_GAUGES.includes(v.key); // GPU/TEMP: neutral ? glyph instead of the UNKNOWN caption (status stays UNKNOWN)
  const sub=compact?`<span class="g-sub g-glyph" role="img" tabindex="0" aria-label="${esc(UNKNOWN_TIP)}" data-tip="${esc(UNKNOWN_TIP)}">?</span>`:`<small class="g-sub">${esc(v.known?(v.sub||''):'UNKNOWN')}</small>`;
  return `<div class="gauge ${v.known?'':'unknown'}" data-k="${esc(v.key)}" data-status="${v.known?'KNOWN':'UNKNOWN'}" title="${compact?'':esc(v.title)}"><svg viewBox="0 0 100 100" role="img" aria-label="${esc(v.label)} ${esc(v.text)}"><circle class="g-track" cx="50" cy="50" r="40"/><circle class="g-val" cx="50" cy="50" r="40" stroke-dasharray="${(c*pct/100).toFixed(1)} ${c.toFixed(1)}"/><text x="50" y="50">${esc(inner)}</text></svg><label><svg class="lbl-ico" aria-hidden="true"><use href="#ico-${({cpu:'cpu',ram:'layers',disk:'disk',gpu:'grid',temp:'temp'})[v.key]||'cpu'}"/></svg>${esc(v.label)}</label>${sub}</div>`;
}
const COMPACT_GAUGES=['gpu','temp'], UNKNOWN_TIP='UNKNOWN \u2014 no fresh telemetry';
let gaugeTip=null;
function showGaugeTip(el){ // tooltip lives on .stage (panels clip overflow); positioned in stage units
  const stage=document.querySelector('.stage'); if(!stage) return;
  if(!gaugeTip){ gaugeTip=document.createElement('div'); gaugeTip.id='gauge-tip'; gaugeTip.setAttribute('role','tooltip'); gaugeTip.hidden=true; stage.appendChild(gaugeTip); }
  gaugeTip.textContent=el.dataset.tip||UNKNOWN_TIP; gaugeTip.hidden=false;
  const sr=stage.getBoundingClientRect(), k=sr.width/1671||1, r=el.getBoundingClientRect(), w=gaugeTip.offsetWidth;
  const x=Math.max(8,Math.min(1671-w-8,(r.left+r.width/2-sr.left)/k-w/2)); gaugeTip.style.left=x+'px'; gaugeTip.style.top=((r.top-sr.top)/k-gaugeTip.offsetHeight-6)+'px';
}
function hideGaugeTip(){ if(gaugeTip) gaugeTip.hidden=true; }
document.addEventListener('mouseover',e=>{ const t=e.target.closest&&e.target.closest('.g-glyph'); if(t) showGaugeTip(t); });
document.addEventListener('mouseout',e=>{ if(e.target.closest&&e.target.closest('.g-glyph')) hideGaugeTip(); });
document.addEventListener('focusin',e=>{ const t=e.target.closest&&e.target.closest('.g-glyph'); if(t) showGaugeTip(t); });
document.addEventListener('focusout',e=>{ if(e.target.closest&&e.target.closest('.g-glyph')) hideGaugeTip(); });
document.addEventListener('keydown',e=>{ if(e.key==='Escape') hideGaugeTip(); });
function renderResources(snapshot){
  const views=OPS.resourceViews(state.system, snapshot.metrics);
  const g=$('#resource-gauges'); if(g){ const html=views.map(gaugeMarkup).join(''); if(g.dataset.sig!==html){ g.dataset.sig=html; g.innerHTML=html; } } // unchanged markup is not re-rendered, so keyboard focus survives polling
  state.unknownGauges=views.filter(v=>!v.known).map(v=>v.label);
  const lines=OPS.deviceLines(state.system); const el=$('#sys-summary');
  if(el){ const all=lines?lines:['USB / devices: UNKNOWN'].concat(state.system&&state.system.evidence&&state.system.evidence.reason?[state.system.evidence.reason]:[]); el.innerHTML=all.map(t=>`<div>${esc(t)}</div>`).join(''); el.title=all.join(' · '); }
  setSvgText('devices-state', OPS.devicesNodeText(state.system));
  renderSystemConsole();
}
function renderSystemConsole(){
  const sys=state.system; const list=$('#system-devices'); if(!list) return;
  const ev=(sys&&sys.evidence)||null; const vd=ev?ev.validity:(sys&&sys.error?'unavailable':'unknown');
  const badge=$('#system-validity'); if(badge){ badge.textContent=stateLabel(vd); badge.className=`panel-status ${tone(vd==='fixture'?'valid':vd)}`; }
  const unk=state.unknownGauges||[];
  setText('system-evidence', (sys&&sys.error?`System endpoint error: ${sys.error}`:evidenceLine(ev))+(unk.length?` · ${unk.map(l=>l+' UNKNOWN').join(', ')} (no fresh telemetry)`:''));
  const known=(sys&&sys.items)||{}; const disks=known.disks_known===true?(known.disks||[]):[], usb=known.usb_known===true?(known.usb||[]):[];
  const row=(a,b,c)=>`<div class="rail-row"><div class="grow"><strong>${esc(a)}</strong><small>${esc(b)}</small></div><span class="state">${esc(c)}</span></div>`;
  list.innerHTML=(disks.length||usb.length)?
    disks.map(d=>row(`${d.id} ${d.label||''}`.trim(), `${d.kind}${d.access?' · '+d.access:''}`, d.validity==='unavailable'?'size unavailable':`${OPS.formatBytes(d.total_bytes)} · ${OPS.formatBytes(d.free_bytes)} free`)).join('')
    +usb.map(u=>row(u.name, `USB · ${u.kind==='phone_mtp_ptp'?'phone (MTP/PTP) — not a disk':'device'}`, u.kind==='phone_mtp_ptp'?'Storage metrics unavailable':u.status)).join('')
    :`<div class="empty-state compact"><strong>${known.disks_known===true||known.usb_known===true?'NONE REPORTED':'UNKNOWN'}</strong><small>${known.disks_known===true||known.usb_known===true?'The OS probe returned no disks or USB devices.':'The OS probe did not return disks or USB devices.'}</small></div>`;
}
function renderLimits(snapshot){
  const items=(snapshot.model_limits&&snapshot.model_limits.items&&snapshot.model_limits.items.length)?snapshot.model_limits.items:OPS.EMPTY_LIMITS;
  const lim=$('#limit-rows'); if(!lim) return;
  lim.innerHTML=items.map(it=>{ const v=OPS.limitView(it); const fill=v.fill!==null?Math.round(Math.max(0,Math.min(1,v.fill))*100):0;
    return `<div class="limit-row" title="${esc(v.title)}" data-status="${esc(v.status)}" data-p="${esc(it.provider||'')}"><i class="dot ${v.tone}"></i><strong>${esc(v.label)}</strong><div class="bar ${v.dashed?'est':''}"><span style="width:${fill}%"></span></div><span class="v">${esc(v.text)}</span></div>`; }).join('');
}
function renderShell(snapshot){
  { const full=(snapshot.environment || 'UNVERIFIED') + ((snapshot.core && snapshot.core.observed_at) || demoMode || /FIXTURE|DEMO|UNVERIFIED/i.test(snapshot.environment||'') ? '' : ' · UNVERIFIED'); const short=/FIXTURE/i.test(full)?'FIXTURE DATA':/DEMO/i.test(full)?'DEMO DATA':/UNVERIFIED/i.test(full)?'UNVERIFIED':full; setText('env-tag', short); const et=$('#env-tag'); if(et) et.title=full; } // a static server label must not read as a connection claim
  SHELL_PROVIDERS.forEach(([key])=>{ const chip=$(`.source-chip[data-provider="${key}"]`); if(!chip) return; const o=providerObservation(snapshot,key); chip.className=`source-chip ${o.tone}`; const em=chip.querySelector('em'); if(em) em.textContent=o.label; });
  const sessions=(state.chat&&state.chat.sessions)||[];
  const chats=$('#chat-list'); if(chats) chats.innerHTML=sessions.length?sessions.slice(0,8).map(item=>`<div class="rail-row"><svg class="row-ico" aria-hidden="true"><use href="#ico-chat"/></svg><i class="dot ${tone(item.status)}"></i><div class="grow"><strong>${esc(item.name||item.id)}</strong><small>${esc(item.harness||'provider unknown')} · ${esc(stateLabel(item.status))}</small></div></div>`).join(''):'<div class="empty-state compact"><strong>NOT CONNECTED</strong><small>No provider chat sessions observed.</small></div>';
  const projects=(snapshot.projects||[]).filter(item=>item&&(item.id||item.name)); const pr=$('#project-rail');
  if(pr) pr.innerHTML=projects.length?projects.slice(0,8).map((item,i)=>`<div class="rail-row"><svg class="row-ico" style="--ic:${PROJECT_COLORS[i%PROJECT_COLORS.length]}" aria-hidden="true"><use href="#ico-folder"/></svg><div class="grow"><strong>${esc(item.name||item.id)}</strong></div></div>`).join(''):'<div class="empty-state compact"><strong>NOT PROVIDED</strong><small>HIVE Core returned no project catalog.</small></div>';
  const roster=$('#agent-roster'); if(roster) roster.innerHTML=SHELL_ROLES.map(role=>{ const rs=core.roleStates&&core.roleStates.get(role); const fresh=HC.roleFresh(core.roleStates,role,Date.now()); const t=fresh?HC.visualClass(rs.state).tone:'unknown'; return `<div class="rail-row">${roleIcon(role)}<div class="grow"><strong>${role}</strong></div><span class="state ${fresh&&t!=='unknown'?t:''}" title="${fresh?'state observed from an event; provider unknown':'provider and state not observed'}">${fresh?esc(stateLabel(rs.state)):'provider unknown'}</span><i class="dot ${fresh&&t!=='unknown'?t:'hollow'}" title="${fresh?esc(stateLabel(rs.state)):'state not observed'}"></i></div>`; }).join('');
  ingestActivity(snapshot); renderActivity(); renderApprovals();
  renderResources(snapshot); renderLimits(snapshot);
}
function renderShellTail(snapshot){ if(demoMode){ core.tstate={status:'live', lastMessageAt:Date.now(), sourceValidity:'fixture'}; ingestSnapshotEvents(snapshot); } recomputeCore(); }
function setConsole(open){ const c=$('#console'); if(c) c.hidden=!open; }
function tickClock(){ const el=$('#clock-tag'); if(!el) return; const d=new Date(); el.innerHTML=`<b>${esc(d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}))}</b><small>${esc(d.toLocaleDateString([], {day:'numeric',month:'short',year:'numeric'}))}</small>`; }


// ---- P0.2 CORE: transport -> buffer -> derived state -> movement -> SVG overlay (see hive-core.js) ----
const HC = window.HiveCore;
const core = {buffer:HC.createEventBuffer(200), activity:HC.createEventBuffer(100), transport:null, view:{state:'UNKNOWN',reason:'No telemetry observed yet'}, raf:null,
  tstate:{status:'connecting', lastMessageAt:null, sourceValidity:null}, roleStates:new Map()};
const reducedMotion = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
core.movement = HC.createMovementModel(reducedMotion() ? {travelMs:1, returnMs:1} : {});
const SVGNS = 'http://www.w3.org/2000/svg';
function onCoreEvent(ev){
  // Events from an untrusted source (auth_required/unavailable/unknown...) are dropped, not parked: they must never
  // become state or movement later when the source validity flips.
  if(!HC.eventTrusted(ev, core.tstate.sourceValidity)) return;
  core.activity.add(ev);
  if(!core.buffer.add(ev)) return;
  const t=Date.now();
  core.movement.applyEvent(ev,t);
  const role=String(ev.role_id||'').toUpperCase();
  if(role) core.roleStates.set(role,{state:ev.state, at:Date.parse(ev.timestamp||'')||t});
  scheduleCoreFrame(); recomputeCore();
}
function recomputeCore(){
  core.view = HC.deriveCoreState(core.buffer.list(), {now:Date.now(), transportStatus:core.tstate.status, lastMessageAt:core.tstate.lastMessageAt, sourceValidity:core.tstate.sourceValidity});
  applyCoreState();
}
const GLOBAL_LABEL = {IDLE:'IDLE', WORKING:'WORKING', WAITING_APPROVAL:'WAITING', REVIEW:'REVIEW', FAILED:'ERROR', SECURITY_BLOCKED:'ERROR', OFFLINE:'OFFLINE', UNKNOWN:'UNKNOWN'};
function applyCoreState(){
  const stage=$('#core-stage'); if(!stage) return;
  const s=core.view.state, vis=HC.visualClass(s), now=Date.now();
  stage.dataset.coreState=s; stage.dataset.tone=vis.tone; stage.className=`core-stage ${vis.cls}`;
  const envEl=$('#env-tag'); if(envEl && core.tstate.sourceValidity==='fixture' && !/FIXTURE/i.test(envEl.textContent)) envEl.textContent='FIXTURE DATA'; envEl.title='Synthetic fixture data (not live)'; // never show fixture-driven state unlabelled, even before the snapshot loads
  setText('core-center-state', stateLabel(s)); setText('core-state', GLOBAL_LABEL[s]); setText('core-state-detail', core.view.reason);
  const chip=$('#activity-chip'); if(chip){ chip.textContent=GLOBAL_LABEL[s]; chip.className=`hp-chip ${vis.tone==='review'?'warn':vis.tone}`; }
  const dot=$('#core-dot'); if(dot) dot.className=`status-dot ${vis.tone==='review'?'warn':vis.tone}`;
  const lock=$('#core-lock'); if(lock) lock.hidden=!vis.lock;
  const ring=$('#ultron-ring'); if(ring) ring.setAttribute('class',`ultron-ring ${HC.ultronRingClass(s,HC.roleFresh(core.roleStates,'ULTRON',now))}`);
  const fresh = s!=='UNKNOWN' && s!=='OFFLINE';
  $$('#core-agents .core-agent').forEach(g=>{
    const role=g.dataset.agent; const rs=core.roleStates.get(role); const st=(fresh&&rs&&now-rs.at<120000)?rs.state:'UNKNOWN';
    const label=g.querySelector('.ca-state'); if(label){ label.textContent=`${g.dataset.desc||''} · ${({WAITING_APPROVAL:'WAITING',SECURITY_BLOCKED:'BLOCKED'})[st]||stateLabel(st)}`; label.setAttribute('class',`ca-state ${HC.visualClass(st).tone==='unknown'?'':HC.visualClass(st).tone}`); }
    g.setAttribute('class',`core-agent ${HC.visualClass(st).tone==='unknown'?'':HC.visualClass(st).tone}`);
  });
  drawCoreFrame(); renderActivity(); renderApprovals();
}
function scheduleCoreFrame(){ if(core.raf) return; core.raf=requestAnimationFrame(coreFrame); }
function coreFrame(){ core.raf=null; const t=Date.now(); core.movement.tick(t); drawCoreFrame(); if(core.movement.size()||core.movement.queued()) scheduleCoreFrame(); }
function drawCoreFrame(){
  const t=Date.now(); const movers=core.movement.snapshot(t); const overlay=$('#core-overlay'); if(!overlay) return;
  const byRole=new Map(movers.map(m=>[m.role,m]));
  $$('#core-agents .core-agent').forEach(g=>{
    const role=g.dataset.agent; const m=byRole.get(role);
    const p=m?{x:m.x,y:m.y}:HC.homePoint(role);
    g.setAttribute('transform',`translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`); g.classList.toggle('moving',Boolean(m));
  });
  const ringPoint=a=>HC.pointAt(a,1); // the ULTRON ring
  overlay.innerHTML=movers.filter(m=>m.movement_state!=='returning').map(m=>{
    const kind=m.target_kind==='agent'?'handoff':m.target_id==='obsidian'||m.target_node==='obsidian'?'obsidian':'internet';
    let d;
    if(m.target_kind==='node'&&m.target_node==='internet'){ const r=ringPoint(m.target_angle), n=HC.NODES.internet; d=`M${m.x.toFixed(1)} ${m.y.toFixed(1)} L${r.x.toFixed(1)} ${r.y.toFixed(1)} L${n.x} ${n.y}`; } // always passes through the ULTRON ring
    else if(m.target_kind==='node'){ const n=HC.NODES[m.target_node]; d=`M${m.x.toFixed(1)} ${m.y.toFixed(1)} L${n.x} ${n.y}`; }
    else { const q=HC.homePoint(m.target_node); d=`M${m.x.toFixed(1)} ${m.y.toFixed(1)} L${q.x.toFixed(1)} ${q.y.toFixed(1)}`; }
    return `<path class="event-link ${kind}" d="${d}"><title>${esc(m.role)} → ${esc(m.target_node)} · ${esc(m.interaction_id)}</title></path>`;
  }).join('');
  const ctxOn=HC.activeContextNodes(core.buffer.list(), t, 20000, core.tstate.sourceValidity);
  $$('.ctx-item').forEach(el=>el.classList.toggle('on',ctxOn.has(el.dataset.node)));
  const activeTo=id=>movers.some(m=>m.target_kind==='node'&&m.target_node===id&&m.movement_state!=='returning');
  $('#node-internet')?.classList.toggle('active',activeTo('internet')); $('#node-obsidian')?.classList.toggle('active',activeTo('obsidian'));
  setSvgText('internet-state', activeTo('internet')?'ACTIVE · VIA ULTRON':'NO ACTIVITY OBSERVED'); setSvgText('obsidian-state', activeTo('obsidian')?'READ OBSERVED':OPS.obsidianNodeText(state.memory));
  { const on=activeTo('internet'); setText('card-external-main', on?'INTERNET: ACTIVE':'INTERNET'); setText('card-external-sub', on?'via ULTRON · observed event':'NO ACTIVITY OBSERVED'); const m=$('#card-external-main'); if(m) m.className=`tc-main ${on?'ok':'unknown'}`; }
}
function setSvgText(id,value){ const el=document.getElementById(id); if(el) el.textContent=value; }
function ingestSnapshotEvents(snapshot, validity){
  (snapshot.events||[]).forEach(raw=>{ const ev=HC.normalizeEvent(raw); if(ev) onCoreEvent(ev); });
}
async function pollSnapshotForCore(signal){
  const response=await fetch('/api/dashboard/snapshot',{headers:{Accept:'application/json'},cache:'no-store',signal});
  if(!response.ok) throw new Error(`HTTP ${response.status}`);
  const body=await response.json(); const ev=(body.events&&body.events.items)||[]; const ee=(body.events&&body.events.evidence)||{};
  return {events:ev, validity:ee.validity||null};
}
function startCore(){
  if(demoMode){
    core.tstate={status:'live', lastMessageAt:Date.now(), sourceValidity:'fixture'};
    const tag=document.createElementNS(SVGNS,'text'); tag.setAttribute('class','core-demo-tag'); tag.setAttribute('x','800'); tag.setAttribute('y','880'); tag.setAttribute('text-anchor','middle'); tag.textContent='DEMO'; $('#hive-core-art')?.appendChild(tag);
    return;
  }
  const scenario=new URLSearchParams(location.search).get('scenario');
  core.transport=HC.createTransport({streamUrl:'/api/events/stream'+(scenario&&/^[a-z0-9_-]{1,24}$/.test(scenario)?'?scenario='+scenario:''), EventSource:window.EventSource, pollFn:pollSnapshotForCore, onEvent:onCoreEvent, onStatus:s=>{core.tstate=s; recomputeCore();}});
  core.transport.start();
}
setInterval(()=>{ core.movement.tick(Date.now()); recomputeCore(); }, 5000);

// ---- P0.3 Activity / Approvals / Chat (logic in hive-ops.js; sanitisation in hive-core.js) ----
const OPS = window.HiveOps;
function ingestActivity(snapshot){ (snapshot.events||[]).forEach(raw=>{ const ev=HC.normalizeEvent(raw); if(ev) core.activity.add(ev); }); }
function renderActivity(){
  const el=$('#activity-rows'); if(!el) return;
  const rows=core.activity.list().map(HC.sanitizeActivityRow).filter(r=>r&&r.time).sort((a,b)=>Date.parse(b.time)-Date.parse(a.time)).slice(0,10);
  el.innerHTML=rows.length?rows.map(r=>`<div class="act-row"><time>${esc(isoTime(r.time))}</time><div><div class="act-meta"><b style="${ROLE_COLORS[String(r.role||'').toUpperCase()]?`color:${ROLE_COLORS[String(r.role).toUpperCase()]}`:''}">${esc(r.role||'role n/a')}</b>${r.provider?`<span>${esc(r.provider)}</span>`:''}<span class="state ${tone(r.state)}">${esc(stateLabel(r.state))}</span></div><div class="act-action">${esc(r.action)}</div></div></div>`).join(''):'<div class="empty-state compact"><strong>Nothing observed</strong><small>Rows appear only from timestamped events.</small></div>';
}
const APPROVAL_KEY='hive.approvals.local.v1';
function loadLocalDecisions(){ try{ const v=JSON.parse(localStorage.getItem(APPROVAL_KEY)||'{}'); return v&&typeof v==='object'?v:{}; }catch(_e){ return {}; } }
function saveLocalDecisions(v){ try{ localStorage.setItem(APPROVAL_KEY, JSON.stringify(v)); }catch(_e){ /* storage unavailable: decision stays in memory only */ } }
core.localDecisions=loadLocalDecisions();
const approvalConnector = null; // no source connector supports approve/reject/edit yet -> all decisions are local
function renderApprovals(){
  const el=$('#approval-rows'); if(!el) return;
  const telemetryOk = core.view && !['UNKNOWN','OFFLINE'].includes(core.view.state);
  const pending=OPS.pendingApprovals(core.activity.list(), Date.now());
  el.innerHTML=[['gpt','GPT'],['codex','CODEX'],['claude','CLAUDE']].map(([k,label])=>{
    const items=pending[k]; const item=items[0]; const dec=item&&core.localDecisions[item.key];
    const status = item ? (dec ? `${dec.decision==='APPROVED'?'Approved':'Rejected'} locally, source not updated` : `${items.length} PENDING · ${esc(item.summary||'approval requested')}`) : (telemetryOk ? 'NONE OBSERVED' : 'UNKNOWN');
    const can=Boolean(item&&!dec);
    return `<div class="approval-row" data-provider="${k}" style="--acc:${PROVIDER_ACCENT[k]}" title="${item?'':telemetryOk?'No pending approval observed':'Unknown: no fresh trusted telemetry'}"><i class="ap-ring ${item&&!dec?'pending':''}"></i><strong>${label}</strong><span class="ap-state">${status}</span><span class="ap-actions"><button class="ap-btn approve" data-act="approve" data-key="${esc(item?item.key:'')}" ${can?'':'disabled'}><svg aria-hidden="true"><use href="#ico-ok"/></svg>Approve</button><button class="ap-btn" data-act="edit" ${OPS.editAvailable(item||{provider:k},approvalConnector)?'':'disabled'} title="${OPS.editAvailable(item||{provider:k},approvalConnector)?'Open source task':'No source adapter or deep link available'}"><svg aria-hidden="true"><use href="#ico-edit"/></svg>Edit</button><button class="ap-btn reject" data-act="reject" data-key="${esc(item?item.key:'')}" ${can?'':'disabled'}><svg aria-hidden="true"><use href="#ico-x"/></svg>Reject</button></span></div>`;
  }).join('');
}
document.addEventListener('click', async event=>{
  const btn=event.target.closest('.ap-btn[data-act]'); if(!btn||btn.disabled) return;
  const act=btn.dataset.act; if(act==='edit') return;
  const row=btn.closest('.approval-row'); const pending=OPS.pendingApprovals(core.activity.list(), Date.now());
  const item=(pending[row.dataset.provider]||[]).find(i=>i.key===btn.dataset.key); if(!item) return;
  const result=await OPS.decide(item, act, approvalConnector);
  if(result.scope==='local'||result.scope==='source'){ core.localDecisions[item.key]={decision:result.decision,scope:result.scope,at:new Date().toISOString()}; saveLocalDecisions(core.localDecisions); }
  renderApprovals();
});

const composer={attachments:[], outbox:null};
function chatConnector(){
  return { connected(){ const ao=state.capabilities&&state.capabilities.ao;
      if(ao&&ao.send_confirmed) return {ok:false, reason:'AO send is configured, but the browser holds no caller token and no authenticated send route exists'};
      return {ok:false, reason:'No provider connector is connected (AO send gate not configured)'}; },
    async send(){ throw new Error('not connected'); } };
}
function fmtSize(n){ return n>=1048576?(n/1048576).toFixed(1)+' MB':n>=1024?Math.round(n/1024)+' KB':n+' B'; }
function renderChips(){
  const box=$('#attachment-chips'); if(!box) return; box.hidden=!composer.attachments.length;
  box.innerHTML=composer.attachments.map(a=>`<span class="chip" data-id="${esc(a.id)}"><span class="chip-name">${esc(a.name)}</span><small>${esc(fmtSize(a.size))}</small><button type="button" class="chip-x" aria-label="Remove ${esc(a.name)}" data-remove="${esc(a.id)}">×</button></span>`).join('')+'<small class="chip-note">attached locally · not uploaded</small>';
}
function renderOutbox(list){
  const box=$('#chat-outbox'); if(!box) return; const msgs=(list||composer.outbox.list()).slice().reverse().slice(0,6);
  box.innerHTML=msgs.length?msgs.map(m=>`<div class="outbox-row" data-state="${m.state}"><div class="ob-top"><span class="ob-state ${m.state==='SENT'?'ok':m.state==='FAILED'?'fail':m.state==='NOT_CONNECTED'?'warn':''}">${m.state}</span><div class="ob-text">${esc(HC.redactSummary(m.text,90)||'(attachments only)')}</div></div><small class="ob-reason">${m.attachments.length?m.attachments.length+' file(s) · ':''}${esc(m.reason||'')}</small>${m.state==='FAILED'||m.state==='NOT_CONNECTED'?`<div class="ob-actions"><button type="button" class="ap-btn" data-retry="${m.id}">Retry</button><button type="button" class="ap-btn" data-draft="${m.id}" title="Open the explicit proposal form with this text">Draft as proposal</button></div>`:''}</div>`).join(''):'<div class="empty-state compact"><strong>Empty</strong><small>Sent and unsent messages appear here with their true state.</small></div>';
}
function initComposer(){
  const form=$('#chat-draft-form'), input=$('#chat-draft-input'), file=$('#attach-input'); if(!form||!input) return;
  composer.outbox=OPS.createOutbox({connector:{connected:()=>chatConnector().connected(), send:a=>chatConnector().send(a)}, onChange:list=>{ renderOutbox(list); const last=list[list.length-1]; setText('chat-draft-status', last?`${last.state}${last.state==='SENT'?'':' · no provider message sent'}`:'Nothing sent yet.'); }});
  $('#attach-button').addEventListener('click',()=>file.click());
  file.addEventListener('change',()=>{ const r=OPS.describeFiles(file.files, composer.attachments); composer.attachments=r.attachments; file.value=''; renderChips(); if(r.rejected.length) setText('chat-draft-status', `Skipped: ${r.rejected.map(x=>x.name+' ('+x.reason+')').join(', ')}`); });
  $('#attachment-chips').addEventListener('click',event=>{ const id=event.target.closest('[data-remove]')?.dataset.remove; if(!id) return; composer.attachments=composer.attachments.filter(a=>a.id!==id); renderChips(); });
  const submit=async()=>{ const text=input.value; const r=await composer.outbox.send(text, composer.attachments); if(r.error){ setText('chat-draft-status', r.error); return; } input.value=''; composer.attachments=[]; renderChips(); autosize(); };
  const autosize=()=>{ input.style.height='auto'; input.style.height=Math.min(input.scrollHeight, 120)+'px'; };
  form.addEventListener('submit',event=>{ event.preventDefault(); submit(); });
  input.addEventListener('keydown',event=>{ if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){ event.preventDefault(); submit(); } });
  input.addEventListener('input',autosize);
  $('#chat-outbox').addEventListener('click',event=>{
    const retry=event.target.closest('[data-retry]')?.dataset.retry; if(retry){ composer.outbox.retry(retry); return; }
    const draft=event.target.closest('[data-draft]')?.dataset.draft; if(draft){ const m=composer.outbox.list().find(x=>x.id===draft); const t=$('#delegate-prompt'); if(m&&t) t.value=m.text; state.view='proposals'; setConsole(true); render(); }
  });
  renderChips(); renderOutbox([]);
}


// ---- Visual parity A/B: procedural, static, decorative artwork (never data) ----
function mulberry32(a){ return function(){ a|=0; a=a+0x6D2B79F5|0; let t=Math.imul(a^a>>>15,1|a); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }; }
function svgEl(name, attrs){ const el=document.createElementNS(SVGNS,name); Object.entries(attrs||{}).forEach(([k,v])=>el.setAttribute(k,v)); return el; }
function renderVortex(cv){
  // Decorative accretion disk, drawn ONCE on a local canvas (additive blending). Never data; tint/spin come from CSS.
  const S=cv.width, c=S/2, g=cv.getContext('2d'); if(!g) return; g.clearRect(0,0,S,S);
  const base=g.createRadialGradient(c,c,0,c,c,c);
  [[0,'rgba(0,0,0,1)'],[.22,'rgba(0,0,0,1)'],[.30,'rgba(40,12,90,.60)'],[.46,'rgba(90,40,170,.30)'],[.62,'rgba(220,100,40,.20)'],[.80,'rgba(40,110,255,.12)'],[1,'rgba(40,110,255,0)']].forEach(([o,col])=>base.addColorStop(o,col));
  g.fillStyle=base; g.fillRect(0,0,S,S);
  g.globalCompositeOperation='lighter'; g.lineCap='round'; g.lineJoin='round';
  const rnd=mulberry32(20261105), gauss=()=>{ let u=0; for(let i=0;i<4;i++) u+=rnd(); return (u-2)/0.58; };
  const colourAt=r=>{ // inner white-hot/orange -> mid magenta/violet -> outer blue/cyan
    const k=Math.max(0,Math.min(1,(r/c-.24)/.62)); const stops=[[255,236,200],[255,168,84],[255,92,150],[160,100,255],[70,140,255],[70,215,255]];
    const f=k*(stops.length-1), i=Math.min(stops.length-2,Math.floor(f)), t=f-i, a=stops[i], b=stops[i+1];
    return [0,1,2].map(j=>Math.round(a[j]+(b[j]-a[j])*t)); };
  const ARMS=6, WIND=2.5;
  const armPoint=(arm,t,off)=>{ const th=arm*Math.PI*2/ARMS+t*WIND, r=c*(.25+.64*t)+off; return [c+r*Math.cos(th), c+r*Math.sin(th), r]; };
  for(let pass=0;pass<2;pass++){
    const n=pass?620:150; // pass 0: soft wide glow strokes; pass 1: fine bright streaks
    for(let i=0;i<n;i++){
      const arm=i%ARMS, t0=rnd()*.62, len=.12+rnd()*(pass?.42:.3), off=gauss()*c*(pass?.045:.07), w=pass?.7+rnd()*2.6:7+rnd()*9;
      const [,,r0]=armPoint(arm,t0,off), col=colourAt(r0), alpha=pass?.14+rnd()*.5:.035+rnd()*.06;
      g.strokeStyle=`rgba(${col[0]},${col[1]},${col[2]},${alpha.toFixed(3)})`; g.lineWidth=w; g.beginPath();
      for(let j=0;j<=24;j++){ const [x,y]=armPoint(arm,t0+len*j/24,off+Math.sin(j*.7+i)*c*.006); j?g.lineTo(x,y):g.moveTo(x,y); }
      g.stroke();
    }
  }
  // bright inner disk hugging the horizon, then a faint lens glow
  const ring=g.createRadialGradient(c,c,c*.22,c,c,c*.46);
  [[0,'rgba(255,255,255,0)'],[.18,'rgba(255,240,215,.95)'],[.38,'rgba(255,170,90,.55)'],[.7,'rgba(255,110,70,.2)'],[1,'rgba(255,110,60,0)']].forEach(([o,col])=>ring.addColorStop(o,col));
  g.fillStyle=ring; g.fillRect(0,0,S,S);
  g.globalCompositeOperation='source-over'; g.fillStyle='#000'; g.beginPath(); g.arc(c,c,c*.235,0,Math.PI*2); g.fill();
}
function fitStage(){
  const k=Math.min(innerWidth/1671, innerHeight/941); document.documentElement.style.setProperty('--k', String(k));
}
function buildArtwork(){
  const cv=$('#core-canvas'); if(cv && !cv.dataset.drawn){ renderVortex(cv); cv.dataset.drawn='1'; }
  fitStage(); window.addEventListener('resize', fitStage);
}
// ---- Visual parity C: top task-card row (truthful: snapshot / memory evidence only) ----
function renderCards(snapshot){
  const v=OPS.taskCardViews(snapshot, state.memory, HC.redactSummary);
  const set=(id,view)=>{ const m=$(`#${id}-main`), sub=$(`#${id}-sub`), card=$(`#${id}`); if(!m) return; m.textContent=view.text; m.className=`tc-main ${view.tone}`; if(sub) sub.textContent=view.sub||''; if(card) card.title=view.title||''; };
  set('card-current',v.current); set('card-next',v.next); set('card-context',v.context);
  const bar=$('#card-current-progress'); if(bar){ const p=v.current.progress; bar.hidden=p===null; if(p!==null){ bar.firstElementChild.style.width=p+'%'; bar.title=`${Math.round(p)}% (progress_percent reported by the task record)`; } }
}

function renderView(){
  $$('[data-views]').forEach(section => {
    const views = (section.dataset.views || '').split(' ').filter(Boolean);
    section.hidden = !views.includes(state.view);
  });
  $$('.nav-item').forEach(item=>item.classList.toggle('active',item.dataset.view===state.view));
}

async function submitDelegation(event){
  event.preventDefault();
  const form=event.currentTarget, status=$('#delegate-status'), button=form.querySelector('button[type="submit"]');
  const prompt=$('#delegate-prompt').value.trim(), project=$('#delegate-project').value||null, worker=$('#delegate-worker').value||null, taskType=$('#delegate-type').value||null, localOnly=$('#delegate-local').checked;
  if(prompt.length<8){status.textContent='Proposal goal must contain at least 8 characters.';return;}
  if(!$('#delegate-confirm').checked){status.textContent='Confirmation is required before submission.';return;}
  button.disabled=true; status.textContent=demoMode?'Demo mode: request not sent.':'Submitting proposal to HIVE Core…';
  if(demoMode){button.disabled=false;return;}
  try{
    const response=await fetch('/api/control/dispatch',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({mode:'proposal',goal:prompt,project_id:project,preferred_worker:worker,task_type:taskType,local_only:localOnly,confirm:true})});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.detail||`Core rejected request (HTTP ${response.status})`);
    status.textContent=`Accepted by Core: proposal ${data.id||'queued'} · ${data.status||'submitted'}`;
    form.reset(); $('#delegate-project').value=project||'';
  }catch(error){status.textContent=`Not submitted: ${error.message}`;}
  finally{button.disabled=false;}
}

function demoSnapshot(){
  const received=new Date().toISOString(); const agoSeconds=seconds=>new Date(Date.now()-seconds*1000).toISOString();
  return {
    received_at: received,
    environment: 'LOCAL / DEMO FIXTURE',
    core: {status:'running', observed_at:agoSeconds(4), reason:'Application health payload accepted · fixture only'},
    metrics: {
      cpu:{value:42,unit:'%',source:'hive',observed_at:agoSeconds(12),validity:'valid'},
      memory:{value:58,unit:'%',source:'hive',observed_at:agoSeconds(12),validity:'valid'},
      disk:{value:71,unit:'%',source:'hive',observed_at:agoSeconds(12),validity:'valid'}
    },
    adapters: {
      hive:{configured:true,token_configured:true,authenticated:true,authentication_validity:'valid',authentication_reason:'HIVE_HEALTH_REQUIRES_AUTH documents /health as auth-guaranteed · fixture only',reachable:true,last_observed_at:agoSeconds(4),validity:'valid',reason:'HIVE Core /health responded · fixture only'},
      beszel:{configured:false,token_configured:false,authenticated:false,authentication_validity:'unavailable',authentication_reason:'Beszel integration is not implemented in this MVP; deferred',reachable:false,last_observed_at:null,validity:'unknown',reason:'Beszel integration is not implemented in this MVP; deferred'}
    },
    projects: {items:[{id:'seed',name:'SEED',status:'active',description:'Build / test pipeline',protected:false},{id:'creator-ops',name:'CREATOR OPS',status:'waiting',description:'Media pipeline',protected:true}], evidence:{source:'hive:/projects',observed_at:agoSeconds(4),validity:'valid',reason:null}},
    project_registry: {items:[{id:'hive-core-seed',name:'HIVE / seed core',status:'active',registration:'registered',workspace_present:true},{id:'creator-ops',name:'CREATOR OPS',status:'waiting',registration:'planned',workspace_present:true},{id:'self-evolution',name:'Self-evolution module',status:'waiting',registration:'historical-implementation-found',workspace_present:false},{id:'jarvis',name:'JARVIS voice layer',status:'waiting',registration:'planned',workspace_present:false}], evidence:{source:'obsidian:Registry/projects.json',observed_at:agoSeconds(4),validity:'valid',reason:'Fixture registry only'}},
    self_evolution: {item:{id:'P-013',name:'Self-evolution control plane',status:'in-progress',completed_steps:1,open_steps:1,next_action:'Map dashboard evidence to HIVE proposal lifecycle',blocker:'Independent review required',proposal_only:true}, evidence:{source:'obsidian:Tasks/self-evolution/P-013-proposal-only-control-plane.ukol.md',observed_at:agoSeconds(4),validity:'valid',reason:'Fixture checkpoint only'}},
    local_workers: {items:[{id:'lmstudio-local',name:'LM Studio',endpoint:'http://127.0.0.1:1234/v1/models',protocol:'openai-compatible',status:'available',models:['qwen3.5-4b'],reason:'Fixture probe only'},{id:'ollama-local',name:'Ollama',endpoint:'http://127.0.0.1:11434/api/tags',protocol:'ollama',status:'unavailable',models:[],reason:'Fixture probe only'}],evidence:{source:'local:worker-probe',observed_at:agoSeconds(4),validity:'valid',reason:'Fixture probe only'}},
    tasks: {items:[{id:'t-1',title:'Review PR #42',status:'active',raw_status:'running',project_id:'seed',worker:'codex',created_at:agoSeconds(300)},{id:'t-2',title:'Draft proposal: cache layer',status:'queued',raw_status:'pending',project_id:'creator-ops',worker:null,created_at:agoSeconds(900)},{id:'t-3',title:'Build fixture data',status:'completed',raw_status:'done',project_id:'seed',worker:'deterministic',created_at:agoSeconds(1800)}], evidence:{source:'hive:/tasks',observed_at:agoSeconds(4),validity:'valid',reason:null}},
    workers: {items:[{id:'deterministic',name:'Deterministic worker',provider:'local',model:'n/a',status:'idle'}], evidence:{source:'hive:/workers',observed_at:agoSeconds(4),validity:'valid',reason:null}},
    events: {items:[{timestamp:agoSeconds(5),timestamp_validity:'valid',kind:'TASK_ROUTED',title:'Task routed to SEED',source:'HIVE event bus',component_id:'seed',severity:'info'},{timestamp:agoSeconds(42),timestamp_validity:'valid',kind:'REVIEW_BLOCKED',title:'Review waiting for approval',source:'Governor audit',component_id:'core',severity:'warning'}], evidence:{source:'hive:/events',observed_at:agoSeconds(4),validity:'valid',reason:null}},
    topology: {status:'deferred', reason:'Topology visualization is deferred for this MVP · fixture only.'}
  };
}

function demoWorkerPolicy(){
  const observed=new Date(Date.now()-4000).toISOString();
  return {
    local_first_enforced:true, accepted_cost_modes:['free','subscription'],
    evidence:{source:'worker-policy:fixture', observed_at:observed, validity:'valid', reason:'Fixture only.'},
    workers:[
      {worker_id:'deterministic', canonical_worker_id:'deterministic', capability:'deterministic_arithmetic_evaluator', execution_mode:'local', cost_mode:'free', network_requirement:'none', fallback_policy:'none_required', endpoint:null, endpoint_basis:'not_applicable', cost_mode_allowed:true},
      {worker_id:'lmstudio-local', canonical_worker_id:'lmstudio-local', capability:'local_llm_inference', execution_mode:'local', cost_mode:'free', network_requirement:'loopback', fallback_policy:'none_required', endpoint:'http://127.0.0.1:1234', endpoint_basis:'documented_default', cost_mode_allowed:true},
      {worker_id:'ollama-local', canonical_worker_id:'ollama-local', capability:'local_llm_inference', execution_mode:'local', cost_mode:'free', network_requirement:'loopback', fallback_policy:'none_required', endpoint:'http://127.0.0.1:11434', endpoint_basis:'documented_default', cost_mode_allowed:true},
      {worker_id:'cline-local', canonical_worker_id:'cline-local', capability:'coding_assistant', execution_mode:'local', cost_mode:'unknown', network_requirement:'opt_in', fallback_policy:'local_preferred', endpoint:null, endpoint_basis:'runtime_unverified', cost_mode_allowed:false},
      {worker_id:'vscode-kilo', canonical_worker_id:'vscode-kilo', capability:'editor_coding', execution_mode:'local', cost_mode:'unknown', network_requirement:'opt_in', fallback_policy:'local_preferred', endpoint:null, endpoint_basis:'extension_adapter_required', cost_mode_allowed:false},
      {worker_id:'opencode-local', canonical_worker_id:'opencode-local', capability:'code_generation', execution_mode:'local', cost_mode:'unknown', network_requirement:'opt_in', fallback_policy:'local_preferred', endpoint:null, endpoint_basis:'wsl_cli_adapter_required', cost_mode_allowed:false},
      {worker_id:'freebuff-local', canonical_worker_id:'freebuff-local', capability:'code_generation', execution_mode:'local', cost_mode:'unknown', network_requirement:'opt_in', fallback_policy:'local_preferred', endpoint:null, endpoint_basis:'wsl_cli_adapter_required', cost_mode_allowed:false},
      {worker_id:'openclaw-local', canonical_worker_id:'openclaw-local', capability:'agent_orchestration', execution_mode:'local', cost_mode:'unknown', network_requirement:'opt_in', fallback_policy:'local_preferred', endpoint:null, endpoint_basis:'runtime_unverified', cost_mode_allowed:false},
      {worker_id:'openrouter_free', canonical_worker_id:'openrouter_free', capability:'remote_llm_inference', execution_mode:'remote', cost_mode:'free', network_requirement:'internet', fallback_policy:'local_preferred', endpoint:null, endpoint_basis:'not_applicable', cost_mode_allowed:true},
      {worker_id:'codex-subscription', canonical_worker_id:'codex-subscription', capability:'remote_llm_inference', execution_mode:'remote', cost_mode:'unknown', network_requirement:'internet', fallback_policy:'local_preferred', endpoint:null, endpoint_basis:'not_applicable', cost_mode_allowed:false},
    ],
  };
}

function demoCapabilities(){ return {handoff:{route:'/api/control/handoff-proposal', proposal_only:true, delivery:false, retry:false}, routing:{provider_execution:false, attestation_shape_only:true}}; }

function demoChat(){
  return {sessions:[{id:'hive-demo',name:'HIVE / demo fixture',status:'working',harness:'local'}],selected:'hive-demo',evidence:{source:'ao:fixture',validity:'valid'},history:[
    {role:'assistant',text:'Evidence-backed HIVE cockpit fixture loaded. No provider message was sent.',timestamp:new Date(Date.now()-42000).toISOString()},
    {role:'user',text:'Show queue and active workers.',timestamp:new Date(Date.now()-36000).toISOString()},
  ],error:null};
}

$$('.nav-item').forEach(item=>item.addEventListener('click',()=>{state.view=item.dataset.view; render();}));
$('#delegate-button').addEventListener('click',()=>{state.view='proposals'; render();});
$('#console-open').addEventListener('click',()=>setConsole(true));
$('#console-close').addEventListener('click',()=>setConsole(false));
document.addEventListener('keydown',event=>{ if(event.key==='Escape') setConsole(false); });
tickClock(); setInterval(tickClock,30000);
$('#delegate-form').addEventListener('submit',submitDelegation);
$('#refresh-button').addEventListener('click',load);
$('#density-toggle').addEventListener('click',()=>{const next=DENSITY_CYCLE[(DENSITY_CYCLE.indexOf(state.density)+1)%DENSITY_CYCLE.length]; state.density=next; savePrefs(); render();});
$$('.mode-button').forEach(button=>button.addEventListener('click',()=>{state.mode=button.dataset.mode; savePrefs(); render();}));
$('#chat-refresh')?.addEventListener('click',load);
initComposer();
$('#evidence-drawer-close').addEventListener('click',()=>$('#evidence-drawer').close());
document.addEventListener('click', event => { const trigger = event.target.closest('[data-evidence-key]'); if(trigger) openEvidenceDrawer(trigger.dataset.evidenceKey, trigger.closest('.panel')?.querySelector('h2')?.textContent || trigger.dataset.evidenceKey); });
document.addEventListener('keydown', event => { if(event.key !== 'Enter' && event.key !== ' ') return; const trigger = event.target.closest('[data-evidence-key]'); if(!trigger) return; event.preventDefault(); openEvidenceDrawer(trigger.dataset.evidenceKey, trigger.closest('.panel')?.querySelector('h2')?.textContent || trigger.dataset.evidenceKey); });
buildArtwork(); startCore(); load(); setInterval(()=>{if(document.visibilityState==='visible')load();},15000);
