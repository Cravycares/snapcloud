# SnapCloud — Azure Photo Sharing Platform
### COM769 Scalable Advanced Software Solutions — CW2

A cloud-native, scalable photo-sharing web application built on Microsoft Azure.
Creators upload photos; consumers browse, search, comment and rate.

---

## Project Structure

```
snapcloud/
├── frontend/                   ← Azure Static Web Apps
│   ├── index.html              ← Login / Register
│   ├── creator.html            ← Creator dashboard
│   ├── consumer.html           ← Consumer feed
│   ├── staticwebapp.config.json
│   ├── css/style.css
│   └── js/app.js
└── backend/                    ← Azure App Service (Python/Flask)
    ├── app.py                  ← REST API (all endpoints)
    ├── requirements.txt
    ├── startup.sh
    └── web.config
```

---

## Azure Architecture

```
Browser
  │
  ├─► Azure Static Web Apps  ──── HTML/CSS/JS frontend
  │         │
  │         │ REST calls (/api/*)
  │         ▼
  ├─► Azure App Service ──────── Flask REST API (Python)
  │         │
  │         ├─► Azure Blob Storage ──── Photo files
  │         ├─► SQLite / CosmosDB ───── User + metadata
  │         └─► Azure Cognitive Svcs ── AI auto-tagging
  │
  └─► Azure CDN ─────────────── Cached image delivery
```

---

## Deployment Guide

### Step 1 — Resource Group
```bash
az group create --name snapcloud-rg --location uksouth
```

### Step 2 — Azure Blob Storage
```bash
az storage account create \
  --name snapcloudstorage \
  --resource-group snapcloud-rg \
  --sku Standard_LRS \
  --kind StorageV2

az storage container create \
  --name photos \
  --account-name snapcloudstorage \
  --public-access blob
```
Copy the connection string:
```bash
az storage account show-connection-string \
  --name snapcloudstorage \
  --resource-group snapcloud-rg
```

### Step 3 — Azure App Service (Backend)
```bash
az appservice plan create \
  --name snapcloud-plan \
  --resource-group snapcloud-rg \
  --sku F1 \
  --is-linux

az webapp create \
  --name snapcloud-api \
  --resource-group snapcloud-rg \
  --plan snapcloud-plan \
  --runtime "PYTHON:3.11"
```

Set environment variables:
```bash
az webapp config appsettings set \
  --name snapcloud-api \
  --resource-group snapcloud-rg \
  --settings \
    JWT_SECRET="your-secret-key-here" \
    AZURE_STORAGE_CONNECTION_STRING="<your-conn-string>" \
    AZURE_BLOB_CONTAINER="photos" \
    AZURE_COGNITIVE_KEY="<optional>" \
    AZURE_COGNITIVE_ENDPOINT="<optional>"
```

Deploy backend:
```bash
cd backend
zip -r backend.zip .
az webapp deployment source config-zip \
  --name snapcloud-api \
  --resource-group snapcloud-rg \
  --src backend.zip
```

Set startup command in Azure Portal:
```
bash /home/site/wwwroot/startup.sh
```

### Step 4 — Update API base URL in frontend
Edit `frontend/js/app.js` line 3:
```js
const API = window.API_BASE || 'https://snapcloud-api.azurewebsites.net';
```

Or set it per-page before loading app.js:
```html
<script>window.API_BASE = 'https://snapcloud-api.azurewebsites.net';</script>
```

### Step 5 — Azure Static Web Apps (Frontend)
1. Push the `frontend/` folder to a GitHub repo
2. In Azure Portal → Create Resource → Static Web App
3. Connect to your GitHub repo, set:
   - App location: `/frontend`
   - API location: *(leave blank — we have a separate App Service)*
   - Output location: `/frontend`

Or via CLI:
```bash
az staticwebapp create \
  --name snapcloud-frontend \
  --resource-group snapcloud-rg \
  --source https://github.com/<you>/<repo> \
  --branch main \
  --app-location /frontend \
  --login-with-github
```

### Step 6 — Azure CDN (Optional but recommended for scalability)
```bash
az cdn profile create \
  --name snapcloud-cdn \
  --resource-group snapcloud-rg \
  --sku Standard_Microsoft

az cdn endpoint create \
  --name snapcloud-photos \
  --profile-name snapcloud-cdn \
  --resource-group snapcloud-rg \
  --origin snapcloudstorage.blob.core.windows.net \
  --origin-host-header snapcloudstorage.blob.core.windows.net
```

---

## Local Development

```bash
# Backend
cd backend
pip install -r requirements.txt
python app.py

# Open frontend
open frontend/index.html
# Or serve with:
python -m http.server 8080 --directory frontend
```

The app uses SQLite locally — no Azure account needed for development.

---

## Demo Credentials

| Role     | Email                 | Password  |
|----------|-----------------------|-----------|
| Creator  | creator@demo.com      | demo1234  |
| Consumer | consumer@demo.com     | demo1234  |

---

## REST API Reference

| Method | Endpoint                         | Auth      | Description              |
|--------|----------------------------------|-----------|--------------------------|
| POST   | /api/auth/register               | None      | Register consumer        |
| POST   | /api/auth/login                  | None      | Login, returns JWT       |
| GET    | /api/photos                      | None      | List/search photos       |
| POST   | /api/photos                      | Creator   | Upload photo             |
| GET    | /api/photos/:id                  | None      | Get photo detail         |
| PUT    | /api/photos/:id                  | Creator   | Edit own photo           |
| DELETE | /api/photos/:id                  | Creator   | Delete own photo         |
| GET    | /api/photos/mine                 | Creator   | My uploads               |
| GET    | /api/photos/:id/comments         | None      | Get comments             |
| POST   | /api/photos/:id/comments         | Consumer  | Post comment             |
| POST   | /api/photos/:id/rate             | Consumer  | Rate 1–5                 |
| GET    | /api/creators                    | None      | List creators (sidebar)  |

---

## Advanced Features (for CW2 marking criteria)

1. **Azure Cognitive Services** — Computer Vision auto-tags uploaded photos
   (configure `AZURE_COGNITIVE_KEY` and `AZURE_COGNITIVE_ENDPOINT`)

2. **Azure CDN** — Serves blob images through CDN for fast global delivery and caching

3. **Role-based auth** — JWT tokens with creator/consumer roles enforced at API level

---

## Scalability Notes

- **App Service** can scale out to multiple instances via Azure Auto Scale rules
- **Blob Storage** is infinitely scalable for media files
- **Azure CDN** reduces origin load by caching images at edge nodes globally
- **SQLite** is for dev only — swap to **Azure Cosmos DB** or **Azure SQL** for production scale
- **Traffic Manager** can route across multiple App Service regions for geo-redundancy
