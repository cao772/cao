const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function app(api=async()=>({items:[]})) {
 const elements=new Map();
 const c=vm.createContext({URL, api, portfolioDate:x=>String(x), escapeHtml:x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),document:{getElementById(id){if(!elements.has(id)) elements.set(id,{value:id==='news-mode'?'hot':'',innerHTML:''}); return elements.get(id);}}});
 const source=fs.readFileSync(require('node:path').join(__dirname,'../industry-news.js'),'utf8').split("newsEls.nav.addEventListener")[0];
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
