# How to Run CheckerAI on Windows

This guide is designed for a completely fresh Windows computer. You do **NOT** need Python, Node.js, or any other developer tools installed — everything runs inside Docker containers.

---

## Step 1: Install Docker Desktop

Docker Desktop bundles everything you need (database, backend, frontend) into isolated containers.

1. Go to [https://docs.docker.com/desktop/install/windows-install/](https://docs.docker.com/desktop/install/windows-install/) and download **Docker Desktop for Windows**.
2. Run the installer and keep all default settings.
   - If prompted, make sure **"Use WSL 2 instead of Hyper-V"** is selected (recommended).
3. Restart your computer if required.
4. Open the **Docker Desktop** app. Wait until the whale icon in the taskbar is steady (not animating) — that means Docker is ready.

---

## Step 2: Get the Project

1. Go to this project's GitHub page.
2. Click the green **Code** button → **Download ZIP**.
3. Extract the ZIP to a folder on your computer (e.g. `C:\Users\YourName\Desktop\CheckerAI`).

> **Important:** Make sure the extracted folder contains `docker-compose.yml`, `All_Paper_JSONs\`, and `frontend\` at the top level.

---

## Step 3: Add Your API Keys

The application needs two API keys to function:

| Key | Where to get it |
|---|---|
| `OPENAI_API_KEY` | [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `ANTHROPIC_API_KEY` | [https://console.anthropic.com/](https://console.anthropic.com/) |

**How to set the keys:**

1. Inside the extracted `CheckerAI` folder, find the file named **`.env.example`**.
2. Copy it and rename the copy to **`.env`** (just `.env`, nothing else).
   - *Tip for Windows:* Open Notepad, paste the contents, fill in your keys, then **File → Save As** → set "Save as type" to **All Files** → name it `.env`.
3. Open `.env` with Notepad and replace the placeholder values:

```
OPENAI_API_KEY=sk-proj-YOUR_ACTUAL_OPENAI_KEY
ANTHROPIC_API_KEY=sk-ant-YOUR_ACTUAL_ANTHROPIC_KEY
```

4. Save and close.

---

## Step 4: Start the Application

1. Open **Command Prompt** (press `Win + R`, type `cmd`, press Enter).
2. Navigate to the project folder:
   ```cmd
   cd C:\Users\YourName\Desktop\CheckerAI
   ```
   *(Replace the path with wherever you extracted the ZIP.)*
3. Run:
   ```cmd
   docker compose up -d --build
   ```
4. Docker will build and start all services. **The first run takes 5–15 minutes** (downloading images, installing dependencies). You'll see lines like:
   ```
   ✔ Container checkerai-db          Started
   ✔ Container checkerai-backend     Started
   ✔ Container setterai-backend      Started
   ✔ Container mentorai-backend      Started
   ✔ Container checkerai-frontend    Started
   ```

---

## Step 5: Open the App

1. Open Chrome, Edge, or any browser.
2. Go to: **[http://localhost](http://localhost)**
3. The CheckerAI interface will load automatically.

---

## Everyday Usage

| Task | Command |
|---|---|
| Start app | `docker compose up -d` |
| Stop app | `docker compose down` |
| View live logs | `docker compose logs -f checker-backend` |
| Rebuild after a git pull | `docker compose up -d --build` |

---

## Troubleshooting

**"Port 80 is already in use"**
Another app (e.g. IIS, Skype) is using port 80. Stop it or change the frontend port in `docker-compose.yml` from `"80:80"` to e.g. `"8080:80"`, then access the app at `http://localhost:8080`.

**"Docker Desktop is not running"**
Open Docker Desktop from the Start menu and wait for it to fully start before running `docker compose up`.

**Grading is very slow the first time**
This is normal — the AI models need to be initialised. Subsequent gradings on the same paper will be faster.

**"Error: ANTHROPIC_API_KEY is not set"**
Make sure your `.env` file (not `.env.example`) exists in the root `CheckerAI` folder and contains a valid `ANTHROPIC_API_KEY`.
