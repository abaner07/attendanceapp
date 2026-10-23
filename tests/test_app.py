import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Handler, Store, ThreadingHTTPServer


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / 'test.db'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicates_closed_links_and_persistence(self):
        self.store.add_students([{'eid': 'abc123', 'name': 'Alex Student'}])
        self.store.create_meeting('First')
        token = self.store.snapshot()['meetings'][0]['token']
        self.store.checkin(token, 'ABC123', 'Another Name')
        self.store.checkin(token, 'abc123', 'Another Name')
        saved = Store(self.store.path).snapshot()
        self.assertEqual(len(saved['attendance']), 1)
        self.assertEqual(saved['students'][0]['name'], 'Alex Student')
        self.store.create_meeting('Second')
        with self.assertRaises(ValueError):
            self.store.checkin(token, 'abc123', 'Alex Student')

    def test_roster_atomic_and_eligibility(self):
        with self.assertRaises(ValueError):
            self.store.add_students([{'eid': 'abc123', 'name': 'Alex Student'}, {'eid': '!', 'name': 'Bad Student'}])
        self.assertEqual(self.store.snapshot()['students'], [])
        self.store.create_meeting('Before joining')
        self.store.add_students([{'eid': 'abc123', 'name': 'Alex Student'}])
        self.assertEqual(self.store.snapshot()['students'][0]['since'], 2)
        token = self.store.snapshot()['meetings'][0]['token']
        self.store.checkin(token, 'new123', 'New Student')
        self.assertEqual(next(s for s in self.store.snapshot()['students'] if s['eid']=='new123')['since'], 1)

    def test_full_http_flow(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.store, server.secret = self.store, 'test-secret'
        base = f'http://127.0.0.1:{server.server_port}'
        server.base_url = base
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, data=None, admin=False, marker=True):
            headers = {'Cookie': 'attendance_admin=test-secret'} if admin else {}
            if marker:
                headers['X-Attendance-Request'] = '1'
            raw = json.dumps(data).encode() if data is not None else None
            req = Request(base + path, data=raw, headers=headers)
            try:
                with urlopen(req) as r:
                    return r.status, r.read()
            except HTTPError as e:
                with e:
                    return e.code, e.read()
        try:
            self.assertEqual(request('/api/state')[0], 403)
            self.assertEqual(request('/api/meetings', {'title':'Hacked'})[0], 403)
            self.assertEqual(request('/api/meetings', {'title':'CSRF'}, True, False)[0], 403)
            self.assertEqual(request('/api/import', {'csv':'eid,name\nabc123,Alex Student\ndef456,Drew Student'}, True)[0], 200)
            self.assertEqual(request('/api/meetings', {'title':'Test Meeting'}, True)[0], 200)
            status, body = request('/api/state', admin=True)
            token = json.loads(body)['meetings'][0]['token']
            self.assertEqual(request('/api/qr', admin=True)[0], 200)
            self.assertIn(b'<svg', request('/api/qr', admin=True)[1])
            self.assertEqual(request('/checkin/' + token)[0], 200)
            self.assertEqual(request('/api/checkin', {'token':token,'eid':'abc123','name':'Alex Student'})[0], 200)
            self.assertEqual(request('/api/close', {}, True)[0], 200)
            self.assertEqual(request('/api/checkin', {'token':token,'eid':'def456','name':'Drew Student'})[0], 400)
            exported = request('/api/export', admin=True)[1].decode('utf-8-sig')
            self.assertIn('abc123,Alex Student,Present', exported)
            self.assertIn('def456,Drew Student,Absent', exported)
            self.assertEqual(request('/api/settings', {'base_url':'javascript:alert(1)'}, True)[0], 400)
            self.assertEqual(request('/api/import', {'csv':'eid,name\ngood123,Good Name\n!,Bad Name'}, True)[0], 400)
            self.assertEqual(len(self.store.snapshot()['students']), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
