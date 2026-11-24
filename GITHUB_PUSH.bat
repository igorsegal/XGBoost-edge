@echo off
chcp 65001 >nul
echo GITHUB_PUSH version 2
cd /d D:\AHexaTrader\XGBoost-edge-git
where git >nul 2>nul
if errorlevel 1 ( echo NO GIT IN PATH & pause & exit /b 1 )
git ls-files --error-unmatch dashscope_key.txt >nul 2>nul
if not errorlevel 1 ( echo STOP: dashscope_key.txt is tracked by git, key must not go to GitHub & pause & exit /b 1 )
echo --- workflows: copy new versions into .github\workflows
copy /Y workflows_new\scrape-and-judge.yml .github\workflows\scrape-and-judge.yml
if errorlevel 1 ( echo COPY FAILED & pause & exit /b 1 )
copy /Y workflows_new\mql5_pipeline.yml .github\workflows\mql5_pipeline.yml
if errorlevel 1 ( echo COPY FAILED & pause & exit /b 1 )
echo --- add files
git add .github .gitignore src registry tests workflows_new GITHUB_PUSH.bat REPORT.md RULES_FOR_TESTER.md
git add -A -- data ":!data/cache" ":!data/debug"
echo --- what will be sent
git status --short
git commit -m "Pipeline to GitHub Actions: scraper limits and block stop, jury state, rules registry, indicators"
echo --- pull
git pull --rebase --autostash
if errorlevel 1 ( echo PULL FAILED, nothing pushed & pause & exit /b 1 )
echo --- push
git push
if errorlevel 1 ( echo PUSH FAILED & pause & exit /b 1 )
echo.
echo PUSH OK
pause
