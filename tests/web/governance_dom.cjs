'use strict';
// Isolated DOM/control-flow regression. No browser/server or network is started.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ids=new Map();
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.events={};this.value='';this._text='';this.disabled=false;this.checked=false;this.classList={add(){},remove(){},toggle(){}};}
  set id(value){this._id=value;ids.set(value,this);} get id(){return this._id;}
  set textContent(value){this._text=String(value);this.children=[];} get textContent(){return this._text+this.children.map(c=>typeof c==='string'?c:c.textContent).join('');}
  append(...nodes){this.children.push(...nodes);if(this.tagName==='select'&&!this.value&&this.children.length)this.value=this.children[0].value;}
  replaceChildren(...nodes){this._text='';this.children=[...nodes];}
  addEventListener(name,fn){this.events[name]=fn;}
  setAttribute(name,value){this[name]=value;}
}
const $=id=>{if(!ids.has(id)){const node=new Element();node.id=id;}return ids.get(id);};
const el=(tag,cls,text)=>{const node=new Element(tag);node.className=cls;if(text!==undefined)node.textContent=text;return node;};
const all=node=>[node,...node.children.flatMap(child=>typeof child==='string'?[]:all(child))];
const field=(form,label)=>{const node=all(form).find(n=>n.tagName==='label'&&n.children[0]?.textContent===label);assert.ok(node,label);return node.children[1];};
const row={case_id:'gov_1',question:'查询 R2 昨天接口排名',timezone:'UTC',kind:'sql_review',status:'open',revision:1,assignee:'',reason_codes:['ranking'],reasons:['SQL 需要审核'],occurrences:{req_source:{request_id:'req_source',session_id:'sid',status:'partial',query_path:'text_to_sql',query_ids:['q1'],captured_at:'2026-10-20T00:00:00Z'}},metric_links:{reviewed_1:{metric_id:'reviewed_1',label:'接口排名',active:true,version:1}},history:[],history_count:0,last_verification:null};
const calls=[];
function packet(){return {cases:[{...row,occurrence_count:1}],total:1,offset:0,limit:20,durable:false,counts:{open:row.status==='open'?1:0,in_progress:row.status==='in_progress'?1:0,resolved:row.status==='resolved'?1:0,dismissed:0}};}
const api=async(url,options={})=>{
  calls.push({url,options});
  if(url.startsWith('/governance/cases?'))return structuredClone(packet());
  if(url==='/governance/cases/gov_1'&&!options.method)return structuredClone(row);
  if(url==='/governance/cases/gov_1'&&options.method==='PATCH'){
    assert.equal(options.body.expected_revision,row.revision);assert.equal(options.body.status,'in_progress');
    Object.assign(row,options.body,{revision:row.revision+1});return structuredClone(row);
  }
  if(url==='/governance/cases/gov_1/verify'){
    assert.equal(options.body.proof_request_id,'req_proof');assert.equal(options.body.metric_id,'reviewed_1');assert.equal(options.body.confirm_scope,true);
    row.status='resolved';row.revision++;row.last_verification={verified:true,checks:[{passed:true,description:'实际证据验证通过'}]};
    return {verified:true,case:structuredClone(row)};
  }
  throw new Error('Unexpected route '+url);
};
const state={epoch:1,user:{user_id:'test'},busy:false};
const context=vm.createContext({document:{getElementById:$},$,el,state,api,URLSearchParams,console,toast(){},listSection(parent,title,items){parent.append(el('h3','',title),...items.map(text=>el('p','',text)));},switchView(){},selectSession(){}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../app/web/governance.js'),'utf8'),context);
(async()=>{
  await vm.runInContext('loadGovernance()',context);
  assert.match($('governance-list').textContent,/查询 R2/);
  assert.match($('governance-detail').textContent,/验证并关闭/);
  assert.match($('governance-storage').textContent,/内存测试模式/);
  let form=all($('governance-detail')).find(n=>n.tagName==='form'&&n.className==='governance-form');
  field(form,'处理状态（已解决只能由验证产生）').value='in_progress';
  field(form,'处理人备注（选填）').value='测试处理人';field(form,'处理说明').value='审核后发布指标，再重新查询验证';
  await form.events.submit({preventDefault(){}});
  assert.equal(row.status,'in_progress');
  form=all($('governance-detail')).find(n=>n.tagName==='form'&&n.className.includes('verify-form'));
  field(form,'关联指标（原问题修复时不用选择）').value='reviewed_1';field(form,'证明请求 ID').value='req_proof';
  field(form,'验证说明').value='已重新查询并核对实际证据与统计口径';
  all(form).find(n=>n.tagName==='input'&&n.type==='checkbox').checked=true;
  await form.events.submit({preventDefault(){}});
  assert.equal(row.status,'resolved');assert.match($('governance-detail').textContent,/实际证据验证通过/);
  assert.equal(all($('governance-detail')).filter(n=>n.tagName==='form'&&n.className.includes('verify-form')).length,0);
  assert.equal(calls.filter(c=>c.url.endsWith('/verify')).length,1);
  assert.ok(calls.every(c=>!c.options.body||!('sql' in c.options.body)));
  // A late request may not repopulate private controls after logout/reset.
  let release;
  context.api=()=>new Promise(resolve=>{release=resolve;});
  const pending=vm.runInContext('loadGovernance()',context);
  state.epoch++;vm.runInContext('resetGovernance()',context);release(packet());await pending;
  assert.equal($('governance-list').children.length,0);assert.equal($('governance-detail').children.length,0);
  console.log('Governance DOM flow passed: list, triage, proof verification, resolved display, stale-login isolation; no server started.');
})().catch(error=>{console.error(error);process.exitCode=1;});
