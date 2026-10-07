"""Read-only checks performed before the first upgrade migration."""
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1]).resolve()
with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
    # Match the migration's Python Unicode normalization, not SQLite's ASCII lower().
    emails = {}
    for identifier, email in connection.execute('SELECT id, email FROM auth_user'):
        normalized = email.strip().lower()
        if normalized:
            emails.setdefault(normalized, []).append(identifier)
    conflicts = [identifiers for identifiers in emails.values() if len(identifiers) > 1]
    if conflicts:
        # Never expose emails; the administrator can resolve by account identifiers.
        raise SystemExit('升级前检查失败：存在重复邮箱，冲突账号 ID：' + '；'.join(','.join(map(str,row)) for row in conflicts))
    result = connection.execute('PRAGMA quick_check').fetchone()[0]
    if result != 'ok':
        raise SystemExit('数据库完整性检查未通过，请先恢复或修复备份。')
print('升级前检查通过：无重复邮箱，数据库完整。')
