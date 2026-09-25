"""
Perchance Turnstile Solver - Browserless API ONLY
Uses https://browserless.io/ headless browser API (1000/month free tier)
Fixes isTopLevel bug via manual window.start() call

Deploy on Render free tier (512MB) - Browserless runs browser remotely, so no local browser needed (fits 512MB)
"""

import os
import re
import json
import time
import random
import secrets
import base64
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
import httpx

BASE_EMBED = "https://image-generation.perchance.org"
BASE_PERCHANCE = "https://perchance.org"
API_GENERATE = f"{BASE_EMBED}/api/generate"
API_AD_CODE = f"{BASE_PERCHANCE}/api/getAccessCodeForAdPoweredStuff"
CLIENT_VERSION_HASH = "9b43eec2e71907610e4e9317b54c208495f6850086e92239a869811d2e2d77ee"

BROWSERLESS_API_TOKEN = os.getenv("BROWSERLESS_API_TOKEN") or os.getenv("BROWSERLESS_TOKEN") or ""
BROWSERLESS_HOST = os.getenv("BROWSERLESS_HOST", "https://chrome.browserless.io")
# For browserless.io, endpoint is https://chrome.browserless.io/function?token=TOKEN or wss

CACHE_DIR = Path.home() / ".perchance-solver"
CACHE_DIR.mkdir(exist_ok=True)
BROWSER_ID_FILE = CACHE_DIR / "browser_id.txt"
USER_KEY_FILE = CACHE_DIR / "user_key.txt"

START_TIME = time.time()
PING_COUNT = {"count": 0}

def load_cached_browser_id() -> str:
    if BROWSER_ID_FILE.exists():
        bid = BROWSER_ID_FILE.read_text().strip()
        if re.fullmatch(r"[a-f0-9]{32}", bid):
            return bid
    bid = secrets.token_hex(16)
    BROWSER_ID_FILE.write_text(bid)
    return bid

def save_user_key(key: str):
    USER_KEY_FILE.write_text(key)

async def get_user_key_via_browserless(timeout: int = 90) -> Optional[Dict[str, Any]]:
    """
    Use Browserless.io /function API to run JS that solves Turnstile
    Browserless free tier: 1000 requests/month
    """
    if not BROWSERLESS_API_TOKEN:
        print("[Solver] BROWSERLESS_API_TOKEN not set - trying without token (may fail)")
    
    print(f"[Solver] Trying Browserless API {BROWSERLESS_HOST}...")
    
    # Browserless /function API expects code that runs in browser context
    # We will navigate to Perchance embed and call window.start() manually
    import urllib.parse as _up, json as _json, random as _rand
    
    hash_data = {"prompt": "test", "seed": 0, "resolution": "512x512", "guidanceScale": 7, "negativePrompt": "", "requestId": f"bl_{_rand.random()}", "iframeId": f"test_{_rand.randint(0,1000000)}"}
    embed_url = f"{BASE_EMBED}/embed#{_up.quote(_json.dumps(hash_data))}"
    
    # JS code to run in Browserless browser
    # This is the same logic as our SeleniumBase fix but runs remotely
    js_code = f"""
    export default async function ({{ page, context }}) {{
        const embedUrl = "{embed_url}";
        console.log("Opening", embedUrl);
        await page.goto(embedUrl, {{ waitUntil: 'networkidle' }});
        await page.waitForTimeout(3000);
        
        const isTop = await page.evaluate(() => window==window.top);
        const hasStart = await page.evaluate(() => typeof window.start);
        console.log("isTopLevel:", isTop, "has start:", hasStart);
        
        await page.evaluate(() => window.start({{reloadPageOnFail:false}}));
        console.log("Called start()");
        
        // Wait for userKey
        for(let attempt=0; attempt<45; attempt++){{
            const bid = await page.evaluate(() => localStorage.getItem('generation-v2-browser'));
            if(bid){{
                for(let i=0;i<5;i++){{
                    const key = await page.evaluate(({{bid, i}}) => localStorage.getItem('generation-v2:'+bid+':userKey-'+i), {{bid, i}});
                    if(key && /^[a-f0-9]{{64}}$/.test(key)){{
                        console.log("FOUND userKey", key.slice(0,20));
                        return {{ bid, userKey: key, attempt, method: 'browserless-manual-start' }};
                    }}
                }}
            }}
            const waiting = await page.evaluate(() => document.getElementById('waitingContentEl')?.innerHTML?.slice(0,200) || '');
            console.log(`Attempt ${{attempt}} waiting: ${{waiting.slice(0,80)}}`);
            await page.waitForTimeout(2000);
        }}
        const bid = await page.evaluate(() => localStorage.getItem('generation-v2-browser'));
        const title = await page.evaluate(() => document.title);
        return {{ error: 'no userKey after 90s', bid, title }};
    }}
    """
    
    try:
        async with httpx.AsyncClient(timeout=timeout+10) as client:
            # Browserless /function endpoint
            url = f"{BROWSERLESS_HOST}/function?token={BROWSERLESS_API_TOKEN}" if BROWSERLESS_API_TOKEN else f"{BROWSERLESS_HOST}/function"
            # Also try chrome.browserless.io/function
            # Payload for /function API
            payload = {
                "code": js_code,
                "context": {}
            }
            print(f"[Browserless] Calling {url}...")
            headers = {"Content-Type": "application/json"}
            if BROWSERLESS_API_TOKEN:
                headers["Authorization"] = f"Bearer {BROWSERLESS_API_TOKEN}"
            
            # Try different Browserless endpoints
            endpoints = [
                f"{BROWSERLESS_HOST}/function?token={BROWSERLESS_API_TOKEN}",
                f"{BROWSERLESS_HOST}/function",
                f"https://chrome.browserless.io/function?token={BROWSERLESS_API_TOKEN}",
                f"https://chrome.browserless.io/function",
            ]
            
            last_error = None
            for endpoint in endpoints:
                if not BROWSERLESS_API_TOKEN and "token=" in endpoint:
                    continue
                try:
                    print(f"[Browserless] Trying endpoint {endpoint[:60]}...")
                    resp = await client.post(endpoint, json=payload, headers=headers, timeout=timeout+10)
                    print(f"[Browserless] Status {resp.status_code} Response: {resp.text[:2000]}")
                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                            # Browserless /function returns result directly or in data
                            if isinstance(data, dict) and 'userKey' in data:
                                bid = data.get('bid', load_cached_browser_id())
                                user_key = data['userKey']
                                if re.fullmatch(r"[a-f0-9]{64}", user_key):
                                    print(f"[Browserless] Got userKey: {user_key[:12]}...")
                                    save_user_key(user_key)
                                    return {"userKey": user_key, "browserId": bid, "method": "browserless-api", "attempt": data.get('attempt')}
                            # Check if response is wrapped
                            if isinstance(data, dict) and 'data' in data and isinstance(data['data'], dict) and 'userKey' in data['data']:
                                bid = data['data'].get('bid', load_cached_browser_id())
                                user_key = data['data']['userKey']
                                if re.fullmatch(r"[a-f0-9]{64}", user_key):
                                    print(f"[Browserless] Got userKey via wrapped data: {user_key[:12]}...")
                                    save_user_key(user_key)
                                    return {"userKey": user_key, "browserId": bid, "method": "browserless-api-wrapped"}
                        except Exception as e:
                            print(f"[Browserless] JSON parse failed: {e}, text: {resp.text[:1000]}")
                            # Try to extract userKey via regex
                            m = re.search(r'"userKey"\s*:\s*"([a-f0-9]{64})"', resp.text)
                            if m:
                                user_key = m.group(1)
                                bid_match = re.search(r'"bid"\s*:\s*"([a-f0-9]{32})"', resp.text)
                                bid = bid_match.group(1) if bid_match else load_cached_browser_id()
                                print(f"[Browserless] Extracted userKey via regex: {user_key[:12]}...")
                                save_user_key(user_key)
                                return {"userKey": user_key, "browserId": bid, "method": "browserless-api-regex"}
                except Exception as e:
                    print(f"[Browserless] Endpoint {endpoint} failed: {e}")
                    last_error = e
                    continue
            
            print(f"[Browserless] All endpoints failed, last error: {last_error}")
            return None
            
    except Exception as e:
        print(f"[Browserless] Failed: {e}")
        import traceback; traceback.print_exc()
        return None

async def get_user_key_via_browserless_playwright_ws(timeout: int = 90) -> Optional[Dict[str, Any]]:
    """
    Alternative: Use Browserless via Playwright WebSocket
    Connect to wss://chrome.browserless.io?token=TOKEN
    """
    if not BROWSERLESS_API_TOKEN:
        print("[Browserless WS] No token, skipping")
        return None
    
    try:
        from playwright.async_api import async_playwright
        import urllib.parse as _up, json as _json, random as _rand
        
        hash_data = {"prompt": "test", "seed": 0, "resolution": "512x512", "guidanceScale": 7, "negativePrompt": "", "requestId": f"bl_{_rand.random()}", "iframeId": f"test_{_rand.randint(0,1000000)}"}
        embed_url = f"{BASE_EMBED}/embed#{_up.quote(_json.dumps(hash_data))}"
        
        print(f"[Browserless WS] Connecting to wss://chrome.browserless.io?token=***")
        async with async_playwright() as p:
            # Connect to Browserless
            browser = await p.chromium.connect_over_cdp(f"wss://chrome.browserless.io?token={BROWSERLESS_API_TOKEN}")
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            await page.goto(embed_url)
            await page.wait_for_timeout(3000)
            is_top = await page.evaluate("() => window==window.top")
            print(f"[Browserless WS] isTop: {is_top}")
            await page.evaluate("() => window.start({reloadPageOnFail:false})")
            print("[Browserless WS] Called start()")
            
            for attempt in range(45):
                bid = await page.evaluate("() => localStorage.getItem('generation-v2-browser')")
                if bid:
                    for i in range(5):
                        key = await page.evaluate(f"() => localStorage.getItem('generation-v2:'+\"{bid}\"+':userKey-'+i)")
                        if key and re.fullmatch(r"[a-f0-9]{64}", key):
                            print(f"[Browserless WS] FOUND userKey: {key[:20]}...")
                            await browser.close()
                            save_user_key(key)
                            return {"userKey": key, "browserId": bid, "method": "browserless-ws", "attempt": attempt}
                await page.wait_for_timeout(2000)
            
            await browser.close()
            print("[Browserless WS] No userKey after 90s")
            return None
    except Exception as e:
        print(f"[Browserless WS] Failed: {e}")
        import traceback; traceback.print_exc()
        return None

async def get_user_key_via_browserless_unified(timeout: int = 120) -> Optional[Dict[str, Any]]:
    """Try WS first (more reliable), then /function API"""
    print("[Solver] Trying Browserless via Playwright WS first...")
    result = await get_user_key_via_browserless_playwright_ws(timeout=timeout)
    if result:
        return result
    print("[Solver] WS failed, trying /function API...")
    return await get_user_key_via_browserless(timeout=timeout)

# --- curl_cffi for ad code + generate ---

def get_ad_code_via_curl_cffi_sync() -> str:
    try:
        from curl_cffi import requests as curl_requests
        cache_bust = int(time.time() // (60 * 10))
        url = f"{API_AD_CODE}?__cacheBust={cache_bust}"
        headers = {"Referer": f"{BASE_PERCHANCE}/stable-diffusion-ai", "Origin": BASE_PERCHANCE, "Accept": "*/*"}
        resp = curl_requests.get(url, impersonate="chrome", headers=headers, timeout=15)
        if resp.status_code == 200:
            code = resp.text.strip()
            if re.fullmatch(r"[a-f0-9]{64}", code):
                print(f"[Solver] Got ad code: {code[:12]}...")
                return code
    except Exception as e:
        print(f"[Solver] ad code failed: {e}")
    return ""

async def get_ad_code_via_curl_cffi() -> str:
    return await asyncio.to_thread(get_ad_code_via_curl_cffi_sync)

async def generate_via_curl_cffi(prompt: str, negative_prompt: str = "", seed: int = -1, resolution: str = "512x512", guidance_scale: float = 7.0, user_key: str = "", ad_code: str = "", browser_id: str = "") -> Dict[str, Any]:
    from curl_cffi import requests as curl_requests
    import urllib.parse
    request_id = f"0.{secrets.randbits(30)}"
    params = {"userKey": user_key, "requestId": request_id, "adAccessCode": ad_code, "v": CLIENT_VERSION_HASH, "__cacheBust": random.random()}
    body = {"prompt": prompt, "negativePrompt": negative_prompt, "seed": seed, "resolution": resolution, "guidanceScale": guidance_scale, "channel": "stable-diffusion-ai", "subChannel": "public", "userKey": user_key, "adAccessCode": ad_code, "requestId": request_id}
    headers = {"Referer": f"{BASE_EMBED}/embed", "Origin": BASE_EMBED, "Content-Type": "application/json", "Accept": "*/*"}
    url = f"{API_GENERATE}?{urllib.parse.urlencode(params)}"
    def _do():
        sess = curl_requests.Session(impersonate="chrome")
        r = sess.post(url, json=body, headers=headers, timeout=30)
        return {"status": r.status_code, "text": r.text[:10000]}
    gen_result = await asyncio.to_thread(_do)
    print(f"[Solver] Generate status {gen_result['status']} {gen_result['text'][:1000]}")
    data = json.loads(gen_result['text'])
    if data.get('status') != 'success':
        raise RuntimeError(f"Generate failed: {data}")
    image_id = data.get('imageId')
    proxy_download = data.get('imageDownloadUrl')
    file_ext = data.get('fileExtension', 'jpeg')
    seed_used = data.get('seed', seed)
    if data.get('imageDataUrls'):
        b64_part = data['imageDataUrls'][0].split(',',1)[1] if ',' in data['imageDataUrls'][0] else ''
        image_bytes = base64.b64decode(b64_part)
        return {"status": "success", "imageId": image_id, "imageDownloadUrl": proxy_download, "fileExtension": file_ext, "seed": seed_used, "dataUrl": data['imageDataUrls'][0], "imageBytes": image_bytes}
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
            except Exception as e:
                print(f"DL error {dl_url}: {e}")
        return {"ok": False}
    dl_result = await asyncio.to_thread(_dl)
    if not dl_result.get('ok'):
        raise RuntimeError(f"Download failed")
    image_bytes = dl_result['bytes']
    data_url = f"data:image/{file_ext};base64,{base64.b64encode(image_bytes).decode()}"
    return {"status": "success", "imageId": image_id, "imageDownloadUrl": proxy_download, "fileExtension": file_ext, "seed": seed_used, "dataUrl": data_url, "imageBytes": image_bytes}

app = FastAPI(title="Perchance Solver - Browserless API ONLY", version="5.0.0-browserless-only")

class SolveRequest(BaseModel):
    browserId: Optional[str] = None

class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    seed: int = -1
    resolution: str = "512x512"
    guidance_scale: float = 7.0

class FlareSolverrRequest(BaseModel):
    cmd: str
    url: str
    maxTimeout: int = 60000

@app.get("/")
async def root():
    return {"name": "perchance-solver-browserless", "status": "ok", "version": "5.0.0-browserless-only", "method": "Browserless API only (1000/month free)", "has_token": bool(BROWSERLESS_API_TOKEN), "uptime": int(time.time()-START_TIME)}

@app.get("/cron")
@app.head("/cron")
@app.get("/ping")
@app.head("/ping")
@app.get("/keepalive")
@app.head("/keepalive")
async def cron_endpoint():
    PING_COUNT["count"] += 1
    return PlainTextResponse("ok")

@app.get("/status")
async def status_endpoint():
    return {"service": "perchance-solver-browserless", "status": "ok", "version": "5.0.0", "uptime": int(time.time()-START_TIME), "ping_count": PING_COUNT["count"], "has_browserless_token": bool(BROWSERLESS_API_TOKEN), "browserless_host": BROWSERLESS_HOST}

@app.post("/solve")
async def solve_turnstile(req: SolveRequest = SolveRequest()):
    result = await get_user_key_via_browserless_unified()
    if not result:
        raise HTTPException(status_code=500, detail="Failed to solve via Browserless")
    return {"status": "success", "userKey": result["userKey"], "browserId": result["browserId"], "method": result["method"], "timestamp": datetime.now(timezone.utc).isoformat()}

@app.post("/generate")
async def generate_image(req: GenerateRequest):
    ad_code = await get_ad_code_via_curl_cffi()
    solve_result = await get_user_key_via_browserless_unified()
    if not solve_result:
        raise HTTPException(status_code=500, detail="Failed to get userKey via Browserless")
    gen_result = await generate_via_curl_cffi(prompt=req.prompt, negative_prompt=req.negative_prompt, seed=req.seed, resolution=req.resolution, guidance_scale=req.guidance_scale, user_key=solve_result["userKey"], ad_code=ad_code, browser_id=solve_result["browserId"])
    b64 = base64.b64encode(gen_result["imageBytes"]).decode()
    return {"status": "success", "prompt": req.prompt, "seed": gen_result.get("seed"), "resolution": req.resolution, "fileSize": len(gen_result["imageBytes"]), "imageBase64": b64, "method": solve_result["method"]}

@app.post("/v1")
async def flaresolverr_compatible(req: FlareSolverrRequest):
    result = await get_user_key_via_browserless_unified()
    return {"status": "ok", "solution": {"url": req.url, "status": 200, "cookies": [], "userAgent": "Mozilla/5.0", "response": f"userKey: {result['userKey'][:20] if result else 'none'}"}, "version": "5.0.0"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("solver:app", host="0.0.0.0", port=port)
