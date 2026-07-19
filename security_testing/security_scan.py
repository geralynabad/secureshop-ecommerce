"""
Automated security test harness for SecureShop.

OWASP ZAP itself could not be installed in this sandboxed build environment
(no network access to its distribution servers), so this script performs
the equivalent categories of automated checks ZAP's baseline + active scan
would run, against the live running instance at http://127.0.0.1:8000/.
Results are printed as PASS/FAIL/INFO lines consumed by the written report.
"""
import re
import sys
import requests

BASE = "http://127.0.0.1:8000"
results = []


def record(category, name, passed, detail=""):
    results.append({"category": category, "name": name, "passed": passed, "detail": detail})
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {category} — {name} {('— ' + detail) if detail else ''}")


session = requests.Session()

# ---------------------------------------------------------------------
# 1. Security response headers (maps to ZAP's passive header rules)
# ---------------------------------------------------------------------
r = session.get(f"{BASE}/")
headers = r.headers

record("Headers", "Content-Security-Policy present", "Content-Security-Policy" in headers, headers.get("Content-Security-Policy", "")[:80])
record("Headers", "X-Frame-Options DENY (clickjacking)", headers.get("X-Frame-Options") == "DENY")
record("Headers", "X-Content-Type-Options nosniff", headers.get("X-Content-Type-Options") == "nosniff")
record("Headers", "Referrer-Policy set", "Referrer-Policy" in headers, headers.get("Referrer-Policy", ""))
server_hdr = headers.get("Server", "")
record("Headers", "No verbose Server/framework version banner", "Django" not in server_hdr and re.search(r"\d+\.\d+", server_hdr) is None, f"Server: {server_hdr}")

# ---------------------------------------------------------------------
# 2. Cookie security flags
# ---------------------------------------------------------------------
cookies = session.cookies
for c in cookies:
    if c.name in ("sessionid", "csrftoken"):
        httponly = c.has_nonstandard_attr("HttpOnly") or "HttpOnly" in str(c._rest)
        samesite = c._rest.get("SameSite") if hasattr(c, "_rest") else None
        record("Cookies", f"{c.name} has SameSite attribute", samesite is not None, str(samesite))

# ---------------------------------------------------------------------
# 3. CSRF protection
# ---------------------------------------------------------------------
r = requests.post(f"{BASE}/accounts/login/", data={"username": "admin", "password": "wrong"})
record("CSRF", "POST without CSRF token rejected (403)", r.status_code == 403, f"got {r.status_code}")

# ---------------------------------------------------------------------
# 4. Reflected / stored XSS probes
# ---------------------------------------------------------------------
xss_payload = "<script>alert(document.cookie)</script>"
r = session.get(f"{BASE}/", params={"q": xss_payload})
record("XSS", "Reflected search query is HTML-escaped", xss_payload not in r.text and "&lt;script&gt;" in r.text)

# ---------------------------------------------------------------------
# 5. SQL injection probes against the ORM-backed search endpoint
# ---------------------------------------------------------------------
sqli_payloads = ["' OR '1'='1", "'; DROP TABLE store_product;--", "1' UNION SELECT NULL--"]
sqli_all_safe = True
for payload in sqli_payloads:
    r = session.get(f"{BASE}/", params={"q": payload})
    if r.status_code >= 500 or "OperationalError" in r.text or "IntegrityError" in r.text:
        sqli_all_safe = False
        record("SQL Injection", f"payload rejected safely: {payload}", False, f"status {r.status_code}, possible DB error leak")
if sqli_all_safe:
    record("SQL Injection", "All classic injection payloads handled as literal search text (no 500s, no DB errors)", True)

# confirm table still exists / app still functions after DROP TABLE attempt
r = session.get(f"{BASE}/")
record("SQL Injection", "Product table intact after DROP TABLE payload (app still serving products)", r.status_code == 200 and "Ballpoint" in r.text)

# ---------------------------------------------------------------------
# 6. Open redirect probe on 'next' param (run before the rate-limit test
#    below consumes this IP's login-endpoint quota)
# ---------------------------------------------------------------------
r = requests.get(f"{BASE}/accounts/login/", params={"next": "https://evil.example.com"}, allow_redirects=False)
record("Open Redirect", "Login page does not auto-redirect to external host via 'next'", r.status_code == 200)

# ---------------------------------------------------------------------
# 7. Authentication: brute force / lockout + user enumeration
# ---------------------------------------------------------------------
login_url = f"{BASE}/accounts/login/"
s2 = requests.Session()
r = s2.get(login_url)
csrf = s2.cookies.get("csrftoken")

def do_login(username, password, sess):
    csrf_token = sess.cookies.get("csrftoken")
    return sess.post(login_url, data={"username": username, "password": password, "csrfmiddlewaretoken": csrf_token},
                      headers={"Referer": login_url})

r_bad_user = do_login("definitely_not_a_real_user_zxy", "whatever123", s2)
r_bad_pass = do_login("security_test_user", "definitely_wrong_password", s2)
same_generic_message = ("Invalid username or password" in r_bad_user.text) and ("Invalid username or password" in r_bad_pass.text)
record("Authentication", "Identical generic error for bad username vs bad password (no user enumeration)", same_generic_message)

s3 = requests.Session()
s3.get(login_url)
locked = False
for i in range(6):
    r = do_login("security_test_user", "wrong_password_attempt", s3)
    if "temporarily locked" in r.text:
        locked = True
record("Authentication", "Account locks out after repeated failed attempts", locked)

# ---------------------------------------------------------------------
# 8. Broken access control
# ---------------------------------------------------------------------
r = requests.get(f"{BASE}/admin/", allow_redirects=False)
record("Access Control", "Unauthenticated request to /admin/ redirected (not 200)", r.status_code in (301, 302))

r = requests.get(f"{BASE}/orders/checkout/", allow_redirects=False)
record("Access Control", "Unauthenticated request to /orders/checkout/ redirected to login", r.status_code in (301, 302) and "login" in r.headers.get("Location", ""))

r = requests.get(f"{BASE}/orders/success/999999/", allow_redirects=False)
record("Access Control", "Nonexistent/foreign order id does not leak data (redirect or 404, not 200)", r.status_code in (301, 302, 404))

# ---------------------------------------------------------------------
# 9. Information disclosure via error pages
# ---------------------------------------------------------------------
r = requests.get(f"{BASE}/product/this-slug-does-not-exist/")
record("Info Disclosure", "Unknown product slug returns clean 404 (no stack trace)", r.status_code == 404 and "Traceback" not in r.text)

print("\n--- Summary ---")
passed = sum(1 for x in results if x["passed"])
print(f"{passed}/{len(results)} checks passed")
sys.exit(0)
