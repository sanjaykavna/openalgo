@echo off
setlocal EnableExtensions
title OpenAlgo Launcher

REM ======================= SETTINGS =======================
REM Leave OPENALGO_DIR empty to auto-detect under %USERPROFILE%\OpenAlgo and %USERPROFILE%\openalgo
set "OPENALGO_DIR=C:\Users\sanja\IdeaProjects\OpenAlgo\openalgo"
set "LOCAL_URL=http://127.0.0.1:5000"
set "TUNNEL_NAME=openalgo"
set "PUBLIC_URL=https://1v8zrjmn-5000.inc1.devtunnels.ms"

REM ---- Environment file OpenAlgo should start with ----
REM A file name inside the OpenAlgo folder (e.g. .nubra.env) or a full path (e.g. D:\keys\.nubra.env).
REM It is copied over OpenAlgo's .env before start (your first original .env is kept once as .env.original).
set "ENV_FILE=.nubra.env"

REM ---- Static IP proxy (from your provider) ----
REM PROXY_TYPE: https (encrypted - what staticip.in needs), http, or auto (tries https then http)
set "PROXY_TYPE=https"
set "PROXY_HOST=dc-mum-602.staticip.in"
set "PROXY_PORT=443"
set "PROXY_USER=sip_240919e943454fe0"
REM If the password has special characters, URL-encode them (@ = %%40, # = %%23, : = %%3A)
REM and write every %% as a double %% in this file. Avoid ! in the password.
set "PROXY_PASS=Sam171098"
REM ONLY these sites use the static IP; everything else uses your normal internet.
REM Comma-separated; a domain also covers its sub-domains (nubra.io = api.nubra.io, ws.nubra.io ...).
set "STATIC_DOMAINS=nubra.io"
REM Exceptions that go DIRECT even though they match above. api-latest.nubra.io is Nubra's
REM order-update WebSocket (only receives updates); the static IP proxy cannot reach it (502).
REM Never put the host that PLACES orders here - check the router window: order calls must show "STATIC IP".
set "DIRECT_DOMAINS=api-latest.nubra.io"
REM Local router that splits the traffic (nubra-ip-router.py must be next to this file)
set "ROUTER_PORT=8899"
REM The static IP registered with Nubra (the proxy's IP)
set "STATIC_IP=2401:c080:2400:2478:3ed9:2693:4276:5a24"
REM ========================================================

setlocal EnableDelayedExpansion
set "LOG=%~dp0launcher-log.txt"
set "PROXY_AUTH=%PROXY_USER%:%PROXY_PASS%@%PROXY_HOST%:%PROXY_PORT%"
set "PROXY_URL="
echo.
echo  ==== OpenAlgo + Static IP + Dev Tunnel launcher ====
echo.
echo [%date% %time%] Launcher started>>"%LOG%"

REM --- 1. Find the OpenAlgo folder (the one containing app.py and broker\) ---
if not defined OPENALGO_DIR (
    for %%r in ("%USERPROFILE%\OpenAlgo" "%USERPROFILE%\openalgo") do (
        if not defined OPENALGO_DIR if exist "%%~r\" (
            for /f "delims=" %%f in ('where /r "%%~r" app.py 2^>nul') do (
                if not defined OPENALGO_DIR if exist "%%~dpfbroker\" set "OPENALGO_DIR=%%~dpf"
            )
        )
    )
)
if defined OPENALGO_DIR if "!OPENALGO_DIR:~-1!"=="\" set "OPENALGO_DIR=!OPENALGO_DIR:~0,-1!"
if not defined OPENALGO_DIR (
    echo [ERROR] Could not find OpenAlgo's app.py. Set OPENALGO_DIR at the top of this file.
    pause
    exit /b 1
)
echo [OK] OpenAlgo folder: !OPENALGO_DIR!

REM --- 1b. Use the chosen environment file (e.g. .nubra.env) as OpenAlgo's .env ---
set "ENV_PATH=%ENV_FILE%"
if "!ENV_PATH:~1,1!" neq ":" if "!ENV_PATH:~0,2!" neq "\\" set "ENV_PATH=!OPENALGO_DIR!\%ENV_FILE%"
if not exist "!ENV_PATH!" (
    echo [ERROR] Environment file not found: !ENV_PATH!
    echo         Create it ^(copy your working .env and rename it^) or change ENV_FILE at the top of this file.
    echo [%date% %time%] ERROR: env file missing: !ENV_PATH!>>"%LOG%"
    pause
    exit /b 1
)
set "ENV_CHANGED="
if exist "!OPENALGO_DIR!\.env" (
    fc /b "!ENV_PATH!" "!OPENALGO_DIR!\.env" >nul 2>&1
    if errorlevel 1 (
        if not exist "!OPENALGO_DIR!\.env.original" copy /y "!OPENALGO_DIR!\.env" "!OPENALGO_DIR!\.env.original" >nul
        set "ENV_CHANGED=1"
    )
) else (
    set "ENV_CHANGED=1"
)
if defined ENV_CHANGED (
    copy /y "!ENV_PATH!" "!OPENALGO_DIR!\.env" >nul
    if errorlevel 1 (
        echo [ERROR] Could not copy !ENV_PATH! to .env ^(file open in another program?^)
        pause
        exit /b 1
    )
    echo [OK] OpenAlgo will use settings from %ENV_FILE% ^(copied to .env^)
    echo [%date% %time%] Env: %ENV_FILE% copied to .env>>"%LOG%"
) else (
    echo [OK] .env already matches %ENV_FILE%
)

REM --- 2. Check the static IP proxy works and shows the registered IP ---
set "PROXY_OK="
if "%PROXY_PASS%"=="YOUR-NEW-PASSWORD-HERE" (
    echo [WARN] Proxy password not set yet - put it in PROXY_PASS at the top of this file.
    echo        Starting WITHOUT the static IP: Nubra will reject orders.
    goto startserver
)
set "SEEN_IP="
set "TYPES=%PROXY_TYPE%"
if /i "%PROXY_TYPE%"=="auto" set "TYPES=https http"
echo [..] Testing proxy %PROXY_HOST%:%PROXY_PORT% ^(%TYPES%^)...
for %%t in (%TYPES%) do (
    if not defined SEEN_IP (
        set "TRY_URL=%%t://!PROXY_AUTH!"
        set "OUT="
        for /f "delims=" %%i in ('curl.exe -sS --max-time 12 -x "!TRY_URL!" https://ifconfig.me 2^>^&1') do set "OUT=%%i"
        set "GOOD="
        if defined OUT (
            set "C1=!OUT:~0,1!"
            if "!OUT:curl=!"=="!OUT!" if "!OUT: =!"=="!OUT!" set "GOOD=1"
        )
        if defined GOOD (
            set "SEEN_IP=!OUT: =!"
            set "PROXY_TYPE=%%t"
            set "PROXY_URL=!TRY_URL!"
            echo [OK]  %%t works
        ) else (
            echo [--]  %%t failed: !OUT!
            echo [%date% %time%] proxy %%t failed: !OUT!>>"%LOG%"
        )
    )
)
if not defined SEEN_IP (
    echo.
    echo [ERROR] Proxy not working with any type. Read the curl messages above:
    echo         "407" or "Proxy Authentication Required" = wrong username/password ^(or special characters not URL-encoded^)
    echo         "Could not resolve proxy"                = wrong PROXY_HOST
    echo         "Failed to connect" / "timed out"          = wrong port, provider down, or your IP not whitelisted with the provider
    echo         "SSL" / "schannel" errors                  = type mismatch; set PROXY_TYPE to the type your provider states
    echo         Also check with the provider: some "static IP" services are VPNs ^(WireGuard/OpenVPN^), not proxies.
    echo         Starting WITHOUT the static IP: Nubra will reject orders until this is fixed.
    echo [%date% %time%] ERROR: proxy not reachable>>"%LOG%"
    goto startserver
)
if /i "%PROXY_TYPE%"=="socks5h" (
    REM Python libraries use socks5:// and need SOCKS support installed in OpenAlgo's venv
    set "PROXY_URL=socks5://!PROXY_AUTH!"
    if exist "!OPENALGO_DIR!\.venv\Scripts\python.exe" "!OPENALGO_DIR!\.venv\Scripts\python.exe" -m pip install -q "httpx[socks]" pysocks >nul 2>&1
)
echo [..] IP seen through the proxy: !SEEN_IP!
echo [%date% %time%] Proxy IP=!SEEN_IP!>>"%LOG%"
if "%STATIC_IP%"=="YOUR-STATIC-IP-HERE" (
    echo [WARN] STATIC_IP not filled in; can't confirm it matches Nubra's registration.
    set "PROXY_OK=1"
) else if /i "!SEEN_IP!"=="%STATIC_IP%" (
    echo [OK] Proxy shows the static IP registered with Nubra.
    set "PROXY_OK=1"
) else (
    echo [WARN] Proxy IP !SEEN_IP! does NOT match registered %STATIC_IP%. Orders may be rejected.
    echo [%date% %time%] WARN: proxy IP mismatch>>"%LOG%"
    set "PROXY_OK=1"
)

:startserver
REM --- 3. Start OpenAlgo with the proxy (only this window uses it) ---
curl.exe -s -o nul --max-time 3 --noproxy "*" %LOCAL_URL%/
if !errorlevel! == 0 (
    echo [INFO] OpenAlgo is already running. If it was started without the proxy/router,
    echo        close the "OpenAlgo Server" and "Nubra IP router" windows and run this launcher again.
    if defined ENV_CHANGED echo [WARN] %ENV_FILE% changed .env, but the running server still uses the old settings - close "OpenAlgo Server" and run this again.
    goto tunnel
)
echo [..] Starting OpenAlgo server...
set "PYEXE=python"
if exist "!OPENALGO_DIR!\.venv\Scripts\python.exe" set "PYEXE=!OPENALGO_DIR!\.venv\Scripts\python.exe"
if defined PROXY_OK (
    if not exist "%~dp0nubra-ip-router.py" (
        echo [ERROR] nubra-ip-router.py not found next to this launcher - put it in %~dp0
        pause
        exit /b 1
    )
    REM Start the router: only STATIC_DOMAINS go via the static IP
    set "UP_HOST=%PROXY_HOST%"
    set "UP_SCHEME=!PROXY_TYPE!"
    set "UP_PORT=%PROXY_PORT%"
    set "UP_USER=%PROXY_USER%"
    set "UP_PASS=%PROXY_PASS%"
    set "PROXY_DOMAINS=%STATIC_DOMAINS%"
    set "DIRECT_DOMAINS=%DIRECT_DOMAINS%"
    start "Nubra IP router" /min cmd /k ""!PYEXE!" "%~dp0nubra-ip-router.py""
    set "UP_PASS="
    timeout /t 2 /nobreak >nul
    echo [OK] Router started: %STATIC_DOMAINS% via static IP, everything else direct
    set "HTTP_PROXY=http://127.0.0.1:%ROUTER_PORT%"
    set "HTTPS_PROXY=http://127.0.0.1:%ROUTER_PORT%"
    set "ALL_PROXY=http://127.0.0.1:%ROUTER_PORT%"
    set "NO_PROXY=localhost,127.0.0.1,::1,devtunnels.ms"
)
if exist "!OPENALGO_DIR!\.venv\Scripts\python.exe" (
    start "OpenAlgo Server" /min /d "!OPENALGO_DIR!" cmd /k ".venv\Scripts\python.exe app.py"
) else (
    where uv >nul 2>nul
    if !errorlevel! == 0 (
        start "OpenAlgo Server" /min /d "!OPENALGO_DIR!" cmd /k "uv run app.py"
    ) else (
        start "OpenAlgo Server" /min /d "!OPENALGO_DIR!" cmd /k "python app.py"
    )
)
REM Clear the proxy so the tunnel and checks below connect directly
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "NO_PROXY="

set /a tries=0
:waitserver
set /a tries+=1
curl.exe -s -o nul --max-time 3 --noproxy "*" %LOCAL_URL%/
if !errorlevel! == 0 goto serverup
if !tries! geq 40 (
    echo [ERROR] OpenAlgo did not start. Check the "OpenAlgo Server" window.
    echo [%date% %time%] ERROR: OpenAlgo did not start>>"%LOG%"
    pause
    exit /b 1
)
timeout /t 3 /nobreak >nul
goto waitserver
:serverup
echo [OK] OpenAlgo is running at %LOCAL_URL%

:tunnel
REM --- 4. Start the permanent dev tunnel (direct, no proxy) ---
set "DT=devtunnel"
where devtunnel >nul 2>nul
if !errorlevel! neq 0 set "DT=%LOCALAPPDATA%\Microsoft\WinGet\Links\devtunnel.exe"
echo [..] Starting dev tunnel "%TUNNEL_NAME%"...
start "Dev Tunnel - %TUNNEL_NAME%" /min cmd /k ""!DT!" host %TUNNEL_NAME%"

set /a tries=0
:waittunnel
set /a tries+=1
set "CODE="
for /f %%c in ('curl.exe -s -o nul -w "%%{http_code}" --max-time 5 %PUBLIC_URL%/.well-known/oauth-authorization-server') do set "CODE=%%c"
if "!CODE!" == "200" goto tunnelup
if !tries! geq 20 (
    echo [WARN] Public URL not responding ^(HTTP !CODE!^). Check the "Dev Tunnel" window; if it asks, run: devtunnel user login
    echo [%date% %time%] WARN: tunnel not responding>>"%LOG%"
    goto login
)
timeout /t 3 /nobreak >nul
goto waittunnel
:tunnelup
echo [OK] Public MCP endpoint live: %PUBLIC_URL%/mcp
echo [%date% %time%] OK: server and tunnel up>>"%LOG%"

:login
REM --- 5. Keep the PC awake while plugged in; open OpenAlgo for the daily Nubra login ---
powercfg /change standby-timeout-ac 0 >nul 2>&1
echo.
echo  NEXT: log in to OpenAlgo and connect Nubra (OTP + MPIN) before 9:15 AM.
if not defined PROXY_OK echo  WARNING: running without the static IP proxy - fix it before market hours.
start "" "%LOCAL_URL%"
echo.
echo  Keep the "OpenAlgo Server" and "Dev Tunnel" windows open during market hours.
echo.
pause
endlocal
endlocal