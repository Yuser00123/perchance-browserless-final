"""
Perchance Solver - Azure B1s - v6.4.0 - Enhanced Turnstile logging + longer wait + browser console
"""
import os, re, json, time, random, secrets, base64, asyncio, shutil, socket
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

BASE_EMBED = "https://image-generation.perchance.org"
BASE_PERCHANCE = "https://perchance.org"
API_GENERATE = f"{BASE_EMBED}/api/generate"
API_AD_CODE = f"{BASE_PERCHANCE}/api/getAccessCodeForAdPoweredStuff"
CLIENT_VERSION_HASH = "9b43eec2e71907610e4e9317b54c208495f6850086e92239a869811d2e2d77ee"

CACHE_DIR = Path.home() / ".perchance-solver"
CACHE_DIR.mkdir(exist_ok=True)
BROWSER_ID_FILE = CACHE_DIR / "browser_id.txt"
START_TIME = time.time()
PING_COUNT = {"count": 0}
LAST_ERROR = {"error": None, "logs": []}

def load_cached_browser_id() -> str:
    if BROWSER_ID_FILE.exists():
        bid = BROWSER_ID_FILE.read_text().strip()
        if re.fullmatch(r"[a-f0-9]{32}", bid):
            return bid
    bid = secrets.token_hex(16)
    BROWSER_ID_FILE.write_text(bid)
    return bid

def log(msg: str):
    print(msg)
    LAST_ERROR["logs"].append(f"{datetime.now().isoformat()} {msg}")
    if len(LAST_ERROR["logs"]) > 300:
        LAST_ERROR["logs"] = LAST_ERROR["logs"][-300:]

def find_chromium():
    for path in ["/usr/bin/chromium", "/usr/bin/chromium-browser", shutil.which("chromium"), shutil.which("chromium-browser")]:
        if path and os.path.exists(path):
            return path
    return "/usr/bin/chromium"

WEBSHARE_PROXIES = [
    "zfixrxxu:gtc6gc36einh@p.webshare.io:80",
    "zfixrxxu:gtc6gc36einh@31.59.20.176:6754",
    "zfixrxxu:gtc6gc36einh@45.38.107.97:6014",
    "zfixrxxu:gtc6gc36einh@64.137.96.74:6641",
    "zfixrxxu:gtc6gc36einh@198.23.243.226:6361",
    "zfixrxxu:gtc6gc36einh@38.154.185.97:6370",
]

def test_proxy_socket(proxy_str: str) -> bool:
    try:
        if "@" in proxy_str:
            hostport = proxy_str.split("@")[-1]
        else:
            hostport = proxy_str
        host, port = hostport.split(":")
        port = int(port)
        s = socket.create_connection((host, port), timeout=5)
        s.close()
        return True
    except Exception as e:
        log(f"[ProxyTest] FAIL {proxy_str[:30]}: {e}")
        return False

def parse_proxy_for_playwright(proxy_str: str):
    if "@" in proxy_str:
        creds, hostport = proxy_str.split("@", 1)
        user, pwd = creds.split(":", 1)
        host, port = hostport.split(":")
        return {"server": f"http://{host}:{port}", "username": user, "password": pwd}
    else:
        host, port = proxy_str.split(":")
        return {"server": f"http://{host}:{port}"}

async def get_user_key_via_playwright_proxy(proxy: Optional[str] = None, timeout: int = 180) -> Optional[Dict[str, Any]]:
    log(f"[Solver] PLAYWRIGHT proxy={proxy[:35] if proxy else 'None'}")
    try:
        chromium_path = find_chromium()
        if proxy and not test_proxy_socket(proxy):
            return None

        def _run_sync():
            from playwright.sync_api import sync_playwright
            import json as _json, urllib.parse as _up, random as _rand, re as _re
            browser_logs = []
            with sync_playwright() as p:
                launch_args = {"headless": True, "args": ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-setuid-sandbox"]}
                if os.path.exists(chromium_path):
                    launch_args["executable_path"] = chromium_path
                browser_kwargs = {}
                if proxy:
                    browser_kwargs["proxy"] = parse_proxy_for_playwright(proxy)
                browser = p.chromium.launch(**launch_args)
                context = browser.new_context(**browser_kwargs, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
                page = context.new_page()
                page.on("console", lambda msg: browser_logs.append(f"console:{msg.type}:{msg.text[:200]}"))
                page.on("pageerror", lambda err: browser_logs.append(f"pageerror:{str(err)[:200]}"))
                
                hash_data = {"prompt": "test", "seed": 0, "resolution": "512x512", "guidanceScale": 7, "negativePrompt": "", "requestId": f"pw_{_rand.random()}", "iframeId": f"test_{_rand.randint(0,1000000)}"}
                embed_url = f"{BASE_EMBED}/embed#{_up.quote(_json.dumps(hash_data))}"
                log(f"[PW] Opening {embed_url[:70]}...")
                try:
                    page.goto(embed_url, timeout=30000)
                except Exception as e:
                    log(f"[PW] goto err: {e}")
                    browser_logs.append(f"goto_err:{e}")
                
                for i in range(8):
                    try:
                        title = page.title()
                        has_start = page.evaluate("typeof window.start")
                        if title and "Perchance" in title and has_start == 'function':
                            log(f"[PW] Page loaded OK at check {i}")
                            break
                    except:
                        pass
                    time.sleep(2)
                
                try:
                    title = page.title()
                    has_start = page.evaluate("typeof window.start")
                    log(f"[PW] Final title='{title}' hasStart={has_start}")
                    if has_start != 'function':
                        html = page.content()[:2000]
                        log(f"[PW] No start html={html[:400]}")
                        browser.close()
                        return {"error": f"no window.start title={title}", "html": html[:1000], "browser_logs": browser_logs[-10:]}
                    
                    page.evaluate("() => { void window.start({reloadPageOnFail:false}); return true; }")
                    log(f"[PW] Called start()")
                    
                    for attempt in range(60):  # 120s
                        try:
                            bid = page.evaluate("localStorage.getItem('generation-v2-browser')")
                            waiting = page.evaluate("document.getElementById('waitingContentEl')?.innerHTML?.slice(0,300) || ''")
                            subtitle = page.evaluate("document.getElementById('waitingSubtitleEl')?.innerHTML?.slice(0,300) || ''")
                            turnstile_iframe = page.evaluate("document.querySelector('iframe[src*=\"turnstile\"]') ? 'found' : 'notfound'")
                            cf_iframe = page.evaluate("document.querySelector('iframe[src*=\"challenges.cloudflare\"]') ? 'found' : 'notfound'")
                            body_text = page.evaluate("document.body.innerText.slice(0,500)")
                        except Exception as e:
                            bid, waiting, subtitle, turnstile_iframe, cf_iframe, body_text = None, "", f"eval err {e}", "err", "err", ""
                        
                        if attempt % 3 == 0:
                            log(f"[PW] Att {attempt} bid={bid} turnstile={turnstile_iframe} cf={cf_iframe} waiting={waiting[:80]} subtitle={subtitle[:80]} body={body_text[:80]}")
                            if browser_logs:
                                log(f"[PW] Browser logs: {browser_logs[-3:]}")
                        
                        if bid:
                            for idx in range(5):
                                try:
                                    key = page.evaluate(f"localStorage.getItem('generation-v2:'+\"{bid}\"+':userKey-'+{idx})")
                                except:
                                    key = None
                                if key and _re.fullmatch(r"[a-f0-9]{64}", key):
                                    log(f"[PW] Got userKey att {attempt}")
                                    browser.close()
                                    return {"bid": bid, "response": {"userKey": key}, "attempt": attempt, "title": title, "browser_logs": browser_logs[-10:]}
                        time.sleep(2)
                    
                    try:
                        bid = page.evaluate("localStorage.getItem('generation-v2-browser')")
                        final_html = page.content()[:3000]
                        final_body = page.evaluate("document.body.innerHTML.slice(0,2000)")
                    except:
                        bid, final_html, final_body = None, "", ""
                    log(f"[PW] No userKey after 120s bid={bid}")
                    browser.close()
                    return {"bid": bid, "error": "no userKey after 120s", "title": title, "html": final_html[:2000], "body": final_body[:2000], "browser_logs": browser_logs[-20:]}
                except Exception as e:
                    log(f"[PW] Error: {e}")
                    import traceback; traceback.print_exc()
                    try:
                        browser.close()
                    except:
                        pass
                    return {"error": str(e), "browser_logs": browser_logs[-20:]}
        
        result = await asyncio.to_thread(_run_sync)
        log(f"[Solver] Result: {str(result)[:1000]}")
        user_key = result.get('response', {}).get('userKey') if isinstance(result, dict) else None
        if user_key and re.fullmatch(r"[a-f0-9]{64}", user_key):
            return {"userKey": user_key, "browserId": result.get('bid', load_cached_browser_id()), "method": "playwright-proxy", "proxy": proxy, "attempt": result.get('attempt')}
        return None
    except Exception as e:
        log(f"[Solver] Playwright fail: {e}")
        import traceback; traceback.print_exc()
        return None

async def get_user_key_via_seleniumbase_no_proxy(timeout: int = 120) -> Optional[Dict[str, Any]]:
    log(f"[Solver] SELENIUMBASE no proxy")
    try:
        from seleniumbase import SB
        chromium_path = find_chromium()
        sb_kwargs = {"uc": True, "headless": True, "chromium_arg": "--no-sandbox --disable-gpu --disable-dev-shm-usage --disable-setuid-sandbox", "binary_location": chromium_path}
        def _run_sync():
            with SB(**sb_kwargs) as sb:
                import json as _json, urllib.parse as _up, random as _rand
                hash_data = {"prompt": "test", "seed": 0, "resolution": "512x512", "guidanceScale": 7, "negativePrompt": "", "requestId": f"sb_{_rand.random()}", "iframeId": f"test_{_rand.randint(0,1000000)}"}
                embed_url = f"{BASE_EMBED}/embed#{_up.quote(_json.dumps(hash_data))}"
                sb.open(embed_url)
                for i in range(8):
                    title = sb.execute_script("return document.title")
                    has_start = sb.execute_script("return typeof window.start")
                    if title and "Perchance" in title and has_start == 'function':
                        break
                    sb.sleep(2)
                title = sb.execute_script("return document.title")
                has_start = sb.execute_script("return typeof window.start")
                log(f"[SB] Final title='{title}' hasStart={has_start}")
                if has_start != 'function':
                    return {"error": f"no window.start title={title}"}
                sb.execute_script("window.start({reloadPageOnFail:false})")
                log(f"[SB] Called start()")
                result = sb.execute_async_script("""
                    const callback = arguments[arguments.length - 1];
                    (async () => {
                        for(let attempt=0; attempt<60; attempt++){
                            const bid = localStorage.getItem('generation-v2-browser');
                            if(bid){
                                for(let i=0;i<5;i++){
                                    const key = localStorage.getItem('generation-v2:'+bid+':userKey-'+i);
                                    if(key && /^[a-f0-9]{64}$/.test(key)){
                                        callback({bid, response: {userKey: key}, attempt});
                                        return;
                                    }
                                }
                            }
                            await new Promise(r => setTimeout(r, 2000));
                        }
                        callback({error: 'no userKey after 120s', bid: localStorage.getItem('generation-v2-browser')});
                    })();
                """, timeout=150)
                if result:
                    result['proxy'] = None
                return result
        result = await asyncio.to_thread(_run_sync)
        log(f"[Solver] SB Result: {result}")
        user_key = result.get('response', {}).get('userKey') if isinstance(result, dict) else None
        if user_key and re.fullmatch(r"[a-f0-9]{64}", user_key):
            return {"userKey": user_key, "browserId": result.get('bid', load_cached_browser_id()), "method": "seleniumbase-uc", "proxy": None}
        return None
    except Exception as e:
        log(f"[Solver] SB fail: {e}")
        return None

async def get_user_key_with_rotation(timeout: int = 600) -> Optional[Dict[str, Any]]:
    log("[Solver] Starting rotation")
    result = await get_user_key_via_seleniumbase_no_proxy()
    if result:
        return result
    for proxy in WEBSHARE_PROXIES:
        log(f"[Solver] Trying proxy {proxy[:40]}")
        result = await get_user_key_via_playwright_proxy(proxy=proxy)
        if result:
            log(f"[Solver] SUCCESS {proxy[:30]}")
            return result
    log("[Solver] All failed")
    return None

def get_ad_code_sync() -> str:
    try:
        from curl_cffi import requests as curl_requests
        url = f"{API_AD_CODE}?__cacheBust={int(time.time()//600)}"
        headers = {"Referer": f"{BASE_PERCHANCE}/stable-diffusion-ai", "Origin": BASE_PERCHANCE}
        resp = curl_requests.get(url, impersonate="chrome", headers=headers, timeout=15)
        if resp.status_code == 200:
            code = resp.text.strip()
            if re.fullmatch(r"[a-f0-9]{64}", code):
                return code
    except Exception as e:
        log(f"ad code fail {e}")
    return ""

async def get_ad_code() -> str:
    return await asyncio.to_thread(get_ad_code_sync)

app = FastAPI(title="Perchance Solver", version="6.4.0")

class GenerateRequest(BaseModel):
    prompt: str

@app.get("/")
async def root():
    return {"status": "ok", "version": "6.4.0", "uptime": int(time.time()-START_TIME)}

@app.get("/cron")
@app.head("/cron")
@app.get("/ping")
@app.head("/ping")
async def cron():
    PING_COUNT["count"] += 1
    return PlainTextResponse("ok")

@app.get("/status")
async def status():
    return {"service": "perchance-solver-azure", "status": "ok", "version": "6.4.0", "uptime": int(time.time()-START_TIME), "ping_count": PING_COUNT["count"], "logs": LAST_ERROR["logs"][-15:]}

@app.get("/logs")
async def logs():
    return {"logs": LAST_ERROR["logs"]}

@app.post("/solve")
async def solve():
    result = await get_user_key_with_rotation()
    if not result:
        raise HTTPException(status_code=500, detail={"error": "Failed", "logs": LAST_ERROR["logs"][-50:]})
    return {"status": "success", "userKey": result["userKey"], "browserId": result["browserId"], "method": result["method"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("solver:app", host="0.0.0.0", port=int(os.getenv("PORT","8000")))
