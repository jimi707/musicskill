#!/usr/bin/env python3
"""快速轮换：选歌 → 删旧 → 添新 → 推送。跳过听歌记录查询，直接用曲库。"""
import json, os, sys, random, base64, urllib.request, urllib.parse
from datetime import date
from Crypto.Cipher import AES

# 配置
MUSIC_U = os.environ.get('MUSIC_U', '')
BARK_KEY = os.environ.get('BARK_KEY', 'uZmXDxFGJtJAFaiksFRAFN')
PID = os.environ.get('PLAYLIST_ID', '18085057022')
COOKIE = f'MUSIC_U={MUSIC_U}; os=pc;'

# 曲库
HERE = os.path.dirname(__file__)
config = json.load(open(os.path.join(HERE, 'config.json'), encoding='utf-8'))
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

# 1. 选歌
random.seed(str(date.today()))
picks = random.sample(IDS, 20)
print(f'选中20首: {[POOL[i] for i in picks]}')

# 2. 删旧
r = post('https://music.163.com/weapi/playlist/detail', {'id': PID, 's': '0', 'n': '100'})
old = [t['id'] for t in r.get('playlist', {}).get('tracks', [])]
if old:
    post('https://music.163.com/weapi/playlist/manipulate/tracks', {'op': 'del', 'pid': PID, 'trackIds': old})

# 3. 添新
r = post('https://music.163.com/weapi/playlist/manipulate/tracks', {'op': 'add', 'pid': PID, 'trackIds': picks})
ok = r.get('code') == 200
print('OK' if ok else f'FAIL: {r}')

# 4. 推送
if BARK_KEY and ok:
    t = 'musicskill 今日推荐已更新'
    b = '\n'.join([POOL[i].replace('-',' — ') for i in picks[:10]]) + f'\n...共{len(picks)}首'
    urllib.request.urlopen(f'https://api.day.app/{BARK_KEY}/{urllib.parse.quote(t)}/{urllib.parse.quote(b)}?group=每日推荐', timeout=5)
    print('推送成功')
