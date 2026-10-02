import hashlib
import io
import sqlite3
from pathlib import Path
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from .tests import scratch_dir


class AccountImportTests(TestCase):
    def test_password_flags_and_source_file_are_preserved(self):
        with scratch_dir('account-import') as directory:
            path=Path(directory)/'old.sqlite3'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE auth_user (id INTEGER PRIMARY KEY, password TEXT, last_login TEXT, is_superuser INTEGER, username TEXT, first_name TEXT, last_name TEXT, email TEXT, is_staff INTEGER, is_active INTEGER, date_joined TEXT)')
            password=make_password('original-password')
            db.execute('INSERT INTO auth_user VALUES (?,?,?,?,?,?,?,?,?,?,?)',(7,password,None,1,'original-admin','','','',1,1,'2026-01-01 00:00:00'))
            db.commit();db.close()
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            call_command('import_accounts',source=str(path),stdout=io.StringIO())
            user=User.objects.get(pk=7)
            self.assertTrue(user.check_password('original-password'))
            self.assertTrue(user.is_staff and user.is_superuser and user.is_active)
            self.assertEqual(user.password,password)
            self.assertEqual(user.date_joined.isoformat(),'2026-01-01T00:00:00+00:00')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
            with self.assertRaises(CommandError):
                call_command('import_accounts',source=str(path),stdout=io.StringIO())
