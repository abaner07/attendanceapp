"""Local, portable meeting attendance. Python 3.10+; dependencies bundled."""
import argparse
import csv
from contextlib import contextmanager
import hmac
import io
import json
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import webbrowser

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
import qrcode
import qrcode.image.svg


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


class Store:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS students (
                    eid TEXT PRIMARY KEY, name TEXT NOT NULL, since INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    created TEXT NOT NULL, token TEXT UNIQUE NOT NULL, open INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS attendance (
                    meeting_id INTEGER REFERENCES meetings(id), eid TEXT REFERENCES students(eid),
                    checked_at TEXT NOT NULL, PRIMARY KEY(meeting_id,eid));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def student(eid, name):
        eid, name = str(eid).strip().lower(), ' '.join(str(name).split())
        if not re.fullmatch(r'[a-z][a-z0-9]{1,19}', eid):
            raise ValueError('Enter a UT EID (2–20 letters and numbers, starting with a letter).')
        if not 2 <= len(name) <= 100:
            raise ValueError('Enter your full name (2–100 characters).')
        return eid, name

    def add_students(self, rows):
        cleaned = [self.student(r.get('eid', ''), r.get('name', '')) for r in rows]
        if not cleaned:
            raise ValueError('No students found. CSV headers must be eid,name.')
        with self.connect() as db:
            baseline = db.execute('SELECT COALESCE(MAX(id),0) FROM meetings').fetchone()[0] + 1
            db.executemany('INSERT INTO students VALUES (?,?,?) ON CONFLICT(eid) DO UPDATE SET name=excluded.name',
                           [(eid, name, baseline) for eid, name in cleaned])
        return len(cleaned)

    def create_meeting(self, title):
        title = str(title).strip()
        if not 1 <= len(title) <= 120:
            raise ValueError('Give the meeting a title (up to 120 characters).')
        with self.connect() as db:
            db.execute('UPDATE meetings SET open=0')
            db.execute('INSERT INTO meetings(title,created,token,open) VALUES (?,?,?,1)',
                       (title, now(), secrets.token_urlsafe(24)))

    def checkin(self, token, eid, name):
        eid, name = self.student(eid, name)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            meeting = db.execute('SELECT * FROM meetings WHERE token=? AND open=1', (token,)).fetchone()
            if not meeting:
                raise ValueError('This check-in is closed. Ask the organizer for the current QR code.')
            db.execute('INSERT OR IGNORE INTO students VALUES (?,?,?)', (eid, name, meeting['id']))
            result = db.execute('INSERT OR IGNORE INTO attendance VALUES (?,?,?)', (meeting['id'], eid, now()))
            return {'message': 'Attendance recorded. You’re all set!' if result.rowcount else 'You’re already checked in for this meeting.'}

    def snapshot(self):
        with self.connect() as db:
            meetings = [dict(r) for r in db.execute('SELECT * FROM meetings ORDER BY id DESC')]
            students = [dict(r) for r in db.execute('SELECT * FROM students ORDER BY name COLLATE NOCASE')]
            attendance = [dict(r) for r in db.execute('SELECT * FROM attendance')]
        return {'meetings': meetings, 'students': students, 'attendance': attendance}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not log student identities or secret QR/admin URLs.

    def reply(self, status, body, content_type='application/json', headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def admin(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            return hmac.compare_digest(cookie['attendance_admin'].value, self.server.secret)
        except (KeyError, ValueError):
            return False

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/admin':
            key = parse_qs(parsed.query).get('key', [''])[0]
            # Bootstrap dashboard access only from the host laptop.
            if self.client_address[0] in ('127.0.0.1', '::1') and hmac.compare_digest(key, self.server.secret):
                return self.reply(303, '', headers={'Location': '/', 'Set-Cookie': f'attendance_admin={key}; HttpOnly; SameSite=Strict; Path=/'})
            return self.reply(403, {'error': 'Open the organizer link printed on the host laptop.'})
        if path in ('/api/state', '/api/export', '/api/qr'):
            if not self.admin():
                return self.reply(403, {'error': 'Organizer access required. Use the link printed in the terminal.'})
            state = self.server.store.snapshot()
            if path == '/api/state':
                return self.reply(200, {**state, 'base_url': self.server.base_url})
            if path == '/api/qr':
                active = next((m for m in state['meetings'] if m['open']), None)
                if not active:
                    return self.reply(404, {'error': 'Start a meeting first.'})
                qr = qrcode.make(self.server.base_url + '/checkin/' + active['token'], image_factory=qrcode.image.svg.SvgPathImage)
                output = io.BytesIO()
                qr.save(output)
                return self.reply(200, output.getvalue(), 'image/svg+xml')
            output = io.StringIO(newline='')
            writer = csv.writer(output)
            meetings = list(reversed(state['meetings']))
            writer.writerow(['eid', 'name'] + [m['title'] + ' (' + m['created'][:10] + ')' for m in meetings])
            checked = {(a['eid'], a['meeting_id']) for a in state['attendance']}
            def safe(value):
                return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r')) else value
            for s in state['students']:
                writer.writerow([s['eid'], safe(s['name'])] + [
                    'Present' if (s['eid'], m['id']) in checked else
                    'Not on roster' if m['id'] < s['since'] else
                    'Not yet checked in' if m['open'] else 'Absent' for m in meetings])
            return self.reply(200, '\ufeff' + output.getvalue(), 'text/csv; charset=utf-8', {'Content-Disposition': 'attachment; filename="attendance.csv"'})
        if path.startswith('/api/meeting/'):
            token = path.rsplit('/', 1)[-1]
            with self.server.store.connect() as db:
                m = db.execute('SELECT title,open FROM meetings WHERE token=?', (token,)).fetchone()
            return self.reply(200 if m else 404, dict(m) if m else {'error': 'Meeting not found.'})
        files = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/checkin.js': 'checkin.js'}
        filename = 'checkin.html' if path.startswith('/checkin/') else files.get(path)
        if not filename:
            return self.reply(404, {'error': 'Page not found.'})
        mime = 'text/html; charset=utf-8' if filename.endswith('.html') else 'text/css' if filename.endswith('.css') else 'text/javascript'
        return self.reply(200, (ROOT / 'static' / filename).read_bytes(), mime)

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1_000_000:
                return self.reply(413, {'error': 'Request too large or empty.'})
            if self.headers.get('X-Attendance-Request') != '1':
                return self.reply(403, {'error': 'Use the attendance app to submit this request.'})
            if self.path != '/api/checkin' and not self.admin():
                return self.reply(403, {'error': 'Organizer access required.'})
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Invalid request.')
            store = self.server.store
            if self.path == '/api/checkin':
                result = store.checkin(str(data.get('token', '')), data.get('eid', ''), data.get('name', ''))
                return self.reply(200, result)
            if self.path == '/api/students':
                rows = data.get('students', [])
                if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                    raise ValueError('Invalid student roster.')
                count = store.add_students(rows)
                return self.reply(200, {'message': f'Saved {count} student(s).'})
            if self.path == '/api/import':
                content = str(data.get('csv', '')).lstrip('\ufeff')
                reader = csv.DictReader(io.StringIO(content))
                if reader.fieldnames:
                    reader.fieldnames = [f.strip().lower() for f in reader.fieldnames]
                count = store.add_students(list(reader))
                return self.reply(200, {'message': f'Imported {count} student(s).'})
            if self.path == '/api/meetings':
                store.create_meeting(data.get('title', ''))
            elif self.path == '/api/close':
                with store.connect() as db:
                    db.execute('UPDATE meetings SET open=0')
            elif self.path == '/api/settings':
                base = str(data.get('base_url', '')).strip().rstrip('/')
                parsed = urlparse(base)
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
                    raise ValueError('Enter a base URL such as http://192.168.1.20:8765 (no path).')
                self.server.base_url = base
            else:
                return self.reply(404, {'error': 'Not found.'})
            return self.reply(200, {'message': 'Saved.'})
        except (ValueError, TypeError, csv.Error) as exc:
            return self.reply(400, {'error': str(exc)})
        except sqlite3.Error:
            return self.reply(500, {'error': 'Could not save. Please try again.'})


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('8.8.8.8', 80))
            return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--base-url', help='Address phones can reach, e.g. http://192.168.1.20:8765')
    parser.add_argument('--db', default=str(ROOT / 'data' / 'attendance.sqlite3'))
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.store = Store(args.db)
    server.secret = secrets.token_urlsafe(32)
    server.base_url = args.base_url or f'http://{lan_ip()}:{args.port}'
    admin_url = f'http://localhost:{args.port}/admin?key={server.secret}'
    print(f'\nHOOKEM Attendance\nOrganizer (keep private): {admin_url}\nPhone network address: {server.base_url}\nDatabase: {args.db}\nKeep this window open. Ctrl+C stops the app.\n', flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(admin_url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
