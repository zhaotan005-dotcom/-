

import re
import sys
import time
import json
import html
import urllib.error
import urllib.parse
import urllib.request

# 安卓上有时SSL证书报错, 直接放开校验
try:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

UA = (u"Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      u"(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")


# ================= 工具 =================

def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return u""


def getf(m, *names):
    for n in names:
        v = m.get(n)
        if v:
            return v
    return u""


def normalize_gmail(addr):
    addr = addr.strip().lower()
    if u"@" not in addr:
        raise ValueError(u"邮箱格式不对: " + addr)
    local, _, domain = addr.rpartition(u"@")
    local = local.split(u"+", 1)[0]
    if domain in (u"gmail.com", u"googlemail.com"):
        local = local.replace(u".", u"")
        domain = u"gmail.com"
    return local + u"@" + domain


def clean_kw(kw):
    out = []
    for p in (kw or u"").lower().split():
        p = re.sub(r"^https?://", u"", p)
        p = re.sub(r"^www\.", u"", p)
        p = p.split(u"/", 1)[0].split(u"?", 1)[0].split(u":", 1)[0]
        if p:
            out.append(p)
    return u" ".join(out)


def find_code(text):
    if not text:
        return u""
    m = re.search(u"(?i)(?:code|otp|passcode|验证码|驗證碼|認證碼)"
                  u".{0,30}?(?=[0-9A-Za-z]*[0-9])([0-9A-Za-z]{4,12})"
                  u"(?![0-9A-Za-z])", text)
    if m:
        return m.group(1)
    m = re.search(r"(?<![0-9])([0-9]{4,8})(?![0-9])", text)
    return m.group(1) if m else u""


def find_link(raw, plain=u""):
    urls = []
    for m in re.finditer(r'(?i)href\s*=\s*["\']([^"\']+)["\']', raw or u""):
        urls.append(html.unescape(m.group(1)).strip())
    if not urls and plain:
        urls = re.findall(r'(?i)https?://[^\s<>"\')\]}]+', plain)

    bad = (u".png", u".jpg", u".jpeg", u".gif", u".css", u".js", u".svg",
           u".ico", u"unsubscribe", u"mailto:", u"facebook.com",
           u"twitter.com", u"instagram.com", u"youtube.com",
           u"google-analytics", u"doubleclick", u"privacy", u"terms")
    urls = [u for u in urls
            if u.lower().startswith(u"http")
            and not any(b in u.lower() for b in bad)]
    if not urls:
        return u""

    keys = (u"verify", u"confirm", u"activate", u"valid", u"regist",
            u"signup", u"sign-up", u"auth", u"token", u"click")
    for u in urls:
        if any(k in u.lower() for k in keys):
            return u
    return urls[0]


def strip_html(s):
    s = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", u" ", s)
    s = re.sub(r"(?s)<[^>]+>", u" ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", u" ", s).strip()


def ts_of(m):
    v = m.get(u"timestamp")
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or u"").strip()
    return float(s) if s.isdigit() else 0.0


def match_kw(m, kw):
    if not kw:
        return True
    hay = (str(getf(m, u"from")) + u" " +
           str(getf(m, u"subject"))).lower()
    return any(p in hay for p in kw.lower().split())


def is_noise(m):
    frm = str(getf(m, u"from")).lower()
    subj = str(getf(m, u"subject")).lower()
    if (u"mailer-daemon" in frm or u"postmaster@" in frm or
            u"mail delivery subsystem" in frm):
        return True
    for k in (u"delivery status notification", u"undelivered mail",
              u"mail delivery failed", u"returned mail",
              u"delayed mail", u"delivery incomplete"):
        if k in subj:
            return True
    return False


# ================= 日志排版 (纯文本版) =================

def stamp():
    return u"[" + time.strftime(u"%H:%M:%S") + u"]"


def fmt_sec(sec):
    sec = int(sec)
    if sec < 60:
        return u"%d秒" % sec
    m, s = divmod(sec, 60)
    if s == 0:
        return u"%d分钟" % m
    return u"%d分%02d秒" % (m, s)


def disp_w(s):
    return sum(2 if ord(c) > 127 else 1 for c in s)


def pad(s, w):
    return s + u" " * max(0, w - disp_w(s))


def short(s, w=44):
    return s if disp_w(s) <= w else s[:w] + u".."


def extract_email(frm):
    """从发件人字符串中提取邮箱地址，如果太长则截断"""
    m = re.search(r'<([^>]+)>', frm)
    if m:
        return m.group(1)
    m = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', frm)
    if m:
        return m.group(1)
    return short(frm, 36)


def box(lines):
    inner = max(disp_w(l) for l in lines)
    bar = u"  +" + u"-" * (inner + 2) + u"+"
    print(bar)
    for l in lines:
        print(u"  | " + pad(l, inner) + u" |")
    print(bar)


def code_banner(code, src=u"", wait_sec=None):
    tail = u"  (" + fmt_sec(wait_sec) + u")" if wait_sec is not None else u""
    rows = [u"验证码  " + code + tail]
    if src:
        rows.append(u"来自: " + extract_email(src))
    box(rows)


def link_banner(url, src=u"", wait_sec=None):
    tail = u"  (" + fmt_sec(wait_sec) + u")" if wait_sec is not None else u""
    rows = [u"验证链接" + tail]
    if src:
        rows.append(u"来自: " + extract_email(src))
    rows.append(short(url, 50))
    box(rows)
    print(u"  " + url)


# ================= emailnator 接口 =================

class Emailnator(object):
    BASE = u"https://www.emailnator.com"
    DOT_COMBOS = [[3], [3, 2], [2], [1, 2, 3, 8]]

    def __init__(self):
        self.opener = urllib.request.build_opener()
        self.opener.addheaders = [(u"User-Agent", UA)]

    def _raw(self, req):
        try:
            return self.opener.open(req, timeout=30).read().decode(u"utf-8", u"replace")
        except urllib.error.HTTPError as e:
            detail = u""
            try:
                detail = e.read().decode(u"utf-8", u"replace")[:120]
            except Exception:
                pass
            raise RuntimeError(u"HTTP " + str(e.code) + u" " + detail)

    def _json(self, req):
        raw = self._raw(req)
        try:
            return json.loads(raw)
        except ValueError:
            raise RuntimeError(u"接口返回异常: " + raw[:80])

    def _post(self, path, payload):
        body = json.dumps(payload).encode(u"utf-8")
        req = urllib.request.Request(
            self.BASE + path, data=body,
            headers={u"Content-Type": u"application/json",
                     u"Accept": u"application/json",
                     u"Referer": self.BASE + u"/",
                     u"Origin": self.BASE})
        return self._json(req)

    def _get(self, path):
        req = urllib.request.Request(
            self.BASE + path,
            headers={u"Accept": u"application/json",
                     u"Referer": self.BASE + u"/"})
        return self._json(req)

    def generate(self):
        last = None
        for ids in self.DOT_COMBOS:
            try:
                res = self._post(u"/api/generate-email", {u"ids": ids})
                if isinstance(res, dict):
                    addr = res.get(u"email")
                    if isinstance(addr, str) and u"@" in addr:
                        return addr
                    last = res.get(u"message") or res.get(u"error") or str(res)[:80]
                else:
                    last = str(res)[:80]
            except Exception as e:
                last = e
        raise RuntimeError(u"生成失败: " + str(last))

    def messages(self, addr):
        res = self._post(u"/api/message-list", {u"email": addr, u"limit": 20})
        if not isinstance(res, dict):
            return []
        if res.get(u"status") not in (None, u"success"):
            raise RuntimeError(str(res.get(u"message") or res)[:80])
        out = []
        for m in res.get(u"messages") or []:
            if isinstance(m, dict) and getf(m, u"id", u"messageID") != u"ADSVPN":
                out.append(m)
        return out

    def detail(self, mid):
        return self._get(u"/api/message/" + urllib.parse.quote(mid, safe=u""))


# ================= 盯收件箱 =================

def msg_key(m):
    return (str(getf(m, u"from")) + u"|" +
            str(getf(m, u"subject")) + u"|" +
            str(getf(m, u"timestamp")))


def show_msg(api, m, t0):
    subj = str(getf(m, u"subject")).strip() or u"(无主题)"
    frm = str(getf(m, u"from")) or u"(未知)"
    print(u"  " + stamp() + u" 发现新邮件: " + short(subj, 32))

    code = find_code(subj)
    raw = u""
    
    mid = getf(m, u"id", u"messageID")
    if mid:
        try:
            d = api.detail(mid)
            raw = str(d.get(u"content") or u"")
        except Exception:
            pass
            
    if not code:
        code = find_code(strip_html(raw))

    plain = strip_html(raw)
    link = find_link(raw, plain) if raw else u""

    if code:
        code_banner(code, frm, time.time() - t0)
    if link:
        link_banner(link, frm, time.time() - t0)

    if link:
        return (u"link", link)
    elif code:
        return (u"code", code)

    print(u"        (未提取到码/链接, 继续盯)")
    return None


def watch_once(api, addr, kw=u""):
    base = None
    base_max_ts = 0.0
    t0 = time.time()
    errs = 0
    polls = 0
    
    while True:
        try:
            msgs = api.messages(addr)
            errs = 0
        except Exception:
            errs += 1
            if errs >= 12:
                print(u"  " + stamp() + u" 连续失败12次, 中止")
                return None
            time.sleep(5)
            continue
            
        if base is None:
            base = set(msg_key(m) for m in msgs)
            base_max_ts = max([ts_of(m) for m in msgs] or [0.0])
            print(u"  " + stamp() + u" 开始盯箱 (已忽略 %d 封旧邮件)" % len(msgs))
        else:
            fresh = []
            for m in msgs:
                k = msg_key(m)
                if k in base:
                    continue
                base.add(k)
                ts = ts_of(m)
                if ts and ts < max(base_max_ts - 60, time.time() - 600):
                    continue
                fresh.append(m)
                
            hit = False
            for m in fresh:
                if is_noise(m):
                    continue
                if not match_kw(m, kw):
                    continue
                r = show_msg(api, m, t0)
                if r:
                    return r
                hit = True
                
            polls += 1
            if not hit and polls % 12 == 0:
                print(u"  " + stamp() + u" 持续盯箱中 (已盯 " + fmt_sec(time.time() - t0) + u")")
        time.sleep(5)


# ================= 主流程 =================

def main():
    kw = clean_kw(u" ".join(sys.argv[1:]))
    api = Emailnator()

    print(u"")
    print(u"  自动生成临时邮箱...")
    try:
        dotted = api.generate()
    except Exception as e:
        print(u"  失败: " + str(e))
        dotted = ask(u"  手动输入 emailnator 网页生成的地址: ")
        if not dotted:
            return
            
    main_addr = normalize_gmail(dotted)
    print(u"")
    box([u"拿这个邮箱去目标网站注册:", main_addr])
    print(u"  " + main_addr)
    
    if kw:
        print(u"  只认关键词: " + kw)
        
    print(u" 验证码/验证链接到了自动弹出")
    
    while True:
        r = watch_once(api, main_addr, kw)
        if not r:
            return
        kind, val = r
        if kind == u"link":
            try:
                import webbrowser
                webbrowser.open(val)
            except Exception:
                pass
                
        print(u"  " + u"-" * 44)
        a = ask(u"  [操作] 输入 r 继续盯, 直接回车退出: ")
        if a.lower() != u"r":
            print(u"  收工!")
            return
        print(u"  忽略这次, 继续盯...")
        print(u"")


if __name__ == u"__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(u"")
        print(u"  已退出")