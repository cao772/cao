const newsState = {requestId: 0, payload: null, visibleCount: 12};
const newsEls = Object.fromEntries(['nav','view','mode','query','status','results','refresh','more','category','copy'].map(key => [key, document.getElementById(`news-${key}`)]));
const newsCategories = {'ai-models':'模型发布','ai-products':'产品发布',industry:'行业动态',paper:'论文研究',tip:'技巧与观点'};
function newsLink(url, label) {
  try {
    const parsed = new URL(url);
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) return '';
    return `<a href="${escapeHtml(parsed.href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
  } catch (_) { return ''; }
}
function newsCategory(item) {
  return item.section || newsCategories[item.category] || '热点事件';
}
function matchingNews() {
  const query = newsEls.query.value.trim().toLocaleLowerCase();
  const category = newsEls.category.value;
  return (newsState.payload?.items || []).filter(item => (!category || newsCategory(item) === category) &&
    [item.title,item.summary,item.source,newsCategory(item)].join(' ').toLocaleLowerCase().includes(query));
}
function updateNewsCategories() {
  const selected = newsEls.category.value;
  const counts = new Map();
  for (const item of newsState.payload?.items || []) {
    const category = newsCategory(item);
    counts.set(category,(counts.get(category) || 0) + 1);
  }
  newsEls.category.innerHTML = '<option value="">全部分类</option>' + [...counts].map(([label,count]) => `<option value="${escapeHtml(label)}">${escapeHtml(label)}（${count}）</option>`).join('');
  newsEls.category.value = counts.has(selected) ? selected : '';
}
function newsBrief() {
  const items = matchingNews().slice(0, newsState.visibleCount);
  const payload = newsState.payload || {};
  if (!items.length) return '';
  const date = value => value ? portfolioDate(value) : '未提供';
  const lines = ['AI 行业资讯 · 当前列表简报',`数据来源：AIHOT · 本机获取 ${date(payload.fetched_at)}`];
  if (payload.status === 'stale') lines.push('来源暂不可用，以下为此前获取的内容。');
  if (payload.report_date) lines.push(`日报日期：${payload.report_date}`);
  items.forEach((item,index) => {
    lines.push('',`${index+1}. ${item.title}${item.rank ? `（热点原始排名 ${item.rank}）` : ''}`,`${newsCategory(item)} · ${item.source || '来源未注明'}`,`原文发布：${date(item.published_at)}`);
    if (item.summary) lines.push(item.summary);
    // Validate URLs using the same rules as the rendered links.
    if (newsLink(item.url,'原文')) lines.push(`原文：${item.url}`);
    if (newsLink(item.attribution_url,'整理页')) lines.push(`AIHOT：${item.attribution_url}`);
  });
  lines.push('',`仅复制当前显示的 ${items.length} 条；摘要来自 AIHOT，未独立核实，请通过原文核对。`);
  return lines.join('\n');
}
function renderIndustryNews() {
  const payload = newsState.payload;
  if (!payload) return;
  const query = newsEls.query.value.trim();
  const items = matchingNews();
  const shown = items.slice(0, newsState.visibleCount);
  const date = value => value ? portfolioDate(value) : '未提供';
  const status = payload.status === 'stale' ? '来源暂时连接失败，展示上次获取的内容。' : payload.status === 'unavailable' ? '来源暂不可用，请稍后重试；不代表没有资讯。' : '已接入 AIHOT 已发布资讯。';
  newsEls.status.textContent = `${status}${payload.fetched_at ? ` 本机获取：${date(payload.fetched_at)}。` : ''}${payload.report_date ? ` 日报日期：${payload.report_date}。` : ''} 已载入 ${payload.items?.length || 0} 条，筛选匹配 ${items.length} 条，显示 ${shown.length} 条。${payload.has_more ? '精选仅载入最近 7 天前 80 条，更多内容可前往来源网站。' : ''}`;
  newsEls.more.hidden = items.length <= shown.length;
  newsEls.copy.disabled = !shown.length;
  newsEls.results.innerHTML = shown.length ? shown.map(item => `<article class="portfolio-search-hit news-card">
    <div class="news-card-category">${item.rank ? `<span class="news-rank">热点 #${escapeHtml(item.rank)}</span> ` : ''}${escapeHtml(newsCategory(item))}${item.source_count != null ? ` · ${escapeHtml(item.source_count)} 个报道来源` : ''}</div>
    <h3>${highlightEvidence(item.title, query)}</h3>
    ${item.summary ? `<p>${highlightEvidence(item.summary, query)}</p><small>以上为 AIHOT 整理的摘要，请通过原文核对。</small>` : ''}
    <small>${escapeHtml(item.source || '来源未注明')}</small>
    <small>原文发布：${escapeHtml(date(item.published_at))}${item.discovered_at ? ` · AIHOT 收录：${escapeHtml(date(item.discovered_at))}` : ''}${item.latest_at ? ` · 事件最近更新：${escapeHtml(date(item.latest_at))}` : ''}</small>
    <div class="news-links">${newsLink(item.url,'查看原文')}${newsLink(item.attribution_url,'AIHOT 整理页')}${newsLink(item.story_url,'事件时间线')}</div>
  </article>`).join('') : `<div class="portfolio-empty">${payload.status === 'unavailable' ? '目前无法读取资讯来源。' : query || newsEls.category.value ? '当前已载入列表没有匹配内容，可换关键词、分类或切换栏目。' : '来源返回的当前栏目暂无条目。'}</div>`;
}
async function loadIndustryNews() {
  const requestId = ++newsState.requestId;
  const mode = newsEls.mode.value;
  newsState.payload = null;
  newsState.visibleCount = 12;
  newsEls.results.innerHTML = '<div class="portfolio-empty">正在读取已发布资讯…</div>';
  newsEls.status.textContent = '正在连接资讯来源…';
  newsEls.more.hidden = true;
  newsEls.refresh.disabled = true;
  newsEls.copy.disabled = true;
  try {
    const payload = await api(`/api/v1/industry-news?view=${encodeURIComponent(mode)}`);
    if (requestId !== newsState.requestId) return;
    newsState.payload = payload;
    updateNewsCategories();
    renderIndustryNews();
  } catch (_) {
    if (requestId !== newsState.requestId) return;
    newsEls.status.textContent = '资讯暂时读取失败，请重试。';
    newsEls.results.innerHTML = '<div class="portfolio-empty">读取失败，不代表没有资讯。</div>';
  } finally {
    if (requestId === newsState.requestId) newsEls.refresh.disabled = false;
  }
}
function showIndustryNews() {
  state.selectedProjectId = null;
  renderProjectList();
  for (const id of ['portfolio-view','dashboard-view','settings-view','intelligence-view']) document.getElementById(id)?.classList.add('hidden');
  for (const id of ['portfolio-nav','settings-nav']) document.getElementById(id)?.classList.remove('active');
  newsEls.view.classList.remove('hidden');
  newsEls.nav.classList.add('active');
  return loadIndustryNews();
}
newsEls.nav.addEventListener('click',showIndustryNews);
newsEls.refresh.addEventListener('click',loadIndustryNews);
newsEls.mode.addEventListener('change',loadIndustryNews);
newsEls.query.addEventListener('input',()=> { newsState.visibleCount=12; renderIndustryNews(); });
newsEls.more.addEventListener('click',()=> { newsState.visibleCount+=12; renderIndustryNews(); });

newsEls.category.addEventListener('change',()=> { newsState.visibleCount=12; renderIndustryNews(); });
newsEls.copy.addEventListener('click',async()=> {
  const brief = newsBrief();
  if (!brief) return;
  try { await navigator.clipboard.writeText(brief); showToast('当前资讯简报已复制，保留来源链接'); }
  catch (_) { showToast('浏览器未允许复制，请重试',true); }
});
