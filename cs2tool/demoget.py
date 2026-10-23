"""CS2 demo 直下：分享码 → Valve demo CDN（纯标准库，不依赖 CS2 客户端）

本模块把「拿到一场比赛的 .dem demo 文件」这件事拆成四步，全部只用 Python 标准库
（urllib / bz2 / os / time / concurrent.futures / threading）完成：

1. 解分享码：CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx 这类分享码，本质是把
   (matchId, reservationId, tvPort) 三个整数编码进 57 进制的字符串。解码算法是纯
   数学运算，不需要登录 Steam、不需要任何网络请求，本地即可算出比赛标识。
   （算法源自 akiver/csgo-sharecode，MIT 许可）
2. 拼文件名：demo 在 CDN 上的文件名主体固定为 "<matchId:021d>_<reservationId>"，
   扩展名是 .dem.bz2。
3. 找分片：Valve 的 demo CDN 由 replay1.valve.net … replay500.valve.net 多个镜像
   组成，同一个文件会同时存在于其中少数几个分片上。对每个分片发一个 HEAD 请求，
   状态码 200 即命中。这里必须用 http://（Valve 这些 CDN 节点对现代 TLS 握手会
   失败），请求头带一个普通 User-Agent 就够，不需要认证或 cookie。
   分片不是随机撒的：按地区/CDN 池分配，同一网络环境下往往固定那几个，所以
   find_url 支持「缓存优先」——先用上次命中的分片，不到 1 秒就能定位；缓存全部
   失效时才回退到并发扫描 replay1-200，仍失败再扫 replay201-500。
4. 下载 + 解压：CDN 支持 Range 断点续传（返回 206），所以大文件可以分次续传；
   下载得到的是 bz2 压缩包，流式解压成 .dem 即可。

为什么能绕开 CS2 客户端：分享码在本地可解，而 demo 本身就是 Valve CDN 上的公开
静态文件（GET 即可，无鉴权）。客户端做的事情只是「解码 + 拼文件名 + 挑分片 +
下载 + 解压」，这些在本模块里全部复现。

典型用法::

    from cs2tool.demoget import download_one
    r = download_one('CSGO-RhCA2-GQbyi-RwMfm-XahGp-MsdVG',
                     demo_dir='data/demos', tmp_dir='data/tmp',
                     log=print)
    if r['ok']:
        print(r['demo_path'], r['bytes_unpacked'])
    else:
        print('失败：', r['error'])
"""

from __future__ import annotations

import bz2
import http.client
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

__all__ = [
    'DICT',
    'decode_share_code',
    'make_body',
    'parse_body',
    'find_url',
    'download',
    'unpack_bz2',
    'download_one',
]

# 57 个字符的字典：去掉了容易看错的 I、l、o、0、1
DICT = 'ABCDEFGHJKLMNOPQRSTUVWXYZabcdefhijkmnopqrstuvwxyz23456789'

_SHARE_PREFIX = 'CSGO'          # 分享码固定前缀
_SHARE_BODY_LEN = 25            # 去掉前缀与连字符后的字符数
_SHARE_BASE = 57                # 进制
_SHARE_BYTES = 18               # 分享码承载的整数字节数（8 + 8 + 2）
_SHARE_MAX = 1 << (_SHARE_BYTES * 8)   # 18 字节能表示的上界，超出即视为损坏

_CDN_HOST = 'replay{n}.valve.net'   # 分片主机名模板
_CDN_APP = '730'                    # CS2 的 appid
_USER_AGENT = 'Mozilla/5.0'         # 带个普通 UA 即可，无需认证
_DEFAULT_SLOTS = range(1, 201)      # 默认扫描 replay1 … replay200
_FALLBACK_SLOTS = range(201, 501)   # 主区间全失败后的扩大范围（覆盖 replay403 这类）

_READ_CHUNK = 262144                # 默认每块 256 KB
_PROGRESS_BYTES = 512 * 1024        # 进度回调的字节节流阈值
_PROGRESS_SECONDS = 0.5             # 进度回调的时间节流阈值

# 需要重试的「网络类」异常（这些都是标准库里的类型）
_NET_ERRORS = (
    urllib.error.URLError,
    socket.timeout,
    TimeoutError,
    ConnectionResetError,
    http.client.IncompleteRead,
    http.client.HTTPException,
    OSError,
)


class _ShortRead(Exception):
    """读完后字节数与 Content-Length 不符，按网络异常处理并重试。"""


# --------------------------------------------------------------------------
# 分享码编解码
# --------------------------------------------------------------------------

def decode_share_code(code):
    """把分享码解成 (matchId, prevMatchId, outcomeIdLow16)。

    18 字节的真实布局（2026-10-24 用两组「分享码 ↔ 下载链接」实测确认）：

        b[0:8]   小端 = 上一场比赛的 matchId（链式结构，用来往后推进）
        b[8:16]  小端 = 本场 matchId           ← demo 文件名前半
        b[16:18] 小端 = 文件名后半的低 16 位   ← ⚠ 只有低 16 位

    实测对照::

        CSGO-peXk7-… → b[8:16]=3849944656909435518
                        实际文件名 003849944656909435518_1163610824
        CSGO-hXtJm-… → b[8:16]=3849940076326813921
                        实际文件名 003849940076326813921_0395798432

    文件名后半（outcomeId，32 位）只存了低 16 位，高位不在分享码里 ——
    所以**光凭分享码拼不出可下载的地址**，那一段只能从比赛历史页取。
    这里保留解码能力，用于识别"这场是哪场"，不要用它读拼 URL。
    """
    if not isinstance(code, str):
        raise ValueError('分享码必须是字符串')

    raw = code.strip()
    if not raw:
        raise ValueError('分享码为空')
    if raw[:len(_SHARE_PREFIX)].upper() != _SHARE_PREFIX:
        raise ValueError('分享码必须以 "CSGO" 开头，例如 CSGO-RhCA2-GQbyi-RwMfm-XahGp-MsdVG')

    # 前缀之后的部分保留原始大小写（字典里有大写也有小写），只去掉连字符
    body = raw[len(_SHARE_PREFIX):].replace('-', '').strip()
    if len(body) != _SHARE_BODY_LEN:
        raise ValueError(
            '分享码去掉前缀与连字符后应为 %d 个字符，实际为 %d 个：%r'
            % (_SHARE_BODY_LEN, len(body), body)
        )

    # 57 进制累加：最低位在前，所以遍历反序后的字符
    big = 0
    for ch in reversed(body):
        idx = DICT.find(ch)
        if idx < 0:
            raise ValueError(
                '分享码含非法字符 %r：合法字符集不含 I、l、o、0、1' % ch
            )
        big = big * _SHARE_BASE + idx

    if big >= _SHARE_MAX:
        raise ValueError('分享码数值超出 18 字节范围，分享码可能已损坏')

    buf = big.to_bytes(_SHARE_BYTES, 'big')
    prev_match_id = int.from_bytes(buf[0:8], 'little')
    match_id = int.from_bytes(buf[8:16], 'little')
    tail16 = int.from_bytes(buf[16:18], 'little')
    return match_id, prev_match_id, tail16


def make_body(match_id, reservation_id):
    """拼出 demo 文件名主体：``<matchId 左补零到 21 位>_<reservationId>``。"""
    try:
        match_id = int(match_id)
        reservation_id = int(reservation_id)
    except (TypeError, ValueError):
        raise ValueError('matchId 与 reservationId 必须是整数')
    if match_id < 0 or reservation_id < 0:
        raise ValueError('matchId 与 reservationId 不能为负数')
    return '%021d_%d' % (match_id, reservation_id)


def parse_body(body):
    """从文件名主体反解出 (matchId, reservationId)，用于调试与自检。"""
    if not isinstance(body, str):
        raise ValueError('文件名主体必须是字符串')
    text = body.strip()
    # 兼容误传完整文件名的情况
    for suffix in ('.dem.bz2', '.dem'):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
            break
    parts = text.split('_')
    if len(parts) != 2 or not all(p.isascii() and p.isdigit() for p in parts):
        raise ValueError(
            '文件名主体格式应为 <matchId>_<reservationId>，实际为 %r' % (body,)
        )
    return int(parts[0]), int(parts[1])


# --------------------------------------------------------------------------
# CDN 分片探测
# --------------------------------------------------------------------------

def _demo_url(body, slot):
    """拼出某个分片上的完整下载地址（固定 http://，https 会握手失败）。"""
    return 'http://' + _CDN_HOST.format(n=slot) + '/%s/%s.dem.bz2' % (_CDN_APP, body)


def _probe(body, slot, timeout):
    """对单个分片发 HEAD，200 视为命中。任何异常都当作未命中。"""
    req = urllib.request.Request(
        _demo_url(body, slot), method='HEAD', headers={'User-Agent': _USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, 'status', None) or resp.getcode()
            return int(status) == 200
    except Exception:
        return False


def find_url(body, ranges=None, workers=24, timeout=8, log=None,
             known_hosts=None, cache_path=None, exclude=None):
    """查找可用分片，返回第一个能用的完整 URL；全部未命中返回 None。

    查找顺序（命中即停）：

    1. ``known_hosts``（缓存下来的分片号，串行 HEAD，通常只有 1~3 个）；
    2. ``ranges`` 指定的范围（默认 range(1, 201)）；
    3. 主范围全部失败后，再扫 range(201, 501)，覆盖 replay403 这类偏远分片。

    命中会把该分片号提到 ``known_hosts`` 最前（去重、最多保留 12 个），
    若给了 ``cache_path`` 则把列表写进该 JSON 文件，下次可直接走缓存。

    分片号不是随机撒的：同一网络/地区环境往往固定用那少数几个池子里的节点，
    所以缓存优先能把 200 次 HEAD 缩成 1~3 次。

    ``exclude`` 里的分片号会被跳过（换源重试时用来避开刚失效的节点）。
    """
    body = str(body).strip()
    if not body:
        raise ValueError('demo 文件名主体不能为空')

    # 1) 先试缓存分片（串行即可，数量很少）
    excluded = set(_normalise_hosts(exclude))
    cached = [n for n in _normalise_hosts(known_hosts) if n not in excluded]
    if not cached and cache_path:
        cached = [n for n in _load_hosts(cache_path) if n not in excluded]
        if cached and log:
            log('从缓存文件读取到分片：%s' % _fmt_hosts(cached))

    hit_slot = None
    if cached:
        if log:
            log('先试缓存分片 %s …' % _fmt_hosts(cached))
        for slot in cached:
            if _probe(body, slot, timeout):
                hit_slot = slot
                if log:
                    log('用缓存分片 replay%d 命中' % slot)
                break
        if hit_slot is None and log:
            log('缓存分片全部失效，转为扫描')

    # 2) 逐段扫描；显式传了 ranges 就只扫那一段
    scanned = []
    if hit_slot is None:
        stages = [list(ranges) if ranges is not None else list(_DEFAULT_SLOTS)]
        if ranges is None:
            stages.append(list(_FALLBACK_SLOTS))
        for index, slots in enumerate(stages):
            if excluded:
                slots = [n for n in slots if n not in excluded]
            if not slots:
                continue
            if log:
                if index == 0:
                    log('缓存未命中，开始扫描 replay%d-replay%d 共 %d 个分片'
                        '（%d 线程，单位超时 %ss）…'
                        % (slots[0], slots[-1], len(slots), workers, timeout))
                else:
                    log('前 %d 个分片都没命中，扩大范围扫描 replay%d-replay%d'
                        ' 共 %d 个分片…'
                        % (len(stages[0]), slots[0], slots[-1], len(slots)))
            hit_slot = _scan_slots(body, slots, workers, timeout)
            scanned.append('replay%d-replay%d' % (slots[0], slots[-1]))
            if hit_slot is not None:
                if log:
                    log('命中分片 replay%d' % hit_slot)
                break

    if hit_slot is None:
        if log:
            if scanned:
                log('未找到可用分片（已扫 %s）' % '、'.join(scanned))
            else:
                log('未找到可用分片')
        return None

    # 3) 命中后回写缓存：命中的排最前，去重，最多 12 个
    updated = _normalise_hosts([hit_slot] + cached)
    updated = updated[:12]
    _remember_hosts(known_hosts, updated)
    if cache_path:
        _save_hosts(cache_path, updated)
        if log:
            log('已缓存分片到 %s：%s' % (cache_path, _fmt_hosts(updated)))
    else:
        if log:
            log('本次可用分片顺序：%s' % _fmt_hosts(updated))

    return _demo_url(body, hit_slot)


def _normalise_hosts(hosts):
    """把 ['replay141', 142, '403'] 之类的输入统一成 [141, 142, 403]（去重保序）。"""
    if not hosts:
        return []
    result = []
    for item in hosts:
        slot = _host_number(item)
        if slot is not None and slot not in result:
            result.append(slot)
    return result


def _host_number(item):
    """从分片号或 'replay141' / 'http://replay141.valve.net/...' 里取出数字。"""
    if isinstance(item, bool):
        return None
    if isinstance(item, int):
        return item if item > 0 else None
    text = str(item).strip()
    digits = ''.join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    slot = int(digits)
    return slot if slot > 0 else None


def _fmt_hosts(hosts):
    """把分片号列表格式化成 'replay141, replay142' 便于日志阅读。"""
    return ', '.join('replay%d' % n for n in hosts) if hosts else '（空）'


def _host_from_url(url):
    """从 http://replay141.valve.net/730/xxx.dem.bz2 里取出分片号 141。"""
    if not url:
        return None
    match = re.search(r'replay(\d+)\.', str(url))
    return int(match.group(1)) if match else None


def _drop_host(hosts, slot):
    """若 hosts 是可变的 list，就把某个失效分片从里面剔除（其余顺序不变）。"""
    if isinstance(hosts, list) and slot is not None:
        hosts[:] = [n for n in hosts if _host_number(n) != slot]


def _forget_host(cache_path, slot):
    """把某个失效分片从 JSON 缓存里剔除，避免下次还优先用它。"""
    if not cache_path or slot is None:
        return
    hosts = _load_hosts(cache_path)
    if slot not in hosts:
        return
    _save_hosts(cache_path, [n for n in hosts if n != slot])


def _load_hosts(cache_path):
    """从 JSON 缓存文件读分片号，文件不存在或格式不对时返回空列表。"""
    try:
        with open(str(cache_path), 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get('hosts')
    return _normalise_hosts(data)


def _save_hosts(cache_path, hosts):
    """把分片号列表写进 JSON 缓存文件；写失败不影响主流程。"""
    try:
        path = str(cache_path)
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'hosts': list(hosts)}, fh, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def _remember_hosts(target, hosts):
    """若调用方传进来的是一个 list，就地把内容改成最新的分片顺序。"""
    if isinstance(target, list):
        target[:] = list(hosts)


def _scan_slots(body, slots, workers, timeout):
    """并发扫一段分片，返回第一个命中的分片号；全失败返回 None。"""
    hit = None
    pool = ThreadPoolExecutor(max_workers=max(1, min(int(workers), len(slots))))
    try:
        futures = {pool.submit(_probe, body, n, timeout): n for n in slots}
        for fut in as_completed(futures):
            slot = futures[fut]
            try:
                ok = fut.result()
            except Exception:
                ok = False
            if ok:
                hit = slot
                break
    finally:
        # 已命中的话不必等剩下的分片扫完
        pool.shutdown(wait=False, cancel_futures=True)
    return hit


# --------------------------------------------------------------------------
# 下载（支持断点续传）
# --------------------------------------------------------------------------

def _fmt_size(n):
    """把字节数格式化成人类可读的字符串，None 或负数返回「未知」。"""
    if n is None or n < 0:
        return '未知'
    value = float(n)
    for unit in ('B', 'KB', 'MB'):
        if value < 1024:
            if unit == 'B':
                return '%d B' % int(value)
            return '%.1f %s' % (value, unit)
        value /= 1024.0
    return '%.1f GB' % value


def _file_size(path):
    """返回文件大小，文件不存在返回 0。"""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _remote_total(url, timeout):
    """用 HEAD 拿远端总字节数；拿不到返回 None（此时不做完整性校验）。"""
    req = urllib.request.Request(
        url, method='HEAD', headers={'User-Agent': _USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.headers.get('Content-Length')
            if text and text.strip().isdigit():
                return int(text.strip())
    except Exception:
        return None
    return None


def _parse_content_range_total(text):
    """从 ``bytes 100-189/190190048`` 里取出总长度。"""
    if not text:
        return None
    _, _, tail = text.partition('/')
    tail = tail.strip()
    if tail.isdigit():
        return int(tail)
    return None


def _fetch_once(url, part_path, total, timeout, log, progress, chunk):
    """单次下载尝试：按已有大小续传，返回 (最终大小, 远端总大小)。"""
    have = _file_size(part_path)
    headers = {'User-Agent': _USER_AGENT}
    if have > 0:
        headers['Range'] = 'bytes=%d-' % have

    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        # 416 说明本地文件已经不小于远端大小，交由上层校验
        if exc.code == 416 and total is not None and have >= total:
            if log:
                log('本地已有 %.1f%% 数据，无需续传' % (100.0 * have / total))
            return have, total
        raise

    with resp:
        status = int(getattr(resp, 'status', None) or resp.getcode())
        mode = 'ab'
        if status == 206:
            if log:
                log('服务端支持续传（206），从 %s 继续' % _fmt_size(have))
            parsed = _parse_content_range_total(resp.headers.get('Content-Range'))
            if parsed:
                total = parsed
        elif have > 0:
            # 服务端忽略了 Range（200），只能清空重下
            if log:
                log('该分片不支持续传，从头下载（本地 %s 已清空）' % _fmt_size(have))
            have = 0
            mode = 'wb'
        else:
            mode = 'wb'

        if total is None:
            text = resp.headers.get('Content-Length')
            if text and text.strip().isdigit():
                total = have + int(text.strip())

        done = have
        last_report_bytes = done
        last_report_time = time.monotonic()
        with open(part_path, mode) as fh:
            while True:
                block = resp.read(chunk)
                if not block:
                    break
                fh.write(block)
                done += len(block)
                now = time.monotonic()
                # 节流：每 ~512 KB 或每 ~0.5 秒回调一次
                if progress and (done - last_report_bytes >= _PROGRESS_BYTES
                                 or now - last_report_time >= _PROGRESS_SECONDS):
                    last_report_bytes = done
                    last_report_time = now
                    progress(done, -1 if total is None else total)

        if progress:
            progress(done, -1 if total is None else total)

        if total is not None and done != total:
            raise _ShortRead(
                '字节数不符：已读 %d，应为 %d' % (done, total)
            )
        return done, total


def download(url, part_path, timeout=60, log=None, progress=None,
             chunk=_READ_CHUNK, max_retries=5):
    """断点续传到 ``part_path``，返回 (本地大小, 远端总大小)；总大小未知时为 -1。

    已有 part 文件时用 ``Range: bytes=<已有大小>-`` 续传：206 追加写，200 清空重写。
    网络异常最多重试 max_retries 次，每次重试前 sleep 1~3 秒并从当前已有大小续上。
    全部失败抛 RuntimeError，消息里带最后一次异常类型和已完成字节数。
    """
    part_path = str(part_path)
    parent = os.path.dirname(os.path.abspath(part_path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    total = _remote_total(url, timeout)
    if log:
        log('远端大小：%s' % _fmt_size(total))
    have = _file_size(part_path)
    if total is not None and have > total:
        # 本地残留比远端还大，说明不是同一份数据，直接清空重下
        if log:
            log('本地临时文件 %s 大于远端 %s，判定为无效残留，清空重下'
                % (_fmt_size(have), _fmt_size(total)))
        try:
            os.remove(part_path)
        except OSError:
            pass
    elif have and log:
        log('发现未完成的临时文件：%s，将尝试续传' % _fmt_size(have))

    last_exc = None
    for attempt in range(max(0, int(max_retries)) + 1):
        if attempt:
            wait = min(3.0, 1.0 + attempt)
            if log:
                log('第 %d 次重试（等待 %.1f 秒，从 %s 处续传）…'
                    % (attempt, wait, _fmt_size(_file_size(part_path))))
            time.sleep(wait)
        try:
            done, total = _fetch_once(url, part_path, total, timeout, log, progress, chunk)
            return done, -1 if total is None else total
        except urllib.error.HTTPError as exc:
            # 4xx/5xx 属于确定性的服务端应答，重试也没意义，直接失败
            done = _file_size(part_path)
            raise RuntimeError(
                '下载中断：HTTP %s（已完成 %s / %s）'
                % (exc.code, _fmt_size(done), _fmt_size(total))
            ) from exc
        except _NET_ERRORS as exc:
            last_exc = exc
            if log:
                log('下载异常（%s）：%s' % (type(exc).__name__, exc))
            continue

    done = _file_size(part_path)
    raise RuntimeError(
        '下载中断：%s: %s（已完成 %s / %s）'
        % (type(last_exc).__name__ if last_exc else '未知错误',
           last_exc, _fmt_size(done), _fmt_size(total))
    )


# --------------------------------------------------------------------------
# 解压
# --------------------------------------------------------------------------

def unpack_bz2(part_path, out_path, chunk=1024 * 1024):
    """把 .dem.bz2 流式解压成 .dem，返回解压后的字节数（不删源文件）。"""
    part_path = str(part_path)
    out_path = str(out_path)
    if not os.path.isfile(part_path):
        raise FileNotFoundError('待解压文件不存在：%s' % part_path)

    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    written = 0
    with bz2.open(part_path, 'rb') as src, open(out_path, 'wb') as dst:
        while True:
            block = src.read(chunk)
            if not block:
                break
            dst.write(block)
            written += len(block)
    return written


# --------------------------------------------------------------------------
# 一步到位：分享码 / 文件名主体 → 本地 .dem
# --------------------------------------------------------------------------

def download_one(code_or_body, demo_dir, tmp_dir, log=None, progress=None,
                 known_hosts=None, cache_path=None, max_sources=3):
    """完整跑一场：解码 → 找分片 → 续传下载 → 解压 → 清理 part。

    参数既可以是分享码（``CSGO-...``），也可以是已拼好的文件名主体
    （``003849497106284806149_1761859902``）。

    ``known_hosts`` / ``cache_path`` 会透传给 :func:`find_url` 做分片缓存，
    多个任务共用同一个 list 或同一个 JSON 文件即可越用越快。

    分片状态会漂移（同一台机器挂多个 replay 别名，时而 200 时而 404），
    所以 ``download()`` 重试耗尽后会重新 :func:`find_url` 换一个分片接着下，
    最多 ``max_sources`` 轮（默认初次 + 2 次换源）。换源沿用同一个 .part 文件，
    由 ``download()`` 用 Range 从已有字节数续传；新分片不支持续传则从头下。
    Content-Length 拿不到时不做总大小校验，按流读完正常结束判定完成。

    任何异常都不会向外抛，全部收敛进返回 dict 的 ``error`` 字段，方便后台线程调用。
    返回 dict 字段：ok / body / url / bytes_downloaded / bytes_unpacked /
    demo_path / error。
    """
    result = {
        'ok': False,
        'body': '',
        'url': None,
        'bytes_downloaded': 0,
        'bytes_unpacked': 0,
        'demo_path': None,
        'error': None,
    }

    part_path = None
    given_url = None
    try:
        text = '' if code_or_body is None else str(code_or_body).strip()
        if not text:
            raise ValueError('分享码或文件名主体为空')

        if text.lower().startswith(('http://', 'https://')):
            # 页面里复制来的完整链接：直接用，不用扫分片
            m = re.search(r'/730/(\d+_\d+)\.dem\.bz2', text)
            if not m:
                raise ValueError('链接里找不到 <matchid>_<outcomeid>.dem.bz2：%s' % text)
            body = m.group(1)
            match_id, reservation_id = parse_body(body)
            given_url = text
        elif text[:len(_SHARE_PREFIX)].upper() == _SHARE_PREFIX:
            match_id, _prev, _tail = decode_share_code(text)
            raise ValueError(
                '分享码只能定位比赛（matchId=%d），文件名后半段的完整值（outcomeId）'
                '不在分享码里，拼不出下载地址。请在比赛历史页复制该场的 demo 链接粘进来。'
                % match_id)
        else:
            match_id, reservation_id = parse_body(text)
            body = make_body(match_id, reservation_id)
        result['body'] = body

        if log:
            log('比赛标识：matchId=%d reservationId=%d' % (match_id, reservation_id))
            log('文件名主体：%s.dem.bz2' % body)

        os.makedirs(str(demo_dir), exist_ok=True)
        os.makedirs(str(tmp_dir), exist_ok=True)

        part_path = os.path.join(str(tmp_dir), body + '.dem.bz2.part')
        out_path = os.path.join(str(demo_dir), body + '.dem')

        # 分片会漂移（几分钟前 200、刚才 404），所以下载失败要能换源再试。
        # 轮数 = 初次 URL + 最多 (max_sources - 1) 次换源，默认共 3 轮。
        failed_hosts = []
        last_error = None
        done = 0
        for round_index in range(max(1, int(max_sources))):
            if round_index == 0 and given_url:
                url = given_url
                if log:
                    log('用页面给的链接直接下：%s' % url)
            else:
                url = find_url(body, log=log, known_hosts=known_hosts,
                               cache_path=cache_path, exclude=failed_hosts)
            if not url:
                if last_error:
                    result['error'] = (
                        '%s；已无其他可用分片可换（试过 %s）'
                        % (last_error, _fmt_hosts(failed_hosts))
                    )
                else:
                    result['error'] = '找不到可用的 CDN 分片（已扫 replay1-500）'
                return result
            result['url'] = url

            if round_index > 0 and log and failed_hosts:
                log('replay%d 失效，换 replay%d 继续（已下载 %s）'
                    % (failed_hosts[-1], _host_from_url(url) or 0,
                       _fmt_size(_file_size(part_path))))

            try:
                # 同一个 part 文件：download 内部会用 Range 从已有字节数续上
                done, _total = download(url, part_path, log=log, progress=progress)
                result['bytes_downloaded'] = done
                break
            except RuntimeError as exc:
                last_error = str(exc)
                done = _file_size(part_path)
                result['bytes_downloaded'] = done
                bad = _host_from_url(url)
                if bad is not None:
                    failed_hosts.append(bad)
                    # 失效分片从缓存里剔除/降级，避免下次还优先用它
                    _drop_host(known_hosts, bad)
                    _forget_host(cache_path, bad)
                if log:
                    log('replay%s 下载失败（%s），已下载 %s，准备换源…'
                        % (bad if bad is not None else '?', last_error,
                           _fmt_size(done)))
        else:
            result['error'] = (
                '下载中断：已换 %d 个分片仍失败（已完成 %s）；最后一次：%s'
                % (max(0, len(failed_hosts) - 1), _fmt_size(done), last_error)
            )
            return result

        if log:
            log('下载完成：%s，开始解压…' % _fmt_size(done))
        unpacked = unpack_bz2(part_path, out_path)
        result['bytes_unpacked'] = unpacked
        result['demo_path'] = out_path
        result['ok'] = True

        # 解压确认成功后才删 part，失败时保留以便续传
        try:
            os.remove(part_path)
        except OSError:
            pass

        if log:
            log('完成：%s（解压后 %s）' % (out_path, _fmt_size(unpacked)))
        return result

    except Exception as exc:  # 后台线程调用方不应该看到异常
        result['error'] = str(exc) or type(exc).__name__
        if part_path:
            result['bytes_downloaded'] = _file_size(part_path)
        if log:
            log('失败：%s' % result['error'])
        return result
