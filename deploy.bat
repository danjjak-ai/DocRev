@echo off
setlocal enabledelayedexpansion

:: Add gcloud and firebase to PATH if not already present
set "GCLOUD_PATH=C:\Users\jaehu\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin"
where gcloud >nul 2>nul
if %ERRORLEVEL% neq 0 (
    if exist "%GCLOUD_PATH%" (
        set "PATH=%PATH%;%GCLOUD_PATH%"
    )
)

:: Load configuration
if not exist deploy_config.bat (
    echo [ERROR] deploy_config.bat file not found.
    echo Please create it from the template provided.
    exit /b 1
)

call deploy_config.bat

echo ===================================================
echo [DocRev] Start Automated Deployment to GCP
echo ===================================================
echo [Config] Project ID: %PROJECT_ID%
echo [Config] Region:     %REGION%
echo [Config] Service:    %SERVICE_NAME%
echo ===================================================

:: 1. Set gcloud project
echo [Step 1] Setting gcloud project to %PROJECT_ID%...
call gcloud config set project %PROJECT_ID%
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to set gcloud project.
    exit /b 1
)

:: 2. Deploy to Cloud Run
echo [Step 2] Deploying Backend to Cloud Run...
:: Build environment variables string
set "ENV_VARS_FLAG="
if not "%GEMINI_API_KEY%"=="" (
    set "ENV_VARS_FLAG=--set-env-vars=GEMINI_API_KEY=%GEMINI_API_KEY%"
)
if not "%GEMINI_MODEL%"=="" (
    if "!ENV_VARS_FLAG!"=="" (
        set "ENV_VARS_FLAG=--set-env-vars=GEMINI_MODEL=%GEMINI_MODEL%"
    ) else (
        set "ENV_VARS_FLAG=!ENV_VARS_FLAG!,GEMINI_MODEL=%GEMINI_MODEL%"
    )
)

:: Using --quiet to avoid interactive prompts
:: 수정된 부분: --platform managed 추가
call gcloud run deploy %SERVICE_NAME% ^
  --source . ^
  --region %REGION% ^
  --platform managed ^
  --allow-unauthenticated ^
  %ENV_VARS_FLAG% ^
  --quiet

if %ERRORLEVEL% neq 0 (
    echo [ERROR] Cloud Run deployment failed.
    exit /b 1
)

:: 3. Get Service URL
echo [Step 3] Retrieving Service URL...
for /f "tokens=*" %%i in ('gcloud run services describe %SERVICE_NAME% --region %REGION% --format="value(status.url)"') do set SERVICE_URL=%%i

if "%SERVICE_URL%"=="" (
    echo [ERROR] Could not retrieve Service URL.
    exit /b 1
)
echo [Info] Backend Service URL: %SERVICE_URL%

:: 4. Update config.js
echo [Step 4] Updating config.js with new Service URL...
:: We use powershell to safely replace the URL in config.js
powershell -Command "$url='%SERVICE_URL%'; (Get-Content config.js) -replace 'https://.*\.run\.app', $url | Set-Content config.js"
:: Fallback if no matching run.app URL found (initial replacement)
powershell -Command "if (!(Select-String -Path config.js -Pattern '%SERVICE_URL%')) { (Get-Content config.js) -replace '(?<=: '').*(?='';)', '%SERVICE_URL%' | Set-Content config.js }"

:: Build Tailwind CSS
echo [Step 4.5] Building Tailwind CSS...
call npx tailwindcss -i ./css/input.css -o ./css/output.css --minify

:: 5. Deploy to Firebase Hosting
echo [Step 5] Deploying Frontend to Firebase Hosting...
call firebase deploy --only hosting --project %PROJECT_ID%

if %ERRORLEVEL% neq 0 (
    echo [ERROR] Firebase deployment failed.
    exit /b 1
)

echo ===================================================
echo [SUCCESS] Deployment completed successfully!
echo [SUCCESS] Backend: %SERVICE_URL%
echo ===================================================
pause
