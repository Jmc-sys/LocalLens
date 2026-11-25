/** Read-only ER layout. The only relationship source is INFORMATION_SCHEMA FKs. */
export const SECTIONS = [
  ["accounts", "Accounts & access"],
  ["media", "Media library"],
  ["albums", "Albums & sharing"],
  ["identity", "People, pets & tags"],
  ["processing", "Background processing"],
  ["system", "System & configuration"],
  ["other", "Other"],
];
export function sectionOf(name) {
  const n = String(name || "").toLowerCase();
  if (n === "users" || /^(user_|users_|auth|session|permission|role|login)/.test(n)) return "accounts";
  if (/(album|share|family|collection|invite|group_member)/.test(n)) return "albums";
  if (/(face|person|people|pet|animal|embedding|identity|recognition|ai_tag|tag_feedback|ai_label)/.test(n)) return "identity";
  if (/(scan|index|queue|job|retry|worker|task|scheduler|processing|upload_activ|browser_activ|ai_activity|ai_status)/.test(n)) return "processing";
  if (/(photo|video|media|motion|thumbnail|trash|favorite|asset|file_)/.test(n)) return "media";
  if (/(setting|config|system|audit|event|notification|log)/.test(n)) return "system";
  return "other";
}
export function validEdges(tables, relationships) {
  const names = new Set(tables.map(t => t.name));
  return (relationships || []).filter(e => names.has(e.from_table) && names.has(e.to_table) &&
    Array.isArray(e.from_columns) && Array.isArray(e.to_columns));
}
export function fieldList(table, allFields) {
  const cols = table.columns || [];
  if (allFields) return cols;
  const keys = new Set((table.foreign_keys || []).flatMap(e => e.from_columns || []));
  const important = cols.filter(c => c.primary || keys.has(c.name));
  const regular = cols.filter(c => !c.primary && !keys.has(c.name));
  return [...important, ...regular.slice(0, Math.max(0, 7 - important.length))];
}
export function cardinality(edge, tableByName) {
  const child = tableByName.get(edge.from_table);
  if (!child) return "1 : many";
  const cols = edge.from_columns || [];
  const isUnique = (child.indexes || []).some(i => i.unique && i.columns?.length === cols.length &&
    i.columns.every((c, n) => c === cols[n]));
  return isUnique ? "1 : 0..1" : "1 : 0..N";
}
export function relationshipText(e, byName) {
  return `${e.to_table}.${(e.to_columns || []).join(", ")} → ${e.from_table}.${(e.from_columns || []).join(", ")} · ${cardinality(e, byName)}`;
}

// ll-er-responsive-0610: lay out cards across the available graph width.
export function buildErLayout(tables, relationships, {allFields=false, compact=false, focus=null,containerWidth=1400}={}) {
  const names = new Set(tables.map(t=>t.name));
  const valid = validEdges(tables, relationships);
  let included = tables;
  if (focus && names.has(focus)) {
    const neighborhood = new Set([focus]);
    valid.forEach(e=> { if(e.to_table===focus) neighborhood.add(e.from_table); if(e.from_table===focus) neighborhood.add(e.to_table); });
    included=tables.filter(t=>neighborhood.has(t.name));
  }
  const byName=new Map(included.map(t=>[t.name,t]));
  const edges=valid.filter(e=>byName.has(e.from_table)&&byName.has(e.to_table));
  const children=new Map(included.map(t=>[t.name,[]]));
  const parents=new Map(included.map(t=>[t.name,[]]));
  for(const e of edges) if(e.from_table!==e.to_table){children.get(e.to_table).push(e.from_table);parents.get(e.from_table).push(e.to_table);}
  // ll-er-hierarchy-v0616: organize every declared FK chain under its highest
  // available referenced root, not just the chains descending from users.
  // Inferred application links are rendered but never promoted to declared roots.
  const hierarchyChildren=new Map(included.map(t=>[t.name,new Set()]));
  const hierarchyParents=new Map(included.map(t=>[t.name,new Set()]));
  for(const edge of edges){
    if(edge.inferred || edge.from_table===edge.to_table)continue;
    hierarchyChildren.get(edge.to_table).add(edge.from_table);
    hierarchyParents.get(edge.from_table).add(edge.to_table);
  }
  const alphabet=(a,b)=>a.localeCompare(b);
  const rootsAndLevels=(names,preferredRoots=[])=>{
    const members=new Set(names);
    const incoming=new Map(names.map(n=>[n,[...(hierarchyParents.get(n)||[])].filter(p=>members.has(p)).length]));
    const levels=new Map();
    const roots=names.filter(n=>incoming.get(n)===0).sort(alphabet);
    const queue=[...roots];
    for(const name of roots)levels.set(name,0);
    for(let i=0;i<queue.length;i++){
      const parent=queue[i];
      for(const child of [...(hierarchyChildren.get(parent)||[])].filter(c=>members.has(c)).sort(alphabet)){
        levels.set(child,Math.max(levels.get(child)||0,(levels.get(parent)||0)+1));
        const next=incoming.get(child)-1;incoming.set(child,next);
        if(next===0)queue.push(child);
      }
    }
    // Cyclic FK groups have no acyclic starting point. Pick a stable anchor,
    // keep all tables visible, and don't invent an external relationship.
    const cyclic=names.filter(n=>!levels.has(n)).sort(alphabet);
    if(cyclic.length){
      const seed=cyclic.find(n=>preferredRoots.includes(n))||cyclic[0];
      const pending=[seed];levels.set(seed,0);
      for(let i=0;i<pending.length;i++){
        const name=pending[i];
        for(const child of [...(hierarchyChildren.get(name)||[])].filter(c=>members.has(c)).sort(alphabet)){
          if(!levels.has(child)){levels.set(child,(levels.get(name)||0)+1);pending.push(child);}
        }
      }
      for(const name of cyclic)if(!levels.has(name)) levels.set(name,0);
    }
    return {roots:roots.length?roots:cyclic.slice(0,1),levels};
  };
  const clusters=[];
  if(focus && byName.has(focus)){
    const levels=new Map([[focus,1]]);
    for(const p of parents.get(focus)||[])levels.set(p,0);
    for(const c of children.get(focus)||[])if(!levels.has(c))levels.set(c,2);
    for(const t of included)if(!levels.has(t.name))levels.set(t.name,3);
    clusters.push({label:`DIRECT RELATIONSHIPS · ${focus}`,names:included.map(t=>t.name),levels});
  }else{
    const reached=new Set();
    if(byName.has("users")){
      const walk=["users"];reached.add("users");
      for(let i=0;i<walk.length;i++){
        for(const child of [...hierarchyChildren.get(walk[i])].sort(alphabet)){
          if(!reached.has(child)){reached.add(child);walk.push(child);}
        }
      }
      clusters.push({label:"USERS · DECLARED FOREIGN-KEY HIERARCHY",names:[...reached],levels:rootsAndLevels([...reached],["users"]).levels});
    }
    const remaining=new Set([...byName.keys()].filter(n=>!reached.has(n)));
    const standalone=[];
    const disconnected=[];
    while(remaining.size){
      const seed=[...remaining].sort(alphabet)[0];remaining.delete(seed);
      const component=[seed];
      for(let i=0;i<component.length;i++){
        const name=component[i];
        for(const other of [...hierarchyParents.get(name),...hierarchyChildren.get(name)].sort(alphabet)){
          if(remaining.has(other)){remaining.delete(other);component.push(other);}
        }
      }
      if(component.length===1 && !hierarchyParents.get(seed).size && !hierarchyChildren.get(seed).size){
        standalone.push(seed);continue;
      }
      const {roots,levels}=rootsAndLevels(component);
      disconnected.push({roots,names:component,levels});
    }
    disconnected.sort((a,b)=>a.roots[0].localeCompare(b.roots[0]));
    for(const group of disconnected){
      const rootLabel=group.roots.join(" + ");
      clusters.push({label:`INDEPENDENT FK ROUTE · ${rootLabel}`,names:group.names,levels:group.levels});
    }
    if(standalone.length){
      const levels=new Map(standalone.map(n=>[n,0]));
      clusters.push({label:"STANDALONE TABLES · NO DECLARED FK ROUTE",names:standalone.sort(alphabet),levels});
    }
  }
  const W=compact?218:256, GAP=compact?55:75, MARGIN=20;
  const available=Math.max(300,Number(containerWidth)||1400);
  const COLUMN_COUNT=Math.max(1,Math.min(4,Math.floor((available-2*MARGIN+GAP)/(W+GAP))));
  const width=2*MARGIN+W*COLUMN_COUNT+GAP*(COLUMN_COUNT-1);
  const nodes=[];let y=38,breakAt=null;
  const sectionHeadings=[];
  const pos=new Map();
  for(const [index,cluster] of clusters.entries()){
    if(!cluster.names.length)continue;
    if(index>0 && !focus && breakAt===null)breakAt=y;
    sectionHeadings.push({label:cluster.label,y:y+13,kind:index===0 && cluster.names.includes("users")?"users":"independent"});
    y+=48;
    const groups=new Map();
    for(const name of cluster.names){
      const level=cluster.levels.get(name)||0;
      if(!groups.has(level))groups.set(level,[]);
      groups.get(level).push(byName.get(name));
    }
    for(const level of [...groups.keys()].sort((a,b)=>a-b)){
      const entries=groups.get(level);
      entries.sort((a,b)=>{
        if(a.name==="users")return -1;if(b.name==="users")return 1;
        const parentX=name=>[...hierarchyParents.get(name)].map(p=>pos.get(p)?.x).filter(x=>x!==undefined);
        const pa=parentX(a.name),pb=parentX(b.name);
        const av=pa.length?pa.reduce((s,x)=>s+x,0)/pa.length:null;
        const bv=pb.length?pb.reduce((s,x)=>s+x,0)/pb.length:null;
        if(av!==null && bv!==null && av!==bv)return av-bv;
        if(av!==null && bv===null)return -1;if(av===null && bv!==null)return 1;
        return sectionOf(a.name).localeCompare(sectionOf(b.name))||alphabet(a.name,b.name);
      });
      for(let start=0;start<entries.length;start+=COLUMN_COUNT){
        const chunk=entries.slice(start,start+COLUMN_COUNT);
        const heights=chunk.map(t=>compact?77:70+fieldList(t,allFields).length*23+((t.columns||[]).length>fieldList(t,allFields).length?24:0));
        const maxH=Math.max(...heights);
        const rowWidth=chunk.length*W+(chunk.length-1)*GAP;
        const left=(width-rowWidth)/2;
        chunk.forEach((t,i)=>{
          const n={name:t.name,table:t,level,x:left+i*(W+GAP),y,w:W,h:heights[i],section:sectionOf(t.name),cluster:cluster.label};
          nodes.push(n);pos.set(t.name,n);
        });
        y+=maxH+88;
      }
    }
    y+=32;
  }
  const height=Math.max(330,y+38);
  const resultEdges=edges.map((e,i)=>{
    const source=pos.get(e.to_table),target=pos.get(e.from_table);
    if(!source||!target)return null;
    let path;
    if(source.name===target.name){
      const x=source.x+source.w,y=source.y+32;
      path=`M ${x} ${y} C ${x+55} ${y-48}, ${x+55} ${y+92}, ${x} ${y+64}`;
    }else if(source.y<target.y){
      const sx=source.x+source.w/2+((i%5)-2)*6,sy=source.y+source.h;
      const tx=target.x+target.w/2+((i%5)-2)*6,ty=target.y;
      const half=sy+Math.max(24,(ty-sy)/2);
      path=`M ${sx} ${sy} C ${sx} ${half}, ${tx} ${half}, ${tx} ${ty}`;
    }else{
      const sx=source.x+source.w,sy=source.y+source.h/2,tx=target.x,ty=target.y+target.h/2;
      const mid=Math.max(sx,tx)+33+(i%4)*8;
      path=`M ${sx} ${sy} C ${mid} ${sy}, ${mid} ${ty}, ${tx} ${ty}`;
    }
    return {...e,path,from:e.to_table,to:e.from_table};
  }).filter(Boolean);
  return {width,height,nodes,edges:resultEdges,breakAt,sections:sectionHeadings};
}
export function buildDomainGraph(tables,relationships){
  const valid=validEdges(tables,relationships);
  const names=new Map(SECTIONS.map(([id,label])=>[id,{id,label,tables:[],out:0,in:0}]));
  tables.forEach(t=>names.get(sectionOf(t.name)).tables.push(t.name));
  const joins=new Map();
  valid.forEach(e=>{
    const a=sectionOf(e.to_table),b=sectionOf(e.from_table);
    if(a===b)return;
    const key=a+"→"+b;joins.set(key,(joins.get(key)||0)+1);
  });
  return {groups:[...names.values()].filter(g=>g.tables.length), links:[...joins].map(([key,count])=>{const [from,to]=key.split("→");return {from,to,count};})};
}
