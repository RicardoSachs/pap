@echo off
rem Doble clic: registra el scheduler unificado (scripts\scheduler.py) como
rem tarea de Windows que arranca al iniciar sesion, y lo arranca ahora.
rem
rem El scheduler es UN proceso por maquina que corre todos los trabajos
rem programados que la maquina tiene habilitados en su .env: la extraccion
rem del valor cuota SPP (16:00, con reintentos a las 16:30 y 17:00), y en
rem la oficina tambien Bloomberg, la adquisicion SBS y FMS. Sin derechos de
rem administrador no hay servicios: la tarea corre con la sesion abierta,
rem que es ademas lo que exige la SBS (Chrome visible).
rem
rem Argumentos:
rem   (ninguno)   registra y arranca
rem   -Estado     muestra la tarea y la ultima senal de vida en la base
rem   -Quitar     elimina la tarea (el proceso que este corriendo sigue
rem               hasta que se cierre su ventana)
rem
rem Resultado de cada corrida: tabla job_runs; senal de vida:
rem scheduler_heartbeat (cada 5 min). Los logs quedan en
rem data\logs\etl\scheduler_AAAAMMDD.log.

setlocal
set "TAREA=pgetl scheduler"
cd /d "%~dp0.."

if /i "%~1"=="-Estado" goto estado
if /i "%~1"=="-Quitar" goto quitar

if not exist ".venv\Scripts\python.exe" (
  echo No existe el entorno .venv
  echo Corre primero scripts\"Instalar entorno.bat"
  echo.
  pause
  exit /b 1
)

schtasks /Create /TN "%TAREA%" /SC ONLOGON /TR "\"%CD%\scripts\bat\scheduler.bat\"" /F
if errorlevel 1 (
  echo No se pudo registrar la tarea.
  pause
  exit /b 1
)
rem Ajustes que schtasks no expone: reintentar si muere, sin limite de duracion.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable; Set-ScheduledTask -TaskName '%TAREA%' -Settings $s | Out-Null"
schtasks /Run /TN "%TAREA%" >nul
echo.
echo Tarea "%TAREA%" registrada (al iniciar sesion) y arrancada.
echo Se abre una ventana "scheduler": es el proceso; no la cierres.
echo Comprueba en un minuto con: scripts\"Programar scheduler.bat" -Estado
echo.
echo PRIMERA VEZ en esta maquina: corre a mano, con alguien mirando,
echo   .venv\Scripts\python.exe scripts\run_sbs_valor_cuota.py --scheduled
echo para resolver una vez la verificacion del WAF de la SBS en Chrome.
pause
exit /b 0

:estado
schtasks /Query /TN "%TAREA%" /FO LIST /V 2>nul | findstr /C:"Nombre de tarea" /C:"TaskName" /C:"Estado" /C:"Status" /C:"Tiempo de" /C:"Last Run" /C:"Resultado" /C:"Last Result"
if errorlevel 1 echo No hay una tarea "%TAREA%" registrada.
rem La senal de vida y las ultimas corridas las muestra el diagnostico.
.venv\Scripts\python.exe scripts\diagnostico.py
pause
exit /b 0

:quitar
schtasks /Delete /TN "%TAREA%" /F
pause
exit /b 0
