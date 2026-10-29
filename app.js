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
const state = {snapshot:null, workerPolicy:null, cliWorkers:{items:[],evidence:null,error:null}, chat:{sessions:[],history:[],selected:null,evidence:null,error:null}, view:'overview', density:prefs.density, mode:prefs.mode, error:null};
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
  return {
    received_at: source.received_at || null,
    environment: source.environment || 'LOCAL / UNVERIFIED',
    core: source.core || {status:'unknown', reason:'No application health payload'},
    metrics,
    events, eventsEvidence,
    projects, projectsEvidence,
    projectRegistry, projectRegistryEvidence, selfEvolution,
    tasks, tasksEvidence,
    workers, workersEvidence, localWorkers, localWorkersEvidence,
    adapters,
    topology,
  };
}

async function load(){
  $('#refresh-button').disabled = true;
  state.error = null;
  if(demoMode){ state.snapshot = normalize(demoSnapshot()); state.workerPolicy = demoWorkerPolicy(); state.chat = demoChat(); $('#demo-banner').hidden = false; }
  else {
    try { const response = await fetch('/api/dashboard/snapshot', {headers:{Accept:'application/json'}, cache:'no-store'}); if(!response.ok) throw new Error(`adapter returned HTTP ${response.status}`); state.snapshot = normalize(await response.json()); }
    catch(error){ state.error = error; state.snapshot = normalize(null); }
    try { const response = await fetch('/api/control/worker-policy', {headers:{Accept:'application/json'}, cache:'no-store'}); state.workerPolicy = response.ok ? await response.json() : null; }
    catch(_error){ state.workerPolicy = null; }
    try { const response = await fetch('/api/local-workers/cli-status', {headers:{Accept:'application/json'}, cache:'no-store'}); state.cliWorkers = response.ok ? await response.json() : {items:[],evidence:{validity:'unavailable',reason:`CLI probe returned HTTP ${response.status}`}}; }
    catch(error){ state.cliWorkers = {items:[],evidence:{validity:'unavailable',reason:`CLI probe unavailable: ${error.message}`}}; }
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
  renderSummary(snapshot); renderHiveOrbit(snapshot); renderProjects(snapshot); renderEvolution(snapshot); renderTasks(snapshot); renderAdapters(snapshot); renderWorkerPolicy(); renderLocalWorkers(snapshot); renderCliWorkers(); renderEvents(snapshot); renderChat(); renderTargets(snapshot); renderView();
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

function demoChat(){
  return {sessions:[{id:'hive-demo',name:'HIVE / demo fixture',status:'working',harness:'local'}],selected:'hive-demo',evidence:{source:'ao:fixture',validity:'valid'},history:[
    {role:'assistant',text:'Evidence-backed HIVE cockpit fixture loaded. No provider message was sent.',timestamp:new Date(Date.now()-42000).toISOString()},
    {role:'user',text:'Show queue and active workers.',timestamp:new Date(Date.now()-36000).toISOString()},
  ],error:null};
}

$$('.nav-item').forEach(item=>item.addEventListener('click',()=>{state.view=item.dataset.view; render();}));
$('#delegate-button').addEventListener('click',()=>{state.view='proposals'; render();});
$('#delegate-form').addEventListener('submit',submitDelegation);
$('#refresh-button').addEventListener('click',load);
$('#density-toggle').addEventListener('click',()=>{const next=DENSITY_CYCLE[(DENSITY_CYCLE.indexOf(state.density)+1)%DENSITY_CYCLE.length]; state.density=next; savePrefs(); render();});
$$('.mode-button').forEach(button=>button.addEventListener('click',()=>{state.mode=button.dataset.mode; savePrefs(); render();}));
$('#chat-refresh')?.addEventListener('click',load);
$('#chat-draft-form')?.addEventListener('submit',event=>{event.preventDefault(); const input=$('#chat-draft-input'), status=$('#chat-draft-status'); const prompt=input?.value.trim(); if(!prompt){if(status)status.textContent='Enter a bounded request first.';return;} const target=$('#delegate-prompt'); if(target)target.value=prompt; state.view='proposals'; render(); if(status)status.textContent='Draft copied to proposal form · no provider message sent.';});
$('#evidence-drawer-close').addEventListener('click',()=>$('#evidence-drawer').close());
document.addEventListener('click', event => { const trigger = event.target.closest('[data-evidence-key]'); if(trigger) openEvidenceDrawer(trigger.dataset.evidenceKey, trigger.closest('.panel')?.querySelector('h2')?.textContent || trigger.dataset.evidenceKey); });
document.addEventListener('keydown', event => { if(event.key !== 'Enter' && event.key !== ' ') return; const trigger = event.target.closest('[data-evidence-key]'); if(!trigger) return; event.preventDefault(); openEvidenceDrawer(trigger.dataset.evidenceKey, trigger.closest('.panel')?.querySelector('h2')?.textContent || trigger.dataset.evidenceKey); });
load(); setInterval(()=>{if(document.visibilityState==='visible')load();},15000);
