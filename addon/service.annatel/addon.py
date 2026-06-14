"""
Annatel IPTV — Kodi service addon

Fetches the Annatel channel list, writes an M3U playlist to the addon
profile directory, serves it over a local HTTP URL, then configures and
reloads pvr.iptvsimple automatically.
Refreshes every 4 hours.  Only settings: username + password.
"""

import json
import os
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

# ---------------------------------------------------------------------------
# Module-level constants (evaluated once at startup)
# ---------------------------------------------------------------------------

_ADDON = xbmcaddon.Addon()
ADDON_ID = _ADDON.getAddonInfo('id')
ADDON_NAME = _ADDON.getAddonInfo('name')
PROFILE_DIR = xbmcvfs.translatePath(_ADDON.getAddonInfo('profile'))
M3U_PATH = os.path.join(PROFILE_DIR, 'channels.m3u')

CHANNELS_API = 'http://www.annatel.tv/api/getchannels'
IPTVSIMPLE_ID = 'pvr.iptvsimple'
REFRESH_INTERVAL = 4 * 60 * 60          # seconds
INVALID_CREDS_MARKER = 'un utilisateur premium pour utiliser'


# ---------------------------------------------------------------------------
# Annatel — API client & M3U writer
# ---------------------------------------------------------------------------

class Annatel:
    """Fetches the Annatel channel list and writes an M3U playlist file."""

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password

    # ------------------------------------------------------------------

    def _fetch_xml(self) -> ET.Element:
        params = urllib.parse.urlencode({'login': self.username, 'password': self.password})
        url = f'{CHANNELS_API}?{params}'
        req = urllib.request.Request(
            url,
            headers={'User-Agent': f'Kodi/{xbmc.getInfoLabel("System.BuildVersion")} AnnatelIPTV/1.0'},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        return ET.fromstring(raw)

    # ------------------------------------------------------------------

    def fetch_channels(self) -> list[dict]:
        """Return list of channel dicts: {name, logo, url}.

        Raises PermissionError for invalid credentials.
        Raises RuntimeError for an empty or unrecognised API response.
        """
        root = self._fetch_xml()
        channels: list[dict] = []

        for ch in root.findall('channel'):
            name = (ch.findtext('name') or '').strip()
            logo = (ch.findtext('logo') or '').strip()
            stream_url = (ch.findtext('url') or '').strip()

            if not stream_url:
                continue

            # The Annatel API returns an error message as a channel name when
            # credentials are wrong.
            if INVALID_CREDS_MARKER in name:
                raise PermissionError('Invalid Annatel credentials')

            channels.append({'name': name, 'logo': logo, 'url': stream_url})

        if not channels:
            raise RuntimeError('Channel list is empty — check your subscription')

        return channels

    # ------------------------------------------------------------------

    def generate_m3u_file(self) -> int:
        """Fetch channels, write M3U, return channel count."""
        channels = self.fetch_channels()

        os.makedirs(PROFILE_DIR, exist_ok=True)

        lines: list[str] = ['#EXTM3U\n']
        for ch in channels:
            lines.append(f'#EXTINF:-1 tvg-logo="{ch["logo"]}",{ch["name"]}\n')
            lines.append(f'{ch["url"]}\n')

        # Write atomically so the HTTP handler below never serves a half-written file.
        tmp_path = f'{M3U_PATH}.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as fh:
            fh.writelines(lines)
        os.replace(tmp_path, M3U_PATH)

        return len(channels)


# ---------------------------------------------------------------------------
# M3U HTTP server
# ---------------------------------------------------------------------------

class _M3UHandler(BaseHTTPRequestHandler):
    """Serves channels.m3u over loopback HTTP.

    pvr.iptvsimple can run as a separate sandboxed process (notably on
    Android, where binary add-ons cannot read files under another add-on's
    special://profile directory). A local HTTP URL works regardless of
    filesystem sandboxing, so we hand pvr.iptvsimple a URL instead of a
    file path — this is what previously required manually copying
    channels.m3u into Android/media after every refresh.
    """

    def do_GET(self) -> None:
        try:
            with open(M3U_PATH, 'rb') as fh:
                body = fh.read()
        except OSError:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header('Content-Type', 'audio/x-mpegurl')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — silence default access log
        pass


# ---------------------------------------------------------------------------
# IptvSimple — pvr.iptvsimple configurator
# ---------------------------------------------------------------------------

class IptvSimple:
    """Configures pvr.iptvsimple to use the generated M3U and reloads it."""

    def __init__(self, m3u_url: str) -> None:
        self.m3u_url = m3u_url

    # ------------------------------------------------------------------

    def _settings(self) -> dict[str, str]:
        """Settings written to pvr.iptvsimple (string values as Kodi expects them)."""
        return {
            # M3U source — fetched over loopback HTTP from our own service,
            # no auto-refresh (we handle it via force_reload)
            'm3uPathType':      '1',        # 1 = remote URL
            'm3uPath':          '',
            'm3uUrl':           self.m3u_url,
            'm3uCache':         'false',
            'm3uRefreshMode':   '0',        # 0 = disabled
            # EPG — disabled
            'epgPathType':      '0',
            'epgPath':          '',
            'epgUrl':           '',
            'epgCache':         'false',
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _rpc(method: str, params: dict) -> dict:
        payload = json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1})
        return json.loads(xbmc.executeJSONRPC(payload))

    # ------------------------------------------------------------------

    def configure(self) -> None:
        """Write settings via xbmcaddon API (writes to pvr.iptvsimple/settings.xml).
        Also removes any empty instance-settings-*.xml that would shadow global settings."""
        self._configure_via_addon_api()
        self._remove_empty_instance_settings()

    def _configure_via_addon_api(self) -> None:
        try:
            iptv_addon = xbmcaddon.Addon(IPTVSIMPLE_ID)
            for key, value in self._settings().items():
                iptv_addon.setSetting(key, value)
        except Exception as exc:  # noqa: BLE001
            xbmc.log(f'[{ADDON_ID}] configure: {exc}', xbmc.LOGWARNING)

    def _remove_empty_instance_settings(self) -> None:
        """Delete any instance-settings-*.xml that have no settings inside.
        An empty instance XML overrides global settings.xml and results in 0 channels."""
        settings_dir = xbmcvfs.translatePath('special://userdata/addon_data/pvr.iptvsimple/')
        import glob
        for path in glob.glob(os.path.join(settings_dir, 'instance-settings-*.xml')):
            try:
                tree = ET.parse(path)
                if len(tree.getroot()) == 0:          # no <setting> children
                    os.remove(path)
                    xbmc.log(f'[{ADDON_ID}] Removed empty {os.path.basename(path)}', xbmc.LOGINFO)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------

    def enable(self) -> None:
        self._rpc('Addons.SetAddonEnabled', {'addonid': IPTVSIMPLE_ID, 'enabled': True})

    def force_reload(self) -> None:
        """Disable then re-enable pvr.iptvsimple so it re-reads the M3U.
        The empty instance-settings-*.xml must be removed BEFORE re-enabling
        so pvr.iptvsimple falls back to settings.xml (which has the M3U path)."""
        self._rpc('Addons.SetAddonEnabled', {'addonid': IPTVSIMPLE_ID, 'enabled': False})
        xbmc.sleep(2000)
        self._remove_empty_instance_settings()   # critical: remove before re-enable
        self._rpc('Addons.SetAddonEnabled', {'addonid': IPTVSIMPLE_ID, 'enabled': True})
        xbmc.sleep(3000)                          # give PVR Manager time to sync channels


# ---------------------------------------------------------------------------
# Service — main loop
# ---------------------------------------------------------------------------

class _Monitor(xbmc.Monitor):
    def __init__(self) -> None:
        super().__init__()
        self.settings_changed = False

    def onSettingsChanged(self) -> None:  # noqa: N802 — Kodi callback name
        self.settings_changed = True


class Service:
    def __init__(self) -> None:
        self.monitor = _Monitor()

        # Bind to an OS-assigned loopback port; re-announced to pvr.iptvsimple
        # on every refresh, so a new port after a Kodi restart is picked up.
        self.http_server = HTTPServer(('127.0.0.1', 0), _M3UHandler)
        self.m3u_url = f'http://127.0.0.1:{self.http_server.server_address[1]}/channels.m3u'
        threading.Thread(target=self.http_server.serve_forever, daemon=True).start()

    # ------------------------------------------------------------------

    def _log(self, message: str, level: int = xbmc.LOGINFO) -> None:
        xbmc.log(f'[{ADDON_ID}] {message}', level)

    def _notify(self, message: str, icon: str = xbmcgui.NOTIFICATION_INFO) -> None:
        xbmcgui.Dialog().notification(ADDON_NAME, message, icon, 5000)

    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """One full cycle: fetch → write M3U → configure + reload iptvsimple."""
        addon = xbmcaddon.Addon()           # re-read settings every cycle
        username = addon.getSetting('username').strip()
        password = addon.getSetting('password').strip()

        if not username or not password:
            self._log('Credentials not set — open addon settings to configure', xbmc.LOGWARNING)
            return

        count = Annatel(username, password).generate_m3u_file()
        self._log(f'M3U written: {count} channels')

        iptv = IptvSimple(self.m3u_url)
        iptv.configure()
        iptv.enable()
        iptv.force_reload()

        self._notify(f'{count} channels loaded')

    # ------------------------------------------------------------------

    def run(self) -> None:
        self._log('Service starting')
        self._log(f'Serving M3U at {self.m3u_url}')

        while not self.monitor.abortRequested():
            try:
                self._refresh()
            except PermissionError as exc:
                self._log(str(exc), xbmc.LOGWARNING)
                self._notify('Invalid username or password — open addon settings',
                              xbmcgui.NOTIFICATION_ERROR)
            except Exception as exc:  # noqa: BLE001
                self._log(f'Refresh failed: {exc}', xbmc.LOGWARNING)
                self._notify('Failed to load channels — check Kodi log',
                              xbmcgui.NOTIFICATION_ERROR)

            # Wait up to 4 hours, but wake immediately if settings changed or Kodi exits.
            waited = 0
            while waited < REFRESH_INTERVAL and not self.monitor.abortRequested():
                if self.monitor.settings_changed:
                    self.monitor.settings_changed = False
                    self._log('Settings changed — refreshing now')
                    break
                self.monitor.waitForAbort(5)
                waited += 5

        self.http_server.shutdown()
        self._log('Service stopped')


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    Service().run()
