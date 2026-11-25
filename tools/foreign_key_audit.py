#!/usr/bin/env python3
"""LocalLens database-wide reference and ownership audit, using live MySQL.

Reports potential missing FKs, orphan and cross-owner records. No changes to
MySQL, photos or other application files. SQL is generated but NEVER executed.
Run from ~/local-lens. The service uses its own MYSQL_PASSWORD environment.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from schema_relationship_candidates import candidate_relationships

IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z_0-9]*$')


def quote(value):
    if not IDENTIFIER.fullmatch(value):
        raise ValueError('Unsafe SQL identifier in live metadata')
    return '`' + value + '`'


def rows(sql, repo):
    # Credentials are expanded only within the DB container. SQL is passed as
    # one argv value and never interpolated into shell command text.
    cmd = ['docker', 'compose', 'exec', '-T', 'db', 'sh', '-c',
           'exec mysql -u locallens -p"$MYSQL_PASSWORD" '
           '--batch --raw --skip-column-names --default-character-set=utf8mb4 '
           'locallens -e "$1"', 'sh', sql]
    p = subprocess.run(cmd, cwd=repo, text=True, capture_output=True, timeout=180)
    if p.returncode:
        raise RuntimeError('MySQL audit query failed: ' + (p.stderr or '')[:450])
    return [line.split('\t') for line in p.stdout.splitlines() if line.strip()]


def single_count(sql, repo):
    result = rows(sql, repo)
    if len(result) != 1 or len(result[0]) != 1:
        raise RuntimeError('Unexpected count query response, refusing to generate SQL')
    return int(result[0][0])


def metadata(repo):
    table_rows=rows('''SELECT TABLE_NAME, TABLE_TYPE, ENGINE
      FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME''',repo)
    col_rows=rows('''SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,COLUMN_KEY,IS_NULLABLE
      FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
      ORDER BY TABLE_NAME,ORDINAL_POSITION''',repo)
    fk_rows=rows('''SELECT TABLE_NAME,COLUMN_NAME,REFERENCED_TABLE_NAME,
      REFERENCED_COLUMN_NAME,CONSTRAINT_NAME,ORDINAL_POSITION
      FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE()
      AND REFERENCED_TABLE_NAME IS NOT NULL
      ORDER BY TABLE_NAME,CONSTRAINT_NAME,ORDINAL_POSITION''',repo)
    tables = {r[0]: {'name':r[0], 'kind':r[1], 'engine':r[2], 'columns':[]} for r in table_rows}
    for t,name,typ,key,nullable in col_rows:
        if t in tables:
            tables[t]['columns'].append({'name':name,'type':typ,'primary':key=='PRI','nullable':nullable=='YES'})
    fks = {}
    for t,c,ref,refc,constraint,ordinal in fk_rows:
        key=(t,constraint)
        edge=fks.setdefault(key,{'from_table':t,'to_table':ref,'from_columns':[],'to_columns':[]})
        edge['from_columns'].append(c)
        edge['to_columns'].append(refc)
    return tables,list(fks.values())


def audit_ownership(repo, tables):
    # Enforce invariant reporting even when a declared FK already exists.
    results=[]
    for name,meta in sorted(tables.items()):
        if meta['kind']!='BASE TABLE' or meta['engine']!='InnoDB':
            continue
        fields={c['name'] for c in meta['columns']}
        targets=[]
        if name!='photos' and 'photos' in tables and {'photo_id','user_id'} <= fields:
            targets.append(('photo_id','photos'))
        if name!='ai_people' and 'ai_people' in tables and {'person_id','user_id'} <= fields:
            targets.append(('person_id','ai_people'))
        if name!='ai_people' and 'ai_people' in tables and {'suggested_person_id','user_id'} <= fields:
            targets.append(('suggested_person_id','ai_people'))
        for col,target in targets:
            if tables[target]['kind']!='BASE TABLE':
                continue
            mismatch=single_count(f'SELECT COUNT(*) FROM {quote(name)} c '
                f'JOIN {quote(target)} p ON p.id=c.{quote(col)} '
                'WHERE c.user_id IS NULL OR c.user_id<>p.user_id',repo)
            results.append({'table':name,'column':col,'target':target,'owner_mismatches':mismatch})
    return results


def audit(repo, tables, declared):
    cross_owner=audit_ownership(repo,tables)
    conflicts={}
    for item in cross_owner:
        conflicts[item['table']]=max(conflicts.get(item['table'],0),item['owner_mismatches'])
    candidates=candidate_relationships(list(tables.values()),declared)
    checked=[]
    for edge in candidates:
        child=edge['from_table']; col=edge['from_columns'][0]
        parent=edge['to_table']; parent_col=edge['to_columns'][0]
        child_meta=tables[child]; parent_meta=tables[parent]
        # Only scan actual MySQL base tables, not views.
        can_scan = child_meta['kind']=='BASE TABLE' and parent_meta['kind']=='BASE TABLE'
        can_scan = can_scan and child_meta['engine']=='InnoDB' and parent_meta['engine']=='InnoDB'
        orphan=None; owner_conflicts=None
        if can_scan:
            orphan=single_count(f'''SELECT COUNT(*) FROM {quote(child)} c
              LEFT JOIN {quote(parent)} p ON p.{quote(parent_col)}=c.{quote(col)}
              WHERE c.{quote(col)} IS NOT NULL AND p.{quote(parent_col)} IS NULL''',repo)
            child_names={c['name'] for c in child_meta['columns']}
            parent_names={c['name'] for c in parent_meta['columns']}
            if 'user_id' in child_names and 'user_id' in parent_names:
                # Covers ai_tags/photo ownership and face/person ownership.
                owner_conflicts=single_count(f'''SELECT COUNT(*) FROM {quote(child)} c
                  JOIN {quote(parent)} p ON p.{quote(parent_col)}=c.{quote(col)}
                  WHERE c.user_id <> p.user_id''',repo)
        ready=(can_scan and edge['type_compatible'] and orphan==0
               and (owner_conflicts is None or owner_conflicts==0)
               and conflicts.get(child,0)==0)
        checked.append({**edge,'orphan_rows':orphan,'owner_mismatch_rows':owner_conflicts,
                        'eligible_for_reviewed_ddl':bool(ready)})
    return checked,cross_owner


def sql_ddl(checked):
    lines=['-- LocalLens candidate constraints (REVIEW ONLY: NOT APPLIED).',
           '-- Warning: MySQL DDL auto-commits; ON DELETE RESTRICT may change delete flows.',
           '-- Requires verified backup, app delete-flow review, and repeated prechecks.',
           '-- Only uncomment selected statements after reviewing each migration.', '']
    for e in checked:
        if not e['eligible_for_reviewed_ddl']:
            continue
        child=e['from_table']; col=e['from_columns'][0];parent=e['to_table']
        key=f'fk_{child}_{col}'
        if len(key)>64:
            key='fk_'+child[:25]+'_'+col[:25]
        statement=(f'ALTER TABLE {quote(child)} ADD CONSTRAINT {quote(key)} '
                   f'FOREIGN KEY ({quote(col)}) REFERENCES {quote(parent)} (`id`) '
                   'ON DELETE RESTRICT ON UPDATE RESTRICT;')
        lines += [f'-- {child}.{col} -> {parent}.id; no orphans or ownership mismatches at audit time',
                  '-- '+statement, '']
    return '\n'.join(lines)+'\n'


def markdown(checked, tables, declared, cross_owner):
    lines=['# LocalLens — foreign-key and ownership audit','',
           'Generated: '+datetime.now(timezone.utc).isoformat(), '',
           '**Read-only. No constraints were added.** Candidate connections may be intentional logical references, not guaranteed foreign keys.',
           '',f'{len(tables)} live tables/views · {len(declared)} declared constraints · {len(checked)} candidate missing references','',
           '| Candidate relationship | Orphans | Ownership conflicts | SQL eligibility |','|---|---:|---:|---|']
    for e in checked:
        cols=e['from_columns'][0]
        lines.append(f'| `{e["from_table"]}.{cols}` → `{e["to_table"]}.id` '
                     f'| {e["orphan_rows"] if e["orphan_rows"] is not None else "not tested"} '
                     f'| {e["owner_mismatch_rows"] if e["owner_mismatch_rows"] is not None else "n/a"} '
                     f'| {"Reviewable" if e["eligible_for_reviewed_ddl"] else "Blocked / needs review"} |')
    lines += ['', '## Account-ownership checks (including declared relationships)', '',
              '| Table | References | Mismatched owners |', '|---|---|---:|']
    for item in cross_owner:
        lines.append(f'| `{item["table"]}` | `{item["column"]}` → `{item["target"]}.id` | {item["owner_mismatches"]} |')
    if not cross_owner:
        lines.append('| (none) | | |')
    lines += ['', '## Important checks','',
              '- Verify missing references are not deliberate polymorphic IDs or denormalized historical data.',
              '- Check `ai_tags` and other records with both `photo_id` and `user_id` for cross-owner mismatches.',
              '- Do not add `ON DELETE RESTRICT` without reviewing photo/album/user deletion and trash flows.',
              '- Review any rows marked blocked and correct them in a separately backed-up migration, never silently discard them.',
              '- `proposed_constraints.sql` is fully commented out and is never executed by this audit.', '']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,default=Path.home()/'local-lens')
    args=parser.parse_args()
    repo=args.repo.expanduser().resolve()
    tables,declared=metadata(repo)
    checked,cross_owner=audit(repo,tables,declared)
    out=repo/'backups'/('fk-audit-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True,exist_ok=False)
    (out/'foreign-key-report.md').write_text(markdown(checked,tables,declared,cross_owner))
    (out/'foreign-key-report.json').write_text(json.dumps({'candidates':checked,'ownership_checks':cross_owner},indent=2)+'\n')
    (out/'proposed_constraints.sql').write_text(sql_ddl(checked))
    print('Read-only database audit completed (no SQL writes).')
    print('Report:',out/'foreign-key-report.md')
    print('Candidate missing relationships:',len(checked))
    print('Eligible for reviewed SQL:',sum(bool(e['eligible_for_reviewed_ddl']) for e in checked))
    print('Any candidates with orphan rows:',sum((e['orphan_rows'] or 0)>0 for e in checked))
    print('Ownership links with mismatches:',sum(item['owner_mismatches']>0 for item in cross_owner))

if __name__=='__main__':
    main()
