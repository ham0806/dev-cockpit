(() => {
  'use strict';
  const state = { jobs: [], selected: null, diff: null };
  const $ = (id) => document.getElementById(id);
  const statusLabel = { queued: 'Queued', running: 'Running', completed: 'Completed', failed: 'Failed', stopped: 'Stopped' };
  $('token').value = localStorage.getItem('dev-cockpit-token') || '';

  async function request(path, options = {}) {
    const token = $('token').value.trim();
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(path, { headers, ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }
  function setError(message = '') { $('task-error').textContent = message; }
  async function loadProjects() {
    const projects = await request('/api/projects');
    $('project').replaceChildren(...projects.map((project) => { const option = document.createElement('option'); option.value = project.id; option.textContent = project.name; return option; }));
  }
  async function loadAgents() {
    const agents = await request('/api/agents');
    if (!agents.length) throw new Error('利用可能なAgentがありません。');
    const root = $('agent-picker'); root.replaceChildren();
    agents.forEach((agent, index) => {
      const label = document.createElement('label');
      const input = document.createElement('input'); input.type = 'radio'; input.name = 'agent'; input.value = agent.id; input.checked = index === 0;
      label.append(input, document.createTextNode(' ' + agent.name)); root.appendChild(label);
    });
  }
  function agentLabel(job) { return job.routed_agent ? `${job.agent} → ${job.routed_agent}` : job.agent; }
  function renderJobs() {
    const root = $('jobs'); root.replaceChildren();
    if (!state.jobs.length) { root.innerHTML = '<p class="muted">まだJobはありません。</p>'; return; }
    for (const job of state.jobs) {
      const button = document.createElement('button'); button.className = `job ${job.id === state.selected ? 'selected' : ''}`; button.type = 'button';
      const title = document.createElement('span'); title.className = 'job-title'; title.textContent = `${agentLabel(job)} #${job.id}`;
      const prompt = document.createElement('span'); prompt.className = 'job-prompt'; prompt.textContent = job.prompt;
      const status = document.createElement('span'); status.className = `status ${job.status}`; status.textContent = statusLabel[job.status] || job.status;
      button.append(title, prompt, status); button.addEventListener('click', () => selectJob(job.id)); root.appendChild(button);
    }
  }
  async function loadJobs() {
    state.jobs = await request('/api/jobs'); renderJobs();
    if (state.selected) { const selected = state.jobs.find((job) => job.id === state.selected); if (selected) await renderDetail(selected); }
  }
  async function selectJob(id) { state.selected = id; renderJobs(); await renderDetail(await request(`/api/jobs/${encodeURIComponent(id)}`)); }
  function renderMarkdown(source) {
    const escaped = source.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    const blocks = escaped.split(/```/); let html = '';
    blocks.forEach((block, index) => {
      if (index % 2 === 1) { html += `<pre>${block.trim()}</pre>`; return; }
      html += block.replace(/^### (.*)$/gm, '<h3>$1</h3>').replace(/^## (.*)$/gm, '<h2>$1</h2>').replace(/^# (.*)$/gm, '<h1>$1</h1>').replace(/^[-*] (.*)$/gm, '<p>• $1</p>').replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\n{2,}/g, '</p><p>').replace(/\n/g, '<br>');
    });
    return `<p>${html}</p>`;
  }
  async function renderDetail(job) {
    $('detail').classList.remove('hidden'); $('detail-title').textContent = `${agentLabel(job)} #${job.id}`;
    $('detail-status').className = `status ${job.status}`; $('detail-status').textContent = statusLabel[job.status] || job.status;
    const confidence = typeof job.route_confidence === 'number' ? ` · Confidence: ${job.route_confidence.toFixed(2)}` : ''; const route = job.routed_agent ? ` · Route: ${job.route_source || 'router'}${confidence}` : '';
    $('detail-meta').textContent = `Project: ${job.project_id} · Branch: ${job.branch || '準備中'} · Files: ${(job.changed_files || []).length}${route}`;
    $('log').textContent = (job.log || []).join('\n'); $('stop').disabled = job.status !== 'running'; $('request-changes').disabled = job.status === 'running'; $('approve').disabled = job.status === 'running'; $('push').disabled = job.status === 'running';
    if (job.status !== 'running') { try { state.diff = await request(`/api/jobs/${job.id}/diff`); $('diff').textContent = state.diff.patch || '差分はありません。'; renderMarkdownFiles(state.diff.files || []); } catch (error) { $('diff').textContent = error.message; } }
  }
  function renderMarkdownFiles(files) {
    const root = $('markdown'); root.replaceChildren(); const markdownFiles = files.filter((file) => /\.md$/i.test(file.path));
    if (!markdownFiles.length) { root.innerHTML = '<p class="muted">差分にMarkdownファイルはありません。</p>'; return; }
    const select = document.createElement('select'); markdownFiles.forEach((file) => { const option = document.createElement('option'); option.value = file.path; option.textContent = file.path; select.appendChild(option); });
    const preview = document.createElement('div'); preview.className = 'markdown-preview'; root.append(select, preview);
    const load = async () => { try { const data = await request(`/api/jobs/${state.selected}/file?path=${encodeURIComponent(select.value)}`); preview.innerHTML = renderMarkdown(data.content); } catch (error) { preview.textContent = error.message; } }; select.addEventListener('change', load); load();
  }
  async function runTask() {
    setError(''); const prompt = $('prompt').value.trim(); if (!prompt) { setError('Promptを入力してください。'); return; }
    $('run').disabled = true; try { const agent = document.querySelector('input[name="agent"]:checked').value; const job = await request('/api/jobs', { method: 'POST', body: JSON.stringify({ projectId: $('project').value, agent, prompt }) }); $('prompt').value = ''; await selectJob(job.id); await loadJobs(); } catch (error) { setError(error.message); } finally { $('run').disabled = false; }
  }
  async function withSelected(action) { if (!state.selected) return; try { await action(); await loadJobs(); } catch (error) { alert(error.message); } }
  $('run').addEventListener('click', runTask); $('refresh').addEventListener('click', () => loadJobs().catch((error) => setError(error.message)));
  $('token').addEventListener('change', () => { localStorage.setItem('dev-cockpit-token', $('token').value.trim()); boot(); });
  $('stop').addEventListener('click', () => withSelected(() => request(`/api/jobs/${state.selected}/stop`, { method: 'POST', body: '{}' })));
  $('request-changes').addEventListener('click', () => { $('follow-up-box').classList.remove('hidden'); $('follow-up').focus(); });
  $('follow-up').addEventListener('keydown', (event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) withSelected(async () => { const prompt = $('follow-up').value.trim(); if (!prompt) throw new Error('修正指示を入力してください。'); await request(`/api/jobs/${state.selected}/follow-up`, { method: 'POST', body: JSON.stringify({ prompt }) }); $('follow-up').value = ''; $('follow-up-box').classList.add('hidden'); }); });
  $('approve').addEventListener('click', () => withSelected(async () => { const message = prompt('commit message'); if (message) await request(`/api/jobs/${state.selected}/approve`, { method: 'POST', body: JSON.stringify({ commitMessage: message }) }); }));
  $('push').addEventListener('click', () => withSelected(async () => { if (confirm('このJobのbranchをoriginへpushしますか？')) await request(`/api/jobs/${state.selected}/push`, { method: 'POST', body: '{}' }); }));
  $('discard').addEventListener('click', () => withSelected(async () => { if (confirm('worktreeとJob履歴を削除しますか？この操作は戻せません。')) { await request(`/api/jobs/${state.selected}`, { method: 'DELETE' }); state.selected = null; $('detail').classList.add('hidden'); } }));
  document.querySelectorAll('.tab').forEach((tab) => tab.addEventListener('click', () => { document.querySelectorAll('.tab').forEach((item) => item.classList.toggle('active', item === tab)); ['log', 'diff', 'markdown'].forEach((id) => $(id).classList.toggle('hidden', id !== tab.dataset.tab)); }));
  async function boot() { try { await request('/api/health'); $('connection').textContent = 'PC ● Online'; $('connection').classList.add('online'); await Promise.all([loadProjects(), loadAgents()]); await loadJobs(); } catch (error) { $('connection').textContent = 'PC ● Offline'; setError(error.message); } }
  boot(); setInterval(() => loadJobs().catch(() => {}), 4000);
})();
