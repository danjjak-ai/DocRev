@echo off
:: GCP Project ID
SET PROJECT_ID=docrev-488902

:: GCP Region (e.g., us-central1, asia-northeast3)
SET REGION=asia-northeast3

:: Cloud Run Service Name
SET SERVICE_NAME=docrev-backend
SET IMAGE=asia-northeast3-docker.pkg.dev/docrev-488902/cloud-run-source-deploy/docrev-backend@sha256:73902c4e824da9bfd33a5e80e925c2e62756774531d848817d7000309010f690
SET MEMORY=4Gi

:: Extract Gemini API Key from .env file using PowerShell
:: Looks for GEMINI_API_KEY=value and extracts the value
SET ENV_FILE=.env
if exist %ENV_FILE% (
    for /f "tokens=*" %%i in ('powershell -Command "Select-String -Path %ENV_FILE% -Pattern '^GEMINI_API_KEY=(.*)' | %% { $_.Matches.Groups[1].Value }"') do set GEMINI_API_KEY=%%i
)

if "%GEMINI_API_KEY%"=="" (
    echo [WARNING] GEMINI_API_KEY not found in %ENV_FILE%. 
    echo Deployment will proceed, but you must set it in the Google Cloud Console.
) else (
    echo [INFO] GEMINI_API_KEY successfully loaded from %ENV_FILE%.
)
