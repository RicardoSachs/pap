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
rem   -Estado     muestra la tarea y corre el diagnostico (senal de vida
rem               del scheduler, ultimas corridas)
rem   -Quitar     elimina la tarea (el proceso que este corriendo sigue
rem               hasta que se cierre su ventana)
rem
rem Resultado de cada corrida: tabla job_runs; senal de vida:
rem scheduler_heartbeat (cada 5 min). Los logs quedan en
rem data\logs\scheduler_AAAAMMDD.log.

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

rem Registro con PowerShell y no con "schtasks /Create /SC ONLOGON": sin
rem derechos de administrador ese comando responde "Acceso denegado"; la
rem tarea de usuario (sesion interactiva) si se puede crear y arrancar.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value; $a = New-ScheduledTaskAction -Execute '%CD%\scripts\bat\scheduler.bat' -WorkingDirectory '%CD%'; try { $t = New-ScheduledTaskTrigger -AtLogOn -User $sid } catch { $t = New-ScheduledTaskTrigger -AtLogOn }; $p = New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive; $s = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable; Register-ScheduledTask -TaskName '%TAREA%' -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null; Start-ScheduledTask -TaskName '%TAREA%'"
if errorlevel 1 (
  echo No se pudo registrar la tarea.
  pause
  exit /b 1
)
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
powershell -NoProfile -Command "$t = Get-ScheduledTask -TaskName '%TAREA%' -ErrorAction SilentlyContinue; if ($t) { 'Tarea: ' + $t.TaskName + ' | estado: ' + $t.State + ' | accion: ' + $t.Actions[0].Execute } else { 'No hay una tarea \"%TAREA%\" registrada.' }"
rem La senal de vida y las ultimas corridas las muestra el diagnostico.
.venv\Scripts\python.exe scripts\diagnostico.py
pause
exit /b 0

:quitar
schtasks /Delete /TN "%TAREA%" /F
pause
exit /b 0
