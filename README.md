# musicskill 🎵

**网易云音乐 · 每日歌单智能轮换引擎**

```
npx skills add jimi707/musicskill
```

> 商用级稳定性：配置校验 → 安全提取 → 指数退避重试 → 状态持久化 → 自动补齐 → 推送

---

## 它能做什么

每天自动给你的网易云歌单换一批新歌——**精准数量、过滤已听、推送到手机、自动止损**。

| 能力 | 说明 |
|------|------|
| 🎯 精准数量 | 说20首就20首，缺歌自动从曲库补选 |
| 🧠 智能过滤 | 分析你的全部歌单 + 听歌记录，不推听过的 |
| 📱 手机推送 | 换完歌自动 Bark 推送摘要到手机 |
| 🔄 自动重试 | API 失败自动指数退避重试，不丢包 |
| 🛡️ 安全提取 | Cookie 从本地加密数据库解密，用完即删 |
| 📝 日志记录 | 每次运行写结构化日志到 logs/ 目录 |

---

## 快速开始

### 安装

```bash
cd musicskill
npm install
pip install pycryptodome cryptography
```

### 配置

```bash
node auto_rotate.js --dry-run
```

首次运行会检查配置，按提示填写 `config.json` 中的必要字段。

### 执行

```bash
# 正常轮换
node auto_rotate.js

# 预览模式（不修改歌单）
node auto_rotate.js --dry-run

# 带日志记录
node auto_rotate.js --log-file
```

### 配置项

```json
{
  "playlist_id": "18085057022",      // 网易云歌单 ID（必填）
  "user_id": 3946361671,             // 网易云用户 ID（必填）
  "bark_key": "uZmXDxFGJtJAF...",   // Bark 推送 Key（可选）
  "pick_count": 20,                  // 每次推几首（5-100）
  "schedule_time": "08:00",          // 默认执行时间
  "song_pool": [...]                 // 曲库列表（至少10首）
}
```

### 退出码

| 码 | 含义 | 排查方向 |
|----|------|----------|
| 0  | ✅ 完全成功 | - |
| 1  | ❌ 配置错误 | 检查 config.json 格式 |
| 2  | ❌ Cookie 失败 | 打开网易云桌面端 |
| 3  | ❌ 登录失败 | 检查网络或重试 |
| 4  | ⚠️ 部分成功 | 查看 logs/ 中无效歌曲ID |
| 5  | 💥 未捕获异常 | 查看日志 |

---

## 曲库管理

曲库按风格分类，编辑 `config.json` 的 `song_pool` 数组：

| 风格 | 艺人举例 |
|------|----------|
| 华语独立摇滚 | 草东没有派对、告五人、落日飞车、痛仰、deca joins |
| 英伦/另类 | Blur、The Smiths、Radiohead、Suede、The Cure |
| 美式另类 | Nirvana、Foo Fighters、Pearl Jam、Smashing Pumpkins |
| 经典摇滚 | The Beatles、Pink Floyd、David Bowie、Guns N' Roses |
| 华语经典 | 李宗盛、陈奕迅、王菲、朴树、张雨生 |

**添加新歌：** 在网易云搜索到歌曲后，复制 URL 中的数字 ID 加入 `song_pool`。

---

## 故障排除

```
Cookie 提取失败
  → 打开网易云桌面端，确认已登录

-462 风控拦截
  → 自动重试中，如持续出现请减少 pick_count 或等待10分钟

歌单长期不足20首
  → 执行 --dry-run 查看哪些歌曲ID已失效

Bark 推送失败
  → 检查 config.json 中 bark_key 是否正确
```

---

## 技术栈

| 组件 | 选型 |
|------|------|
| 运行时 | Node.js 18+ |
| API 封装 | NeteaseCloudMusicApi |
| Cookie 解密 | Python + win32crypt + AESGCM |
| 随机算法 | LCG + Fisher-Yates shuffle |
| 推送 | Bark (iOS) |
| 日志 | 结构化文本日志 |

---

## 安全说明

- 账号密码永不存储
- Cookie 从桌面端本地加密数据库提取，不经过网络传输
- 临时 Python 脚本执行后即时删除
- 所有操作限制在 `config.json` 指定的唯一歌单
- 日志不包含完整 Cookie 值
