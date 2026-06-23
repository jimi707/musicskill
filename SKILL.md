---
name: musicskill
description: 网易云音乐每日歌单推荐轮换工具。每天自动推荐20首歌，替换歌单旧歌。支持查看听歌记录、个性化曲库管理。
---

# musicskill — 网易云每日歌单轮换

## 概述

自动管理你的网易云歌单：每天推荐新歌，轮换旧歌，推送到手机。

### 功能
- 每天自动给指定歌单替换20首新歌
- 基于你的听歌记录 + 歌单过滤已听过的歌
- 支持自定义曲库风格
- 完成后通过 Bark 推送结果到手机
- 可自定义轮换时间（默认每天9:00）

---

## 🔒 安全规则

1. **权限范围**：只操作用户指定的那个歌单，严禁碰其他任何东西
2. **保密**：用户的账号密码永不写入文件/显示/外传，Cookie用完即弃

---

## 前置依赖

```bash
# Python 3.8+ 需要安装：
pip install pycryptodomex cryptography
```

---

## 使用方式

### 第一步：询问用户偏好

**必须先问用户两个问题，不能直接设默认值：**

1. **⏰ 每天几点推？**（默认可建议 08:00 或 09:00）
2. **📀 每次推几首？**（默认可建议 10-20 首）

用户给出答案后写入 config.json 的 `schedule_time` 和 `pick_count`。

> 特殊用户 flooooow 的固定配置：**8点、20首**。此用户的配置不需询问，直接使用。

### 第二步：配置

告诉用户需要提供以下信息：

| 配置项 | 说明 | 获取方式 |
|--------|------|----------|
| **网易云歌单ID** | 要自动轮换的歌单 | 在网易云App中创建歌单，从URL获取 |
| **Bark Key**（可选） | 推送通知到手机 | 安装Bark App后获取 |

### 第二步：提取登录Cookie（自动）

Skill会自动从网易云桌面端提取登录Cookie：
1. 确保网易云桌面端已登录
2. 读取 `~/AppData/Local/NetEase/CloudMusic/webapp91x64/Cookies`
3. 用 `LocalPrefs.json` 中的加密Key解密 MUSIC_U

### 第三步：管理曲库

曲库分为以下风格分类，用户可自由增删：

**华语独立摇滚：** 草东没有派对、告五人、落日飞车、康士坦的变化球、老王乐队、万能青年旅店、Deca Joins、椅子乐团、蛙池、Chinese Football、傻子与白痴、茄子蛋、痛仰乐队、张蔷

**英伦/另类：** Blur、The Smiths、Pulp、Radiohead、Oasis、Suede、The Cure、Pixies、The Cranberries

**美式另类/独立：** Arctic Monkeys、Tame Impala、Mac DeMarco、Pearl Jam、Sonic Youth、Nirvana、Foo Fighters、The Strokes、Smashing Pumpkins、Modest Mouse

**经典摇滚：** The Beatles、Pink Floyd、David Bowie、Queen、Eagles、Guns N' Roses、Metallica、Red Hot Chili Peppers

**华语殿堂级：** 李宗盛、陈奕迅、王菲、宋冬野、窦唯、朴树、张震岳、赵雷、卢广仲、陶喆、张雨生、许美静

---

## 技术实现

### WeAPI 加密（Python）

```python
import json, base64, random, string, urllib.request
from Crypto.Cipher import AES

MOD = int('00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7', 16)
EXP = int('010001', 16)
FIXED_KEY = b'0CoJUm6Qyw8W8jud'
IV = b'0102030405060708'

def aes_encrypt(text, key):
    if isinstance(text, str): text = text.encode()
    pad = 16 - (len(text) % 16); text += bytes([pad] * pad)
    return base64.b64encode(AES.new(key, AES.MODE_CBC, IV).encrypt(text)).decode()

def rsa_encrypt(text):
    return format(pow(int.from_bytes(text[::-1].encode(), 'big'), EXP, MOD), 'x').zfill(256)

def weapi(data):
    rk = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    return aes_encrypt(aes_encrypt(json.dumps(data, separators=(',', ':')), FIXED_KEY), rk.encode()), rsa_encrypt(rk)
```

### Cookie 解密

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import win32crypt, base64, json, sqlite3

# 1. 获取加密Key
prefs = json.load(open('LocalPrefs.json'))
enc_key = base64.b64decode(prefs['os_crypt']['encrypted_key'])[5:]  # 去掉DPAPI前缀
aes_key = win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]

# 2. 解密Cookie
conn = sqlite3.connect('Cookies')
c = conn.cursor()
c.execute("SELECT encrypted_value FROM cookies WHERE host_key='.music.163.com' AND name='MUSIC_U'")
enc_val = c.fetchone()[0]
nonce = enc_val[3:15]; ct = enc_val[15:-16]; tag = enc_val[-16:]
music_u = AESGCM(aes_key).decrypt(nonce, ct + tag, None).decode()
```

### API 端点

| 操作 | 方法 | 端点 |
|------|------|------|
| 添加/删除歌曲 | `weapi/playlist/manipulate/tracks` | body: `{op, pid, trackIds:[整数数组]}` |
| 歌单详情 | `weapi/v3/playlist/detail` | body: `{id, s:"0", n:"100"}` |
| 听歌记录 | `weapi/v1/play/record` | body: `{uid, type:0, limit:100}` |
| 创建歌单 | `weapi/playlist/create` | body: `{name, privacy, type}` |

**关键：** `trackIds` 必须传整数数组 `[id1, id2, ...]`，不是对象数组。

### 每日轮换逻辑

```python
import random
today = "2026-06-23"  # 用当天日期做种子，保证每天结果一致
random.seed(today)
picks = random.sample(unheard_pool, 20)  # 从没听过的候选池选20首
```

### Bark 推送

```javascript
const title = encodeURIComponent('标题');
const body = encodeURIComponent('内容');
// GET https://api.day.app/{你的BarkKey}/{title}/{body}
```

---

## 发布与安装

### 发布到 GitHub

```bash
# 1. 创建 GitHub 仓库
git init
git add .
git commit -m "Initial musicskill"
git remote add origin https://github.com/你的用户名/musicskill
git push -u origin main

# 2. 用户安装
npx skills add 你的用户名/musicskill
```

### 本地测试

```bash
# 直接引用本地目录
npx skills add /path/to/musicskill
```

---

## 自定义

### 修改推荐风格

告诉Claude：
- "换成更摇滚的风格"
- "加些经典老歌"
- "多放些华语流行"

会自动调整曲库池中的歌曲ID。

### 修改轮换时间

```bash
# 当前为每天9:00
# 可修改 CronCreate 的 cron 参数
```

### 添加新曲库

搜索歌曲ID：
```
GET https://music.163.com/api/search/get/web?type=1&s={歌名+歌手}
取 songs[0].id 加入曲库池
```
