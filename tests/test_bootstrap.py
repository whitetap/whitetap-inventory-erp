import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from werkzeug.security import check_password_hash


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / 'bootstrap.db'
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.executescript('''
                CREATE TABLE tenants (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug VARCHAR(50) NOT NULL UNIQUE,
                    approval_status VARCHAR(50) NOT NULL DEFAULT 'approved',
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP
                );
                CREATE TABLE tenant_users (
                    id INTEGER PRIMARY KEY,
                    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
                    email VARCHAR(255) NOT NULL,
                    password_hash TEXT NOT NULL,
                    role VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP
                );
                INSERT INTO tenants (id, name, slug) VALUES (1, 'Whitetap', 'whitetap');
            ''')

    def start_app(self, password=None, email=None):
        env = os.environ.copy()
        env.update({
            'DATABASE_URL': f'sqlite:///{self.db_path.as_posix()}',
            'SECRET_KEY': 'test-secret-not-for-production',
            'PYTHONDONTWRITEBYTECODE': '1',
        })
        env['INITIAL_ADMIN_PASSWORD'] = ''
        env['INITIAL_ADMIN_EMAIL'] = 'admin@whitetap.com'
        if password is not None:
            env['INITIAL_ADMIN_PASSWORD'] = password
        if email is not None:
            env['INITIAL_ADMIN_EMAIL'] = email
        return subprocess.run(
            [sys.executable, '-c', "import sys; sys.path.insert(0, '.'); import app_fixed_final"],
            cwd=Path(__file__).resolve().parent.parent,
            env=env, capture_output=True, text=True, timeout=30
        )

    def users(self):
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute(
                'SELECT tenant_id, email, password_hash, role FROM tenant_users ORDER BY id'
            ).fetchall()

    def test_creates_admin_once_at_application_import(self):
        result = self.start_app('long-enough-password', ' Owner@Example.com ')
        self.assertEqual(result.returncode, 0, result.stderr)
        users = self.users()
        self.assertEqual(len(users), 1)
        self.assertEqual((users[0][0], users[0][1], users[0][3]), (1, 'owner@example.com', 'admin'))
        self.assertTrue(check_password_hash(users[0][2], 'long-enough-password'))
        self.assertNotEqual(users[0][2], 'long-enough-password')
        result = self.start_app('different-password', 'another@example.com')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.users(), users)

    def test_default_email_and_existing_user(self):
        result = self.start_app('long-enough-password')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.users()[0][1], 'admin@whitetap.com')
        result = self.start_app('short', 'bad-email')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.users()), 1)

    def test_skips_without_password(self):
        result = self.start_app()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Skipping initial admin creation', result.stderr)
        self.assertEqual(self.users(), [])

    def test_rejects_bad_credentials_and_wrong_tenant(self):
        for password, email, expected in (
            ('short', None, 'at least 12 characters'),
            ('long-enough-password', 'invalid', 'valid email address'),
        ):
            with self.subTest(expected=expected):
                result = self.start_app(password, email)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertEqual(self.users(), [])
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("UPDATE tenants SET slug='other' WHERE id=1")
        result = self.start_app('long-enough-password')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('whitetap tenant to have ID 1', result.stderr)
        self.assertEqual(self.users(), [])


if __name__ == '__main__':
    unittest.main()
