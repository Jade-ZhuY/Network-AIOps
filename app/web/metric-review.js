'use strict';

// Loaded before app.js. Handlers run after its authenticated state is ready.
let metricPublishContext = null;

function updateReportReviewSummary(result) {
  const node=document.getElementById('review-summary-'+result.request_id);
  if(!node)return;
  const reviews=Object.values(result.query_reviews||{});
  const stale=reviews.some(review=>review.evidence_changed);
  const verdict=stale?'证据已变化，请重新核对':reviews.some(review=>review.verdict==='changes_requested')?'需要修改':reviews.length&&reviews.every(review=>review.verdict==='approved')?'结果正确':'待核对';
  node.textContent='当前人工审核：'+verdict+'。下方保留生成时的原始报告与状态。';
}

function appendReportReviewSummary(card,result) {
  if(!result.report.requires_review)return;
  const node=el('div','report-review-summary');
  node.id='review-summary-'+result.request_id;
  card.append(node);
  // The card is not attached yet, so set the initial text directly.
  const reviews=Object.values(result.query_reviews||{});
  node.textContent='模型生成 SQL · 原始报告标记为待核对。当前人工审核结论见证据卡片。';
  if(reviews.length&&reviews.every(r=>r.verdict==='approved'&&!r.evidence_changed))node.textContent='当前人工审核：结果正确。下方保留生成时的原始报告与状态。';
  else if(reviews.some(r=>r.verdict==='changes_requested'))node.textContent='当前人工审核：需要修改。下方保留生成时的原始报告与状态。';
}

function resetMetricReview() {
  metricPublishContext = null;
  const dialog = document.getElementById('metric-publish-dialog');
  if (dialog.open) dialog.close();
  document.getElementById('metric-publish-form').reset();
  document.getElementById('metric-publish-contract').textContent='';
  document.getElementById('metric-publish-error').textContent='';
}

function queryReviewPath(result, query) {
  return '/requests/' + encodeURIComponent(result.request_id) + '/queries/' + encodeURIComponent(query.query_id);
}

async function refreshQueryReview(result, epoch) {
  if (epoch !== state.epoch) return;
  const detail = await api('/requests/' + encodeURIComponent(result.request_id));
  if (epoch !== state.epoch) return;
  result.query_reviews = detail.response.query_reviews || {};
  result.governance_feedback = detail.response.governance_feedback;
  updateGovernanceLink(result);
  updateReportReviewSummary(result);
  if (state.lastResult === result) showDetails(result);
}

function appendQueryReviewControls(card, result, query) {
  if (!result.session_id || !state.user || query.kind !== 'generated_sql') return;
  const review = result.query_reviews?.[query.query_id] || {verdict:'pending',revision:0};
  const panel = el('section','query-review');
  panel.setAttribute('aria-label','查询结果人工审核');
  const header = el('div','review-heading');
  const labels = {pending:'待核对',approved:'结果正确',changes_requested:'需要修改'};
  header.append(el('b','','人工审核'),el('span','review-status '+review.verdict,review.evidence_changed?'证据已变化，请重新审核':labels[review.verdict]));
  panel.append(header,el('p','review-note','审核只记录你的判断，不自动修改原始 SQL 或查询结果。'));
  if (review.reviewed_at) panel.append(el('div','source-meta',review.reviewed_by+' · '+new Date(review.reviewed_at).toLocaleString('zh-CN')+' · 审核 v'+review.revision));
  const comment = el('textarea','review-comment');
  comment.maxLength=1200;
  comment.rows=2;
  comment.value=review.comment || '';
  comment.placeholder='核对意见：例如阈值、统计方式或需要修改的地方（选填）';
  comment.setAttribute('aria-label','人工审核意见');
  const actions=el('div','review-actions');
  const correct=el('button','review-button','✓ 结果正确');
  const change=el('button','review-button revise','↺ 需要修改');
  correct.type=change.type='button';
  correct.setAttribute('aria-pressed',String(review.verdict==='approved'));
  change.setAttribute('aria-pressed',String(review.verdict==='changes_requested'));
  actions.append(correct,change);
  const submit=async verdict=>{
    if (state.busy) {toast('请等待当前查询结束。');return;}
    if (review.published_metric?.active && !confirm('重新审核会撤回关联的正式指标；之后需要再次明确发布。继续吗？')) return;
    const epoch=state.epoch;
    correct.disabled=change.disabled=true;
    try {
      await api(queryReviewPath(result,query)+'/review',{method:'PUT',body:{verdict,comment:comment.value,expected_revision:review.revision}});
      await refreshQueryReview(result,epoch);
      if(epoch===state.epoch)toast(verdict==='approved'?'已记录“结果正确”。可继续整理为正式指标。':'已记录“需要修改”；关联正式指标已撤回。');
    } catch(error) {if(epoch===state.epoch)toast(error.message,true);}
    finally {correct.disabled=change.disabled=false;}
  };
  correct.addEventListener('click',()=>submit('approved'));
  change.addEventListener('click',()=>submit('changes_requested'));
  panel.append(comment,actions);
  if(review.verdict==='approved'&&!review.evidence_changed){
    const publish=el('button','publish-metric-button',review.published_metric?.active?'已发布 · '+review.published_metric.label+' ↗':'整理为正式指标 →');
    publish.type='button';
    publish.addEventListener('click',()=>{
      if(review.published_metric?.active)switchView('metrics');
      else openMetricPublish(result,query,publish);
    });
    panel.append(publish);
  }
  if(result.checkpoint_backend==='memory')panel.append(el('p','review-note','当前为内存模式：审核和正式指标在应用重启后不保留。'));
  card.append(panel);
}

async function openMetricPublish(result,query,button){
  const epoch=state.epoch;
  button.disabled=true;
  try{
    const candidate=await api(queryReviewPath(result,query)+'/metric-candidate');
    if(epoch!==state.epoch)return;
    if(!candidate.eligible){toast(candidate.reason,true);return;}
    if(candidate.review.verdict!=='approved'||candidate.review.evidence_changed){toast('请先对当前证据确认“结果正确”。',true);return;}
    metricPublishContext={result,query,candidate,epoch};
    $('metric-publish-form').reset();
    $('metric-publish-error').textContent='';
    $('metric-publish-contract').textContent=JSON.stringify(candidate.contract,null,2);
    $('metric-publish-submit').disabled=false;
    $('metric-publish-dialog').showModal();
    $('metric-label').focus();
  }catch(error){if(epoch===state.epoch)toast(error.message,true);}
  finally{button.disabled=false;}
}

document.getElementById('metric-publish-cancel').addEventListener('click',resetMetricReview);
document.getElementById('metric-publish-dialog').addEventListener('cancel',()=>{metricPublishContext=null;});
document.getElementById('metric-publish-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const context=metricPublishContext;
  if(!context||context.epoch!==state.epoch)return;
  const button=$('metric-publish-submit');
  button.disabled=true;
  $('metric-publish-error').textContent='';
  try{
    await api(queryReviewPath(context.result,context.query)+'/metric',{method:'POST',body:{label:$('metric-label').value.trim(),aliases:$('metric-aliases').value.split(/[,，、\n]/).map(v=>v.trim()).filter(Boolean),description:$('metric-description').value.trim(),review_revision:context.candidate.review.revision,confirm_contract:$('metric-confirm-contract').checked}});
    if(context.epoch!==state.epoch)return;
    resetMetricReview();
    await refreshQueryReview(context.result,context.epoch);
    if(context.epoch===state.epoch)toast('正式指标已发布。后续按名称调用，不再生成这条 SQL。');
  }catch(error){if(context.epoch===state.epoch)$('metric-publish-error').textContent=error.message;}
  finally{button.disabled=false;}
});

async function loadReviewedMetrics(){
  const epoch=state.epoch;
  const data=await api('/metrics/reviewed?include_inactive=true');
  if(epoch!==state.epoch)return;
  const root=$('reviewed-metrics');
  root.replaceChildren();
  $('reviewed-metric-count').textContent=data.metrics.filter(m=>m.active).length+' 个已发布';
  $('reviewed-metric-storage').textContent=data.durable?'审核与指标定义保存在 PostgreSQL。':'当前为内存模式：应用重启后，审核与正式指标不保留。';
  if(!data.metrics.length){
    const empty=el('div','metric-empty');
    empty.append(el('span','eyebrow','REVIEW → DEFINE → REUSE'),el('h2','','先确认一次，以后口径一致。'),el('p','','在模型 SQL 的证据卡片点击“结果正确”，再选择“整理为正式指标”。这里发布的是固定查询定义，不是历史结果缓存。'));
    root.append(empty);
  }
  for(const metric of data.metrics){
    const card=el('article','formal-metric-card'+(metric.active?'':' withdrawn'));
    const heading=el('div','review-heading');
    heading.append(el('span','case-id','REVIEWED METRIC / V'+metric.version),el('span','review-status '+(metric.active?'approved':'changes_requested'),metric.active?'已发布':'已撤回'));
    card.append(heading,el('h2','',metric.label),el('p','metric-description',metric.description));
    if(metric.aliases.length)card.append(el('p','source-meta','别名：'+metric.aliases.join(' / ')));
    card.append(el('div','source-meta','审核：'+metric.reviewed_by+' · '+new Date(metric.reviewed_at).toLocaleString('zh-CN')));
    const details=el('details','metric-contract');
    details.append(el('summary','','查看固定口径、SQL 与版本指纹'),el('pre','',JSON.stringify({definition_hash:metric.definition_hash,...metric.contract},null,2)));
    card.append(details);
    if(metric.active){
      const actions=el('div','review-actions');
      const use=el('button','review-button','查询该指标 ↗');
      use.addEventListener('click',()=>{switchView('chat');$('question').value='查询指标「'+metric.label+'」 R2'+(metric.contract.time_column?' 昨天':'');$('question').focus();toast('请确认设备和时间，再发送查询。');});
      const withdraw=el('button','review-button revise','撤回指标');
      withdraw.addEventListener('click',async()=>{
        if(!confirm('撤回后，新请求将不再使用这个正式指标。继续吗？'))return;
        withdraw.disabled=true;
        try{await api('/metrics/reviewed/'+encodeURIComponent(metric.metric_id)+'?version='+metric.version,{method:'DELETE'});if(epoch===state.epoch)await loadReviewedMetrics();}
        catch(error){if(epoch===state.epoch)toast(error.message,true);}
        finally{withdraw.disabled=false;}
      });
      actions.append(use,withdraw);card.append(actions);
    }
    root.append(card);
  }
}
document.getElementById('refresh-reviewed-metrics').addEventListener('click',()=>loadReviewedMetrics().catch(error=>toast(error.message,true)));
