@echo off
chcp 65001
echo ======================================
echo  특허 Claim Chart 생성기 빌드 스크립트
echo ======================================

echo [1단계] 패키지 설치 확인...
pip install -r requirements.txt

echo.
echo [2단계] --onedir 테스트 빌드...
pyinstaller ^
  --onedir ^
  --console ^
  --name "PatentClaimChart_dev" ^
  --hidden-import "PyQt6.sip" ^
  --hidden-import "fitz" ^
  --hidden-import "PIL._tkinter_finder" ^
  --hidden-import "openpyxl.cell._writer" ^
  --hidden-import "docx" ^
  --collect-all "fitz" ^
  --collect-all "PyQt6" ^
  main.py

echo.
echo [빌드 완료] dist\PatentClaimChart_dev\ 폴더에서 실행 테스트 후,
echo 아래 명령으로 최종 단일 exe를 생성하세요:
echo.
echo pyinstaller --onefile --noconsole --name "PatentClaimChart" ^
echo   --hidden-import "PyQt6.sip" --hidden-import "fitz" ^
echo   --hidden-import "openpyxl.cell._writer" --hidden-import "docx" ^
echo   --collect-all "fitz" --collect-all "PyQt6" main.py
echo.
pause
