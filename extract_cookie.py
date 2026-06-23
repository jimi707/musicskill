#!/usr/bin/env python3
"""
从网易云桌面端提取 MUSIC_U Cookie
每7天左右过期，过期后重新运行此脚本更新 Secret
"""
import os, json, sqlite3, base64, sys
import win32crypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

COOKIES_PATH = os.path.expanduser('~') + '/AppData/Local/NetEase/CloudMusic/webapp91x64/Cookies'
PREFS_PATH = os.path.expanduser('~') + '/AppData/Local/NetEase/CloudMusic/webapp91x64/LocalPrefs.json'

if not os.path.exists(COOKIES_PATH):
    print('❌ 未找到网易云Cookie数据库，请确保已登录网易云桌面端')
    sys.exit(1)

# 1. 获取 AES key
with open(PREFS_PATH) as f:
    prefs = json.load(f)
enc_key = base64.b64decode(prefs['os_crypt']['encrypted_key'])[5:]  # 去掉 DPAPI
aes_key = win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]

# 2. 解密 MUSIC_U
conn = sqlite3.connect(COOKIES_PATH)
c = conn.cursor()
c.execute("SELECT encrypted_value FROM cookies WHERE host_key='.music.163.com' AND name='MUSIC_U'")
row = c.fetchone()
conn.close()

if not row:
    print('❌ 未找到 MUSIC_U Cookie')
    sys.exit(1)

enc_val = row[0]
nonce = enc_val[3:15]; ct = enc_val[15:-16]; tag = enc_val[-16:]
music_u = AESGCM(aes_key).decrypt(nonce, ct + tag, None).decode()

print('✅ MUSIC_U 提取成功!')
print(f'MUSIC_U={music_u}')
print()
print('请复制上面的MUSIC_U值，在GitHub仓库中更新Secret:')
print('Settings → Secrets and variables → Actions → MUSIC_U')
