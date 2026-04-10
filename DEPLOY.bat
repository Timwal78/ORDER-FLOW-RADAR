@echo off
echo ========================================
echo  ORDER FLOW RADAR - DEPLOY TO GITHUB
echo ========================================
echo.

cd /d "%~dp0"

echo [1/5] Initializing git repo...
git init
git branch -M main

echo [2/5] Adding all files...
git add .

echo [3/5] Committing...
git commit -m "Order Flow Radar v1.0.0 - LIVE"

echo [4/5] Creating GitHub repo...
gh repo create order-flow-radar --public --source=. --remote=origin --push

echo [5/5] Done\!
echo.
echo ========================================
echo  DEPLOYED TO GITHUB SUCCESSFULLY
echo  Next: Go to railway.app to deploy
echo ========================================
pause
