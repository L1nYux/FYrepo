"""Verify the iPhone application identity and shared phone resources after Xcode."""
import hashlib
import json
import plistlib
from pathlib import Path
import struct
import sys

root = Path(__file__).resolve().parents[1]
app = Path(sys.argv[1])
version = json.loads((root / 'desktop/package.json').read_text())['version']
with (app / 'Info.plist').open('rb') as source:
    info = plistlib.load(source)
assert info['CFBundleIdentifier'] == 'org.fyrepo.zhiyu.mobile'
assert info['CFBundleShortVersionString'] == version
assert info['CFBundlePackageType'] == 'APPL'
binary = app / info['CFBundleExecutable']
header = binary.read_bytes()[:32]
assert struct.unpack('<II', header[:8]) == (0xFEEDFACF, 0x0100000C), 'A real arm64 Mach-O binary is required.'
manifest = json.loads((app / 'PhoneAssets/SOURCE-MANIFEST.json').read_text())
assert len(manifest) == 7
for name, expected in manifest.items():
    assert hashlib.sha256((app / 'PhoneAssets' / name).read_bytes()).hexdigest() == expected
    assert hashlib.sha256((root / 'mobile/app/src/main/assets' / name).read_bytes()).hexdigest() == expected
assert not (app / 'embedded.mobileprovision').exists(), 'This artifact must remain explicitly unsigned.'
print(json.dumps({'version': version, 'bundle_id': info['CFBundleIdentifier'], 'architecture': 'arm64', 'phone_assets_verified': len(manifest), 'requires_personal_signing': True}))
