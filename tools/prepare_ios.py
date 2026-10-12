"""Prepare the reproducible Xcode project and shared phone assets; no signing secrets."""
import hashlib
import json
from pathlib import Path
import shutil
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'ios' / 'Generated'
VERSION = json.loads((ROOT / 'desktop/package.json').read_text())['version']


def ident(value):
    return hashlib.sha1(value.encode()).hexdigest()[:24].upper()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    phone = OUT / 'PhoneAssets'
    phone.mkdir(exist_ok=True)
    manifest = {}
    for name in ('mobile.css', 'phone-layout.css', 'phone-interactions.js', 'mobile.js', 'phone-assistant.js', 'local-chat.js', 'phone-layout.js'):
        source = ROOT / 'mobile/app/src/main/assets' / name
        shutil.copy2(source, phone / name)
        manifest[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    (phone / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    assets = OUT / 'Assets.xcassets'
    icon = assets / 'AppIcon.appiconset'
    icon.mkdir(parents=True, exist_ok=True)
    (assets / 'Contents.json').write_text('{"info":{"version":1,"author":"xcode"}}\n')
    image = Image.open(ROOT / 'desktop/assets/team-logo.png').convert('RGBA').resize((1024, 1024))
    canvas = Image.new('RGB', (1024, 1024), 'white')
    canvas.paste(image, mask=image.getchannel('A'))
    canvas.save(icon / 'AppIcon.png')
    (icon / 'Contents.json').write_text(json.dumps({'images': [{'filename': 'AppIcon.png', 'idiom': 'universal', 'platform': 'ios', 'size': '1024x1024'}], 'info': {'version': 1, 'author': 'xcode'}}))

    sources = ['AppDelegate.swift', 'MainController.swift', 'DownloadManager.swift', 'ScannerController.swift']
    objects = []
    def obj(name, body):
        objects.append(f'\t\t{ident(name)} = {{ {body} }};')
        return ident(name)
    files = []
    builds = []
    for name in sources:
        file = obj('file:' + name, f'isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = "../Zhiyu/{name}"; sourceTree = "<group>";')
        files.append(file)
        builds.append(obj('build:' + name, f'isa = PBXBuildFile; fileRef = {file};'))
    resources = []
    for name, kind in [('PhoneAssets', 'folder'), ('Assets.xcassets', 'folder.assetcatalog')]:
        file = obj('file:' + name, f'isa = PBXFileReference; lastKnownFileType = {kind}; path = "{name}"; sourceTree = "<group>";')
        files.append(file)
        resources.append(obj('build:' + name, f'isa = PBXBuildFile; fileRef = {file};'))
    product = obj('product', 'isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = Zhiyu.app; sourceTree = BUILT_PRODUCTS_DIR;')
    group = obj('group', f'isa = PBXGroup; children = ({",".join(files)},{product},); sourceTree = "<group>";')
    source_phase = obj('sources', f'isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ({",".join(builds)},); runOnlyForDeploymentPostprocessing = 0;')
    resource_phase = obj('resources', f'isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = ({",".join(resources)},); runOnlyForDeploymentPostprocessing = 0;')
    frameworks = obj('frameworks', 'isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0;')
    project_configs = []
    target_configs = []
    for name in ('Debug', 'Release'):
        project_configs.append(obj('project:' + name, f'isa = XCBuildConfiguration; buildSettings = {{ CLANG_ENABLE_MODULES = YES; SDKROOT = iphoneos; IPHONEOS_DEPLOYMENT_TARGET = 16.0; }}; name = {name};'))
        target_configs.append(obj('target:' + name,
            'isa = XCBuildConfiguration; buildSettings = {'
            ' ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon; CODE_SIGN_STYLE = Automatic;'
            ' INFOPLIST_FILE = "../Zhiyu/Info.plist"; GENERATE_INFOPLIST_FILE = NO;'
            f' MARKETING_VERSION = {VERSION}; CURRENT_PROJECT_VERSION = 1;'
            ' PRODUCT_BUNDLE_IDENTIFIER = org.fyrepo.zhiyu.mobile; PRODUCT_NAME = Zhiyu;'
            ' TARGETED_DEVICE_FAMILY = "1,2"; SUPPORTED_PLATFORMS = "iphoneos iphonesimulator";'
            ' SWIFT_VERSION = 5.0; SWIFT_STRICT_CONCURRENCY = minimal;'
            ' LD_RUNPATH_SEARCH_PATHS = "$(inherited) @executable_path/Frameworks";'
            f' SWIFT_OPTIMIZATION_LEVEL = "{"-Onone" if name == "Debug" else "-O"}";'
            f' }}; name = {name};'))
    def configs(key, items):
        return obj(key, f'isa = XCConfigurationList; buildConfigurations = ({",".join(items)},); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;')
    target_list = configs('target-configs', target_configs)
    project_list = configs('project-configs', project_configs)
    target = obj('target', f'isa = PBXNativeTarget; buildConfigurationList = {target_list}; buildPhases = ({source_phase},{frameworks},{resource_phase},); buildRules = (); dependencies = (); name = Zhiyu; productName = Zhiyu; productReference = {product}; productType = "com.apple.product-type.application";')
    project = obj('project', f'isa = PBXProject; attributes = {{ LastUpgradeCheck = 1600; }}; buildConfigurationList = {project_list}; compatibilityVersion = "Xcode 14.0"; developmentRegion = zh_CN; hasScannedForEncodings = 0; knownRegions = (zh_CN,en,Base,); mainGroup = {group}; projectDirPath = ""; projectRoot = ""; targets = ({target},);')
    folder = OUT / 'Zhiyu.xcodeproj'
    folder.mkdir(exist_ok=True)
    (folder / 'project.pbxproj').write_text('// !$*UTF8*$!\n{ archiveVersion = 1; classes = {}; objectVersion = 56; objects = {\n' + '\n'.join(objects) + '\n}; rootObject = ' + project + '; }\n')
    schemes = folder / 'xcshareddata/xcschemes'
    schemes.mkdir(parents=True, exist_ok=True)
    (schemes / 'Zhiyu.xcscheme').write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1600" version="1.3"><BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{target}" BuildableName="Zhiyu.app" BlueprintName="Zhiyu" ReferencedContainer="container:Zhiyu.xcodeproj"/></BuildActionEntry></BuildActionEntries></BuildAction><LaunchAction buildConfiguration="Debug"/><ProfileAction buildConfiguration="Release"/><AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/></Scheme>''')
    print(json.dumps({'version': VERSION, 'project': str(folder), 'phone_assets': len(manifest), 'signing': 'not performed'}))


if __name__ == '__main__':
    main()
