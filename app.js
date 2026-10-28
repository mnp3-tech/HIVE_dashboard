const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const demoMode = new URLSearchParams(location.search).get('demo') === '1';
const state = {snapshot:null, view:'overview', reduced:localStorage.getItem('hive.dashboard.preferences.v1') === 'reduced', error:null};

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
  const tasks = source.tasks && Array.isArray(source.tasks.items) ? source.tasks.items : [];
  const tasksEvidence = source.tasks && source.tasks.evidence ? source.tasks.evidence : null;
  const workers = source.workers && Array.isArray(source.workers.items) ? source.workers.items : [];
  const workersEvidence = source.workers && source.workers.evidence ? source.workers.evidence : null;
  const adapters = source.adapters || {};
  const topology = source.topology || {status:'deferred', reason:'Topology visualization is deferred for this MVP.'};
  return {
    received_at: source.received_at || null,
    environment: source.environment || 'LOCAL / UNVERIFIED',
    core: source.core || {status:'unknown', reason:'No application health payload'},
    metrics,
    events, eventsEvidence,
    projects, projectsEvidence,
    tasks, tasksEvidence,
    workers, workersEvidence,
    adapters,
    topology,
  };
}

async function load(){
  $('#refresh-button').disabled = true;
  state.error = null;
  if(demoMode){ state.snapshot = normalize(demoSnapshot()); $('#demo-banner').hidden = false; }
  else {
    try { const response = await fetch('/api/dashboard/snapshot', {headers:{Accept:'application/json'}, cache:'no-store'}); if(!response.ok) throw new Error(`adapter returned HTTP ${response.status}`); state.snapshot = normalize(await response.json()); }
    catch(error){ state.error = error; state.snapshot = normalize(null); }
  }
  render(); $('#refresh-button').disabled = false;
}

function setText(id, text){ const element = $(`#${id}`); if(element) element.textContent = text; }
function render(){
  const snapshot = state.snapshot || normalize(null);
  document.body.classList.toggle('reduced-motion', state.reduced);
  setText('view-name', state.view[0].toUpperCase()+state.view.slice(1));
  setText('environment-tag', snapshot.environment);
  setText('freshness-tag', state.error ? 'ADAPTER OFFLINE' : `DATA AGE ${age(snapshot.received_at)}`);
  $('#connection-dot').className = state.error ? 'fail' : snapshot.received_at ? 'live' : '';
  setText('connection-label', state.error ? 'Adapter offline' : `Snapshot received ${age(snapshot.received_at)} ago`);
  renderSummary(snapshot); renderTopologyDeferred(snapshot); renderProjects(snapshot); renderTasks(snapshot); renderAdapters(snapshot); renderEvents(snapshot); renderTargets(snapshot); renderView();
}

function renderSummary(snapshot){
  const cpu=snapshot.metrics.cpu, memory=snapshot.metrics.memory, disk=snapshot.metrics.disk;
  setText('metric-core', stateLabel(snapshot.core.status)); setText('metric-core-detail', snapshot.core.reason || `health evidence · ${age(snapshot.core.observed_at)} ago`); setText('metric-cpu', valueWithUnit(cpu)); setText('metric-cpu-detail', metricDetail(cpu)); setText('metric-memory', valueWithUnit(memory)); setText('metric-memory-detail', metricDetail(memory)); setText('metric-disk', valueWithUnit(disk)); setText('metric-disk-detail', metricDetail(disk)); setText('core-state', stateLabel(snapshot.core.status)); setText('core-state-detail', snapshot.core.reason || 'Application health evidence received'); const dot=$('#core-dot'); dot.className=`status-dot ${tone(snapshot.core.status)}`;
}

function renderTopologyDeferred(snapshot){ setText('topology-deferred-reason', snapshot.topology.reason || 'Topology visualization is deferred for this MVP; no graph or event-derived topology is computed.'); }

function renderProjects(snapshot){
  const evidence = snapshot.projectsEvidence;
  const validity = evidence ? evidence.validity : 'unknown';
  const badge = $('#projects-validity'); badge.textContent = stateLabel(validity); badge.className = `panel-status ${tone(validity)}`;
  setText('projects-evidence', evidenceLine(evidence));
  const list = $('#project-list');
  if(validity === 'unavailable' || validity === 'unknown' || validity === 'auth_required'){
    list.innerHTML = `<div class="empty-state compact"><span>⌁</span><strong>Project catalog ${esc(validity)}</strong><small>${esc(evidence && evidence.reason ? evidence.reason : 'No evidence received from HIVE Core.')}</small></div>`;
    return;
  }
  if(!snapshot.projects.length){
    list.innerHTML = '<div class="empty-state compact"><span>▱</span><strong>No projects registered</strong><small>HIVE Core returned a valid, empty project catalog.</small></div>';
    return;
  }
  list.innerHTML = snapshot.projects.map(project => `<div class="catalog-row"><i class="component-state ${tone(project.status)}"></i><div class="component-main"><strong>${esc(project.name)}</strong><small>${esc(project.id)} · ${esc(project.description || 'no description supplied')}</small></div><span class="component-badge">${esc(stateLabel(project.status))}${project.protected ? ' · PROTECTED' : ''}</span></div>`).join('');
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
    tasks: {items:[{id:'t-1',title:'Review PR #42',status:'active',raw_status:'running',project_id:'seed',worker:'codex',created_at:agoSeconds(300)},{id:'t-2',title:'Draft proposal: cache layer',status:'queued',raw_status:'pending',project_id:'creator-ops',worker:null,created_at:agoSeconds(900)},{id:'t-3',title:'Build fixture data',status:'completed',raw_status:'done',project_id:'seed',worker:'deterministic',created_at:agoSeconds(1800)}], evidence:{source:'hive:/tasks',observed_at:agoSeconds(4),validity:'valid',reason:null}},
    workers: {items:[{id:'deterministic',name:'Deterministic worker',provider:'local',model:'n/a',status:'idle'}], evidence:{source:'hive:/workers',observed_at:agoSeconds(4),validity:'valid',reason:null}},
    events: {items:[{timestamp:agoSeconds(5),timestamp_validity:'valid',kind:'TASK_ROUTED',title:'Task routed to SEED',source:'HIVE event bus',component_id:'seed',severity:'info'},{timestamp:agoSeconds(42),timestamp_validity:'valid',kind:'REVIEW_BLOCKED',title:'Review waiting for approval',source:'Governor audit',component_id:'core',severity:'warning'}], evidence:{source:'hive:/events',observed_at:agoSeconds(4),validity:'valid',reason:null}},
    topology: {status:'deferred', reason:'Topology visualization is deferred for this MVP · fixture only.'}
  };
}

$$('.nav-item').forEach(item=>item.addEventListener('click',()=>{state.view=item.dataset.view; render();}));
$('#delegate-button').addEventListener('click',()=>{state.view='proposals'; render();});
$('#delegate-form').addEventListener('submit',submitDelegation);
$('#refresh-button').addEventListener('click',load);
$('#reduced-motion').addEventListener('click',()=>{state.reduced=!state.reduced; localStorage.setItem('hive.dashboard.preferences.v1',state.reduced?'reduced':'full'); $('#reduced-motion').setAttribute('aria-pressed',String(state.reduced)); render();});
$('#reduced-motion').setAttribute('aria-pressed',String(state.reduced));
load(); setInterval(()=>{if(document.visibilityState==='visible')load();},15000);
