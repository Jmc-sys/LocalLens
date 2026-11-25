"""Conservative *possible* relationships derived from current MySQL metadata.

No application rows read. Candidates are NOT declared MySQL foreign keys.
Do not use these as authorization or assume every candidate should be enforced.
"""
import re

ALIASES = {
    'user': 'users', 'owner': 'users', 'created_by': 'users',
    'updated_by': 'users', 'uploaded_by': 'users', 'invited_by': 'users',
    'photo': 'photos', 'parent_photo': 'photos', 'source_photo': 'photos',
    'album': 'albums', 'face': 'ai_faces', 'person': 'ai_people',
    'suggested_person': 'ai_people', 'shared_album': 'shared_albums',
    'pet_label': 'ai_pet_labels', 'scan_job': 'ai_scan_jobs',
}


def candidate_relationships(tables, declared):
    by_table = {t['name']: t for t in tables}
    mapped = {
        (e['from_table'], column)
        for e in declared for column in e.get('from_columns', ())
    }
    output = []
    for table in tables:
        for col in table.get('columns', ()):
            name = col['name']
            if not name.endswith('_id') or (table['name'], name) in mapped:
                continue
            prefix = name[:-3]
            target = ALIASES.get(prefix)
            if target not in by_table or target == table['name']:
                continue
            keys = [c for c in by_table[target].get('columns', ()) if c['name'] == 'id']
            if not keys or not keys[0].get('primary'):
                continue
            compatible = col.get('type', '').lower() == keys[0].get('type', '').lower()
            output.append({
                'id': f'inferred:{table["name"]}.{name}->{target}.id',
                'from_table': table['name'], 'from_columns': [name],
                'to_table': target, 'to_columns': ['id'],
                'constraint': None, 'inferred': True,
                'type_compatible': compatible,
                'reason': 'Conventional identifier column; NOT a declared FK'
                    + ('' if compatible else ' (types differ; requires schema review)'),
            })
    return output
