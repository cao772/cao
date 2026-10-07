(() => {
  'use strict';
  const el = id => document.getElementById(id);
  let bindings = [];
  let pending = null;
  const labels = {creating_workspace:'正在创建工作区', starting_agent:'正在启动 Codex', agent_started:'Codex 已启动', blocked_compatibility:'Host 版本不兼容，已阻止后续写入', unknown:'执行结果待核实，禁止重复启动'};
  async function api(path, data) {
    const response = await fetch(`/api/v1/execution/${path}`, {
      method: data ? 'POST' : 'GET',
      headers: {'Content-Type':'application/json', 'X-Collector-Token':el('token').value},
      ...(data ? {body:JSON.stringify(data)} : {})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : `请求失败 (${response.status})`);
    return result;
  }
  function note(text) { el('status').textContent = text; }
  async function refresh() {
    const result = await api('runs');
    el('runs').replaceChildren();
    for (const item of result.executions) {
      const row = document.createElement('article');
      const title = document.createElement('strong');
      title.textContent = `${item.task_title} · ${labels[item.status] || item.status}`;
      const description = document.createElement('p');
      description.textContent = `${item.project_id} / ${item.repository_id} · Workspace ${item.workspace_id} · Session ${item.session_id || '未确认'} · 正式完成：未确认`;
      const button = document.createElement('button');
      button.className = 'secondary-button'; button.textContent = '检查工作区与进程';
      button.onclick = async () => {try {const state=await api(`runs/${item.id}`);description.textContent=`${state.workspace.worktreePath} · 进程 ${state.runtime_status} · 进程状态不代表任务完成`;}catch(error){note(error.message);}};
      row.append(title,description,button); el('runs').append(row);
    }
    if (!result.executions.length) el('runs').textContent = '尚无执行记录';
  }
  el('connect').onclick = async () => {
    try {
      const provider = await api('provider'); bindings = provider.bindings;
      el('repository').replaceChildren();
      for (const [index,binding] of bindings.entries()) {
        const option=document.createElement('option'); option.value=String(index);
        option.textContent=`${binding.project_id} / ${binding.repository_id}`; el('repository').append(option);
      }
      el('repository').disabled=!bindings.length;
      el('start').disabled=!bindings.length || !provider.compatibility?.version_matches;
      el('refresh').disabled=false;
      note(provider.compatibility?.version_matches
        ? `本地 Host ${provider.health.version} 已连接 · ${bindings.length} 个授权仓库`
        : `本地 Host ${provider.health.version || '版本未知'} 不兼容，已禁止启动；需要 ${provider.compatibility?.expected_version || '已验证版本'}`);
      await refresh();
    } catch(error) { note(error.message); el('start').disabled=true; }
  };
  el('refresh').onclick = () => refresh().catch(error => note(error.message));
  el('launch').onsubmit = async event => {
    event.preventDefault();
    const binding=bindings[Number(el('repository').value)]; if(!binding)return;
    const draft={project_id:binding.project_id,repository_id:binding.repository_id,task_id:el('task').value,task_title:el('title').value,prompt:el('prompt').value,agent:'codex'};
    if(!pending || JSON.stringify(pending.draft)!==JSON.stringify(draft))pending={draft,request_id:crypto.randomUUID()};
    el('start').disabled=true;
    try {
      const result=await api('runs',{...draft,request_id:pending.request_id});
      note(labels[result.status] || result.status); await refresh();
      if(result.status==='unknown')return;
      pending=null;
    } catch(error) { note(`${error.message}；重试将沿用同一请求 ID。`); }
    finally {el('start').disabled=false;}
  };
})();
