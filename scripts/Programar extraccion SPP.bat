@echo off
rem Doble clic para registrar la extraccion diaria del SPP a las 16:00
rem (con reintentos a las 16:30 y 17:00).
rem
rem Existe porque Windows no ejecuta archivos .ps1 con doble clic y la
rem politica por defecto (Restricted) rechaza el guion desde la consola:
rem el operador veia "running scripts is disabled on this system" y se
rem quedaba sin extraccion automatica. Este .bat llama al mismo guion
rem con -ExecutionPolicy Bypass, que solo aplica a este proceso.
rem
rem Admite los mismos argumentos que scripts\schedule_sbs_valor_cuota.ps1:
rem   "Programar extraccion SPP.bat" -Time 19:30
rem   "Programar extraccion SPP.bat" -Status
rem   "Programar extraccion SPP.bat" -Test
rem   "Programar extraccion SPP.bat" -Remove

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0schedule_sbs_valor_cuota.ps1" %*
pause
