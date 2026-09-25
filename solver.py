"""
Perchance Solver v5.1.0 - Browserless with detailed errors
"""

import os, re, json, time, random, secrets, base64, asyncio, glob
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import httpx

BASE_EMBED = "https://image-generation.perchance.org"
BASE_PERCHANCE = "https://perchance.org"
API_GENERATE = f"{BASE_EMBED}/api/generate"
API_AD_CODE = f"{BASE_PERCHANCE}/api/getAccessCodeForAdPoweredStuff"
CLIENT_VERSION_HASH = "9b43eec2e71907610e4e9317b54c208495f6850086e92239a869811d2e2d77ee"

BROWSERLESS_API_TOKEN = os.getenv("BROWSERLESS_API_TOKEN") or ""
BROWSERLESS_HOST = os.getenv("BROWSERLESS_HOST", "https://chrome.browserless.io")

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

def log_error(msg: str):
    print(msg)
    LAST_ERROR["error"] = msg[:2000]
    LAST_ERROR["logs"].append(f"{datetime.now().isoformat()} {msg}")
    if len(LAST_ERROR["logs"]) > 50:
        LAST_ERROR["logs"] = LAST_ERROR["logs"][-50:]

async def get_user_key_via_browserless_ws_detailed(timeout: int = 90) -> Optional[Dict[str, Any]]:
    if not BROWSERLESS_API_TOKEN:
        log_error("BROWSERLESS_API_TOKEN not set")
        return None
    try:
        from playwright.async_api import async_playwright
        import urllib.parse as _up, json as _json, random as _rand
        
        hash_data = {"prompt": "test", "seed": 0, "resolution": "512x512", "guidanceScale": 7, "negativePrompt": "", "requestId": f"bl_{_rand.random()}", "iframeId": f"test_{_rand.randint(0,1000000)}"}
        embed_url = f"{BASE_EMBED}/embed#{_up.quote(_json.dumps(hash_data))}"
        
        log_error(f"[Browserless WS] Connecting to wss://chrome.browserless.io?token=***, URL {embed_url[:80]}")
        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(f"wss://chrome.browserless.io?token={BROWSERLESS_API_TOKEN}", timeout=30000)
            except Exception as e:
                log_error(f"[Browserless WS] Connect failed: {e}")
                return None
            
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.goto(embed_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
                
                title = await page.evaluate("() => document.title")
                is_top = await page.evaluate("() => window==window.top")
                has_start = await page.evaluate("() => typeof window.start")
                log_error(f"[Browserless WS] Title: {title}, isTop: {is_top}, hasStart: {has_start}")
                
                await page.evaluate("() => window.start({reloadPageOnFail:false})")
                log_error("[Browserless WS] Called start()")
                
                for attempt in range(30):
                    bid = await page.evaluate("() => localStorage.getItem('generation-v2-browser')")
                    waiting = await page.evaluate("() => document.getElementById('waitingContentEl')?.innerHTML?.slice(0,200) || ''")
                    subtitle = await page.evaluate("() => document.getElementById('waitingSubtitleEl')?.innerHTML?.slice(0,200) || ''")
                    if attempt % 5 == 0:
                        log_error(f"[Browserless WS] Attempt {attempt} bid={bid[:8] if bid else 'None'} waiting={waiting[:60]} subtitle={subtitle[:60]}")
                    if bid:
                        for i in range(5):
                            key = await page.evaluate(f"() => localStorage.getItem('generation-v2:'+\"{bid}\"+':userKey-'+i)")
                            if key and re.fullmatch(r"[a-f0-9]{64}", key):
                                log_error(f"[Browserless WS] FOUND userKey attempt {attempt}")
                                await browser.close()
                                return {"userKey": key, "browserId": bid, "method": "browserless-ws", "attempt": attempt}
                    await page.wait_for_timeout(2000)
                
                html = await page.evaluate("() => document.documentElement.innerHTML.slice(0,2000)")
                log_error(f"[Browserless WS] No userKey after 60s, html: {html[:500]}")
                await browser.close()
                return None
            except Exception as e:
                log_error(f"[Browserless WS] Page error: {e}")
                try:
                    await browser.close()
                except:
                    pass
                return None
    except Exception as e:
        log_error(f"[Browserless WS] Failed: {e}")
        import traceback; traceback.print_exc()
        return None

async def get_user_key_via_browserless_unified(timeout: int = 120) -> Optional[Dict[str, Any]]:
    LAST_ERROR["logs"] = []
    result = await get_user_key_via_browserless_ws_detailed(timeout=timeout)
    if result:
        return result
    log_error("All Browserless methods failed")
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
        log_error(f"ad code failed: {e}")
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
    print(f"Generate status {gen_result['status']}")
    data = json.loads(gen_result['text'])
    if data.get('status') != 'success':
        raise RuntimeError(f"Generate failed: {data}")
    image_id = data.get('imageId')
    proxy_download = data.get('imageDownloadUrl')
    file_ext = data.get('fileExtension', 'jpeg')
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

app = FastAPI(title="Perchance Solver Browserless", version="5.1.0")

class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    seed: int = -1
    resolution: str = "512x512"
    guidance_scale: float = 7.0

@app.get("/")
async def root():
    return {"name": "perchance-solver-browserless", "status": "ok", "version": "5.1.0", "has_token": bool(BROWSERLESS_API_TOKEN), "uptime": int(time.time()-START_TIME), "last_error": LAST_ERROR["error"]}

@app.get("/cron")
@app.head("/cron")
@app.get("/ping")
@app.head("/ping")
async def cron():
    PING_COUNT["count"] += 1
    return PlainTextResponse("ok")

@app.get("/status")
async def status():
    return {"service": "perchance-solver-browserless", "status": "ok", "version": "5.1.0", "uptime": int(time.time()-START_TIME), "ping_count": PING_COUNT["count"], "has_token": bool(BROWSERLESS_API_TOKEN), "last_error": LAST_ERROR["error"], "logs": LAST_ERROR["logs"][-20:]}

@app.get("/logs")
async def logs():
    return {"last_error": LAST_ERROR["error"], "logs": LAST_ERROR["logs"]}

@app.post("/solve")
async def solve():
    result = await get_user_key_via_browserless_unified()
    if not result:
        raise HTTPException(status_code=500, detail={"error": "Failed to solve via Browserless", "last_error": LAST_ERROR["error"], "logs": LAST_ERROR["logs"][-10:]})
    return {"status": "success", "userKey": result["userKey"], "browserId": result["browserId"], "method": result["method"]}

@app.post("/generate")
async def generate(req: GenerateRequest):
    ad_code = await get_ad_code()
    solve_result = await get_user_key_via_browserless_unified()
    if not solve_result:
        raise HTTPException(status_code=500, detail={"error": "Failed to get userKey", "last_error": LAST_ERROR["error"]})
    gen_result = await generate_via_curl_cffi(prompt=req.prompt, user_key=solve_result["userKey"], ad_code=ad_code, browser_id=solve_result["browserId"])
    b64 = base64.b64encode(gen_result["imageBytes"]).decode()
    return {"status": "success", "prompt": req.prompt, "seed": gen_result.get("seed"), "fileSize": len(gen_result["imageBytes"]), "imageBase64": b64, "method": solve_result["method"], "last_error": LAST_ERROR["error"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("solver:app", host="0.0.0.0", port=int(os.getenv("PORT","8000")))
