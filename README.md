# Hookem Attendance

Students scan a QR code and enter their UT EID and name. The dashboard shows check-ins, attendance rates, and students missing meetings. Includes CSV roster import and attendance export.

## Setup once

Download and extract this repository. Install **Python 3.10+** and [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/). Dependencies are bundled; no pip install is needed.

## Start each meeting

1. In the app folder, double-click **START_WINDOWS.bat**, or run:

   ```powershell
   python app.py
   ```

   Keep the terminal open. The dashboard opens automatically; otherwise use the private **Organizer** link printed in the terminal.

2. In a second terminal, start Cloudflare. Use the actual path to your downloaded executable, for example:

   ```powershell
   & "$env:USERPROFILE\Desktop\cloudflared-windows-amd64.exe" tunnel --url http://localhost:8765
   ```

3. Copy the **Cloudflare HTTPS address** ending in `.trycloudflare.com` (a URL, not an IP). In the dashboard, expand **Phone connection & meeting history**, paste it into **Phone-accessible address**, and click **Update QR address**. Repeat each time you restart the tunnel because its address changes.
4. Import your roster **before starting the meeting**. CSV headers: `eid,name` (see `sample_roster.csv`). Without a roster, the app cannot identify members who never check in.
5. Enter a title, click **Start meeting**, and display the QR. Keep the laptop awake, online, and both terminals running during check-in. Students can use any internet connection.
6. Click **Close meeting**, optionally **Export CSV**, then press **Ctrl+C** in both terminals.

## Saved records

Check-ins save immediately to `data/attendance.sqlite3` on the host laptop. Restarting loads the same records. Stop the app before copying that file to back up or transfer records. To start fresh, stop the app and rename the database; the next launch creates an empty one. Records are excluded from Git.

Quick Tunnels are suitable for a pilot and have no uptime guarantee. Attendance is self-reported; UT identities are not verified. Keep the organizer link private.

## Development

```powershell
python -m unittest discover -s tests -v
```

Optional dashboard checks: `node tests/test_dashboard.cjs`. Build a clean shareable ZIP: `python package_app.py`.
