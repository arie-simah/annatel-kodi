"""
Annatel IPTV — Kodi service addon

Fetches the Annatel channel list, writes an M3U playlist to the addon
profile directory, then configures and reloads pvr.iptvsimple automatically.
Refreshes every 4 hours.  Only settings: username + password.
"""

import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

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

        with open(M3U_PATH, 'w', encoding='utf-8') as fh:
            fh.writelines(lines)

        return len(channels)


# ---------------------------------------------------------------------------
# IptvSimple — pvr.iptvsimple configurator
# ---------------------------------------------------------------------------

class IptvSimple:
    """Configures pvr.iptvsimple to use the generated M3U and reloads it."""

    # Settings written to pvr.iptvsimple (string values as Kodi expects them).
    _SETTINGS: dict[str, str] = {
        # M3U source — local file, no remote URL, no auto-refresh (we handle it)
        'm3uPathType':      '0',        # 0 = local file
        'm3uPath':          M3U_PATH,
        'm3uUrl':           '',
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
        """Write settings via both the xbmcaddon API (Kodi 19) and direct XML
        (Kodi 20+ multi-instance).  Both are idempotent and harmless to run."""
        self._configure_via_addon_api()
        self._configure_via_instance_xml()

    def _configure_via_addon_api(self) -> None:
        """xbmcaddon.Addon.setSetting() writes to settings.xml and triggers
        pvr.iptvsimple's migration path on Kodi 20+."""
        try:
            iptv_addon = xbmcaddon.Addon(IPTVSIMPLE_ID)
            for key, value in self._SETTINGS.items():
                iptv_addon.setSetting(key, value)
        except Exception as exc:  # noqa: BLE001
            xbmc.log(f'[{ADDON_ID}] xbmcaddon configure: {exc}', xbmc.LOGWARNING)

    def _configure_via_instance_xml(self) -> None:
        """Write instance-settings-1.xml for Kodi 20+ multi-instance PVR."""
        settings_dir = xbmcvfs.translatePath('special://userdata/addon_data/pvr.iptvsimple/')
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, 'instance-settings-1.xml')

        lines: list[str] = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n',
            '<settings version="2">\n',
        ]
        for key, value in self._SETTINGS.items():
            escaped = (
                value
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
            )
            lines.append(f'    <setting id="{key}">{escaped}</setting>\n')
        lines.append('</settings>\n')

        try:
            with open(settings_path, 'w', encoding='utf-8') as fh:
                fh.writelines(lines)
        except OSError as exc:
            xbmc.log(f'[{ADDON_ID}] instance-settings write: {exc}', xbmc.LOGWARNING)

    # ------------------------------------------------------------------

    def enable(self) -> None:
        self._rpc('Addons.SetAddonEnabled', {'addonid': IPTVSIMPLE_ID, 'enabled': True})

    def force_reload(self) -> None:
        """Disable then re-enable pvr.iptvsimple so it re-reads the M3U."""
        self._rpc('Addons.SetAddonEnabled', {'addonid': IPTVSIMPLE_ID, 'enabled': False})
        xbmc.sleep(2000)
        self._rpc('Addons.SetAddonEnabled', {'addonid': IPTVSIMPLE_ID, 'enabled': True})


# ---------------------------------------------------------------------------
# Service — main loop
# ---------------------------------------------------------------------------

class Service:
    def __init__(self) -> None:
        self._settings_changed = False
        monitor = xbmc.Monitor()
        monitor.onSettingsChanged = self._on_settings_changed
        self.monitor = monitor

    def _on_settings_changed(self) -> None:
        """Called by Kodi immediately when the user saves addon settings."""
        self._settings_changed = True

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

        iptv = IptvSimple()
        iptv.configure()
        iptv.enable()
        iptv.force_reload()

        self._notify(f'{count} channels loaded')

    # ------------------------------------------------------------------

    def run(self) -> None:
        self._log('Service starting')

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
                if self._settings_changed:
                    self._settings_changed = False
                    self._log('Settings changed — refreshing now')
                    break
                self.monitor.waitForAbort(5)
                waited += 5

        self._log('Service stopped')


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    Service().run()
