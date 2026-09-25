"""
Perchance Solver - Azure B1s - v6.3.2 - Fix Playwright evaluate hang on async window.start()
"""
import os, re, json, time, random, secrets, base64, asyncio, glob, shutil, socket
from pathlib import Path
from datetime import datetime, timezone
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
    if len(LAST_ERROR["logs"]) > 200:
        LAST_ERROR["logs"] = LAST_ERROR["logs"][-200:]

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
        log(f"[ProxyTest] Testing socket {host}:{port}...")
        s = socket.create_connection((host, port), timeout=5)
        s.close()
        log(f"[ProxyTest] Socket OK {host}:{port}")
        return True
    except Exception as e:
        log(f"[ProxyTest] Socket FAIL {proxy_str[:30]}: {e}")
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

async def get_user_key_via_playwright_proxy(proxy: Optional[str] = None, timeout: int = 120) -> Optional[Dict[str, Any]]:
    log(f"[Solver] Trying PLAYWRIGHT proxy={proxy[:30] if proxy else 'None'}")
    try:
        chromium_path = find_chromium()
        log(f"[Solver] Chromium: {chromium_path}, exists: {os.path.exists(chromium_path)}")
        
        if proxy and not test_proxy_socket(proxy):
            log(f"[Solver] Proxy socket failed, skipping")
            return None

        def _run_sync():
            from playwright.sync_api import sync_playwright
            import json as _json, urllib.parse as _up, random as _rand
            with sync_playwright() as p:
                launch_args = {"headless": True, "args": ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-setuid-sandbox"]}
                if os.path.exists(chromium_path):
                    launch_args["executable_path"] = chromium_path
                
                browser_kwargs = {}
                if proxy:
                    browser_kwargs["proxy"] = parse_proxy_for_playwright(proxy)
                    log(f"[PW] Using proxy {browser_kwargs['proxy']['server']}")

                browser = p.chromium.launch(**launch_args)
                context = browser.new_context(**browser_kwargs, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
                page = context.new_page()
                
                hash_data = {"prompt": "test", "seed": 0, "resolution": "512x512", "guidanceScale": 7, "negativePrompt": "", "requestId": f"pw_{_rand.random()}", "iframeId": f"test_{_rand.randint(0,1000000)}"}
                embed_url = f"{BASE_EMBED}/embed#{_up.quote(_json.dumps(hash_data))}"
                log(f"[PW] Opening {embed_url[:80]}...")
                try:
                    page.goto(embed_url, timeout=30000)
                except Exception as e:
                    log(f"[PW] goto error: {e}")
                
                for i in range(10):
                    try:
                        title = page.title()
                        has_start = page.evaluate("typeof window.start")
                        log(f"[PW] Load check {i}: title='{title[:50]}' hasStart={has_start}")
                        if title and "Perchance" in title and has_start == 'function':
                            log(f"[PW] Page loaded OK")
                            break
                    except Exception as e:
                        log(f"[PW] Load check error: {e}")
                    time.sleep(2)
                
                try:
                    title = page.title()
                    has_start = page.evaluate("typeof window.start")
                    log(f"[PW] Final: title='{title}' hasStart={has_start}")
                    if has_start != 'function':
                        html = page.content()[:2000]
                        log(f"[PW] No window.start, html: {html[:500]}")
                        browser.close()
                        return {"error": f"no window.start, title={title}", "html": html[:1000]}
                    
                    # FIX: void to not wait for async promise
                    page.evaluate("() => { void window.start({reloadPageOnFail:false}); return true; }")
                    log(f"[PW] Called start()")
                    
                    for attempt in range(45):
                        try:
                            bid = page.evaluate("localStorage.getItem('generation-v2-browser')")
                        except:
                            bid = None
                        if attempt % 5 == 0:
                            try:
                                waiting = page.evaluate("document.getElementById('waitingContentEl')?.innerHTML?.slice(0,100) || ''")
                                subtitle = page.evaluate("document.getElementById('waitingSubtitleEl')?.innerHTML?.slice(0,100) || ''")
                                log(f"[PW] Attempt {attempt} bid={bid} waiting={waiting[:50]} subtitle={subtitle[:50]}")
                            except Exception as e:
                                log(f"[PW] Attempt {attempt} eval error: {e}")
                        if bid:
                            for idx in range(5):
                                try:
                                    key = page.evaluate(f"localStorage.getItem('generation-v2:'+\"{bid}\"+':userKey-'+{idx})")
                                except:
                                    key = None
                                if key and re.fullmatch(r"[a-f0-9]{{64}}", key):
                                    log(f"[PW] Got userKey attempt {attempt}")
                                    browser.close()
                                    return {"bid": bid, "response": {"userKey": key, "status": "success"}, "attempt": attempt, "title": title}
                        time.sleep(2)
                    
                    try:
                        bid = page.evaluate("localStorage.getItem('generation-v2-browser')")
                    except:
                        bid = None
                    log(f"[PW] No userKey after 90s bid={bid}")
                    browser.close()
                    return {"bid": bid, "error": "no userKey after 90s", "title": title}
                except Exception as e:
                    log(f"[PW] Error after start: {e}")
                    import traceback; traceback.print_exc()
                    try:
                        browser.close()
                    except:
                        pass
                    return {"error": str(e)}
        
        result = await asyncio.to_thread(_run_sync)
        log(f"[Solver] Result: {result}")
        user_key = result.get('response', {}).get('userKey') if isinstance(result, dict) else None
        if user_key and re.fullmatch(r"[a-f0-9]{64}", user_key):
            log(f"[Solver] Got userKey: {user_key[:12]}... attempt {result.get('attempt')}")
            return {"userKey": user_key, "browserId": result.get('bid', load_cached_browser_id()), "method": "playwright-proxy", "proxy": proxy, "attempt": result.get('attempt')}
        return None
    except Exception as e:
        log(f"[Solver] Playwright proxy={proxy} failed: {e}")
        import traceback; traceback.print_exc()
        return None

async def get_user_key_via_seleniumbase_no_proxy(timeout: int = 120) -> Optional[Dict[str, Any]]:
    log(f"[Solver] Trying SELENIUMBASE without proxy")
    try:
        from seleniumbase import SB
        chromium_path = find_chromium()
        log(f"[Solver] Chromium: {chromium_path}, exists: {os.path.exists(chromium_path)}")
        sb_kwargs = {
            "uc": True,
            "headless": True,
            "chromium_arg": "--no-sandbox --disable-gpu --disable-dev-shm-usage --disable-setuid-sandbox --lang=en-US --user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "binary_location": chromium_path,
        }
        def _run_sync():
            with SB(**sb_kwargs) as sb:
                import json as _json, urllib.parse as _up, random as _rand
                hash_data = {"prompt": "test", "seed": 0, "resolution": "512x512", "guidanceScale": 7, "negativePrompt": "", "requestId": f"sb_{_rand.random()}", "iframeId": f"test_{_rand.randint(0,1000000)}"}
                embed_url = f"{BASE_EMBED}/embed#{_up.quote(_json.dumps(hash_data))}"
                log(f"[SB] Opening {embed_url[:80]}...")
                sb.open(embed_url)
                for i in range(10):
                    title = sb.execute_script("return document.title")
                    has_start = sb.execute_script("return typeof window.start")
                    log(f"[SB] Load check {i}: title='{title[:50]}' hasStart={has_start}")
                    if title and "Perchance" in title and has_start == 'function':
                        log(f"[SB] Page loaded OK")
                        break
                    sb.sleep(2)
                title = sb.execute_script("return document.title")
                has_start = sb.execute_script("return typeof window.start")
                log(f"[SB] Final: title='{title}' hasStart={has_start}")
                if has_start != 'function':
                    html = sb.execute_script("return document.documentElement.innerHTML.slice(0,2000)")
                    log(f"[SB] No window.start, html: {html[:500]}")
                    return {"error": f"no window.start, title={title}", "html": html[:1000]}
                sb.execute_script("window.start({reloadPageOnFail:false})")
                log(f"[SB] Called start()")
                result = sb.execute_async_script("""
                    const callback = arguments[arguments.length - 1];
                    (async () => {
                        for(let attempt=0; attempt<45; attempt++){
                            const bid = localStorage.getItem('generation-v2-browser');
                            if(bid){
                                for(let i=0;i<5;i++){
                                    const key = localStorage.getItem('generation-v2:'+bid+':userKey-'+i);
                                    if(key && /^[a-f0-9]{64}$/.test(key)){
                                        callback({bid, response: {userKey: key, status: 'success'}, attempt});
                                        return;
                                    }
                                }
                            }
                            await new Promise(r => setTimeout(r, 2000));
                        }
                        callback({error: 'no userKey after 90s', bid: localStorage.getItem('generation-v2-browser'), title: document.title});
                    })();
                """, timeout=120)
                if result:
                    result['proxy'] = None
                return result
        result = await asyncio.to_thread(_run_sync)
        log(f"[Solver] Result: {result}")
        user_key = result.get('response', {}).get('userKey') if isinstance(result, dict) else None
        if user_key and re.fullmatch(r"[a-f0-9]{64}", user_key):
            log(f"[Solver] Got userKey: {user_key[:12]}... attempt {result.get('attempt')}")
            return {"userKey": user_key, "browserId": result.get('bid', load_cached_browser_id()), "method": "seleniumbase-uc", "proxy": None, "attempt": result.get('attempt')}
        return None
    except Exception as e:
        log(f"[Solver] SB failed: {e}")
        import traceback; traceback.print_exc()
        return None

async def get_user_key_with_rotation(timeout: int = 300) -> Optional[Dict[str, Any]]:
    log("[Solver] Starting rotation - try WITHOUT proxy first")
    result = await get_user_key_via_seleniumbase_no_proxy(timeout=120)
    if result:
        log("[Solver] SUCCESS without proxy!")
        return result
    log("[Solver] Without proxy failed, trying Playwright proxies...")
    for proxy in WEBSHARE_PROXIES:
        log(f"[Solver] Trying proxy {proxy[:40]}...")
        result = await get_user_key_via_playwright_proxy(proxy=proxy, timeout=120)
        if result:
            log(f"[Solver] SUCCESS with {proxy[:30]}!")
            return result
        await asyncio.sleep(1)
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
        log(f"ad code failed: {e}")
    return ""

async def get_ad_code() -> str:
    return await asyncio.to_thread(get_ad_code_sync)

async def generate_via_curl_cffi(prompt: str, user_key: str, ad_code: str, browser_id: str) -> Dict[str, Any]:
    from curl_cffi import requests as curl_requests
    import urllib.parse
    request_id = f"0.{secrets.randbits(30)}"
    params = {"userKey": user_key, "requestId": request_id, "adAccessCode": ad_code, "v": CLIENT_VERSION_HASH, "__cacheBust": random.random()}
    body = {"prompt": prompt, "negativePrompt": "", "seed": -1, "resolution": "512x512", "guidanceScale": 7.0, "channel": "stable-diffusion-ai", "subChannel": "public", "userKey": user_key, "adAccessCode": ad_code, "requestId": request_id}
    headers = {"Referer": f"{BASE_EMBED}/embed", "Origin": BASE_EMBED, "Content-Type": "application/json"}
    url = f"{API_GENERATE}?{urllib.parse.urlencode(params)}"
    def _do():
        sess = curl_requests.Session(impersonate="chrome")
        r = sess.post(url, json=body, headers=headers, timeout=30)
        return {"status": r.status_code, "text": r.text[:10000]}
    gen_result = await asyncio.to_thread(_do)
    data = json.loads(gen_result['text'])
    if data.get('status') != 'success':
        raise RuntimeError(f"Generate failed: {data}")
    image_id = data.get('imageId')
    proxy_download = data.get('imageDownloadUrl')
    if data.get('imageDataUrls'):
        b64_part = data['imageDataUrls'][0].split(',',1)[1] if ',' in data['imageDataUrls'][0] else ''
        image_bytes = base64.b64decode(b64_part)
        return {"imageBytes": image_bytes, "seed": data.get('seed')}
    def _dl():
        sess = curl_requests.Session(impersonate="chrome")
        urls = []
        if proxy_download:
            urls.append(proxy_download if proxy_download.startswith('http') else f"{BASE_EMBED}{proxy_download}")
        if image_id:
            urls.append(f"{BASE_EMBED}/api/downloadTemporaryImage?imageId={image_id}")
        for dl_url in urls:
            try:
                r = sess.get(dl_url, headers={"Referer": f"{BASE_EMBED}/embed", "Origin": BASE_EMBED}, timeout=30)
                if r.status_code == 200 and len(r.content) > 1000:
                    return {"ok": True, "bytes": r.content}
            except:
                pass
        return {"ok": False}
    dl_result = await asyncio.to_thread(_dl)
    if not dl_result.get('ok'):
        raise RuntimeError("Download failed")
    return {"imageBytes": dl_result['bytes'], "seed": data.get('seed')}

app = FastAPI(title="Perchance Solver Azure", version="6.3.2-fix-hang")

class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    seed: int = -1
    resolution: str = "512x512"
    guidance_scale: float = 7.0

@app.get("/")
async def root():
    return {"name": "perchance-solver-azure", "status": "ok", "version": "6.3.2-fix-hang", "uptime": int(time.time()-START_TIME)}

@app.get("/cron")
@app.head("/cron")
@app.get("/ping")
@app.head("/ping")
async def cron():
    PING_COUNT["count"] += 1
    return PlainTextResponse("ok")

@app.get("/status")
async def status():
    return {"service": "perchance-solver-azure", "status": "ok", "version": "6.3.2", "uptime": int(time.time()-START_TIME), "ping_count": PING_COUNT["count"], "last_error": LAST_ERROR["error"], "logs": LAST_ERROR["logs"][-20:]}

@app.get("/logs")
async def logs():
    return {"last_error": LAST_ERROR["error"], "logs": LAST_ERROR["logs"]}

@app.post("/solve")
async def solve():
    result = await get_user_key_with_rotation()
    if not result:
        raise HTTPException(status_code=500, detail={"error": "Failed to solve", "logs": LAST_ERROR["logs"][-40:]})
    return {"status": "success", "userKey": result["userKey"], "browserId": result["browserId"], "method": result["method"], "proxy": result.get("proxy")}

@app.post("/generate")
async def generate(req: GenerateRequest):
    ad_code = await get_ad_code()
    solve_result = await get_user_key_with_rotation()
    if not solve_result:
        raise HTTPException(status_code=500, detail={"error": "Failed to get userKey", "logs": LAST_ERROR["logs"][-40:]})
    gen_result = await generate_via_curl_cffi(prompt=req.prompt, user_key=solve_result["userKey"], ad_code=ad_code, browser_id=solve_result["browserId"])
    b64 = base64.b64encode(gen_result["imageBytes"]).decode()
    return {"status": "success", "prompt": req.prompt, "seed": gen_result.get("seed"), "fileSize": len(gen_result["imageBytes"]), "imageBase64": b64, "method": solve_result["method"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("solver:app", host="0.0.0.0", port=int(os.getenv("PORT","8000")))
