# Annatel IPTV for Kodi

A Kodi service addon that automatically fetches your [Annatel](https://www.annatel.tv) IPTV channel list and loads it into Kodi's TV menu.

**Only two settings required: username and password.** Everything else is automatic.

---

## How it works

1. At startup the addon calls the Annatel API with your credentials
2. Writes a local M3U playlist of all your channels
3. Configures and reloads [IPTV Simple Client](https://github.com/kodi-pvr/pvr.iptvsimple) automatically
4. Refreshes every 4 hours

---

## Requirements

- Kodi 20 (Nexus) or 21 (Omega)
- [IPTV Simple Client](https://kodi.wiki/view/Add-on:PVR_IPTV_Simple_Client) (`pvr.iptvsimple`) — installed automatically as a dependency
- A valid Annatel subscription

---

## Installation

### Linux (local)

```bash
bash install.sh
```

Then restart Kodi.

### Android TV (or any device without a terminal)

1. Build the installable zip:
   ```bash
   bash package.sh
   ```
   Output: `dist/service.annatel-<version>.zip`

2. Copy the zip to a USB stick (or serve it with `python3 -m http.server 8080`)

3. In Kodi on your Android TV:
   - **Settings → System → Add-ons → Unknown sources** → On
   - **Add-ons → Install from zip** → navigate to `service.annatel-<version>.zip`

### From a GitHub release

Download `service.annatel-<version>.zip` from the [Releases](../../releases) page and install via **Add-ons → Install from zip**.

---

## Configuration

After enabling the addon:

1. **Add-ons → My add-ons → Services → Annatel IPTV → Configure**
2. Enter your Annatel **username** and **password**
3. Click OK — channels load within a few seconds

The TV menu will appear in Kodi's main menu automatically once channels are loaded.

---

## Project structure

```
annatel-kodi/
├── addon/
│   └── service.annatel/
│       ├── addon.xml               Kodi addon manifest
│       ├── addon.py                Service logic (API fetch, M3U write, pvr config)
│       └── resources/
│           ├── settings.xml        Username + password settings
│           └── language/
│               └── resource.language.en_gb/strings.po
├── dist/                           Built zips (gitignored)
├── install.sh                      Install to ~/.kodi/addons/ (Linux)
└── package.sh                      Build installable zip
```

---

## Troubleshooting

**Channels not loading after entering credentials**
- Check the Kodi log: `~/.kodi/temp/kodi.log`
- Filter for: `grep -i "annatel\|iptvsimple\|error" ~/.kodi/temp/kodi.log`

**"Invalid username or password" notification**
- Verify your credentials at [annatel.tv](https://www.annatel.tv)
- The API uses plain HTTP — make sure no firewall/proxy is blocking it

**TV menu not visible in Kodi**
- Go to **Settings → PVR & Live TV → General → Enable** and restart Kodi

**Android TV crash on startup**
- Make sure you are running Kodi 20+ (the addon requires Python 3)
