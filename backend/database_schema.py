"""Read-only, admin-scoped MySQL information_schema introspection for LocalLens.

Never queries application rows. A parent admin router must supply authentication.
"""
from collections import defaultdict
from schema_relationship_candidates import candidate_relationships
from datetime import datetime, timezone


def read_schema(get_connection):
    conn = get_connection()
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT DATABASE() AS schema_name')
        current = cursor.fetchone() or {}
        schema = current.get('schema_name')
        if not schema:
            raise RuntimeError('No MySQL database selected')

        cursor.execute('''
            SELECT TABLE_NAME, TABLE_TYPE, ENGINE
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME
        ''', (schema,))
        table_rows = cursor.fetchall()

        cursor.execute('''
            SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_TYPE,
                   IS_NULLABLE, COLUMN_DEFAULT, EXTRA, COLUMN_KEY
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        ''', (schema,))
        column_rows = cursor.fetchall()

        cursor.execute('''
            SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
        ''', (schema,))
        index_rows = cursor.fetchall()

        cursor.execute('''
            SELECT TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME,
                   ORDINAL_POSITION, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s
              AND REFERENCED_TABLE_NAME IS NOT NULL
            ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION
        ''', (schema,))
        fk_rows = cursor.fetchall()

        # Metadata-only: does not read application content, media paths, or faces.
        tables = {}
        for r in table_rows:
            name = r['TABLE_NAME']
            tables[name] = dict(name=name, kind=r['TABLE_TYPE'], engine=r.get('ENGINE'),
                                columns=[], indexes=[], foreign_keys=[])
        for r in column_rows:
            table = tables.get(r['TABLE_NAME'])
            if table is None:
                continue
            table['columns'].append(dict(name=r['COLUMN_NAME'], type=r['COLUMN_TYPE'],
                                         nullable=r['IS_NULLABLE']=='YES',
                                         default=r.get('COLUMN_DEFAULT'),
                                         auto_increment='auto_increment' in (r.get('EXTRA') or ''),
                                         primary=r.get('COLUMN_KEY')=='PRI'))

        indexes = defaultdict(list)
        for r in index_rows:
            indexes[(r['TABLE_NAME'], r['INDEX_NAME'])].append(r)
        for (table_name, index_name), members in indexes.items():
            if table_name not in tables:
                continue
            tables[table_name]['indexes'].append(dict(name=index_name,
                unique=members[0]['NON_UNIQUE']==0,
                columns=[x['COLUMN_NAME'] for x in members]))

        relationships = []
        foreign_keys = defaultdict(list)
        for r in fk_rows:
            foreign_keys[(r['TABLE_NAME'], r['CONSTRAINT_NAME'])].append(r)
        for (source, constraint), members in foreign_keys.items():
            target = members[0]['REFERENCED_TABLE_NAME']
            edge = dict(id=f'{source}.{constraint}', from_table=source,
                        from_columns=[x['COLUMN_NAME'] for x in members],
                        to_table=target,
                        to_columns=[x['REFERENCED_COLUMN_NAME'] for x in members],
                        constraint=constraint)
            relationships.append(edge)
            if source in tables:
                tables[source]['foreign_keys'].append(edge)

        result_tables = list(tables.values())
        return dict(schema=schema, generated_at=datetime.now(timezone.utc).isoformat(),
                    table_count=len(result_tables),
                    column_count=sum(len(t['columns']) for t in result_tables),
                    relationship_count=len(relationships),
                    tables=result_tables, relationships=relationships,
                    inferred_relationships=candidate_relationships(result_tables, relationships))
    finally:
        if cursor is not None:
            cursor.close()
        conn.close()
