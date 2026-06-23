# musicskill 🎵

**网易云音乐每日歌单轮换工具** — 比官方推荐更懂你。

```
npx skills add 你的用户名/musicskill
```

---

## 这是什么？

`musicskill` 是一个 Claude Code skill，它能：

- ✅ **每天自动** 给你的网易云歌单换一批新歌
- ✅ **绕过你的听歌记录**，推荐你没听过的歌
- ✅ **随时改风格** — "换成摇滚"、"加些华语经典" 一句话就改
- ✅ **推送到手机** — 换完歌自动通知你

## 和网易云自带推荐的区别

| | 网易云推荐 | musicskill |
|---|---|---|
| **算法透明** | 黑箱，不知道为啥推这些 | 曲库完全可控，知道每首歌从哪来 |
| **自定义程度** | 只能点"不感兴趣" | **一句话改风格**，随时换曲库 |
| **更新频率** | 每天日推，过了就没了 | 每天固定歌单**持续累积** |
| **听歌历史过滤** | 偶尔会推听过的 | **严格过滤**你600+首已听歌曲 |
| **隐私安全** | 数据上传云端分析 | 本地运行，Cookie用完即弃 |
| **可扩展** | ❌ | 可以自己加歌、改池子、换逻辑 |

### 一句话总结

**网易云推荐 → 算法喂给你什么你就听什么**
**musicskill → 你想听什么就喂什么**

---

## 快速开始

### 前置条件

- Claude Code
- 网易云音乐桌面端（已登录）
- Python 3.8+

```bash
pip install pycryptodomex cryptography
```

### 安装 skill

```bash
npx skills add 你的GitHub用户名/musicskill
```

### 首次使用

在 Claude Code 中调用 skill：

```
/musicskill 帮我设置每日推荐
```

按提示提供：
1. **歌单ID** — 你创建的网易云歌单的数字ID
2. **Bark Key**（可选）— 用于推送通知到手机

### 管理推荐风格

随时跟 Claude 说：

> "把推荐风格改成更摇滚的"
> "加些经典老歌进去"
> "最近想听华语流行，换一批"
> "这20首里有几首我听过了，换掉"

---

## 项目结构

```
musicskill/
├── SKILL.md    # Skill 指令（Claude 读取执行）
├── README.md   # 本文件
└── _meta.json  # Skill 元数据
```

## 技术原理

- 从网易云桌面端本地 Cookie 提取登录态（**不存密码**）
- 使用 WeAPI 加密方式调用网易云 API
- 双层 AES + RSA 加密，模拟官方客户端请求
- 每日用日期种子随机选歌，保证每天不同但结果稳定

## 安全

- 账号密码**永不存储**，仅运行时从本地加密 Cookie 提取
- 所有操作**仅限于你指定的那个歌单**
- Cookie 用完即弃，不落盘

---

## 自行发布

Fork 这个仓库，修改后推送到你的 GitHub：

```bash
git clone https://github.com/你的用户名/musicskill.git
# 修改 SKILL.md 中的曲库
git add .
git commit -m "自定义曲库"
git push
```

其他人即可安装：
```bash
npx skills add 你的用户名/musicskill
```
