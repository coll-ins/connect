"""Build backend/companies/data/route_network.json: every route in both
directions, on real roads, with stages that sit on the line.

Run by hand when routes change (needs internet); the result is committed and
loaded by a migration, so the server never calls these services at deploy.

Sources: road lines from OSRM (router.project-osrm.org, OpenStreetMap roads);
stage names and positions from OpenStreetMap via Photon (photon.komoot.io).
A stage is used only when OSM has a feature of that exact name beside the
route's line; it is then pinned to the nearest point on the line.

    python tools/build_route_network.py [cache_dir]
"""
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'backend', 'companies', 'data', 'route_network.json')
CACHE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, '.route_cache')
os.makedirs(CACHE, exist_ok=True)

_sp = importlib.util.spec_from_file_location('geo', os.path.join(ROOT, 'backend', 'companies', 'geo.py'))
geomod = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(geomod)

# CBD stages. Super Metro: beside the Kenya National Archives; Kitengela side
# from Ronald Ngala Street (business.co.ke listing 2026, Ngong Road SACCO guide).
# terminus key -> (stage name, lat, lng)
T = {
 'SM':  ('Super Metro Stage, Archives', -1.28499, 36.82595),
 'SMR': ('Super Metro Stage, Ronald Ngala', -1.28608, 36.82723),
 'KEN': ('Kencom', -1.28564, 36.82499),
 'ODE': ('Odeon, Tom Mboya Street', -1.28330, 36.82505),
}
# (company, existing route name or None, far end, terminus, (far stage, lat, lng),
#  fare, vias, long distance). Far stages are OSM features (bus stations where
# OSM has one). Fares of new routes are provisional, like migration 0003.
# Kawangware is steered along Gitanga Road at Valley Arcade, the 46 road.
# A via ('Company', 'Far end', (lat, lng)) borrows the point nearest (lat, lng)
# on that already-built pair, so the line follows the same road.
S = 'Supermetro'; C = 'CityShuttle'; L = 'Latema'
R = [
 (S,'CBD to Rongai','Rongai','SM',('Rongai, Magadi Road Stage',-1.396906,36.753483),'80.00',[],0),
 (S,'CBD to Ngong','Ngong','SM',('Ngong Matatu Terminus',-1.3604193,36.6564516),'100.00',[],0),
 (S,'CBD to Kikuyu','Kikuyu','SM',('Kikuyu Bus Station',-1.2426167,36.6647886),'80.00',[],0),
 (S,'CBD to Juja','Juja','SM',('Juja Town',-1.101327,37.01575),'80.00',[],0),
 (S,'CBD to Makongeni','Makongeni','SM',('Makongeni, Thika',-1.0560609,37.1109349),'80.00',[],0),
 (S,'CBD to Thika Town','Thika Town','SM',('Thika Bus Station',-1.0382624,37.0802042),'100.00',[],0),
 (S,'CBD to Kitengela','Kitengela','SMR',('Kitengela Bus Stage',-1.4706469,36.9599339),'100.00',[],0),
 (S,'CBD to JKIA','JKIA','SMR',('JKIA Terminals',-1.3306259,36.9260516),'100.00',[],0),
 (S,'CBD to Mlolongo','Mlolongo','SMR',('Mlolongo',-1.396886,36.9423766),'80.00',[],0),
 (S,'CBD to Cabanas','Cabanas','SMR',('Cabanas Bus Stop',-1.3355893,36.893227),'80.00',[],0),
 (S,'CBD to Pipeline','Pipeline','SMR',('Pipeline, Stage Mpya',-1.3131215,36.8918178),'80.00',[],0),
 (S,'CBD to Taj Mall','Taj Mall','SMR',('Taj Mall',-1.3236703,36.8991616),'80.00',[('Supermetro','Pipeline',(-1.2992254,36.8886888))],0),
 (S,'CBD to Jogoo Road','Jogoo Road','SMR',('Buruburu',-1.2861866,36.8774336),'60.00',[],0),
 (S,'Nairobi to Kisumu','Kisumu','SM',('Kisumu Bus Park',-0.0975,34.7580),'1000.00',[],1),
 (S,'Nairobi to Kakamega','Kakamega','SM',('Kakamega Bus Park',0.2827,34.7519),'1200.00',[],1),
 (S,'CBD to Mfangano','Mfangano','SM',('Mfangano Street',-1.2866288,36.8279808),'60.00',[],0),
 (S,'CBD -  Kawangware','Kawangware','SM',('Kawangware 46 Stage',-1.2837632,36.7424656),'70.00',[(-1.2899397,36.7703418)],0),
 (S,None,'Kahawa West','SM',('Kahawa West Bus Station',-1.1855653,36.9071288),'80.00',[],0),
 (S,None,'Kabiria','SM',('Kabiria',-1.2912477,36.7256737),'80.00',[(-1.2990,36.7600)],0),
 (S,None,'Regen','SM',('Regen',-1.2472492,36.6813574),'80.00',[],0),
 (S,None,'Juja Farm','SM',('Juja Farm',-1.166232,37.0895719),'120.00',[],0),
 (S,None,'Malaa','SM',('Malaa',-1.2712917,37.1373512),'150.00',[],0),
 (S,None,'Roysambu','SM',('Roysambu',-1.2175606,36.8914926),'60.00',[],0),
 (S,None,'Westlands','SM',('Westlands Stage',-1.2614964,36.8036087),'50.00',[],0),
 (C,'CBD to Westlands','Westlands','KEN',('Sarit Centre',-1.262223,36.803281),'70.00',[],0),
 (C,'CBD to Karen','Karen','KEN',('Karen Shopping Centre',-1.3228991,36.7069392),'100.00',[],0),
 (C,'CBD to Upper Hill','Upper Hill','KEN',('Kenyatta National Hospital',-1.3009034,36.8085978),'70.00',[],0),
 (C,'CBD to Ngong Road','Ngong Road','KEN',('Ngong Road, Kimbo Stage',-1.302458,36.752073),'70.00',[],0),
 (L,'CBD to Eastleigh','Eastleigh','ODE',('Eastleigh Section 3',-1.2847147,36.8558693),'60.00',[],0),
 (L,'CBD to Umoja','Umoja','ODE',('Umoja Innercore',-1.2823008,36.8913652),'80.00',[('Supermetro','Pipeline',(-1.2952187,36.8718614))],0),
 (L,'CBD to Waiyaki Way','Waiyaki Way','KEN',('Mountain View',-1.2642966,36.7382719),'70.00',[],0),
 (L,'CBD to Kikuyu','Kikuyu','KEN',('Kikuyu Bus Station',-1.2426167,36.6647886),'80.00',[],0),
 (L,'CBD to Kinoo','Kinoo','KEN',('Kinoo',-1.2553597,36.6941523),'80.00',[],0),
 (L,'CBD to Uthiru','Uthiru','KEN',('Uthiru',-1.2607484,36.7174416),'70.00',[],0),
 (L,'CBD to Kawangware','Kawangware','KEN',('Kawangware 46 Stage',-1.2837632,36.7424656),'70.00',[(-1.2899397,36.7703418)],0),
 (L,'CBD to Kabiria','Kabiria / Satellite','KEN',('Kabiria',-1.2912477,36.7256737),'80.00',[(-1.2990,36.7600)],0),
 (L,'CBD to Ngong Road','Ngong Road','KEN',('Ngong Road, Kimbo Stage',-1.302458,36.752073),'70.00',[],0),
 (L,'CBD to Adams Arcade','Adams Arcade','KEN',('Adams Arcade',-1.300038,36.780462),'70.00',[],0),
 (L,'CBD to Gachie','Gachie','KEN',('Gachie',-1.2219243,36.7797876),'100.00',[],0),
 (L,'CBD to Thika Road','Thika Road','ODE',('Ruiru Bus Park',-1.147426,36.9592604),'80.00',[],0),
 (L,'CBD to Juja','Juja','ODE',('Juja Town',-1.101327,37.01575),'80.00',[],0),
 (L,'CBD to Makongeni','Makongeni','ODE',('Makongeni',-1.2940,36.85087),'80.00',[],0),
 (L,'Kamau','Ruiru','ODE',('Ruiru Bus Park',-1.147426,36.9592604),'80.00',[],0),
 (L,'Nairobi to Nakuru','Nakuru','ODE',('Nakuru Bus Terminus',-0.2849301,36.0755816),'500.00',[],1),
]

# (stage name shown to riders, OSM search text, exact OSM feature names accepted)
M = [
 ('Kenyatta National Hospital','KNH',['KNH/KMTC']),('Kenyatta National Hospital','Kenyatta National Hospital',['Kenyatta National Hospital Bus Stop','Kenyatta National Hospital']),
 ('Prestige Plaza','Prestige Plaza',['Prestige Plaza']),('Adams Arcade','Adams',['Adams','Adams Arcade']),('Junction Mall','Junction Mall',['The Junction Mall']),
 ('Dagoretti Corner','Dagoretti Corner',['Dagoretti Corner']),('Santack','Santack',['Santack stage']),('Racecourse','Racecourse',['Racecourse Bus Stage']),
 ('Lenana','Lenana',['Lenana']),('Kabuagi','Kabuagi',['Kabuagi']),('Karen','Karen Bus Stop',['Karen Bus Stop']),('Bulbul','Bul Bul',['Bul Bul Bus Stop']),
 ('Zambia','Zambia',['Zambia']),('Juanco','Juanco',['Juanco Bus Stop']),
 ('Nyayo Stadium','Nyayo Stadium',['Nyayo National Stadium']),('Wilson Airport','Wilson Airport',['Wilson Airport']),('Galleria Mall','Galleria',['Galleria']),
 ('Bomas of Kenya','Bomas',['Bomas of Kenya','Bomas']),('Multimedia University','Multimedia University',['Multimedia University of Kenya']),
 ('Catholic University','Catholic University',['Catholic University of East Africa']),('The Hub Karen','The Hub',['The Hub Karen']),('Karen Hospital','Karen Hospital',['Karen Hospital']),
 ('Museum Hill','Museum Hill',['Nairobi National Museum']),('Chiromo','Chiromo',['Chiromo Bus Stage','Chiromo']),('Westlands','Westlands',['Westlands']),
 ('Safaricom House','Safaricom',['Safaricom/Saf']),('ABC Place','ABC',['ABC']),('Kangemi','Kangemi',['Kangemi']),('Mountain View','Mountain View',['Mountain View']),
 ('Uthiru','Uthiru',['Uthiru','Uthiru Bus Stop']),('Kinoo','Kinoo',['Kinoo Bus stop','Kinoo/Kikuyu']),('Muthiga','Muthiga',['Muthiga']),('Regen','Regen',['White House/Regen']),
 ('Gitaru','Gitaru',['Gitaru']),('Sarit Centre','Sarit',['Sarit Center']),
 ('Ngara','Ngara',['Ngara']),('Pangani','Pangani',['Pangani']),('Muthaiga','Muthaiga',['Muthaiga','Muthaiga Shopping Centre','Muthaiga Mini Market']),('Allsops','Allsops',['Allsops']),('Garden City','Garden City',['Garden City Mall']),
 ('Roysambu','Roysambu',['Roysambu']),('Githurai 45','Githurai',['Githurai']),('Kahawa Sukari','Kahawa Sukari',['Kahawa sukari']),('Kenyatta University','Kenyatta University',['Kenyatta University']),
 ('Kahawa Wendani','Wendani',['Kahawa Wendani']),('Ruiru','Ruiru',['Ruiru']),('Juja','Juja',['Juja']),('Thika Road Mall','Thika Road Mall',['Thika Road Mall TRM']),
 ('Zimmerman','Zimmerman',['Zimmerman Stage']),('Githurai 44','Githurai 44',['Githurai 44','Githurai 44 Stage']),
 ('South B','South B',['South B']),('Capital Centre','Capital Centre',['Capital Centre']),('Imara Daima','Imara Daima',['Imara Daima']),('Cabanas','Cabanas',['Cabanas Bus Stop']),
 ('Syokimau','Syokimau',['Syokimau']),('Mlolongo','Mlolongo',['Mlolongo']),('Athi River','Athi River',['Athi River']),
 ('Muthurwa','Muthurwa',['Muthurwa Bus Station']),('City Stadium','City Stadium',['City Stadium']),('Makongeni','Makongeni',['Makongeni','makongeni']),('Makadara','Makadara',['Makadara']),
 ('Hamza','Hamza',['Hamza']),('Buruburu','Buruburu',['Buruburu']),('Donholm','Donholm',['Donholm','Doonholm']),('Tena','Tena',['Tena']),('Umoja 1','Umoja',['Umoja I']),('Taj Mall','Taj Mall',['Taj Mall']),
 ('Tassia','Tassia',['Tassia Matatu Stage']),('California','California',['California']),('Mlango Kubwa','Mlango Kubwa',['Mlango Kubwa Stage']),
 ('Yaya Centre','Yaya',['Yaya Centre']),('Valley Arcade','Valley Arcade',['Valley Arcade','Valley Arcade Bus Stop']),('Lavington','Lavington',['Lavington Mall']),('Congo','Congo',['Congo','Congo Stage']),
 ('Kawangware','Kawangware',['Kawangware','Kawangware Sokoni']),('Riruta','Riruta',['Riruta','Riruta Stage']),('Wanyee','Wanye',['Wanye']),
 ('Daystar University','Daystar',['Daystar University, Nairobi Campus','Daystar University (Nairobi campus)','Daystar University']),('Coptic Hospital','Coptic',['Coptic Hospital']),
 ('Parklands','Parklands',['Parklands']),('Village Market','Village Market',['Village Market']),('Gigiri','Gigiri',['Kobil Gigiri','UN/Gigiri/KTTC','Gigiri']),
 ('Two Rivers','Two Rivers',['Two Rivers Bus station','Two Rivers Mall']),('Ruaka','Ruaka',['Ruaka']),
 ('Kayole Junction','Kayole',['Kayole 1']),('Njiru','Njiru',['Njiru']),('Ruai','Ruai',['Ruai']),('Kamulu','Kamulu',['Kamulu Stage','Kamulu']),('Joska','Joska',['Joska']),('Komarock','Komarock',['Komarock']),
 ('Uhuru Gardens','Uhuru Gardens',['Uhuru Gardens']),('Langata Barracks','Langata Barracks',['Langata Barracks']),('Langata Cemetery','Langata Cemetery',['Langata Cemetery']),
 ('Gateway Mall','Gateway Mall',['Gateway Mall']),('Signature Mall','Signature Mall',['Signature Mall']),('Sameer Business Park','Sameer Business Park',['Sameer Business Park']),
 ('Nextgen Mall','Nextgen Mall',['NextGen Shopping Mall']),('Africa Nazarene University','Africa Nazarene University',['Africa Nazarene University']),('Kware','Kware',['Kware']),
 ('Rongai Market','Ongata Rongai',['Ongata Rongai Open Air Market']),('Nairobi West','Nairobi West',['Nairobi West']),('Jericho','Jericho',['Jericho']),('Kariokor','Kariokor',['Kariokor','Kariokor Market']),
 ('Safari Park','Safari Park Hotel',['Safari Park Hotel']),('Kasarani Stadium','Kasarani Stadium',['Kasarani Stadium','Moi International Sports Centre']),('Mountain Mall','Mountain Mall',['Mountain Mall']),
 ('Juja City Mall','Juja City Mall',['Juja City Mall']),('JKUAT','JKUAT',['Jomo Kenyatta University of Agriculture and Technology','JKUAT Main stage']),('Witeithie','Witeithie',['Witethie']),
 ('Fedha','Fedha',['Fedha Matatu Stage']),('Mama Lucy Hospital','Mama Lucy',['Mama Lucy Kibaki Memorial Hospital']),('Kariobangi','Kariobangi',['Kariobangi']),('Chokaa','Chokaa',['Chokaa Stage']),
 ('Mihango','Mihango',['Mihango stage']),('Globe Roundabout','Globe Roundabout',['Globe Roundabout']),('City Park','City Park',['City Park','Total/City Park']),('Stima Plaza','Stima Plaza',['Stima Plaza','Stima Plaza Stage']),
 ('Panari','Panari',['Panari Sky Centre']),('Dandora','Dandora',['Dandora']),('Utawala','Utawala',['Utawala']),('Embakasi','Embakasi',['Embakasi']),
]
BIG = {'Wilson Airport','Bomas of Kenya','Multimedia University','Catholic University','Kenyatta University','Nyayo Stadium','JKUAT','Africa Nazarene University','Uhuru Gardens','Langata Barracks','Kasarani Stadium'}


def get(url, pause=0.35):
    key = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
    if os.path.exists(key):
        return json.load(open(key))
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'route-builder/1.0'})
            data = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
            json.dump(data, open(key, 'w'))
            time.sleep(pause)
            return data
        except Exception as exc:
            err = exc
            time.sleep(3 * (attempt + 1))
    raise err


def hav(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 12742000 * math.asin(math.sqrt(h))


def osrm(points):
    coords = ';'.join(f'{lng:.6f},{lat:.6f}' for lat, lng in points)
    data = get('https://router.project-osrm.org/route/v1/driving/' + coords
               + '?overview=full&geometries=geojson&steps=false&continue_straight=true', 1.0)
    assert data['code'] == 'Ok', data
    return [(y, x) for x, y in data['routes'][0]['geometry']['coordinates']]


def cum(line):
    out = [0.0]
    for a, b in zip(line, line[1:]):
        out.append(out[-1] + hav(a, b))
    return out


def project(line, p, cm=None):
    """Nearest point on a polyline: (offset_m, along_m, (lat, lng))."""
    cm = cm or cum(line)
    best = None
    k = math.cos(math.radians(p[0]))
    for i, (a, b) in enumerate(zip(line, line[1:])):
        ax, ay = (a[1] - p[1]) * k, a[0] - p[0]
        dx, dy = (b[1] - a[1]) * k, b[0] - a[0]
        length = dx * dx + dy * dy
        t = 0 if length == 0 else max(0, min(1, -(ax * dx + ay * dy) / length))
        q = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        d = hav(p, q)
        if best is None or d < best[0]:
            best = (d, cm[i] + hav(a, q), q)
    return best


def health(line):
    return geomod.line_health({'type': 'LineString', 'coordinates': [[x, y] for y, x in line]}, [])


def spurs(line):
    return health(line)['spurs']


def trim(line):
    """Cut the stub a router adds when a terminus sits across a divided road:
    it drives past, turns round and comes back. The bus simply starts (or
    stops) on its own side, so the line should too."""
    for end in (0, 1):
        if end:
            line = line[::-1]
        cm = cum(line)
        limit = min(1500, 0.2 * cm[-1])
        turn = None
        for p in health(line)['spur_points']:
            along = project(line, (p[0], p[1]), cm)[1]
            if along < limit and (turn is None or along > turn):
                turn = along
        if turn is not None:
            # Where the line comes back past its own start, after the turn.
            i = next(k for k, c in enumerate(cm) if c > turn)
            j = next((k for k, c in enumerate(cm) if c > 2 * turn + 300), len(line) - 1)
            if j > i:
                off, along, q = project(line[i:j + 1], line[0])
                if off < 150:
                    rest = [p for p, c in zip(line[i:], cm[i:]) if c - cm[i] > along]
                    line = [q] + rest
        if end:
            line = line[::-1]
    return line


def share(ref, line):
    """Fraction of `line` that runs within 150 m of `ref`."""
    cr, cm = cum(ref), cum(line)
    n = ok = 0
    nxt = 0
    for i, p in enumerate(line):
        if cm[i] < nxt:
            continue
        nxt = cm[i] + 250
        n += 1
        ok += project(ref, p, cr)[0] <= 150
    return ok / max(n, 1)


def at(line, frac):
    cm = cum(line)
    target = cm[-1] * frac
    return next(p for p, c in zip(line, cm) if c >= target)


def simplify(line, tol=4):
    """Douglas-Peucker, tolerance in metres: same shape, far fewer points."""
    keep = [0, len(line) - 1]
    stack = [(0, len(line) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        seg = [line[i], line[j]]
        best, bk = 0, None
        for k in range(i + 1, j):
            d = project(seg, line[k], [0, 1])[0]
            if d > best:
                best, bk = d, k
        if best > tol:
            keep.append(bk)
            stack += [(i, bk), (bk, j)]
    return [line[k] for k in sorted(keep)]


TRANSIT = ('bus_stop', 'bus_station')
PLACE = ('suburb', 'quarter', 'neighbourhood', 'village', 'town', 'hamlet', 'locality')
BBOX = '36.55,-1.55,37.20,-0.95'
GENERIC = re.compile(
    r'^(bus ?(stop|station|stage)|stage|stop|terminus|matatu)$|towards|school$|^route|high ?point'
    r'|^n [(]|trufi|minibus|naivasha|nakuru|^no[.]? ?[0-9]|seniou', re.I)


def candidates():
    found = {}
    for shown, query, names in M:
        data = get('https://photon.komoot.io/api/?' + urllib.parse.urlencode(
            {'q': query, 'lat': -1.286, 'lon': 36.82, 'limit': 40, 'bbox': BBOX}))
        for f in data.get('features', []):
            props = f['properties']
            if props.get('name') in names:
                lng, lat = f['geometry']['coordinates']
                found.setdefault(shown, []).append((lat, lng, props.get('osm_value')))
    return found


def stops_along(line, step=450, maxoff=60):
    """Named OSM bus stops within `maxoff` m of the line: (along, name, point)."""
    cm = cum(line)
    out = {}
    nxt = 0
    for i, p in enumerate(line):
        if cm[i] < nxt:
            continue
        nxt = cm[i] + step
        data = get(f'https://photon.komoot.io/reverse?lat={p[0]:.5f}&lon={p[1]:.5f}'
                   '&radius=0.3&limit=30&osm_tag=highway:bus_stop')
        for f in data.get('features', []):
            name, oid = f['properties'].get('name'), f['properties'].get('osm_id')
            if not name or oid in out:
                continue
            lng, lat = f['geometry']['coordinates']
            off, along, q = project(line, (lat, lng), cm)
            if off <= maxoff:
                out[oid] = (along, name, q)
    return sorted(out.values())


def clean(name):
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'[\s/-]*(bus[ -]?stop|bus stage|stage|bus station)$', '', name, flags=re.I).strip(' -/') or name
    if name.isupper() and len(name) > 4:
        name = name.title()
    return name[:1].upper() + name[1:]


def pick(line, first, last, cand, prefer=()):
    """Well-known stages OSM puts on this line, then local stops in the gaps."""
    cm = cum(line)
    total = cm[-1]
    ends = {w for w in re.split(r'\W+', (first + ' ' + last).lower()) if len(w) > 3}
    got = []
    for shown, places in cand.items():
        if set(re.split(r'\W+', shown.lower())) & ends:
            continue
        best = None
        for lat, lng, kind in places:
            off, along, q = project(line, (lat, lng), cm)
            limit = 60 if kind in TRANSIT else 700 if shown in BIG else 400 if kind in PLACE else 300
            if shown in prefer:
                limit += 150
            if kind not in TRANSIT and not 1200 < along < total - 1200:
                continue
            if off <= limit and 400 < along < total - 500 and (best is None or off < best[0]):
                best = (off, along, q)
        if best:
            got.append((best[1], shown, best[2]))
    got.sort(key=lambda s: (s[1] not in prefer, s[0]))
    kept = []
    for s in got:
        if all(abs(s[0] - k[0]) >= 450 for k in kept):
            kept.append(s)
    names = {s[1].lower() for s in kept}
    for along, raw, q in stops_along(line):
        name = clean(raw)
        if len(kept) >= 16:
            break
        if (GENERIC.search(raw.strip()) or len(name) < 4 or name.lower() in names
                or not 1500 < along < total - 1200
                or set(re.split(r'\W+', name.lower())) & ends):
            continue
        if all(abs(along - k[0]) >= 1300 for k in kept):
            kept.append((along, name, q))
            names.add(name.lower())
    return sorted(kept)


def main():
    cand = candidates()
    built = {}
    out = []
    for comp, existing, far, tk, (ename, elat, elng), price, vias, longd in R:
        tname, tlat, tlng = T[tk]
        a, b = (tlat, tlng), (elat, elng)
        v_out, v_back = [], []
        for via in vias:
            if isinstance(via[0], str):
                ref_out, ref_back = built[(via[0], via[1])]
                v_out.append(project(ref_out, via[2])[2])
                v_back.append(project(ref_back, via[2])[2])
            else:
                v_out.append(via)
                v_back.append(via)
        # Everything below works on the slimmed line that gets stored, so the
        # checks see exactly what the map will draw.
        go = simplify(osrm([a, *v_out, b]))
        ret = simplify(osrm([b, *reversed(v_back), a]))
        note = ''
        shared = share(go, ret)
        if not longd and shared < 0.6 and cum(go)[-1] > 8000:
            # The router took a different road each way. Put both on one road:
            # first try the outbound road, else the return road.
            # A steering point can land on the far side of a divided road
            # and force a loop, so try a few and keep only a clean line.
            def along(ref, start, end):
                for fracs in ((0.5,), (0.35, 0.65), (0.25, 0.5, 0.75), (0.4,), (0.6,)):
                    alt = simplify(osrm([start, *[at(ref, 1 - f) for f in fracs], end]))
                    if share(ref, alt) >= 0.8 and cum(alt)[-1] <= 1.3 * cum(ref)[-1] and not spurs(trim(alt)):
                        return alt
            alt = along(go, b, a)
            if alt:
                ret, note = alt, f' | return moved onto outbound road (was {shared:.0%} shared)'
            else:
                alt = along(ret, a, b)
                if alt:
                    go, note = alt, f' | outbound moved onto return road (was {shared:.0%} shared)'
                else:
                    note = f' | DIFFERENT ROADS EACH WAY ({shared:.0%} shared)'
        go, ret = trim(go), trim(ret)
        built[(comp, far)] = (go, ret)
        home, short = ('Nairobi', 'Nairobi') if longd else ('Nairobi CBD', 'CBD')
        mids_go = [] if longd else pick(go, tname, ename, cand)
        mids_ret = [] if longd else pick(ret, ename, tname, cand, prefer={m[1] for m in mids_go})
        for back, line, mids in ((0, go, mids_go), (1, ret, mids_ret)):
            first, last = (ename, tname) if back else (tname, ename)
            stages = [(first, line[0])] + [(n, q) for _, n, q in mids] + [(last, line[-1])]
            name = f'{far} to {short}' if back else (existing or f'{short} to {far}')
            out.append({
                'company': comp, 'name': name,
                'start_point': far if back else home, 'end_point': home if back else far,
                'price': price,
                'stages': [[n, round(q[0], 6), round(q[1], 6)] for n, q in stages],
                'line': [[round(x, 5), round(y, 5)] for y, x in line],
            })
            print(f'\n{comp} | {name} | {cum(line)[-1] / 1000:.1f} km | {len(line)} pts'
                  f' | spurs {spurs(line)}{note}')
            print('   ' + ' > '.join(n for n, _ in stages), flush=True)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print(f'\n{len(out)} routes -> {OUT}')


if __name__ == '__main__':
    main()
