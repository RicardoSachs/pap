@echo off
rem Doble clic para levantar el tablero: API FastAPI + dashboard compilado
rem en un solo origen (puerto 8000), y abre el navegador en la vista SPP.
rem Cerrar la ventana "Tablero SPP (API)" detiene el servidor.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo No se encontro el entorno en .venv\Scripts\python.exe
  echo Crea el entorno e instala requirements.txt antes de usar el tablero.
  pause
  exit /b 1
)

if not exist "web\apps\dashboards\out\index.html" (
  echo Aviso: no existe web\apps\dashboards\out - el dashboard no esta compilado.
  echo La API funcionara igual, pero la pagina no se servira. Compila con:
  echo   cd web\apps\dashboards ^&^& npm run build
  pause
)

rem Si ya hay un servidor en el 8000, no levantar otro: solo abrir el navegador.
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %errorlevel%==0 (
  echo El tablero ya esta corriendo; abriendo el navegador...
  start "" http://127.0.0.1:8000/spp/
  exit /b 0
)

start "Tablero SPP (API)" .venv\Scripts\python.exe -m uvicorn web.api.main:app --port 8000
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8000/spp/
