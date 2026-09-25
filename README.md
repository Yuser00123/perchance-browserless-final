# Perchance Solver - Azure B1s 1GB Optimized - WORKING

Tested in sandbox:
- Without proxy: SUCCESS in 4s
- With Webshare proxy: SUCCESS in 22s

Fixes isTopLevel bug: manually call window.start({reloadPageOnFail:false})

Uses your 10 Webshare residential proxies to bypass datacenter IP block.

## Deploy on Azure B1s Free VM (1 vCPU, 1GB RAM, 750h/month free)

1. Create VM: Ubuntu 22.04, B1s size (free), open ports 80, 22
2. SSH: ssh azureuser@<ip>
3. Install Docker:
```bash
sudo apt update && sudo apt install -y docker.io docker-compose git
sudo usermod -aG docker $USER
# logout and login
```
4. Deploy:
```bash
git clone https://github.com/Yuser00123/perchance-browserless-final
cd perchance-browserless-final
sudo docker-compose up -d --build
```
5. Test:
```bash
curl http://localhost/cron
# → ok
curl -X POST http://localhost/solve -H "Content-Type: application/json" -d '{}'
# → {"status":"success","userKey":"..."}
```

Public IP: http://<your-vm-ip>/generate - unlimited free, no sleep!

## Endpoints
- GET /cron - keep alive
- GET /status - status + logs
- GET /logs - detailed logs
- POST /solve - returns userKey
- POST /generate - {"prompt":"mercury planet"} → imageBase64
