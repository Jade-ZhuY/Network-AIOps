'use strict';

const governanceView = {selected:null,offset:0,sequence:0,detailSequence:0};
const governanceStatusLabels = {open:'待处理',in_progress:'处理中',resolved:'已验证关闭',dismissed:'暂不处理'};
const governanceKindLabels = {sql_review:'SQL 待审核',source_missing:'源数据缺口',semantic_gap:'指标能力缺口',semantic_ambiguity:'口径有歧义',execution_failure:'查询执行异常'};

function resetGovernance(){
  governanceView.selected=null;governanceView.offset=0;governanceView.sequence++;governanceView.detailSequence++;
  for(const id of ['governance-list','governance-detail','governance-counts'])document.getElementById(id).replaceChildren();
  document.getElementById('governance-storage').textContent='';
  document.getElementById('governance-status').value='';document.getElementById('governance-kind').value='';document.getElementById('governance-page').textContent='';
}

function updateGovernanceLink(result){
  const root=document.getElementById('governance-link-'+result.request_id);
  if(!root)return;
  root.replaceChildren();
  const feedback=result.governance_feedback;
  if(!feedback)return;
  if(feedback.capture_status==='pending'){
    root.append(el('span','',feedback.message||'治理反馈尚未归档，可补收。'));
    const collect=el('button','resume-button','补收本次反馈');
    collect.addEventListener('click',async()=>{
      const epoch=state.epoch;collect.disabled=true;
      try{
        await api('/governance/capture/'+encodeURIComponent(result.request_id),{method:'POST'});
        if(epoch!==state.epoch)return;
        const detail=await api('/requests/'+encodeURIComponent(result.request_id));
        if(epoch!==state.epoch)return;
        result.governance_feedback=detail.response.governance_feedback;
        updateGovernanceLink(result);
      }catch(error){if(epoch===state.epoch)toast(error.message,true);}
      finally{collect.disabled=false;}
    });
    root.append(collect);
  }
  for(const caseId of feedback.case_ids||[]){
    const button=el('button','resume-button','已记录治理反馈 · 查看 ↗');
    button.addEventListener('click',()=>{governanceView.selected=caseId;switchView('governance');});
    root.append(button);
  }
}

function appendGovernanceLink(card,result){
  if(!result.session_id)return;
  const root=el('div','governance-report-link');root.id='governance-link-'+result.request_id;
  card.append(root);
  // Rendering is deferred until addReport has attached the card to the document.
}

async function loadGovernance(){
  const epoch=state.epoch,sequence=++governanceView.sequence;
  const params=new URLSearchParams({offset:String(governanceView.offset),limit:'20'});
  if($('governance-status').value)params.set('status',$('governance-status').value);
  if($('governance-kind').value)params.set('kind',$('governance-kind').value);
  const data=await api('/governance/cases?'+params.toString());
  if(epoch!==state.epoch||sequence!==governanceView.sequence)return;
  if(data.offset>0&&data.offset>=data.total){governanceView.offset=data.total?Math.floor((data.total-1)/20)*20:0;return loadGovernance();}
  $('governance-storage').textContent=data.durable?'治理反馈保存于 PostgreSQL；与当前用户、租户和权限范围绑定。':'内存测试模式：应用重启后治理记录不保留。';
  $('governance-counts').replaceChildren();
  for(const key of ['open','in_progress','resolved','dismissed']){
    const item=el('div','governance-counter');item.append(el('b','',data.counts[key]||0),el('span','',governanceStatusLabels[key]));$('governance-counts').append(item);
  }
  $('governance-page').textContent=data.total?'第 '+(data.offset+1)+'–'+Math.min(data.offset+data.limit,data.total)+' 条 / '+data.total+' 条':'暂无匹配记录';
  $('governance-prev').disabled=data.offset===0;
  $('governance-next').disabled=data.offset+data.limit>=data.total;
  const list=$('governance-list');list.replaceChildren();
  if(!data.cases.length)list.append(el('p','governance-empty','当前没有匹配的治理项。问数中发现的能力缺口、口径歧义和待审核 SQL 会自动进入这里；也可补收历史请求。'));
  if(!governanceView.selected&&data.cases.length)governanceView.selected=data.cases[0].case_id;
  for(const row of data.cases){
    const button=el('button','governance-case'+(row.case_id===governanceView.selected?' selected':''));
    const top=el('div','review-heading');top.append(el('span','case-id',governanceKindLabels[row.kind]),el('span','governance-status '+row.status,governanceStatusLabels[row.status]));
    button.append(top,el('b','case-question',row.question),el('small','',row.occurrence_count+' 次记录 · '+(row.assignee||'未填写处理人')));
    button.addEventListener('click',()=>{governanceView.selected=row.case_id;loadGovernance().catch(error=>toast(error.message,true));});
    list.append(button);
  }
  if(governanceView.selected)await loadGovernanceDetail(governanceView.selected);
  else $('governance-detail').replaceChildren(el('p','governance-empty','选择一个治理项，查看原因、处理记录与验证证据。'));
}

async function openGovernanceRequest(requestId){
  if(state.busy){toast('请等待当前查询结束。');return;}
  const epoch=state.epoch;
  try{
    const request=await api('/requests/'+encodeURIComponent(requestId));
    if(epoch!==state.epoch)return;
    const session=await api('/sessions/'+encodeURIComponent(request.session_id));
    if(epoch!==state.epoch)return;
    await selectSession(session);
    if(epoch===state.epoch&&request.response)showDetails(request.response);
  }catch(error){if(epoch===state.epoch)toast(error.message,true);}
}

function governanceField(form,title,input){
  const label=el('label','governance-field');label.append(el('span','',title),input);form.append(label);return input;
}

async function loadGovernanceDetail(caseId){
  const epoch=state.epoch,sequence=++governanceView.detailSequence;
  const row=await api('/governance/cases/'+encodeURIComponent(caseId));
  if(epoch!==state.epoch||sequence!==governanceView.detailSequence||caseId!==governanceView.selected)return;
  const root=$('governance-detail');root.replaceChildren();
  const head=el('div','review-heading');head.append(el('span','eyebrow','COLLECT → TRIAGE → VERIFY'),el('span','governance-status '+row.status,governanceStatusLabels[row.status]));
  root.append(head,el('h2','',row.question),el('p','source-meta',row.case_id+' · v'+row.revision+' · '+row.timezone));
  listSection(root,'记录原因',row.reasons.length?row.reasons:row.reason_codes);
  root.append(el('p','governance-hint','审核和发布不自动结案。需发布后重新查询，或修复后重查原问题，再用实际成功请求验证关闭。'));
  const occurrences=Object.values(row.occurrences).sort((a,b)=>b.captured_at.localeCompare(a.captured_at));
  const source=occurrences.find(o=>o.query_ids.length)||occurrences[0];
  if(source){const open=el('button','review-button','打开调查 · 审核 / 发布 ↗');open.addEventListener('click',()=>openGovernanceRequest(source.request_id));root.append(open);}
  if(Object.keys(row.metric_links).length){
    const links=el('section','governance-artifacts');links.append(el('h3','','关联正式指标'));
    for(const metric of Object.values(row.metric_links))links.append(el('p','',metric.label+' / v'+metric.version+' · '+(metric.active?(row.status==='resolved'&&row.resolution?.metric_id===metric.metric_id?'已发布，已验证':'已发布，待验证'):'已撤回')));
    const open=el('button','resume-button','查看正式指标库 ↗');open.addEventListener('click',()=>switchView('metrics'));links.append(open);root.append(links);
  }
  const form=el('form','governance-form');form.append(el('h3','','处理记录'));
  const status=el('select');
  for(const key of ['open','in_progress','dismissed']){const option=el('option','',governanceStatusLabels[key]);option.value=key;status.append(option);}
  status.value=row.status==='resolved'?'open':row.status;
  governanceField(form,'处理状态（已解决只能由验证产生）',status);
  const assignee=el('input');assignee.value=row.assignee;assignee.maxLength=80;assignee.placeholder='仅作处理人备注，不授予访问权限';governanceField(form,'处理人备注（选填）',assignee);
  const note=el('textarea');note.rows=2;note.minLength=5;note.maxLength=1200;note.required=true;note.placeholder='说明补什么数据、调整什么口径，或暂不处理的原因';governanceField(form,'处理说明',note);
  const save=el('button','review-button',row.status==='resolved'?'重新打开并保存说明':'保存处理记录');save.type='submit';form.append(save);
  form.addEventListener('submit',async event=>{
    event.preventDefault();save.disabled=true;
    try{await api('/governance/cases/'+encodeURIComponent(caseId),{method:'PATCH',body:{expected_revision:row.revision,status:status.value,assignee:assignee.value,note:note.value}});if(epoch===state.epoch)await loadGovernance();}
    catch(error){if(epoch===state.epoch)toast(error.message,true);}
    finally{save.disabled=false;}
  });root.append(form);
  if(!['resolved','dismissed'].includes(row.status)){
    const verify=el('form','governance-form verify-form');verify.append(el('h3','','验证并关闭'),el('p','governance-hint','先到调查页重新查询。本操作只核验已保存的请求，不自动执行 SQL。'));
    const mode=el('select');for(const [value,text] of [['published_metric','正式指标发布后，已重新查询'],['original_query_fixed','源数据 / 原问法修复，原问题已成功'],['clarification_confirmed','本次调查口径已澄清，查询已成功']]){const option=el('option','',text);option.value=value;mode.append(option);}governanceField(verify,'验证方式',mode);
    const metric=el('select');const blank=el('option','','选择来自本项的正式指标');blank.value='';metric.append(blank);
    for(const item of Object.values(row.metric_links).filter(m=>m.active)){const option=el('option','',item.label+' / v'+item.version);option.value=item.metric_id;metric.append(option);}governanceField(verify,'关联指标（原问题修复时不用选择）',metric);
    const proof=el('input');proof.maxLength=64;proof.required=true;proof.placeholder='req_…，从下方请求记录复制';governanceField(verify,'证明请求 ID',proof);
    const notes=el('textarea');notes.rows=2;notes.minLength=10;notes.maxLength=1200;notes.required=true;notes.placeholder='说明解决了什么，以及已核对的口径与证据';governanceField(verify,'验证说明',notes);
    const confirm=el('input');confirm.type='checkbox';confirm.required=true;const confirmation=el('label','contract-confirm');confirmation.append(confirm,el('span','','我确认证明请求与本治理项针对同一问题，已核对查询定义和实际证据。'));verify.append(confirmation);
    const submit=el('button','publish-metric-button','验证并关闭');submit.type='submit';verify.append(submit);
    mode.addEventListener('change',()=>{metric.disabled=mode.value!=='published_metric';});
    verify.addEventListener('submit',async event=>{
      event.preventDefault();submit.disabled=true;
      try{
        const result=await api('/governance/cases/'+encodeURIComponent(caseId)+'/verify',{method:'POST',body:{expected_revision:row.revision,proof_request_id:proof.value.trim(),resolution_kind:mode.value,metric_id:mode.value==='published_metric'?metric.value:null,note:notes.value,confirm_scope:confirm.checked}});
        if(epoch!==state.epoch)return;
        toast(result.verified?'证据校验通过，治理项已关闭。':'验证未通过，记录仍待处理，请查看检查项。',!result.verified);await loadGovernance();
      }catch(error){if(epoch===state.epoch)toast(error.message,true);}
      finally{submit.disabled=false;}
    });root.append(verify);
  }
  if(row.last_verification){
    const receipt=el('section','governance-receipt');receipt.append(el('h3','',row.last_verification.verified?(row.status==='resolved'?'最近验证 · 通过':'历史验证 · 通过（当前已重新打开）'):'最近验证 · 未通过'));
    for(const check of row.last_verification.checks)receipt.append(el('p',check.passed?'check-pass':'check-fail',(check.passed?'✓ ':'! ')+check.description));root.append(receipt);
  }
  const requests=el('details','metric-contract');requests.append(el('summary','','请求记录 · '+occurrences.length));
  for(const occurrence of occurrences){const item=el('div','governance-occurrence');item.append(el('code','',occurrence.request_id),el('small','',occurrence.status+' · '+(occurrence.query_path||'unknown')));const open=el('button','resume-button','打开');open.addEventListener('click',()=>openGovernanceRequest(occurrence.request_id));item.append(open);requests.append(item);}root.append(requests);
  const history=el('details','metric-contract');history.append(el('summary','','处理历史 · 最近 '+row.history.length+' / '+row.history_count+' 条'));
  for(const event of [...row.history].reverse())history.append(el('p','source-meta',event.at+' · '+event.actor+' · '+event.action+(event.note?'\n'+event.note:'')));root.append(history);
}

for(const id of ['governance-status','governance-kind'])document.getElementById(id).addEventListener('change',()=>{governanceView.offset=0;governanceView.selected=null;loadGovernance().catch(error=>toast(error.message,true));});
document.getElementById('refresh-governance').addEventListener('click',()=>loadGovernance().catch(error=>toast(error.message,true)));
document.getElementById('governance-prev').addEventListener('click',()=>{governanceView.offset=Math.max(0,governanceView.offset-20);loadGovernance().catch(error=>toast(error.message,true));});
document.getElementById('governance-next').addEventListener('click',()=>{governanceView.offset+=20;loadGovernance().catch(error=>toast(error.message,true));});
document.getElementById('collect-governance').addEventListener('click',async()=>{
  const epoch=state.epoch,button=$('collect-governance');button.disabled=true;
  try{const result=await api('/governance/collect?limit=20',{method:'POST'});if(epoch!==state.epoch)return;toast('检查 '+result.examined+' 条请求，归档 '+result.recorded+' 条，待补收 '+result.pending.length+' 条。');await loadGovernance();}
  catch(error){if(epoch===state.epoch)toast(error.message,true);}
  finally{button.disabled=false;}
});
