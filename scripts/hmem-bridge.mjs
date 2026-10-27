import fs from 'node:fs';
import { HMEM } from '../vendor/hmem/index.ts';
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const h=new HMEM({persistDir:input.path,actor:'signaldesk-user-verified'});
const refs=new Map(h.store.all().map(m=>[m.source,m]));
for(const e of input.evidence){
  const source=`signaldesk:evidence:${e.id}`;
  if(refs.has(source))continue;
  const prior=e.supersedes?refs.get(`signaldesk:evidence:${e.supersedes}`):null;
  const m=h.add({content:`${e.status}: ${e.claim}`,type:'factual',layer:'long_term',tags:['project:relationships',`org:${input.org}`],confidence:e.status==='verified'?1:0.5,source,chatId:input.org,supersedes:prior?.id,provenance:{origin:e.supersedes?'user_correction':'manual',learnedAt:Date.parse(e.created_at),label:`${e.source_date} · ${e.status} by user`,refs:[e.source_url||source]}});
  if(prior)h.store.update(prior.id,{supersededBy:m.id});
  refs.set(source,m);
}
const active=new Set(input.active.map(id=>`signaldesk:evidence:${id}`));
const result=h.query(input.query||'relationship client connection correction',{chatId:input.org,threshold:0,topN:100});
result.memories=result.memories.filter(r=>active.has(r.memory.source)).slice(0,8);
result.context=result.memories.map(r=>r.memory.content).join('\n');
h.store.persist();
console.log(JSON.stringify({engine:'Meterless H-MEM reference 0.1.0',mode:'deterministic reference; hash embeddings',...result}));
