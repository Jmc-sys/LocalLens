#!/usr/bin/env python3
"""Private, offline GPS-to-tag backfill (no model, network requests, or photo modification).

Reads original HEIC/JPEG EXIF GPS; resolves nearby city using on-disk
GeoNames data; writes location-derived tags separately from AI classifier
output. Periodically restores tags that classifier rescans may replace.
"""
from __future__ import annotations

import logging
import math
import os
import re
import signal
import time
import unicodedata
from pathlib import Path

import mysql.connector
from PIL import Image, ExifTags
from pillow_heif import register_heif_opener

register_heif_opener()
LOG = logging.getLogger('locallens-location')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
ROOT = Path(os.getenv('MEDIA_ROOT', '/storage')).resolve()
MAX_CITY_KM = float(os.getenv('LOCATION_CITY_RADIUS_KM', '30'))
BATCH = min(50, max(1, int(os.getenv('LOCATION_BATCH_LIMIT', '10'))))
SLEEP = max(1, float(os.getenv('LOCATION_PHOTO_PAUSE_SEC', '1.0')))
STOP = False


def handle_stop(*_):
    global STOP
    STOP = True


def _degree(value):
    vals = list(value)
    if len(vals) != 3:
        raise ValueError('Invalid EXIF coordinate')
    d, m, s = (float(v) for v in vals)
    if not (0 <= m < 60 and 0 <= s < 60 and d >= 0):
        raise ValueError('Invalid EXIF DMS coordinate')
    return d + m / 60 + s / 3600


def gps_from_exif(image):
    """Return (lat, lon) only when both signed axes are valid EXIF GPS values."""
    exif = image.getexif()
    if not exif:
        return None
    try:
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    except (KeyError, AttributeError, TypeError, ValueError):
        gps = exif.get(34853)
    if not gps or not hasattr(gps, 'get'):
        return None
    lat = gps.get(2)
    lon = gps.get(4)
    north = gps.get(1)
    east = gps.get(3)
    if not all((lat, lon, north, east)):
        return None
    north = north.decode('ascii','ignore') if isinstance(north, bytes) else str(north)
    east = east.decode('ascii','ignore') if isinstance(east, bytes) else str(east)
    if north.upper() not in ('N','S') or east.upper() not in ('E','W'):
        return None
    latitude = _degree(lat) * (-1 if north.upper() == 'S' else 1)
    longitude = _degree(lon) * (-1 if east.upper() == 'W' else 1)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    # (0,0) often indicates missing/erroneous GPS metadata.
    if latitude == 0 and longitude == 0:
        return None
    return (latitude, longitude)


def get_photo_gps(path):
    with Image.open(path) as img:
        return gps_from_exif(img)


def distance_km(lat1, lon1, lat2, lon2):
    r = math.pi / 180
    a = math.sin((lat2-lat1)*r/2)**2 + math.cos(lat1*r)*math.cos(lat2*r)*math.sin((lon2-lon1)*r/2)**2
    return 12742.0 * math.asin(min(1.0, math.sqrt(a)))


class LocalPlaces:
    """GeoNamesCache is a local on-disk database: no HTTP geocoding."""
    def __init__(self):
        import geonamescache
        self.db = geonamescache.GeonamesCache(min_city_population=5000)
        self.countries = self.db.get_countries()
        self.us_states = self.db.get_us_states()
        self.cities = list(self.db.get_cities().values())
        # Approximate latitude-index buckets reduce lookups for each photo.
        self.buckets = {}
        for city in self.cities:
            try:
                lat = float(city['latitude'])
                lon = float(city['longitude'])
            except (KeyError, TypeError, ValueError):
                continue
            self.buckets.setdefault(math.floor(lat), []).append((lat,lon,city))
        LOG.info('Offline GeoNames data loaded: %d cities',len(self.cities))

    def nearest(self, lat, lon):
        best = None
        best_distance = MAX_CITY_KM + 1
        # 30km is less than one degree latitude; look in adjoining buckets.
        for degree in range(math.floor(lat)-1, math.floor(lat)+2):
            for cy, cx, city in self.buckets.get(degree, []):
                if abs(cx-lon) > 2 and abs(lat)<80:
                    continue
                d = distance_km(lat,lon,cy,cx)
                if d < best_distance:
                    best_distance, best = d, city
        if best is None or best_distance > MAX_CITY_KM:
            return None
        code = best.get('countrycode') or ''
        country = (self.countries.get(code) or {}).get('name')
        region = None
        if code == 'US':
            region = (self.us_states.get(best.get('admin1code','')) or {}).get('name')
        # Do not mislabel non-US region codes as human-readable state names.
        return {'city':best.get('name'), 'region':region, 'country':country}


def normalize(value):
    # Match LocalLens's existing ai_tag_feedback.normalize_tag constraints.
    value = unicodedata.normalize('NFKD', str(value or '')).encode('ascii','ignore').decode().strip().lower()
    value = re.sub(r'\s+', '-', value)
    value = re.sub('[^a-z0-9_-]', '', value)
    return value[:80] if re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}',value) else None


def tags_for(place):
    if not place:
        return []
    return list(dict.fromkeys(t for t in (normalize(place.get(k)) for k in ('city','region','country')) if t))


def _path(uid, recorded):
    path = Path(recorded).resolve()
    root = (ROOT / 'users' / str(uid) / 'originals').resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileNotFoundError('Original missing or outside owner storage')
    return path


def connect():
    return mysql.connector.connect(host=os.getenv('DB_HOST','db'), port=int(os.getenv('DB_PORT','3306')),
        user=os.getenv('DB_USER','locallens'), password=os.environ['DB_PASSWORD'],
        database=os.getenv('DB_NAME','locallens'), connection_timeout=10, autocommit=False)


def idle(conn):
    """Allow active uploads/high load priority over metadata extraction."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('''SELECT COUNT(*) AS busy FROM ai_upload_leases
            WHERE heartbeat_at > DATE_SUB(NOW(6), INTERVAL 45 SECOND)''')
        return cur.fetchone()['busy'] > 0
    finally:
        cur.close()


def candidates(conn, limit=BATCH):
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('''SELECT p.id,p.user_id,p.storage_path
            FROM photos p LEFT JOIN ai_photo_locations loc ON loc.photo_id=p.id
            WHERE p.deleted_at IS NULL AND COALESCE(p.media_type,'photo') <> 'video'
              AND loc.photo_id IS NULL
            ORDER BY p.id ASC LIMIT %s''',(limit,))
        return cur.fetchall()
    finally:
        cur.close()


def scan_one(conn, row, places):
    uid, pid = int(row['user_id']), int(row['id'])
    try:
        gps = get_photo_gps(_path(uid,row['storage_path']))
        place = places.nearest(*gps) if gps else None
        status = 'tagged' if place else ('no_gps' if gps is None else 'no_nearby_city')
        tags = tags_for(place)
    except (FileNotFoundError, OSError, ValueError) as exc:
        LOG.warning('Location metadata skipped for photo %s: %s',pid,str(exc)[:100])
        status='unreadable'; place=None; tags=[]
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('''INSERT IGNORE INTO ai_photo_locations
            (photo_id,user_id,status,city,region,country) VALUES (%s,%s,%s,%s,%s,%s)''',
            (pid,uid,status,place.get('city') if place else None,
            place.get('region') if place else None,place.get('country') if place else None))
        for tag in tags:
            cur.execute('''INSERT IGNORE INTO ai_location_tags (photo_id,user_id,tag)
                           VALUES (%s,%s,%s)''',(pid,uid,tag))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return bool(tags)


def restore_tags(conn, batch=150):
    """Keep location tags discoverable after AI classifier deletes ai_tags on rescans.

    Manual tag rejections are respected. We only reinsert absent tags.
    """
    cur = conn.cursor()
    try:
        cur.execute('''INSERT IGNORE INTO ai_tags (photo_id,user_id,tag,score)
          SELECT t.photo_id,t.user_id,t.tag,1.0
          FROM ai_location_tags t
          JOIN photos p ON p.id=t.photo_id AND p.user_id=t.user_id AND p.deleted_at IS NULL
          LEFT JOIN ai_tags existing ON existing.photo_id=t.photo_id AND existing.tag=t.tag
          LEFT JOIN ai_tag_feedback f ON f.photo_id=t.photo_id AND f.user_id=t.user_id
                                   AND f.tag=t.tag AND f.action='reject'
          WHERE existing.photo_id IS NULL AND f.photo_id IS NULL LIMIT %s''', (batch,))
        count = cur.rowcount
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def run():
    places = LocalPlaces()
    conn = None
    last_restore = 0.0
    while not STOP:
        try:
            if conn is None or not conn.is_connected():
                conn = connect()
            if idle(conn):
                time.sleep(10)
                continue
            work = candidates(conn)
            for row in work:
                if STOP or idle(conn):
                    break
                scan_one(conn,row,places)
                time.sleep(SLEEP)
            if time.monotonic()-last_restore > 30:
                restored = restore_tags(conn)
                if restored:
                    LOG.info('Restored %d location search tags',restored)
                last_restore=time.monotonic()
            time.sleep(8 if work else 30)
        except Exception:
            LOG.exception('Location indexer error; retrying after cooldown')
            if conn is not None:
                try:conn.close()
                except Exception:pass
            conn = None
            time.sleep(30)
    if conn:
        conn.close()


if __name__=='__main__':
    signal.signal(signal.SIGTERM,handle_stop)
    signal.signal(signal.SIGINT,handle_stop)
    run()
