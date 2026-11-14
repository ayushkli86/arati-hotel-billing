# Sync Arati Hotel Billing to New Windows Machine

Run these commands in **PowerShell (Admin)** on the new Windows computer:

---

## 1. One-Command Full Setup (Recommended)

```powershell
# Clone and setup everything in one go
git clone https://github.com/ayushkli86/arati-hotel-billing.git
cd arati-hotel-billing
.\scripts\setup-windows.ps1
```

This script:
- Installs Python 3.11 + Tcl/Tk + Git (via winget)
- Creates virtual environment
- Installs all Python deps (desktop + web)
- Runs database migrations
- Seeds catalog (rooms, dishes, services)
- Builds Windows standalone exe (`AratiHotel.exe`)
- Creates Start Menu shortcuts

---

## 2. Manual Step-by-Step (If Script Fails)

```powershell
# 1. Clone repo
git clone https://github.com/ayushkli86/arati-hotel-billing.git
cd arati-hotel-billing

# 2. Install Python 3.11 (if not installed)
winget install Python.Python.3.11

# 3. Create venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install -r webapp/requirements.txt

# 5. Initialize database (runs migrations + seeds)
python -m arati.db

# 6. Run desktop app
python app.py

# 7. Run web app (separate terminal)
.\run_web.ps1
# Opens http://127.0.0.1:8000/billing/create
```

---

## 3. Pull Latest Changes Later

```powershell
cd arati-hotel-billing
git pull origin main
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r webapp/requirements.txt
python -m arati.db  # Runs any new migrations
```

---

## 4. Kotlin/Flutter Mobile App (arati_kot_mobile)

The mobile app is a **separate Flutter project** in `arati_kot_mobile/`. It connects to the **webapp API** (FastAPI), not directly to the desktop database.

### Setup Mobile App on Windows:

```powershell
# 1. Install Flutter
winget install Flutter.Flutter

# 2. Install Android Studio (for emulator) or use physical device
winget install Google.AndroidStudio

# 3. Setup Flutter doctor
flutter doctor --android-licenses
flutter doctor

# 4. Build mobile app
cd arati_kot_mobile
flutter pub get
flutter run -d windows   # Run on Windows desktop
flutter run -d android   # Run on Android emulator/device
flutter run -d chrome    # Run as web app
```

### Connect Mobile to Backend:

1. **Start the webapp API** on your Windows machine:
   ```powershell
   cd arati-hotel-billing
   .\run_web.ps1
   # API runs at http://127.0.0.1:8000
   ```

2. **Find your Windows LAN IP**:
   ```powershell
   ipconfig | findstr IPv4
   # e.g., 192.168.1.45
   ```

3. **Update mobile app API base URL** in `arati_kot_mobile/lib/config/api_config.dart`:
   ```dart
   // Change from localhost to your LAN IP
   static const String baseUrl = 'http://192.168.1.45:8000/api/v1';
   ```

4. **Allow Windows Firewall** for port 8000:
   ```powershell
   New-NetFirewallRule -DisplayName "Arati WebAPI" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
   ```

5. **Test from mobile**: Open `http://192.168.1.45:8000/docs` in phone browser — should see FastAPI Swagger UI.

---

## 5. Database Sync Notes

| Component | Database | Sync Method |
|-----------|----------|-------------|
| **Desktop app** | SQLite (`arati.db`) | Local file — copy `%LOCALAPPDATA%\AratiHotel\Billing\arati.db` between machines |
| **Webapp** | SQLAlchemy (SQLite by default) | `webapp/arati_web.db` — separate from desktop |
| **Mobile app** | None (client-only) | Consumes webapp REST API |

**To share data between desktop and webapp:** They use separate databases by design. If you need sync, export/import via Reports → CSV, or build a sync service.

---

## 6. Quick Test Checklist

After setup, verify:

- [ ] Desktop app launches: `python app.py` → login `admin` / `arat123`
- [ ] Create test invoice → prints PDF → thermal receipt works
- [ ] Webapp loads: `http://127.0.0.1:8000/billing/create` → login `admin` / `admin123`
- [ ] Mobile app connects to `http://<LAN_IP>:8000/api/v1`
- [ ] Room Board shows 25 rooms (101–125)
- [ ] Daily close runs: `python scripts/close_day.py --catch-up`

---

## 7. For Your AI Agent (Copy-Paste Prompt)

> **Prompt for AI agent on new Windows machine:**
> 
> "Set up the Arati Hotel Billing project from GitHub. Clone `https://github.com/ayushkli86/arati-hotel-billing.git`, run the Windows setup script (`.\scripts\setup-windows.ps1`), then verify the desktop app launches and the webapp serves at `http://127.0.0.1:8000`. Also set up the Flutter mobile app in `arati_kot_mobile/` and connect it to the local webapp API. Run `flutter doctor` first, then `flutter pub get` and `flutter run -d windows`. Update the mobile app's API base URL to the machine's LAN IP so it can talk to the FastAPI backend."