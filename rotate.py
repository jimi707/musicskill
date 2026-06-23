#!/usr/bin/env python3
"""
网易云每日歌单轮换 - GitHub Actions 版
从 config.json 读取曲库，自动轮换20首歌
"""
import json, os, sys, random, base64, urllib.request, urllib.parse, hashlib
from datetime import date

# ====== 从环境变量读取配置 ======
MUSIC_U = os.environ.get('MUSIC_U', '')
BARK_KEY = os.environ.get('BARK_KEY', '')
PLAYLIST_ID = os.environ.get('PLAYLIST_ID', '')

if not MUSIC_U or not PLAYLIST_ID:
    print('请设置 MUSIC_U 和 PLAYLIST_ID 环境变量')
    sys.exit(1)

# ====== 读取 config.json ======
config_path = os.path.join(os.path.dirname(__file__), 'config.json')
with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

PLAYLIST_ID = PLAYLIST_ID or config.get('playlist_id', '')
BARK_KEY = BARK_KEY or config.get('bark_key', '')
COOKIE_STR = f'MUSIC_U={MUSIC_U}; os=pc;'

# 构建曲库
all_songs = {s['id']: f"{s['name']}-{s['artist']}" for s in config['song_pool']}
all_ids = list(all_songs.keys())

# ====== WeAPI 加密 ======
MOD = int('00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7', 16)
EXP = int('010001', 16); FIXED = b'0CoJUm6Qyw8W8jud'; IV = b'0102030405060708'

try:
    from Crypto.Cipher import AES
    def aes_encrypt(text, key):
        if isinstance(text, str): text = text.encode()
        pad = 16 - (len(text) % 16); text += bytes([pad] * pad)
        return base64.b64encode(AES.new(key, AES.MODE_CBC, IV).encrypt(text)).decode()
except ImportError:
    print('需要 pycryptodome: pip install pycryptodomex')
    sys.exit(1)

def rsa_encrypt(text):
    return format(pow(int.from_bytes(text[::-1].encode(), 'big'), EXP, MOD), 'x').zfill(256)

def weapi(data):
    import random as rnd, string
    rk = ''.join(rnd.choices(string.ascii_letters + string.digits, k=16))
    return aes_encrypt(aes_encrypt(json.dumps(data, separators=(',', ':')), FIXED), rk.encode()), rsa_encrypt(rk)

def api(url, data):
    p, ek = weapi(data)
    body = urllib.parse.urlencode({'params': p, 'encSecKey': ek}).encode()
    req = urllib.request.Request(url, data=body, headers={
        'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': 'https://music.163.com/', 'Cookie': COOKIE_STR,
    })
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())

# ====== 获取已听记录 ======
print('获取听歌记录...')
heard_ids = set()
try:
    r = api('https://music.163.com/weapi/v1/play/record', {'uid': 0, 'type': 0, 'limit': 100})
    for item in r.get('allData', []):
        s = item.get('song', {})
        if s and s.get('id'): heard_ids.add(s['id'])
except Exception as e:
    print(f'获取听歌记录失败: {e}')

# 也查歌单内的歌
for pid in ['5301136143', '10144460360', '2749905876']:
    try:
        r = api('https://music.163.com/weapi/v3/playlist/detail', {'id': pid, 's': '0', 'n': '200'})
        for t in r.get('playlist', {}).get('tracks', []): heard_ids.add(t['id'])
    except: pass

# ====== 筛选未听过 ======
unheard = [sid for sid in all_ids if sid not in heard_ids]
if len(unheard) < 20:
    print(f'未听过歌曲不足20首（只有{len(unheard)}首），使用全部候选')
    picks = unheard + [sid for sid in all_ids if sid in heard_ids][:20-len(unheard)]
else:
    random.seed(str(date.today()))
    picks = random.sample(unheard, 20)

print(f'曲库共 {len(all_ids)} 首，已听过 {len(heard_ids & set(all_ids))} 首')
print(f'今日选 {len(picks)} 首: {[all_songs.get(p,"?") for p in picks]}')

# ====== 轮换歌单 ======
pid = PLAYLIST_ID
print('删除旧歌...')
try:
    r = api('https://music.163.com/weapi/playlist/detail', {'id': pid, 's': '0', 'n': '100'})
    old_ids = [t['id'] for t in r.get('playlist', {}).get('tracks', [])]
    if old_ids:
        api('https://music.163.com/weapi/playlist/manipulate/tracks', {'op': 'del', 'pid': pid, 'trackIds': old_ids})
except: pass

print('添加新歌...')
r = api('https://music.163.com/weapi/playlist/manipulate/tracks', {'op': 'add', 'pid': pid, 'trackIds': picks})
success = r.get('code') == 200
print('成功' if success else f'失败: {r}')

# ====== Bark 推送 ======
if BARK_KEY and success:
    title = '🎵 每日歌单已更新'
    body = '\n'.join([all_songs.get(p, '').replace('-', ' — ') for p in picks[:10]])
    body += f'\n...共{len(picks)}首'
    url = f'https://api.day.app/{BARK_KEY}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}?group=每日推荐'
    try: urllib.request.urlopen(url, timeout=5)
    except: pass
    print('已推送')
