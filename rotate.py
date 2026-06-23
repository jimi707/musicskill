#!/usr/bin/env python3
"""网易云歌单轮换：选歌 → 删旧 → 添新 → 推送。支持智能/快速两种模式。"""
import json, os, sys, random, base64, urllib.request, urllib.parse, subprocess, time
from datetime import date
from Crypto.Cipher import AES

HERE = os.path.dirname(__file__)
config = json.load(open(os.path.join(HERE, 'config.json'), encoding='utf-8'))
MUSIC_U = os.environ.get('MUSIC_U', '')
BARK_KEY = os.environ.get('BARK_KEY', config.get('bark_key', ''))
PID = os.environ.get('PLAYLIST_ID', config.get('playlist_id', ''))
COUNT = int(os.environ.get('PICK_COUNT', config.get('pick_count', 20)))
SMART = config.get('smart_recommend', True)
COOKIE = f'MUSIC_U={MUSIC_U}; os=pc;'

POOL = {s['id']: f"{s['name']}-{s['artist']}" for s in config['song_pool']}
IDS = list(POOL.keys())

# WeAPI
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
    return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())

# ====== 智能模式：分析口味 + 过滤已听 ======
heard_ids = set()
if SMART:
    print('智能模式：分析口味中...')
    try:
        # 1. 获取用户歌单列表
        uid = config.get('user_id', 0)
        playlists = post('https://music.163.com/weapi/user/playlist', {'uid': uid, 'limit': 30, 'offset': 0})
    except:
        # 如果没配置user_id，尝试从cookie获取
        playlists = {'playlist': []}

    user_pids = [pl['id'] for pl in playlists.get('playlist', []) if pl.get('id') != int(PID)]

    # 2. 获取所有歌单里的歌 + 听歌记录
    for plid in user_pids[:5]:  # 最多取5个歌单
        try:
            r = post('https://music.163.com/weapi/v3/playlist/detail', {'id': str(plid), 's': '0', 'n': '200'})
            for t in r.get('playlist', {}).get('tracks', []):
                if t.get('id'): heard_ids.add(t['id'])
        except: pass

    try:
        r = post('https://music.163.com/weapi/v1/play/record', {'uid': uid or 0, 'type': 0, 'limit': 100})
        for item in r.get('allData', []):
            s = item.get('song', {})
            if s and s.get('id'): heard_ids.add(s['id'])
    except: pass

    print(f'已听歌曲: {len(heard_ids)} 首')

# ====== 选歌 ======
random.seed(str(date.today()))

if SMART:
    # 智能：只从没听过的歌里选
    candidates = [sid for sid in IDS if sid not in heard_ids]
    # 如果候选不够20首，补齐
    if len(candidates) < COUNT:
        candidates = candidates + [sid for sid in IDS if sid in heard_ids]
    picks = random.sample(candidates, min(COUNT, len(candidates)))
    print(f'智能筛选: 候选{len(candidates)}首 → 选{len(picks)}首')
else:
    # 快速：直接随机选
    picks = random.sample(IDS, min(COUNT, len(IDS)))
    print(f'快速模式: 选{len(picks)}首')

names = [POOL[i].replace('-', ' — ') for i in picks]
for n in names: print(f'  {n}')

# ====== 删旧（分批） ======
r = post('https://music.163.com/weapi/v3/playlist/detail', {'id': PID, 's': '0', 'n': '200'})
old = [t['id'] for t in r.get('playlist', {}).get('tracks', [])]
for i in range(0, len(old), 10):
    post('https://music.163.com/weapi/playlist/manipulate/tracks', {'op': 'del', 'pid': PID, 'trackIds': old[i:i+10]})
    time.sleep(0.3)
print(f'已删{len(old)}首旧歌' if old else '无旧歌')

# ====== 添新 ======
r = post('https://music.163.com/weapi/playlist/manipulate/tracks', {'op': 'add', 'pid': PID, 'trackIds': picks})
ok = r.get('code') == 200
print(f'添加{len(picks)}首: {"OK" if ok else "FAIL"}')

# ====== 推送 ======
if BARK_KEY and ok:
    preview = '\n'.join(names[:8]) + f'\n...共{len(picks)}首'
    node_code = f'''
        const h = require("https");
        h.get("https://api.day.app/{BARK_KEY}/"+encodeURIComponent("musicskill 今日推荐已更新")+"/"+encodeURIComponent({json.dumps(preview)})+"?group=每日推荐");
    '''
    subprocess.run(['node', '-e', node_code], timeout=10)
    print('推送成功')
