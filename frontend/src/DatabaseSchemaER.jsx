import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { SECTIONS, sectionOf, validEdges, fieldList, cardinality, relationshipText, buildErLayout, buildDomainGraph } from "./er-layout-model";
import "./database-schema-er.css";

const MODES = [
  ["er", "Full ER diagram"],
  ["dependencies", "Dependency flow"],
  ["domains", "System modules"],
  ["focus", "Table relationships"],
];
// ll-er-composite-pk-v0611: one PRIMARY index can contain several columns.
const primaryKeyColumns = table => {
  const primaryIndex = (table?.indexes || []).find(index => String(index.name).toUpperCase() === "PRIMARY");
  return primaryIndex?.columns?.length ? primaryIndex.columns : (table?.columns || []).filter(column => column.primary).map(column => column.name);
};
const keyLabel = (name, primaryColumns, foreignColumns) => {
  const position = primaryColumns.indexOf(name);
  const isForeign = foreignColumns.has(name);
  if (position >= 0) return `PK${primaryColumns.length > 1 ? position + 1 : ""}${isForeign ? "/FK" : ""}`;
  return isForeign ? "FK" : "";
};
const nf = n => Number.isFinite(Number(n)) ? Number(n).toLocaleString() : "—";
const gib = n => `${(Number(n || 0) / 1073741824).toFixed(1)} GiB`;
const when = v => { if (!v) return "—"; const d = new Date(v); return isNaN(d.valueOf()) ? "—" : d.toLocaleString(); };
const short = (s, limit=27) => String(s).length>limit?String(s).slice(0,limit-1)+"…":String(s);

// ll-er-autoexpand-0610: the page, not the canvas, handles scrolling.
// ll-er-hierarchy-v0616: clear selected tables by clicking the diagram background.
function Graph({ layout, selected, setSelected, onClearSelection, query, zoom, setZoom, compact, allFields, byName, mode, availableWidth }) {
  const fitted=Math.min(1,Math.max(300,availableWidth-4)/layout.width);
  const scale=fitted*Math.max(.4,Math.min(1.7,zoom));
  const selectedMatches=new Set(layout.edges.filter(e=>e.from===selected||e.to===selected).flatMap(e=>[e.from,e.to]));
  if (selected) selectedMatches.add(selected);
  const highlight=(n)=>selectedMatches.has(n);
  const queryMatches=(name)=>!query||name.toLowerCase().includes(query.toLowerCase()) ||
    (byName.get(name)?.columns||[]).some(c=>c.name.toLowerCase().includes(query.toLowerCase()));
  const fit=()=>setZoom(1);
  return <div className="ll-er-graph-shell">
    <div className="ll-er-canvas-tools">
      <span>{mode==="er"?"All MySQL tables and declared foreign keys":mode==="focus"?"Direct parents and dependents":"Declared foreign-key dependency flow"}</span>
      <div className="ll-er-zoom-tools"><button type="button" onClick={()=>setZoom(z=>Math.max(.35,+(z-.15).toFixed(2)))} aria-label="Zoom out">−</button>
        <output>{Math.round(zoom*100)}%</output><button type="button" onClick={()=>setZoom(z=>Math.min(1.7,+(z+.15).toFixed(2)))} aria-label="Zoom in">+</button>
        <button type="button" onClick={fit}>Fit all</button></div>
    </div>
    <div className="ll-er-viewport" onClick={onClearSelection}>
      <svg className="ll-er-svg" width={Math.round(layout.width*scale)} height={Math.round(layout.height*scale)} viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label={`${layout.nodes.length} database tables and ${layout.edges.length} declared foreign keys. users first.`}>
        <defs><marker id="ll-er-many" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="8" markerHeight="8" orient="auto"><path d="M 1 1 L 11 6 L 1 11 M 1 6 L 11 6" fill="none" stroke="#8ec8df" strokeWidth="1.4" /></marker><marker id="ll-er-one" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="8" markerHeight="8" orient="auto"><path d="M 7 0 L 7 12 M 10 0 L 10 12" stroke="#8ec8df" strokeWidth="1.4" /></marker></defs>
        {(layout.sections||[]).map((section,i)=><g key={`${section.label}-${i}`}>
          <line x1="16" x2={layout.width-16} y1={section.y+6} y2={section.y+6} className="ll-er-section-divider"/>
          <text x="20" y={section.y-3} className="ll-er-section-heading">
            {short(section.label,Math.max(20,Math.floor(layout.width/10)))}
          </text>
        </g>)}
        {layout.edges.map((e,i)=>{
          const emphasized=!!selected&&(e.from===selected||e.to===selected);
          return <g key={e.id||i} className={e.inferred ? "ll-v615-inferred" : "ll-v615-declared"}>
          <path d={e.path} strokeDasharray={e.inferred ? "7 7" : undefined}
            className={`ll-er-link ${emphasized?"ll-er-link-active":""} ${selected&&!emphasized?"ll-er-link-muted":""}`}
            markerEnd={cardinality(e,byName)==="1 : 0..1"?"url(#ll-er-one)":"url(#ll-er-many)"}>
            <title>{relationshipText(e,byName)} · {e.inferred ? "POSSIBLE application reference, NOT enforced by MySQL" : `declared foreign key ${e.constraint||e.id}`}</title>
          </path>
          {(() => { const a=layout.nodes.find(n=>n.name===e.from), b=layout.nodes.find(n=>n.name===e.to);
            if(!a||!b) return null;
            const phrase=e.to_table==="users" ? "owns" : e.to_table==="albums" ? "contains" :
              e.to_table==="photos" ? "has" : e.to_table==="ai_people" ? "identifies" : "references";
            return <text className="ll-v615-edge-label" x={(a.x+a.w/2+b.x+b.w/2)/2}
              y={(a.y+a.h/2+b.y+b.h/2)/2-4} textAnchor="middle">{phrase}{e.inferred ? " ?" : ""}</text>;
          })()}
          </g>;
        })}
        {layout.nodes.map(n=>{
          const cols=compact?[]:fieldList(n.table,allFields);
          const fkNames=new Set((n.table.foreign_keys||[]).flatMap(e=>e.from_columns||[]));
          const pkNames=primaryKeyColumns(n.table);
          const muted=(selected&&!highlight(n.name)) || !queryMatches(n.name);
          return <g key={n.name} className={`ll-er-node ${selected===n.name?"is-current":""} ${muted?"is-muted":""}`} transform={`translate(${n.x}, ${n.y})`}
            onMouseDown={e=>e.stopPropagation()} onClick={e=>{e.stopPropagation();setSelected(n.name);}} role="button" tabIndex="0" aria-label={`Inspect ${n.name}`}
            onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();setSelected(n.name);}}}>
            <rect className="ll-er-node-body" width={n.w} height={n.h} rx="11" />
            <path className={`ll-er-node-stripe kind-${n.section}`} d={`M 11 0 H ${n.w-11} Q ${n.w} 0 ${n.w} 11 V 37 H 0 V 11 Q 0 0 11 0 Z`} />
            <text x="13" y="24" className="ll-er-node-name"><title>{n.name}</title>{short(n.name, compact?24:28)}</text>
            {compact ? <text x="13" y="57" className="ll-er-node-meta">{(n.table.columns||[]).length} columns · {(n.table.foreign_keys||[]).length} outgoing FKs</text> : <>
              <line x1="0" x2={n.w} y1="41" y2="41" className="ll-er-node-divider" />
              {cols.map((c,i)=><g key={c.name} transform={`translate(0,${53+i*23})`}>
                <text x="12" y="8" className={`ll-er-node-key ${pkNames.includes(c.name)?"is-pk":fkNames.has(c.name)?"is-fk":""}`}>{keyLabel(c.name,pkNames,fkNames)}</text>
                <text x="62" y="8" className="ll-er-node-col"><title>{c.name}: {c.type}</title>{short(c.name,16)}</text>
                <text x={n.w-11} y="8" textAnchor="end" className="ll-er-node-type">{short(c.type,12)}</text>
              </g>)}
              {(n.table.columns||[]).length>cols.length&&<text x="13" y={58+cols.length*23} className="ll-er-node-more">+{n.table.columns.length-cols.length} more columns · inspect table</text>}
            </>}
            <title>{n.name} · {n.table.columns?.length||0} columns · select for all fields and relationships</title>
          </g>;
        })}
      </svg>
    </div>
    <div className="ll-er-legend"><span><b className="ll-er-key-pk">PK / PK1 / PK2</b> Primary key / ordered composite members</span><span><b className="ll-er-key-fk">FK</b> Foreign key · PK1/FK means both</span><span>Crow’s foot: one-to-many · double bar: one-to-one</span><span>Links run referenced table → dependent table</span><span className="ll-v615-key">Dashed: inferred application reference — not a MySQL FK</span><span>Click a table to highlight actual relationships</span></div>
  </div>;
}

function DomainView({tables,relationships,onSelect}) {
  const model=useMemo(()=>buildDomainGraph(tables,relationships),[tables,relationships]);
  const groups=model.groups; const w=1060,h= Math.ceil(groups.length/3)*200+60;
  const locations=new Map(groups.map((g,i)=>[g.id,{x:35+(i%3)*350,y:32+Math.floor(i/3)*200,w:295,h:138}]));
  return <div className="ll-er-domain-shell"><p className="ll-er-help">Functional categories are navigation aids. Only the arrows and counts below represent declared MySQL foreign keys.</p>
    <div className="ll-er-domain-scroller"><svg viewBox={`0 0 ${w} ${h}`} className="ll-er-domain-svg" width="1060" height={h} role="img" aria-label="Database table groups with verified cross-group foreign keys">
      {model.links.map((l,i)=>{const a=locations.get(l.from),b=locations.get(l.to);if(!a||!b)return null;
        const sx=a.x+a.w/2,sy=a.y+a.h/2,tx=b.x+b.w/2,ty=b.y+b.h/2;
        return <g key={i}><path d={`M ${sx} ${sy} Q ${(sx+tx)/2+36} ${(sy+ty)/2} ${tx} ${ty}`} className="ll-er-domain-line"><title>{l.count} declared FKs: {l.from} → {l.to}</title></path></g>;
      })}
      {groups.map(g=>{const p=locations.get(g.id);return <g key={g.id} transform={`translate(${p.x},${p.y})`}>
        <rect width={p.w} height={p.h} rx="14" className="ll-er-domain-card"/>
        <text x="14" y="28" className="ll-er-domain-name">{g.label}</text><text x="14" y="51" className="ll-er-domain-count">{g.tables.length} tables</text>
        {g.tables.slice(0,4).map((t,i)=><text key={t} x="14" y={73+i*16} className="ll-er-domain-table" onClick={()=>onSelect(t)} role="button" tabIndex="0">{short(t,32)}</text>)}
        {g.tables.length>4&&<text x="200" y="124" className="ll-er-domain-more">+{g.tables.length-4} more</text>}
      </g>;})}
    </svg></div>
    <div className="ll-er-domain-relations"><strong>Verified cross-module relationships</strong>
      {model.links.length ? model.links.map(l=><span key={`${l.from}-${l.to}`}>{l.from} → {l.to} <b>{l.count} FK{l.count===1?"":"s"}</b></span>) : <p>No cross-module foreign keys are declared.</p>}
    </div></div>;
}

function Inspector({table,tables,edges,onSelect}){
  if(!table)return <aside className="ll-er-inspector">Select a table to inspect its keys and relationships.</aside>;
  const byName=new Map(tables.map(t=>[t.name,t]));
  const usedAsFK=new Set((table.foreign_keys||[]).flatMap(e=>e.from_columns||[]));
  const pkColumns=primaryKeyColumns(table);
  const relatives=edges.filter(e=>!e.inferred&&(e.from_table===table.name||e.to_table===table.name));
  const suggested=edges.filter(e=>e.inferred&&(e.from_table===table.name||e.to_table===table.name));
  return <aside className="ll-er-inspector" aria-label="Selected table details">
    <div className="ll-er-inspector-header"><span>TABLE INSPECTOR</span><h3>{table.name}</h3><small>{table.kind} · {table.columns.length} fields</small></div>
    {pkColumns.length>0 && <div className="ll-er-composite-summary">
      <strong>{pkColumns.length > 1 ? `One composite primary key (${pkColumns.length} columns)` : "Primary key"}</strong>
      <code>PRIMARY ({pkColumns.join(", ")})</code>
      {pkColumns.length>1&&<small>Each PK number identifies its position in this single constraint; PK/FK indicates a column is also a foreign key.</small>}
    </div>}
    <div className="ll-er-inspector-scroll"><table><thead><tr><th>Key</th><th>Column</th><th>MySQL type</th></tr></thead><tbody>
      {table.columns.map(col=><tr key={col.name}><td><b className={pkColumns.includes(col.name)?"is-pk":usedAsFK.has(col.name)?"is-fk":""}>{keyLabel(col.name,pkColumns,usedAsFK)}</b></td><td><code>{col.name}</code>{col.nullable&&<small> nullable</small>}</td><td><code>{col.type}</code></td></tr>)}
    </tbody></table></div>
    <h4>Declared relationships ({relatives.length})</h4>
    {relatives.length?relatives.map(e=><div className="ll-er-inspector-rel" key={e.id}><button type="button" onClick={()=>onSelect(e.from_table===table.name?e.to_table:e.from_table)}>{e.from_table===table.name?e.to_table:e.from_table}</button><small>{relationshipText(e,byName)}</small></div>):<p>No foreign keys declared for this table. Similar column names do not establish a database constraint.</p>}
    <h4>Possible application references ({suggested.length})</h4>
    {suggested.length? suggested.map(e=><div className="ll-er-inspector-rel" key={e.id}>
      <button type="button" onClick={()=>onSelect(e.from_table===table.name?e.to_table:e.from_table)}>
        {e.from_table===table.name?e.to_table:e.from_table}</button>
      <small>Not enforced in MySQL · {e.from_table}.{e.from_columns?.join(",")} → {e.to_table}.{e.to_columns?.join(",")}</small>
    </div>):<p>No conventional unlinked ID columns for this table.</p>}
    <h4>Indexes ({(table.indexes||[]).length})</h4>
    {(table.indexes||[]).map(i=><div className="ll-er-index" key={i.name}><code>{i.name}</code> · {i.unique?"unique":"non-unique"}<small>{i.columns?.join(", ")}</small></div>)}
  </aside>;
}

export default function DatabaseSchemaER(){
  const [schema,setSchema]=useState(null),[storage,setStorage]=useState(null),[error,setError]=useState("");
  const [mode,setMode]=useState("er"),[selected,setSelected]=useState(null),[zoom,setZoom]=useState(1);
  const mainRef=useRef(null);
  const [graphWidth,setGraphWidth]=useState(1080);
  useEffect(()=>{
    const main=mainRef.current;
    if(!main)return;
    const sync=()=>setGraphWidth(Math.max(300,Math.floor(main.clientWidth||1080)));
    sync();
    const observer=typeof ResizeObserver!=="undefined"?new ResizeObserver(sync):null;
    observer?.observe(main);
    window.addEventListener("resize",sync);
    return()=>{observer?.disconnect();window.removeEventListener("resize",sync);};
  },[]);
  const [query,setQuery]=useState(""),[allFields,setAllFields]=useState(false),[loading,setLoading]=useState(false);
  const [highlightOn,setHighlightOn]=useState(false);
  const [autoUpdate,setAutoUpdate]=useState(true);
  const refreshing=useRef(false);
  const refresh=useCallback(async()=>{
    if (document.hidden||refreshing.current)return;
    refreshing.current=true;setLoading(true);
    try{
      const result=await api("/admin/database/schema");
      if(!result||!Array.isArray(result.tables)||!Array.isArray(result.relationships)) throw new Error("Invalid MySQL schema response");
      setSchema(result);setError("");
      try{setStorage(await api("/admin/storage"));}catch{setStorage(null);}
    }catch(e){setError(e?.message||"Could not read MySQL schema");}finally{refreshing.current=false;setLoading(false);}
  },[]);
  useEffect(()=>{
    void refresh();
    const ticker=window.setInterval(()=>{if(autoUpdate&&!document.hidden)void refresh();},60000);
    const vis=()=>{if(autoUpdate&&!document.hidden)void refresh();};
    document.addEventListener("visibilitychange",vis);
    return()=>{clearInterval(ticker);document.removeEventListener("visibilitychange",vis);};
  },[autoUpdate,refresh]);
  const tables=schema?.tables||[];
  const declaredEdges=useMemo(()=>validEdges(tables,schema?.relationships),[tables,schema]);
  const inferredEdges=useMemo(()=>validEdges(tables,schema?.inferred_relationships),[tables,schema]);
  const edges=useMemo(()=>[...declaredEdges,...((mode==="er"||mode==="focus")?inferredEdges:[])],
    [declaredEdges,inferredEdges,mode]);
  const byName=useMemo(()=>new Map(tables.map(t=>[t.name,t])),[tables]);
  const current=byName.get(selected)||null;
  const layout=useMemo(()=>buildErLayout(tables,edges,{compact:mode==="dependencies",allFields:mode==="er"&&allFields,focus:mode==="focus"?(current?.name||byName.get("users")?.name||tables[0]?.name):null,containerWidth:graphWidth}),[tables,edges,mode,allFields,current,graphWidth]);
  const clearSelection=()=>{setSelected(null);setHighlightOn(false);
    if(mode==="focus")setMode("er");};
  const chooseTable=(name)=>{if(!name){clearSelection();return;}setSelected(name);setHighlightOn(true);};
  const nextMode=(direction)=>setMode(m=>{const index=MODES.findIndex(x=>x[0]===m);return MODES[(index+direction+MODES.length)%MODES.length][0];});
  return <section className="ll-er-root" aria-label="Live LocalLens database ER diagram">
    <header className="ll-er-header"><div><span>ADMIN / MYSQL / LIVE SCHEMA</span><h2>Database architecture</h2>
      <p>Complete ER diagram from actual MySQL tables and foreign keys. The full ER view is always the default.</p></div>
      <button type="button" onClick={()=>void refresh()} disabled={loading}>{loading?"Updating…":"↻ Refresh"}</button>
    </header>
    {error&&<p role="alert" className="ll-er-error">{error}</p>}
    {!schema&&!error&&<p className="ll-er-loading">Loading live database structure…</p>}
    {schema&&<>
      <div className="ll-er-metrics"><div><b>{nf(schema.table_count??tables.length)}</b><span>Tables</span></div><div><b>{nf(schema.column_count)}</b><span>Columns</span></div><div><b>{nf(schema.relationship_count??edges.length)}</b><span>Declared FKs · {inferredEdges.length} inferred</span></div><div><b>{schema.schema}</b><span>Updated {when(schema.generated_at)}</span></div></div>
      <div className="ll-er-tabs" aria-label="Database diagram selection"><button type="button" aria-label="Previous diagram" onClick={()=>nextMode(-1)}>‹</button>
        {MODES.map(([id,label])=><button type="button" key={id} className={mode===id?"is-active":""} aria-pressed={mode===id} onClick={()=>setMode(id)}>{label}</button>)}
        <button type="button" aria-label="Next diagram" onClick={()=>nextMode(1)}>›</button></div>
      <div className="ll-er-controls"><label>Find table or field<input type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="users, photos, face_id…"/></label>
        <label>Selected table<select value={current?.name||""} onChange={e=>chooseTable(e.target.value)}><option value="">All tables (none selected)</option>{[...tables].sort((a,b)=>(a.name==="users"?-1:b.name==="users"?1:a.name.localeCompare(b.name))).map(t=><option key={t.name}>{t.name}</option>)}</select></label>
        {mode==="er"&&<label className="ll-er-checkbox"><input type="checkbox" checked={allFields} onChange={e=>setAllFields(e.target.checked)}/>Show every column on cards</label>}
        <label className="ll-er-checkbox"><input type="checkbox" checked={autoUpdate} onChange={e=>setAutoUpdate(e.target.checked)}/>Live updates (60s)</label>
      </div>
      <div className="ll-er-layout">
        <div className="ll-er-main" ref={mainRef}>
          {mode==="domains"?<DomainView tables={tables} relationships={edges} onSelect={name=>{chooseTable(name);setMode("focus");}}/>:
            <Graph key={mode} layout={layout} selected={highlightOn?(current?.name||""):""} setSelected={chooseTable} onClearSelection={clearSelection} query={query} zoom={zoom} setZoom={setZoom}
              compact={mode==="dependencies"} allFields={allFields} byName={byName} mode={mode} availableWidth={graphWidth}/>}
          <p className="ll-er-note">Solid lines are declared MySQL foreign keys. Dashed lines are plausible application references based on ID column names; they are not enforced. Click a table to inspect keys and verify each relationship.</p>
        </div>
        <Inspector table={current} tables={tables} edges={edges} onSelect={chooseTable}/>
      </div>
      {storage&&Number.isFinite(Number(storage.disk_used_bytes))&&Number.isFinite(Number(storage.media_bytes))&&<div className="ll-er-storage"><strong>Storage accounting</strong><div><span>Server disk used <b>{gib(storage.disk_used_bytes)}</b></span><span>Media attributed to users <b>{gib(storage.media_bytes)}</b></span><span>Other / accounting difference <b>{gib(Number(storage.disk_used_bytes)-Number(storage.media_bytes))}</b></span></div><small>These totals include different storage scopes and may be on different mounts.</small></div>}
    </>}
  </section>;
}
