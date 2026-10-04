const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function app(api=async()=>({items:[]})) {
 const elements=new Map();
 const c=vm.createContext({URL, api, portfolioDate:x=>String(x), escapeHtml:x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),document:{getElementById(id){if(!elements.has(id)) elements.set(id,{value:id==='news-mode'?'hot':'',innerHTML:''}); return elements.get(id);}}});
 const source=fs.readFileSync(require('node:path').join(__dirname,'../industry-news.js'),'utf8').split("newsEls.nav.addEventListener")[0];
 const appSource=fs.readFileSync(require('node:path').join(__dirname,'../app.js'),'utf8');
 vm.runInContext(appSource.slice(appSource.indexOf('function highlightEvidence('),appSource.indexOf('function renderGlobalSearchResults(')),c);
 vm.runInContext(source,c); return {c,elements};
}
test('news links reject executable URLs and credential-bearing URLs',()=>{
 const {c}=app();assert.equal(c.newsLink('javascript:alert(1)','bad'),'');assert.equal(c.newsLink('https://u:password@example.com','bad'),'');assert.match(c.newsLink('https://example.com','source'),/noopener noreferrer/);
});
test('unknown publication stays unknown, content is escaped, and filtering stays local',()=>{
 const {c,elements}=app();
 vm.runInContext(`newsState.payload={status:'ready',items:[{title:'<script>Agent</script>',summary:'Local evidence',discovered_at:'2026-10-04',url:'https://example.com'}]};`,c);
 c.renderIndustryNews();const html=elements.get('news-results').innerHTML;assert.match(html,/原文发布：未提供/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
 elements.get('news-query').value='does not match';c.renderIndustryNews();assert.match(elements.get('news-results').innerHTML,/当前已载入列表没有匹配/);
});
test('older news requests cannot overwrite a newer column',async()=>{
 const pending=[];const {c,elements}=app(path=>new Promise(resolve=>pending.push({path,resolve})));
 const old=c.loadIndustryNews();elements.get('news-mode').value='daily';const fresh=c.loadIndustryNews();
 pending[0].resolve({status:'ready',items:[{title:'OLD'}]});await old;assert.equal(elements.get('news-refresh').disabled,true);
 pending[1].resolve({status:'ready',items:[{title:'NEW'}]});await fresh;assert.match(elements.get('news-results').innerHTML,/NEW/);assert.doesNotMatch(elements.get('news-results').innerHTML,/OLD/);assert.equal(elements.get('news-refresh').disabled,false);
});

test('category and keyword filters intersect and preserve original hotspot ranking',()=>{
 const {c,elements}=app();
 vm.runInContext(`newsState.payload={status:'ready',items:[{title:'Agent A',category:'paper',rank:7},{title:'Agent B',category:'ai-products',rank:2},{title:'Other',category:'paper',rank:3}]};`,c);
 elements.get('news-category').value='论文研究';elements.get('news-query').value='Agent';
 c.renderIndustryNews();const html=elements.get('news-results').innerHTML;
 assert.match(html,/热点 #7/);assert.match(html,/<mark>Agent<\/mark>/);
 assert.doesNotMatch(html,/Agent B|Other/);
 assert.match(elements.get('news-status').textContent,/已载入 3 条，筛选匹配 1 条/);
});
test('copy brief keeps provenance, stale status and only the visible filtered rows',()=>{
 const {c,elements}=app();
 vm.runInContext(`newsState.payload={status:'stale',fetched_at:'2026-10-04',items:Array.from({length:15},(_,i)=>({title:'News '+i,category:'paper',url:'https://example.com/'+i,attribution_url:'https://aihot.news/items/'+i}))};`,c);
 const brief=c.newsBrief();assert.match(brief,/来源暂不可用/);assert.match(brief,/原文：https:\/\/example.com\/0/);
 assert.match(brief,/AIHOT：https:\/\/aihot.news\/items\/0/);assert.match(brief,/当前显示的 12 条/);assert.doesNotMatch(brief,/News 12/);
 elements.get('news-query').value='missing';assert.equal(c.newsBrief(),'');c.renderIndustryNews();assert.equal(elements.get('news-copy').disabled,true);
});
test('categories show loaded counts and reset an unavailable selection on column change',()=>{
 const {c,elements}=app();
 vm.runInContext(`newsState.payload={items:[{category:'paper'},{category:'paper'},{category:'industry'}]};`,c);
 elements.get('news-category').value='论文研究';c.updateNewsCategories();
 assert.equal(elements.get('news-category').value,'论文研究');assert.match(elements.get('news-category').innerHTML,/论文研究（2）/);
 vm.runInContext(`newsState.payload={items:[{section:'快讯'}]};`,c);c.updateNewsCategories();assert.equal(elements.get('news-category').value,'');
});
