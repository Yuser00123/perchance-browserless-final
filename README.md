# Perchance Solver - Browserless API ONLY

Uses https://browserless.io/ headless browser API to solve Turnstile (1000/month free tier).

**Fixes:**
- `isTopLevel` bug: manually call `window.start({reloadPageOnFail:false})`
- HF datacenter IP blocked: Browserless uses residential IPs, bypasses Turnstile

**Deploy on Render (512MB fits, no local browser):**
1. Create Render Web Service from this repo
2. Add env var `BROWSERLESS_API_TOKEN` = your token from https://browserless.io/
3. Deploy - uses 100-200MB RAM only (browser runs remotely)

**Endpoints:**
- `GET /` - status
- `GET /cron` - keep alive (ok) - for cron-job.org every 13 mins
- `GET /status` - detailed status
- `POST /solve` - returns userKey
- `POST /generate` - generates image, returns base64

**Test:**
```bash
curl https://your-app.onrender.com/cron
# -> ok

curl -X POST https://your-app.onrender.com/solve -H "Content-Type: application/json" -d '{}'
# -> {"status":"success","userKey":"...","browserId":"..."}

curl -X POST https://your-app.onrender.com/generate -H "Content-Type: application/json" -d '{"prompt":"mercury planet"}'
# -> {"status":"success","imageBase64":"..."}
```

**Keep alive:** cron-job.org every 13 mins pinging `/cron` (Render sleeps after 15 mins free tier)

**Unlimited?** Browserless free tier 1000/month, but you can self-host Browserless via Docker for unlimited (https://docs.browserless.io/).
