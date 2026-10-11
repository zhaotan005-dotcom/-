import base64
import json
import time
import uuid
import re
import random
import requests

# ================= 配置区 =================
INVITE_CODE = "4C2216A0"
RUN_TIMES = 15
EAZO = "https://eazo.ai"
GENAUTH = "https://eazo.genauth.ai"
APP_ID = "6972f32040acf5801552404b"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

MAIL_BASE_URL = "https://laisilsyx.tw.cpolar.io"
TLD_LIST = ["store", "edu"]

SEND_EMAIL_MUTATION = """mutation sendEmail($email: String!, $scene: EmailScene!) {
  sendEmail(email: $email, scene: $scene) { message code }
}"""

IS_USER_EXISTS_QUERY = """query isUserExists($email: String, $phone: String, $username: String, $externalId: String) {
  isUserExists(email: $email, phone: $phone, username: $username, externalId: $externalId)
}"""

def mail_api_request(method, path, data=None):
    url = MAIL_BASE_URL + path
    try:
        if method == "POST":
            res = requests.post(url, headers={"Content-Type": "application/json"}, json=data, timeout=15)
        elif method == "GET":
            res = requests.get(url, headers={"Content-Type": "application/json"}, timeout=15)
        elif method == "DELETE":
            res = requests.delete(url, headers={"Content-Type": "application/json"}, timeout=15)
        return res.json() if 200 <= res.status_code < 300 else None
    except Exception as e:
        return None

def extract_code(content):
    if not content: return None
    plain_text = re.sub(r'<[^>]+>', ' ', content)
    plain_text = re.sub(r'#[0-9a-fA-F]{6}', ' ', plain_text)
    plain_text = re.sub(r'\b(19|20)\d{2}\b', ' ', plain_text)
    match = re.search(r'(?:code|验证码|verify)[^0-9]*(\d{4,6})', plain_text, re.IGNORECASE)
    if match: return match.group(1)
    fallback = re.search(r'\b(\d{4,6})\b', plain_text)
    return fallback.group(1) if fallback else None

def b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")

def new_state(invite_code: str) -> dict:
    now = int(time.time() * 1000)
    return {
        "invite_code": invite_code,
        "anonymous_id": f"anon_{uuid.uuid4()}",
        "session_id": f"sess_{uuid.uuid4()}",
        "signup_attempt_id": f"signup_attempt_{uuid.uuid4()}",
        "landing_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "started_at": now,
        "auth_provider": "unknown",
        "signup_method_detail": "unknown",
        "email": None,
        "token": None,
        "inviter_user_id": None,
    }

def client_context(state: dict, page: str = None) -> str:
    page = page or f"/invite/{state['invite_code']}"
    ctx = {
        "session_id": state["session_id"], "anonymous_id": state["anonymous_id"],
        "product_name": "creator_web", "source_platform": "creator_web",
        "client_type": "web", "event_time": int(time.time() * 1000),
        "posthog_distinct_id": None, "device_type": "desktop",
        "platform": "Windows", "os_name": "Windows", "os_version": "10",
        "device_model": None, "browser": "Chrome", "browser_name": "Chrome",
        "browser_version": "126.0.0.0", "host_app": None,
        "locale": "en-US", "browser_language": "en-US", "app_language": "en",
        "country_code": None, "timezone_name": "Asia/Shanghai", "timezone_offset_minutes": -480,
        "screen_width": 1920, "screen_height": 1080, "viewport_width": 1552, "viewport_height": 840,
        "page_path": page, "page_url": f"{EAZO}{page}", "page_referrer": "",
        "page_version": "0.1.0", "invite_code": state["invite_code"],
        "inviter_user_id": state.get("inviter_user_id"), "share_product_name": "creator_web",
        "signup_attempt_id": state["signup_attempt_id"], "flow_intent": "signup",
        "auth_provider": state["auth_provider"], "signup_method_detail": state["signup_method_detail"],
        "started_at": state["started_at"], "app_version": None, "build_number": None, "user_agent": UA,
    }
    return b64url(json.dumps(ctx, separators=(",", ":")))

def eazo_headers(state: dict, token: str = None) -> dict:
    h = {
        "Content-Type": "application/json", "User-Agent": UA, "Origin": EAZO,
        "Referer": f"{EAZO}/invite/{state['invite_code']}",
        "X-Eazo-Client-Context": client_context(state),
    }
    if token: h["Authorization"] = f"Bearer {token}"
    return h

def genauth_headers() -> dict:
    return {
        "Content-Type": "application/json", "User-Agent": UA, "Origin": EAZO,
        "Referer": f"{EAZO}/", "x-authing-app-id": APP_ID,
        "x-authing-request-from": "sdk", "x-authing-lang": "zh-CN",
    }

def run_single(invite_code) -> bool:
    state = new_state(invite_code)
    mail_id = None
    try:
        tld = random.choice(TLD_LIST)
        create_res = mail_api_request("POST", "/api/v1/create", {"tld": tld})
        if not create_res or 'mail' not in create_res:
            print("[-] 创建临时邮箱失败")
            return False
        email = create_res['mail']
        mail_id = create_res['id']
        print(f"[*] 临时邮箱: {email}")

        r = requests.get(f"{EAZO}/creator/api/invites/inviter-info", params={"code": invite_code}, headers={"User-Agent": UA}, timeout=20)
        state["inviter_user_id"] = r.json()["inviter_user_id"]
        
        requests.post(f"{EAZO}/api/analytics/attribution", headers=eazo_headers(state), json={
            "invite_code": invite_code, "inviter_user_id": state["inviter_user_id"], "share_product_name": "creator_web"
        }, timeout=20)
        
        requests.post(f"{GENAUTH}/graphql/v2", headers=genauth_headers(), json={
            "query": IS_USER_EXISTS_QUERY, "variables": {"email": email}
        }, timeout=20)

        r = requests.post(f"{GENAUTH}/graphql/v2", headers=genauth_headers(), json={
            "query": SEND_EMAIL_MUTATION, "variables": {"email": email, "scene": "LOGIN_VERIFY_CODE"}
        }, timeout=20)
        if r.json().get("errors"):
            print("[-] 发码失败，被风控拦截")
            return False
        state["email"] = email
        print("[+] 发码成功，等待收信...")
        
        code = None
        start_time = time.time()
        while time.time() - start_time < 90:
            time.sleep(4)
            inbox = mail_api_request("GET", f"/api/v1/mail/{mail_id}")
            if inbox and inbox.get('mails'):
                for m in inbox['mails']:
                    code = extract_code(m.get('content', ''))
                    if code: break
                if code: break
            print("    ...等待邮件中...")
        
        if not code:
            print("[-] 未收到验证码（IP或临时邮箱触发风控限制）")
            return False
        print(f"[🔥] 成功提取验证码: {code}")

        r = requests.post(f"{GENAUTH}/api/v2/login/email-code", headers=genauth_headers(), json={
            "email": email, "code": code, "phoneCountryCode": None, "clientIp": None, "params": None, "context": None
        }, timeout=20)
        raw = r.json()
        user = raw.get("data") if isinstance(raw.get("data"), dict) and raw.get("code") in (200, 201) else raw
        token = user.get("token") or user.get("id_token") or user.get("access_token")
        if not token:
            print("[-] 未解析到 Token")
            return False
        state["token"] = token
        state["auth_provider"] = "email"
        state["signup_method_detail"] = "email_code"
        print(f"[+] 登录成功: {user.get('email')}")

        requests.get(f"{EAZO}/api/user/info", headers=eazo_headers(state, token), timeout=20)
        requests.post(f"{EAZO}/api/analytics/attribution/claim", headers=eazo_headers(state, token), json={}, timeout=20)
        
        body = {"code": invite_code, "invite_landing_at": state["landing_at"], "channel": "creator_web"}
        for delay in [0, 400, 1200, 3000]:
            if delay: time.sleep(delay / 1000)
            r = requests.post(f"{EAZO}/creator/api/invites/redeem", headers=eazo_headers(state, token), json=body, timeout=20)
            if r.status_code == 200:
                data = r.json()
                if not (data.get("ineligible") and data.get("ineligible_reason") == "missing_user"):
                    print(f"[🎉] 核销成功: {json.dumps(data, ensure_ascii=False)}")
                    return True
            if r.status_code not in (401, 408, 409, 425, 429) and r.status_code < 500:
                break
        print("[-] 核销失败，但注册已完成")
        return False
    except Exception as e:
        print(f"[-] 单次运行异常: {e}")
        return False
    finally:
        if mail_id:
            mail_api_request("DELETE", f"/api/v1/mail/{mail_id}")
            print("[*] 临时邮箱已销毁")

def run_batch():
    print("="*50)
    print(f" Eazo 批量全自动脚本 (目标: 连续运行 {RUN_TIMES} 次)")
    print("="*50)
    
    success_count = 0
    for i in range(1, RUN_TIMES + 1):
        print(f"\n{'='*15} 第 {i} / {RUN_TIMES} 次尝试 {'='*15}")
        ok = run_single(INVITE_CODE)
        if ok:
            success_count += 1
        
        if not ok and i < RUN_TIMES:
            print("\n[!] 单次失败。脚本自动暂停 5 分钟，以降低风控风险并等待IP解封...")
            time.sleep(300)
            
        if i < RUN_TIMES:
            wait_time = random.uniform(8, 15)
            print(f"\n[*] 本次任务完成。随机等待 {wait_time:.1f} 秒后继续...")
            time.sleep(wait_time)
            
    print(f"\n{'='*50}")
    print(f"[🏁] 批量运行结束！总计成功: {success_count} / {RUN_TIMES} 次。")
    print(f"{'='*50}")

if __name__ == "__main__":
    run_batch()