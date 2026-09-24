const renderSearchResultsBeforeCommunications = renderSearchResults;
renderSearchResults = function renderSearchResultsWithCommunications(payload) {
  const materialPayload = Object.assign({}, payload, {count:payload.material_count == null ? payload.count : payload.material_count});
  renderSearchResultsBeforeCommunications(materialPayload);
  const communications = payload.communications || [];
  if (!communications.length) {
    if ((payload.material_count || 0) === 0) {
      intelligenceEls.searchStatus.textContent = "没有找到匹配的项目材料或微信沟通。";
    }
    return;
  }

  const html = communications.map(function(item) {
    const sender = item.sender || "未知发送人";
    const labels = (item.category_labels || []).join(" / ") || "项目沟通";
    return '<div class="search-result"><div class="search-result-head"><div class="search-result-title"><strong>' +
      escapeHtml(item.conversation_name || "微信群") + '</strong><div class="search-result-path">' +
      escapeHtml(sender) + " · " + escapeHtml(intelligenceDate(item.observed_at)) +
      '</div></div><div><span class="badge info">微信沟通</span></div></div><div class="search-result-snippet">' +
      escapeHtml(item.text || "") + '</div><div class="search-result-footer"><span>' + escapeHtml(labels) +
      '</span><span>来源：个人微信</span></div></div>';
  }).join("");

  intelligenceEls.searchResults.insertAdjacentHTML("beforeend", html);
  intelligenceEls.searchStatus.textContent =
    "找到 " + (payload.count || 0) + " 项（材料 " + (payload.material_count || 0) +
    "，微信 " + (payload.communication_count || 0) + "）。材料与项目沟通已统一检索。";
};

const renderIntelligenceSummaryBeforeCommunications = renderIntelligenceSummary;
renderIntelligenceSummary = function renderIntelligenceSummaryWithCommunications(data) {
  renderIntelligenceSummaryBeforeCommunications(data);
  const messageCount = (data.communications && data.communications.message_count) || 0;
  if (!messageCount) return;
  const card = document.createElement("div");
  card.className = "intelligence-summary-card";
  card.innerHTML = "<span>微信消息</span><strong>" + escapeHtml(messageCount) + "</strong>";
  intelligenceEls.summary.appendChild(card);
};

const loadProjectIntelligenceBeforeCommunications = loadProjectIntelligence;
loadProjectIntelligence = async function loadProjectIntelligenceWithCommunications(projectId) {
  await loadProjectIntelligenceBeforeCommunications(projectId);
  const count = (intelligenceState.data && intelligenceState.data.communications && intelligenceState.data.communications.message_count) || 0;
  if (count) intelligenceEls.subtitle.textContent = "理解项目材料、微信沟通、版本关系和最近变化，并统一搜索关键信息";
};
