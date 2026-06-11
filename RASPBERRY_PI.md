# Raspberry Pi setup

Use a Python virtual environment. Do not install the Python libraries through apt unless you specifically want system-wide packages.

## 1. Install system packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

BeautifulSoup's Debian package is called `python3-bs4`, not `python3-beautifulsoup4`. You usually do not need it because `pip install -r requirements.txt` installs `beautifulsoup4` into the venv.

```bash
sudo apt install -y python3-bs4
```

## 2. Create the venv and install Python dependencies

```bash
cd /home/timoh/bots/WGModsStatistics
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 3. Install Chromium

On Raspberry Pi OS, Playwright's bundled browser install may not work on ARM. Use system Chromium instead.

Try one of these:

```bash
sudo apt install -y chromium-browser
```

or, on newer Raspberry Pi OS/Debian versions:

```bash
sudo apt install -y chromium
```

Find the Chromium path:

```bash
which chromium-browser || which chromium
```

Then set it in `config.json`:

```json
"browser": {
  "headless": true,
  "slow_mo_ms": 0,
  "navigation_timeout_ms": 60000,
  "executable_path": "/usr/bin/chromium-browser",
  "args": ["--no-sandbox", "--disable-dev-shm-usage"]
}
```

If your Pi returns `/usr/bin/chromium`, use that instead.

## 4. Run

```bash
source .venv/bin/activate
python main.py snapshot
```

## Notes

If `pip install playwright` says there is no matching distribution, check:

```bash
uname -m
python3 --version
```

A 32-bit Raspberry Pi OS can cause trouble. Prefer a 64-bit Raspberry Pi OS where `uname -m` returns `aarch64`.
