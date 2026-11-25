/** Pure schema-model helpers. MySQL is authoritative for foreign keys. */
export const SECTIONS = [
  { id: "accounts", title: "Accounts & access", description: "Users, sessions, and permissions" },
  { id: "media", title: "Photos & videos", description: "Media records, files, and previews" },
  { id: "albums", title: "Albums & sharing", description: "Collections and shared access" },
  { id: "identity", title: "People, pets & recognition", description: "Detected faces, learned identities, and tags" },
  { id: "processing", title: "Background processing", description: "Scan runs, queues, retries, and progress" },
  { id: "system", title: "Application settings", description: "Configuration and supporting records" },
  { id: "other", title: "Other tables", description: "Tables not matched to a named category" },
];

export function tableSection(name) {
  const n = String(name || "").toLowerCase();
  if (n === "users" || /(^user[_s]|^auth|^session|^login|^password|^permission|^role)/.test(n)) return "accounts";
  if (/(album|share|family|collection|group_member|invite)/.test(n)) return "albums";
  if (/(face|person|people|pet|animal|embedding|identity|recognition|ai_tag|tag_feedback|ai_labels?)/.test(n)) return "identity";
  if (/(scan|index|queue|job|retry|worker|task|scheduler|processing|upload_activ|browser_activ|ai_activity|ai_status)/.test(n)) return "processing";
  if (/(photo|video|media|motion|thumbnail|trash|favorite|asset|file_)/.test(n)) return "media";
  if (/(setting|configuration|system|audit|event|notification|log)/.test(n)) return "system";
  return "other";
}

export function orderedTables(tables) {
  return [...tables].sort((a, b) => (a.name === "users" ? -1 : 0) - (b.name === "users" ? -1 : 0) || a.name.localeCompare(b.name));
}

export function groupedTables(tables) {
  const groups = Object.fromEntries(SECTIONS.map(g => [g.id, []]));
  orderedTables(tables).forEach(t => { if (t.name !== "users") groups[tableSection(t.name)].push(t); });
  return SECTIONS.map(g => ({ ...g, tables: groups[g.id] }));
}

/** Relationship direction for display: referenced table -> dependent table. */
export function relationshipsOf(name, edges, tableNames) {
  const valid = new Set(tableNames);
  const filtered = edges.filter(e => valid.has(e.from_table) && valid.has(e.to_table));
  const parents = filtered.filter(e => e.from_table === name && e.to_table !== name);
  const children = filtered.filter(e => e.to_table === name && e.from_table !== name);
  const self = filtered.filter(e => e.from_table === name && e.to_table === name);
  const unique = (arr, prop) => [...new Set(arr.map(e => e[prop]))].sort();
  return { parents, children, self, parentNames: unique(parents, "to_table"), childNames: unique(children, "from_table") };
}

export function relationSummary(e) {
  const from = (e.from_columns || []).join(", ");
  const to = (e.to_columns || []).join(", ");
  return `${e.to_table}.${to} → ${e.from_table}.${from}`;
}

export function searchTables(tables, query) {
  const q = query.toLocaleLowerCase().trim();
  if (!q) return orderedTables(tables);
  return orderedTables(tables).filter(t => t.name.toLocaleLowerCase().includes(q) || (t.columns || []).some(c => c.name.toLocaleLowerCase().includes(q)));
}
