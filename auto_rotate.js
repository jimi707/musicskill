#!/usr/bin/env node
/**
 * musicskill — 网易云每日歌单智能轮换引擎
 * =========================================
 * 商用级稳定性设计：配置校验 → 安全提取 → 指数退避重试 → 状态持久化 → 自动补齐 → Bark推送
 *
 * 退出码:
 *   0 = 完全成功（歌单精准 COUNT 首）
 *   1 = 配置错误
 *   2 = Cookie 提取失败
 *   3 = API 登录/刷新失败
 *   4 = 部分成功（歌单不足 COUNT 首但 > 0）
 *   5 = 完全失败（歌单0首或关键步骤崩溃）
 *
 * 用法:
 *   node auto_rotate.js              # 正常执行
 *   node auto_rotate.js --dry-run    # 仅预览，不修改歌单
 *   node auto_rotate.js --log-file   # 同时输出日志到文件
 */

'use strict';

// ============================================================================
// 依赖
// ============================================================================
const path = require('path');
const fs   = require('fs');
const { execSync } = require('child_process');
const crypto = require('crypto');
const https = require('https');

// ============================================================================
// 常量
// ============================================================================
const APP_DIR     = __dirname;
const CONFIG_PATH = path.join(APP_DIR, 'config.json');
const STATE_PATH  = path.join(APP_DIR, 'state.json');
const LOG_DIR     = path.join(APP_DIR, 'logs');
const PY_TMP_PAT  = path.join(APP_DIR, '._extract_');

const COOKIE_DB   = process.env.USERPROFILE + '\\AppData\\Local\\NetEase\\CloudMusic\\webapp91x64\\Cookies';
const PREFS_DB    = process.env.USERPROFILE + '\\AppData\\Local\\NetEase\\CloudMusic\\webapp91x64\\LocalPrefs.json';

const EXIT = { OK: 0, CONFIG_ERR: 1, COOKIE_ERR: 2, LOGIN_ERR: 3, PARTIAL: 4, FAIL: 5 };

// NeteaseCloudMusicApi 响应中 playlist_tracks 的成功判断
const TRACK_OK = r => r?.body?.body?.code === 200;

// ============================================================================
// 日志系统
// ============================================================================
class Logger {
  constructor(logFile = false) {
    this._logs = [];
    this._logFile = logFile;
    if (logFile) {
      try { fs.mkdirSync(LOG_DIR, { recursive: true }); } catch {}
      this._stream = fs.createWriteStream(
        path.join(LOG_DIR, `rotate_${new Date().toISOString().slice(0,10)}.log`),
        { flags: 'a', encoding: 'utf-8' }
      );
    }
  }

  _fmt(level, msg) {
    const ts = new Date().toISOString().replace('T', ' ').slice(0, 19);
    return `[${ts}] [${level}] ${msg}`;
  }

  _out(level, msg) {
    const line = this._fmt(level, msg);
    this._logs.push(line);
    if (this._stream) this._stream.write(line + '\n');
  }

  info(msg)  { this._out('INFO',  msg); console.log(msg); }
  warn(msg)  { this._out('WARN',  msg); console.warn('⚠️', msg); }
  error(msg) { this._out('ERROR', msg); console.error('❌', msg); }
  ok(msg)    { this._out('OK',    msg); console.log('✅', msg); }
  step(msg)  { this._out('STEP',  msg); console.log(`\n━━━ ${msg} ━━━`); }

  get summary() { return this._logs.join('\n'); }
  close() { if (this._stream) this._stream.end(); }
}

// ============================================================================
// 配置校验
// ============================================================================
function loadConfig() {
  if (!fs.existsSync(CONFIG_PATH)) {
    console.error('❌ 缺少 config.json');
    process.exit(EXIT.CONFIG_ERR);
  }

  let raw;
  try { raw = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8')); }
  catch (e) { console.error('❌ config.json 格式错误:', e.message); process.exit(EXIT.CONFIG_ERR); }

  const errors = [];
  if (!raw.playlist_id || !String(raw.playlist_id).match(/^\d+$/))
    errors.push('playlist_id 必须为数字字符串');
  if (!raw.user_id || typeof raw.user_id !== 'number')
    errors.push('user_id 必须为数字');
  if (!Array.isArray(raw.song_pool) || raw.song_pool.length < 10)
    errors.push('song_pool 至少需要10首歌');
  for (const [i, s] of (raw.song_pool || []).entries()) {
    if (!s.id || !s.name || !s.artist)
      errors.push(`song_pool[${i}] 缺少 id/name/artist`);
  }
  // 检查重复 ID
  const ids = raw.song_pool.map(s => s.id);
  const dupes = ids.filter((id, i) => ids.indexOf(id) !== i);
  if (dupes.length) errors.push(`song_pool 中有重复 ID: ${[...new Set(dupes)].join(',')}`);

  if (errors.length) {
    console.error('❌ 配置校验失败:');
    errors.forEach(e => console.error('   -', e));
    process.exit(EXIT.CONFIG_ERR);
  }

  return {
    playlist_id: String(raw.playlist_id),
    user_id:     raw.user_id,
    bark_key:    raw.bark_key || '',
    serverChan_key: raw.serverChan_key || '',
    pick_count:  Math.min(Math.max(raw.pick_count || 20, 5), 100),
    schedule:    raw.schedule_time || '08:00',
    smart:       raw.smart_recommend !== false,
    pool:        raw.song_pool.map(s => ({ id: s.id, name: s.name, artist: s.artist, style: s.style || '' })),
  };
}

// ============================================================================
// 状态持久化（防同日内重复推荐、跨日历史跟踪）
// ============================================================================
class StateStore {
  constructor() {
    this._data = { history: [], lastPicks: [], lastDate: '' };
    if (fs.existsSync(STATE_PATH)) {
      try { this._data = JSON.parse(fs.readFileSync(STATE_PATH, 'utf-8')); } catch {}
    }
  }

  /** 今日是否已执行过 */
  get todayDone() {
    return this._data.lastDate === new Date().toISOString().slice(0, 10);
  }

  /** 保存本次执行记录 */
  save(picks, ok) {
    const date = new Date().toISOString().slice(0, 10);
    this._data.lastDate = date;
    this._data.lastPicks = picks;
    this._data.history.unshift({ date, picks, ok, ts: Date.now() });
    if (this._data.history.length > 365) this._data.history.length = 365; // 保留1年
    try { fs.writeFileSync(STATE_PATH, JSON.stringify(this._data, null, 2), 'utf-8'); } catch {}
  }

  /** 过去 N 天内推荐过的歌曲 ID */
  recentIds(days = 7) {
    const cutoff = Date.now() - days * 86400000;
    const ids = new Set();
    for (const h of this._data.history) {
      if (h.ts < cutoff) break;
      (h.picks || []).forEach(id => ids.add(id));
    }
    return ids;
  }
}

// ============================================================================
// Cookie 安全提取
// ============================================================================
function extractCookie(log) {
  if (!fs.existsSync(COOKIE_DB)) {
    log.error(`未找到 Cookie 数据库: ${COOKIE_DB}`);
    log.error('请确保网易云桌面端已登录并运行过');
    process.exit(EXIT.COOKIE_ERR);
  }
  if (!fs.existsSync(PREFS_DB)) {
    log.error(`未找到 LocalPrefs: ${PREFS_DB}`);
    process.exit(EXIT.COOKIE_ERR);
  }

  const tmpFile = PY_TMP_PAT + crypto.randomBytes(4).toString('hex') + '.py';
  const script = [
    '# -*- coding: utf-8 -*-',
    'import json, sqlite3, base64, win32crypt',
    'from cryptography.hazmat.primitives.ciphers.aead import AESGCM',
    `COOKIES_PATH = ${JSON.stringify(COOKIE_DB)}`,
    `PREFS_PATH = ${JSON.stringify(PREFS_DB)}`,
    'with open(PREFS_PATH) as f: prefs = json.load(f)',
    "enc_key = base64.b64decode(prefs['os_crypt']['encrypted_key'])[5:]",
    'aes_key = win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]',
    "rows = sqlite3.connect(COOKIES_PATH).execute(\"SELECT name, encrypted_value FROM cookies WHERE host_key='.music.163.com'\").fetchall()",
    'parts = []',
    'for name, enc_val in rows:',
    '  if enc_val and len(enc_val) > 15:',
    '    try:',
    '      nonce = enc_val[3:15]; ct = enc_val[15:-16]; tag = enc_val[-16:]',
    '      val = AESGCM(aes_key).decrypt(nonce, ct + tag, None).decode()',
    "      parts.append(f'{name}={val}')",
    '    except: pass',
    "print('; '.join(parts))",
  ].join('\n');

  try {
    fs.writeFileSync(tmpFile, script, 'utf-8');
    const out = execSync(`python -X utf8 "${tmpFile}"`, { encoding: 'utf-8', timeout: 20000, windowsHide: true });
    const cookie = out.trim();
    if (!cookie || cookie.length < 50) throw new Error('Cookie 内容异常');
    return cookie;
  } catch (e) {
    log.error(`Cookie 提取失败: ${e.message.split('\n')[0]}`);
    process.exit(EXIT.COOKIE_ERR);
  } finally {
    try { fs.unlinkSync(tmpFile); } catch {}
  }
}

// ============================================================================
// API 客户端（带指数退避重试）
// ============================================================================
class ApiClient {
  constructor(log, cfg) {
    this._log = log;
    this._cfg = cfg;
    this._api = null;
    try { this._api = require('NeteaseCloudMusicApi'); }
    catch { log.error('缺少 NeteaseCloudMusicApi，请执行: npm install'); process.exit(EXIT.CONFIG_ERR); }
  }

  /** 调用 API 方法，失败时指数退避重试 */
  async call(method, params, { retries = 3, label = '' } = {}) {
    let lastErr;
    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        const r = await this._api[method](params);
        if (r?.body?.code === -462) {
          // 风控错误 — 等更久
          this._log.warn(`${label} 风控拦截(-462)，第${attempt}次重试...`);
          await sleep(attempt * 5000);
          continue;
        }
        return r;
      } catch (e) {
        lastErr = e;
        if (attempt < retries) {
          const delay = Math.min(1000 * Math.pow(2, attempt), 15000);
          this._log.warn(`${label} 失败(attempt ${attempt})，${delay}ms后重试: ${(e.message||'').slice(0,60)}`);
          await sleep(delay);
        }
      }
    }
    throw lastErr || new Error(`${label} 请求超过最大重试次数`);
  }

  /** 刷新登录 */
  async refresh(cookie) {
    const r = await this.call('login_refresh', { cookie }, { retries: 2, label: 'login_refresh' });
    if (r?.body?.code !== 200) throw new Error(`登录刷新失败: ${r?.body?.message || r?.body?.code}`);
    return r.cookie ? r.cookie.join('; ') : cookie;
  }

  /** 读取歌单详情 */
  async playlistDetail(cookie) {
    return this.call('playlist_detail', { id: this._cfg.playlist_id, cookie, n: '200' }, { label: 'playlist_detail' });
  }

  /** 批量操作曲目（添加/删除） */
  async tracksOp(cookie, ids, op) {
    return this.call('playlist_tracks', { pid: this._cfg.playlist_id, tracks: ids.join(','), op, cookie },
      { retries: 3, label: `tracks_${op}` });
  }
}

// ============================================================================
// 选歌引擎
// ============================================================================
class SongPicker {
  constructor(pool, cfg, state) {
    this._pool = pool;        // Map<id, {name, artist, style}>
    this._ids  = [...pool.keys()];
    this._cfg  = cfg;
    this._state = state;
  }

  /** 生成当日确定性随机选歌 */
  pick(heard = new Set()) {
    // 规则：排除已听过 → 排除近7天推荐过的 → 不足时放宽限制
    const dateSeed = new Date().toISOString().slice(0, 10);
    const seed = parseInt(dateSeed.replace(/-/g, ''), 10);
    const recent = this._state.recentIds(7);

    let candidates = this._ids.filter(id => !heard.has(id) && !recent.has(id));
    if (candidates.length < this._cfg.pick_count) {
      // 放宽：仅排除已听过
      candidates = this._ids.filter(id => !heard.has(id));
    }
    if (candidates.length < this._cfg.pick_count) {
      // 全量
      candidates = [...this._ids];
    }

    // 确定性 shuffle
    const shuffled = this._shuffle(candidates, seed);
    return shuffled.slice(0, this._cfg.pick_count);
  }

  _shuffle(arr, seed) {
    let s = seed;
    const rng = () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
    const a = [...arr];
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  /** 从曲库补齐到目标数（排除已选） */
  fill(added, target, heard = new Set()) {
    const dateSeed = new Date().toISOString().slice(0, 10);
    const seed = parseInt(dateSeed.replace(/-/g, ''), 10);
    const pool = this._ids.filter(id => !added.has(id));
    const shuffled = this._shuffle(pool, seed + 999);
    return shuffled.slice(0, target - added.size);
  }

  /** 获取歌曲显示名 */
  name(id) { const s = this._pool.get(id); return s ? `${s.name} — ${s.artist}` : String(id); }
}

// ============================================================================
// 推送模块（Bark + Server酱）
// ============================================================================
async function pushAll(cfg, log, songs, stats) {
  const title = '🎵 今日推荐已更新';
  const preview = songs.slice(0, 10).map(s => `• ${s}`).join('\n');
  const footer = `\n...共${songs.length}首 | 已听过 ${stats.heardInPool}/${stats.poolSize} | 耗时 ${stats.elapsed}s`;
  const text = preview + footer;

  const results = await Promise.all([
    pushBark(cfg.bark_key, title, text, log),
    pushServerChan(cfg.serverChan_key, title, text, log),
  ]);
  const ok = results.filter(Boolean).length;
  if (results.length > 0) log.info(`推送完成: ${ok}/${results.length} 成功`);
}

async function pushBark(key, title, text, log) {
  if (!key) return false;
  return new Promise(resolve => {
    const req = https.get(
      `https://api.day.app/${encodeURIComponent(key)}/${encodeURIComponent(title)}/${encodeURIComponent(text)}?group=每日推荐&sound=default`,
      res => { let d = ''; res.on('data', c => d += c); res.on('end', () => { const ok = d.includes('"code":200'); log[ok ? 'ok' : 'warn'](`Bark: ${ok ? '✓' : d.slice(0,60)}`); resolve(ok); }); }
    );
    req.on('error', e => { log.warn(`Bark 失败: ${e.message}`); resolve(false); });
    req.setTimeout(10000, () => { req.destroy(); log.warn('Bark 超时'); resolve(false); });
  });
}

async function pushServerChan(key, title, text, log) {
  if (!key) return false;
  return new Promise(resolve => {
    const body = `title=${encodeURIComponent(title)}&desp=${encodeURIComponent(text)}`;
    const req = https.request(`https://sctapi.ftqq.com/${encodeURIComponent(key)}.send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'Content-Length': Buffer.byteLength(body) },
    }, res => {
      let d = ''; res.on('data', c => d += c); res.on('end', () => {
        try {
          const j = JSON.parse(d);
          const ok = j.code === 0 || j.errno === 0;
          log[ok ? 'ok' : 'warn'](`Server酱: ${ok ? '✓' : j.message || j.errmsg || d.slice(0,60)}`);
          resolve(ok);
        } catch { log.warn(`Server酱 响应异常: ${d.slice(0,60)}`); resolve(false); }
      });
    });
    req.on('error', e => { log.warn(`Server酱 失败: ${e.message}`); resolve(false); });
    req.setTimeout(10000, () => { req.destroy(); log.warn('Server酱 超时'); resolve(false); });
    req.write(body);
    req.end();
  });
}

// ============================================================================
// 工具
// ============================================================================
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ============================================================================
// 主流程
// ============================================================================
async function main() {
  const startTime = Date.now();
  const isDryRun = process.argv.includes('--dry-run');
  const useLogFile = process.argv.includes('--log-file');
  const log = new Logger(useLogFile);

  if (isDryRun) log.info('🏁 DRY RUN 模式 — 不会修改歌单');

  // 1. 加载并校验配置
  log.step('加载配置');
  const cfg = loadConfig();
  const poolMap = new Map(cfg.pool.map(s => [s.id, s]));
  log.info(`歌单: ${cfg.playlist_id} | 目标: ${cfg.pick_count}首 | 曲库: ${cfg.pool.length}首`);

  // 2. 加载 API
  log.step('加载 API');
  const api = new ApiClient(log, cfg);

  // 3. 提取 Cookie
  log.step('提取 Cookie');
  const rawCookie = extractCookie(log);
  log.ok('Cookie 提取成功');

  // 4. 刷新登录
  log.step('刷新登录');
  let cookie;
  try {
    cookie = await api.refresh(rawCookie);
    log.ok('登录刷新成功');
  } catch (e) {
    log.error(`登录失败: ${e.message}`);
    process.exit(EXIT.LOGIN_ERR);
  }

  // 5. 分析口味
  log.step('分析口味');
  const heard = new Set();
  try {
    const playlists = await api.call('user_playlist', { uid: cfg.user_id, limit: 30, cookie },
      { retries: 2, label: 'user_playlist' });
    for (const pl of (playlists?.body?.playlist || [])) {
      if (String(pl.id) === cfg.playlist_id) continue;
      try {
        const detail = await api.call('playlist_detail', { id: pl.id, cookie, n: '200' },
          { retries: 1, label: `pl_detail:${pl.id}` });
        for (const t of (detail?.body?.playlist?.tracks || [])) { if (t.id) heard.add(t.id); }
      } catch {}
    }
    const records = await api.call('user_record', { uid: cfg.user_id, type: 0, limit: 100, cookie },
      { retries: 2, label: 'user_record' });
    for (const item of (records?.body?.allData || [])) { if (item.song?.id) heard.add(item.song.id); }
    // 当前歌单已有的歌
    const current = await api.playlistDetail(cookie);
    for (const t of (current?.body?.playlist?.tracks || [])) { if (t.id) heard.add(t.id); }
  } catch (e) {
    log.warn(`口味分析异常，降级为纯随机: ${e.message.slice(0,80)}`);
  }
  const heardInPool = cfg.pool.filter(s => heard.has(s.id)).length;
  log.info(`曲库中已听过 ${heardInPool}/${cfg.pool.length} 首`);

  // 6. 选歌
  log.step('选歌');
  const state = new StateStore();
  if (state.todayDone && !isDryRun) {
    log.warn('今日已执行过，跳过（使用 --dry-run 预览）');
  }
  const picker = new SongPicker(poolMap, cfg, state);
  const picks = picker.pick(heard);
  const songNames = picks.map(id => picker.name(id));
  log.info(`选定 ${picks.length} 首:`);
  songNames.forEach((n, i) => console.log(`  ${i+1}. ${n}`));

  if (isDryRun) {
    log.ok('DRY RUN — 未修改任何内容');
    const elapsed = Math.round((Date.now() - startTime) / 1000);
    await pushAll(cfg, log, songNames, { heardInPool, poolSize: cfg.pool.length, elapsed });
    process.exit(EXIT.OK);
  }

  // 7. 删除旧歌
  log.step('删除旧歌');
  let oldIds = [];
  try {
    const detail = await api.playlistDetail(cookie);
    oldIds = (detail?.body?.playlist?.tracks || []).map(t => t.id);
    if (oldIds.length > 0) {
      log.info(`待删除: ${oldIds.length} 首`);
      for (let i = 0; i < oldIds.length; i += 10) {
        const batch = oldIds.slice(i, i + 10);
        await sleep(1200);
        const r = await api.tracksOp(cookie, batch, 'del');
        if (TRACK_OK(r)) log.ok(`删除批次 ${i/10+1}/${Math.ceil(oldIds.length/10)}`);
        else log.warn(`删除批次 ${i/10+1} 返回: ${r?.body?.body?.code || r?.body?.code}`);
      }
    } else { log.info('歌单为空，跳过删除'); }
  } catch (e) {
    log.error(`删除失败: ${e.message.slice(0,80)}`);
  }

  // 8. 添加新歌
  log.step('添加新歌');
  const added = new Set();
  const remaining = [...picks];

  while (remaining.length > 0) {
    const batch = remaining.splice(0, 10);
    await sleep(1200);
    try {
      const r = await api.tracksOp(cookie, batch, 'add');
      if (TRACK_OK(r)) {
        batch.forEach(id => added.add(id));
        log.ok(`+${batch.length} (${added.size}/${cfg.pick_count})`);
      } else {
        // 逐首重试
        for (const id of batch) {
          await sleep(1000);
          try {
            const r2 = await api.tracksOp(cookie, [id], 'add');
            if (TRACK_OK(r2)) { added.add(id); }
          } catch {}
        }
        log.info(`批次部分成功: ${added.size}/${cfg.pick_count}`);
      }
    } catch {
      // catch 降级逐首
      for (const id of batch) {
        await sleep(1000);
        try {
          const r2 = await api.tracksOp(cookie, [id], 'add');
          if (TRACK_OK(r2)) added.add(id);
        } catch {}
      }
    }
  }

  // 9. 补齐不足
  if (added.size < cfg.pick_count) {
    const need = cfg.pick_count - added.size;
    log.step(`补齐: 不足${need}首`);
    const fill = picker.fill(added, cfg.pick_count, heard);
    for (let i = 0; i < fill.length; i += 10) {
      const batch = fill.slice(i, i + 10);
      await sleep(1200);
      try {
        const r = await api.tracksOp(cookie, batch, 'add');
        if (TRACK_OK(r)) batch.forEach(id => added.add(id));
      } catch {}
    }
    // 补充歌曲名到显示列表
    fill.forEach(id => {
      if (!songNames.includes(picker.name(id))) songNames.push(picker.name(id));
    });
    log.info(`补齐后 ${added.size} 首`);
  }

  // 10. 验证
  log.step('验证');
  await sleep(2000);
  let finalCount = 0;
  try {
    const detail = await api.playlistDetail(cookie);
    finalCount = detail?.body?.playlist?.trackCount || 0;
    const actualTracks = (detail?.body?.playlist?.tracks || []).slice(0, 5);
    log.info(`歌单最终: ${finalCount} 首`);
    actualTracks.forEach(t => console.log(`  ${t.name} — ${(t.ar||[]).map(a=>a.name).join('/')}`));
  } catch (e) {
    log.error(`验证失败: ${e.message.slice(0,80)}`);
  }

  // 11. 持久化状态
  state.save(picks.map(id => picker.name(id)), finalCount >= cfg.pick_count);

  // 12. 推送
  const elapsed = Math.round((Date.now() - startTime) / 1000);
  await pushAll(cfg, log, songNames, { heardInPool, poolSize: cfg.pool.length, elapsed });

  // 13. 完成
  const status = finalCount >= cfg.pick_count ? '✓ 完全成功' :
                 finalCount > 0 ? '⚠️ 部分成功' : '✗ 失败';
  const exitCode = finalCount >= cfg.pick_count ? EXIT.OK :
                   finalCount > 0 ? EXIT.PARTIAL : EXIT.FAIL;
  log.info(`\n🏁 ${status} | 耗时 ${elapsed}s | 歌单 ${finalCount}/${cfg.pick_count} 首`);
  log.close();
  process.exit(exitCode);
}

// ============================================================================
// 启动
// ============================================================================
main().catch(e => {
  console.error('💥 未捕获异常:', e.message);
  process.exit(EXIT.FAIL);
});
