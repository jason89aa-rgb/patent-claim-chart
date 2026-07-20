# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['PyQt6.sip', 'fitz', 'PIL._tkinter_finder', 'openpyxl.cell._writer', 'openpyxl.cell.rich_text', 'docx']
tmp_ret = collect_all('fitz')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PyQt6')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# ---------------------------------------------------------------- Tesseract
# exe 하나만 복사해도 다른 PC에서 OCR이 되도록 Tesseract 실행파일·DLL과
# 언어팩을 통째로 넣는다. core/ocr_engine.py 가 번들본을 우선 사용한다.
TESS_DIR = r"C:\Program Files\Tesseract-OCR"
TESS_LANGS = ["eng", "osd", "chi_sim", "kor"]
# 언어팩은 사용자 폴더에 받아둔 것을 쓴다 (Program Files 는 쓰기 권한이 없어
# chi_sim/kor 을 거기에 설치할 수 없었다)
USER_TESSDATA = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                             "PatentClaimChart", "tessdata")

if os.path.isdir(TESS_DIR):
    # 실행파일과 DLL (하위 doc/tessdata 폴더는 제외 — 언어팩은 아래에서 따로)
    for name in os.listdir(TESS_DIR):
        src = os.path.join(TESS_DIR, name)
        if os.path.isfile(src) and name.lower().endswith((".exe", ".dll")):
            binaries.append((src, "tesseract"))

    for lang in TESS_LANGS:
        fname = lang + ".traineddata"
        for base in (USER_TESSDATA, os.path.join(TESS_DIR, "tessdata")):
            src = os.path.join(base, fname)
            if os.path.isfile(src):
                datas.append((src, "tesseract/tessdata"))
                break
        else:
            print(f"[spec] 경고: {fname} 을(를) 찾지 못했습니다 — 번들 제외")


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PatentClaimChart_fixed',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # Tesseract 실행파일/DLL은 UPX로 압축하면 깨질 수 있어 제외한다
    upx_exclude=['tesseract.exe'] + [
        os.path.basename(src) for src, dest in binaries if dest == 'tesseract'
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
