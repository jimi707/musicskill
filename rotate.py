#!/usr/bin/env python3
"""网易云歌单轮换：选歌→删旧→添新→验证→推送。确保歌单精确到设定数目。"""
import json, os, sys, random, base64, urllib.request, urllib.parse, subprocess, time
from datetime import date
try:
    from Crypto.Cipher import AES
except:
    from Cryptodome.Cipher import AES

# ====== 配置 ======
HERE = os.path.dirname(__file__)
config = json.load(open(os.path.join(HERE, 'config.json'), encoding='utf-8'))
MUSIC_U = os.environ.get('MUSIC_U', '')
BARK_KEY = os.environ.get('BARK_KEY', config.get('bark_key', ''))
PID = os.environ.get('PLAYLIST_ID', config.get('playlist_id', ''))
raw = os.environ.get('PICK_COUNT', '')
COUNT = int(raw) if raw.strip() else int(config.get('pick_count', 20))
SMART = config.get('smart_recommend', True)
COOKIE = f'MUSIC_U={MUSIC_U}; os=pc;'

POOL = {s['id']: f"{s['name']}-{s['artist']}" for s in config['song_pool']}
IDS = list(POOL.keys())

# ====== WeAPI ======
MOD = int('00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7', 16)
EXP = int('010001', 16); FKEY = b'0CoJUm6Qyw8W8jud'; IV = b'0102030405060708'
CHARS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'

def ae(t, k):
    if isinstance(t, str): t = t.encode()
    p = 16 - len(t) % 16; t += bytes([p]) * p
    return base64.b64encode(AES.new(k if isinstance(k, bytes) else k.encode(), AES.MODE_CBC, IV).encrypt(t)).decode()

def re(t):
    return format(pow(int.from_bytes(t[::-1].encode(), 'big'), EXP, MOD), 'x').zfill(256)

def we(d):
    rk = ''.join(random.choices(CHARS, k=16))
    return ae(ae(json.dumps(d, separators=(',', ':')), FKEY), rk), re(rk)

def post(url, d):
    p, ek = we(d)
    b = urllib.parse.urlencode({'params': p, 'encSecKey': ek}).encode()
    req = urllib.request.Request(url, data=b, headers={
        'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': 'https://music.163.com/', 'Cookie': COOKIE,
    })
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())

def get_tracks(pid):
    """获取歌单所有歌曲ID"""
    r = post('https://music.163.com/weapi/v3/playlist/detail', {'id': pid, 's': '0', 'n': '200'})
    return [t['id'] for t in r.get('playlist', {}).get('tracks', [])]

def delete_tracks(pid, ids):
    """分批删除"""
    for i in range(0, len(ids), 10):
        post('https://music.163.com/weapi/playlist/manipulate/tracks',
             {'op': 'del', 'pid': pid, 'trackIds': ids[i:i+10]})
        time.sleep(0.3)

def add_tracks(pid, ids):
    """分批添加，返回成功添加的ID"""
    added = []
    for i in range(0, len(ids), 10):
        batch = ids[i:i+10]
        try:
            r = post('https://music.163.com/weapi/playlist/manipulate/tracks',
                     {'op': 'add', 'pid': pid, 'trackIds': batch})
            if r.get('code') == 200:
                added.extend(batch)
            else:
                # 逐个尝试
                for sid in batch:
                    try:
                        r2 = post('https://music.163.com/weapi/playlist/manipulate/tracks',
                                  {'op': 'add', 'pid': pid, 'trackIds': [sid]})
                        if r2.get('code') == 200:
                            added.append(sid)
                    except: pass
        except: pass
        time.sleep(0.3)
    return added

# ====== 智能选歌 ======
def pick_songs():
    heard = set()
    if SMART:
        print('分析口味中...')
        try:
            playlists = post('https://music.163.com/weapi/user/playlist',
                            {'uid': config.get('user_id', 0), 'limit': 10, 'offset': 0})
            for pl in playlists.get('playlist', []):
                if str(pl.get('id')) == str(PID): continue
                try:
                    r = post('https://music.163.com/weapi/v3/playlist/detail',
                            {'id': str(pl['id']), 's': '0', 'n': '200'})
                    for t in r.get('playlist', {}).get('tracks', []):
                        if t.get('id'): heard.add(t['id'])
                except: pass
            try:
                r = post('https://music.163.com/weapi/v1/play/record',
                        {'uid': config.get('user_id', 0), 'type': 0, 'limit': 100})
                for item in r.get('allData', []):
                    s = item.get('song', {})
                    if s and s.get('id'): heard.add(s['id'])
            except: pass
        except: pass
        print(f'已听过 {len(heard)} 首')

    random.seed(str(date.today()))
    candidates = [sid for sid in IDS if sid not in heard]
    if len(candidates) < COUNT:
        candidates = [sid for sid in IDS if sid not in candidates][:COUNT-len(candidates)] + candidates
    return random.sample(candidates, min(COUNT, len(candidates))), heard

# ====== 主流程 ======
print(f'目标: {COUNT} 首')
picks, heard = pick_songs()
names = [POOL[i].replace('-', ' — ') for i in picks]

print(f'选定: {len(picks)} 首')
for n in names: print(f'  {n}')

# 1. 删旧
print('删旧歌...', end=' ')
old = get_tracks(PID)
if old:
    delete_tracks(PID, old)
    print(f'{len(old)}首 ✓')
else:
    print('无旧歌')

# 2. 添新
print('添新歌...', end=' ')
added = add_tracks(PID, picks)
print(f'{len(added)}首 ✓')

# 3. 验证并修正
print('验证中...', end=' ')
current = get_tracks(PID)
actual = len(current)
print(f'当前 {actual} 首')

if actual < COUNT:
    # 缺 → 补选
    need = COUNT - actual
    more = random.sample([s for s in IDS if s not in current], min(need, len(IDS)))
    if more:
        added2 = add_tracks(PID, more)
        current = get_tracks(PID)
        actual = len(current)
        print(f'补充 {len(added2)} 首 → 当前 {actual} 首')
elif actual > COUNT:
    # 多 → 删多余的
    remove = current[COUNT:]
    delete_tracks(PID, remove)
    current = get_tracks(PID)
    actual = len(current)
    print(f'删除 {len(remove)} 首 → 当前 {actual} 首')

ok = actual == COUNT
print(f'{"✓ 歌单精确" if ok else f"⚠ 歌单{actual}首"}')

# 4. 推送
if BARK_KEY:
    preview = '\n'.join(names[:8]) + f'\n{"...共"+str(len(picks))+"首"}'
    subprocess.run(['node', '-e', f'''
        require("https").get("https://api.day.app/{BARK_KEY}/"+encodeURIComponent("musicskill 今日推荐已更新")+"/"+encodeURIComponent({json.dumps(preview)})+"?group=每日推荐");
    '''], timeout=10)
    print('推送 ✓')
