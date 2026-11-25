"""LocalLens owner-only, read-only universal search (photos, videos, names, tags).

All SQL parameters are bound, all queries scoped by p.user_id, and no model runs
while the user searches. No DB migration needed on a complete v0.6.2 instance.
"""
import re
from contextlib import contextmanager
from fastapi import APIRouter, Depends, HTTPException, Query


@contextmanager
def cursor_for(get_connection):
    connection = get_connection()
    cur = connection.cursor(dictionary=True)
    try:
        yield cur
    finally:
        cur.close()
        connection.close()


def like_word(word):
    # MySQL ESCAPE '!' is explicit and doesn't depend on SQL mode.
    return '%' + word.lower().replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'


def make_where(uid, search='', media='all', favorite=False, trash=False, album_id=None):
    terms = ['p.user_id=%s', 'p.deleted_at IS NOT NULL' if trash else 'p.deleted_at IS NULL']
    values = [uid]
    if media == 'photo':
        terms.append("COALESCE(p.media_type,'photo') <> 'video'")
    elif media == 'video':
        terms.append("COALESCE(p.media_type,'photo') = 'video'")
    if favorite:
        terms.append('p.is_favorite=1')
    if album_id is not None:
        # Never allow browsing an album that belongs to another account.
        terms.append('''EXISTS(SELECT 1 FROM album_photos ap
           JOIN albums a ON a.id=ap.album_id
           WHERE ap.photo_id=p.id AND ap.album_id=%s AND a.user_id=%s)''')
        values.extend([album_id, uid])
    for word in re.findall(r'\S+', search.strip())[:8]:
        like = like_word(word)
        terms.append('''(
            LOWER(p.original_filename) LIKE %s ESCAPE '!'
            OR LOWER(COALESCE(p.description,'')) LIKE %s ESCAPE '!'
            OR EXISTS (
                SELECT 1 FROM ai_tags t
                WHERE t.photo_id=p.id AND t.user_id=p.user_id
                  AND NOT EXISTS (SELECT 1 FROM ai_tag_feedback f
                      WHERE f.user_id=t.user_id AND f.photo_id=t.photo_id
                        AND f.tag=t.tag AND f.action='reject')
                  AND LOWER(REPLACE(t.tag,'-',' ')) LIKE %s ESCAPE '!'
            )
            OR EXISTS (
                SELECT 1 FROM ai_tag_feedback f
                WHERE f.user_id=p.user_id AND f.photo_id=p.id AND f.action='add'
                  AND LOWER(REPLACE(f.tag,'-',' ')) LIKE %s ESCAPE '!'
            )
            OR EXISTS (
                SELECT 1 FROM ai_faces face
                JOIN ai_people people ON people.user_id=face.user_id AND
                     people.id=COALESCE(face.person_id,face.suggested_person_id)
                LEFT JOIN ai_face_reviews review ON review.user_id=face.user_id
                     AND review.face_id=face.id
                WHERE face.user_id=p.user_id AND face.photo_id=p.id
                  AND (face.person_id IS NOT NULL OR review.face_id IS NULL)
                  AND LOWER(people.display_name) LIKE %s ESCAPE '!'
            )
            OR EXISTS (
                SELECT 1 FROM ai_pet_labels pet
                WHERE pet.user_id=p.user_id AND pet.photo_id=p.id
                  AND LOWER(pet.display_name) LIKE %s ESCAPE '!'
            )
        )''')
        values.extend([like] * 6)
    return ' AND '.join(terms), values


SORTS = {
    'newest': 'p.uploaded_at DESC,p.id DESC',
    'oldest': 'p.uploaded_at ASC,p.id ASC',
    'captured': 'COALESCE(p.captured_at,p.uploaded_at) DESC,p.id DESC',
    'name_asc': 'p.original_filename ASC,p.id DESC',
    'name_desc': 'p.original_filename DESC,p.id DESC',
    'largest': 'p.size_bytes DESC,p.id DESC',
    'smallest': 'p.size_bytes ASC,p.id DESC',
}


def build_unified_search_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/ai', tags=['Smart Library unified search'])

    @router.get('/unified-search')
    def search(search: str=Query('',max_length=255),
               media: str=Query('all',pattern='^(all|photo|video)$'),
               favorite: bool=False, trash: bool=False,
               album_id: int|None=Query(None,ge=1),
               sort: str='newest',limit: int=Query(100,ge=1,le=500),
               offset: int=Query(0,ge=0),user=Depends(get_current_user)):
        where,args=make_where(user['id'],search,media,favorite,trash,album_id)
        with cursor_for(get_connection) as cur:
            cur.execute(f'''SELECT p.id,p.original_filename,p.mime_type,p.media_type,
                 p.size_bytes,p.width,p.height,p.captured_at,p.uploaded_at,
                 p.is_favorite,p.description,p.deleted_at
                 FROM photos p WHERE {where}
                 ORDER BY {SORTS.get(sort,SORTS['newest'])}
                 LIMIT %s OFFSET %s''',(*args,limit,offset))
            return cur.fetchall()

    @router.get('/unified-search/count')
    def count(search: str=Query('',max_length=255),
              media: str=Query('all',pattern='^(all|photo|video)$'),
              favorite: bool=False, trash: bool=False,
              album_id: int|None=Query(None,ge=1),user=Depends(get_current_user)):
        where,args=make_where(user['id'],search,media,favorite,trash,album_id)
        with cursor_for(get_connection) as cur:
            cur.execute(f'SELECT COUNT(*) AS total FROM photos p WHERE {where}',tuple(args))
            return {'total':cur.fetchone()['total']}

    @router.get('/library-names')
    def names(user=Depends(get_current_user)):
        uid=user['id']
        with cursor_for(get_connection) as cur:
            cur.execute('''SELECT id, display_name FROM ai_people
                           WHERE user_id=%s ORDER BY display_name,id LIMIT 500''',(uid,))
            people=cur.fetchall()
            cur.execute('''SELECT DISTINCT display_name FROM ai_pet_labels
                           WHERE user_id=%s ORDER BY display_name LIMIT 500''',(uid,))
            pets=[row['display_name'] for row in cur.fetchall()]
        return {'people':people,'pets':pets}

    return router
