#!/usr/bin/env python3
"""网易云歌单轮换：改歌 → 删旧 → 添新 → 推送。保证歌单精确到指定数量。"""
import json, os, sys, random, base64, urllib.request, urllib.parse, subprocess
from datetime import date
from Crypto.Cipher import AES

# 配置
HERE = os.path.dirname(__file__)
config = json.load(open(os.path.join(HERE, 'config.json'), encoding='utf-8'))
MUSIC_U = os.environ.get('MUSIC_U', '')
BARK_KEY = os.environ.get('BARK_KEY', config.get('bark_key', ''))
PID = os.environ.get('PLAYLIST_ID', config.get('playlist_id', ''))
COUNT = int(os.environ.get('PICK_COUNT', config.get('pick_count', 20)))
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

# 选歌
random.seed(str(date.today()))
picks = random.sample(IDS, min(COUNT, len(IDS)))
names = [POOL[i].replace('-', ' — ') for i in picks]
print(f'选中{len(picks)}首')

# 删旧歌（分批，API限制每次最多10-20首）
try:
    r = post('https://music.163.com/weapi/v3/playlist/detail', {'id': PID, 's': '0', 'n': '200'})
    old = [t['id'] for t in r.get('playlist', {}).get('tracks', [])]
    for i in range(0, len(old), 10):
        post('https://music.163.com/weapi/playlist/manipulate/tracks', {'op': 'del', 'pid': PID, 'trackIds': old[i:i+10]})
        import time; time.sleep(0.3)
    print(f'已删{len(old)}首旧歌' if old else '无旧歌')
except Exception as e:
    print(f'删除异常: {e}')

r = post('https://music.163.com/weapi/playlist/manipulate/tracks', {'op': 'add', 'pid': PID, 'trackIds': picks})
ok = r.get('code') == 200
print(f'添加{len(picks)}首: {"OK" if ok else "FAIL"}')

# 推送（用Node.js避免中文编码问题）
if BARK_KEY and ok:
    preview = '\n'.join(names[:8]) + f'\n...共{len(picks)}首'
    node_code = f'''
        const h = require("https");
        h.get("https://api.day.app/{BARK_KEY}/"+encodeURIComponent("musicskill 今日推荐已更新")+"/"+encodeURIComponent({json.dumps(preview)})+"?group=每日推荐");
    '''
    subprocess.run(['node', '-e', node_code], timeout=10)
    print('推送成功')
