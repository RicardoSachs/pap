# Registra, consulta o quita la extraccion automatica diaria del SPP,
# apuntando al pipeline de ESTE repo (scripts/run_sbs_valor_cuota.py).
#
#   .\scripts\"Programar extraccion SPP.ps1"              -> registra a las 18:00
#   .\scripts\"Programar extraccion SPP.ps1" -Hora 19:30  -> a otra hora
#   .\scripts\"Programar extraccion SPP.ps1" -Estado      -> que hay registrado hoy
#   .\scripts\"Programar extraccion SPP.ps1" -Probar      -> la corre ahora
#   .\scripts\"Programar extraccion SPP.ps1" -Quitar      -> la elimina
#
# USA EL MISMO NOMBRE DE TAREA que el monitor standalone a proposito:
# registrarla aqui ES el corte - reemplaza la tarea vieja (-Force), y asi
# nunca hay dos scrapers compitiendo por la misma pagina de la SBS.
#
# No requiere permisos de administrador: la tarea corre en la sesion del
# usuario (-LogonType Interactive), que es justo lo que hace falta para que
# el Chrome visible que exige el WAF exista de verdad.

[CmdletBinding()]
param(
  [string]$Hora = "18:00",
  [switch]$Estado,
  [switch]$Probar,
  [switch]$Quitar
)

$ErrorActionPreference = "Stop"
$Raiz   = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
$Python = Join-Path $Raiz ".venv\Scripts\python.exe"
$Script = Join-Path $Raiz "scripts\run_sbs_valor_cuota.py"
$Tarea  = "Profuturo - Valor cuota SPP"

function Mostrar-Estado {
  $t = Get-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue
  if (-not $t) { Write-Output "No hay ninguna tarea registrada con el nombre '$Tarea'."; return }
  $i = $t | Get-ScheduledTaskInfo
  $disparo = ($t.Triggers | ForEach-Object { $_.StartBoundary }) -join ", "
  Write-Output "Tarea      : $($t.TaskName)"
  Write-Output "Accion     : $($t.Actions[0].Execute) $($t.Actions[0].Arguments)"
  Write-Output "Estado     : $($t.State)"
  Write-Output "Programada : $disparo (hora local)"
  Write-Output "Proxima    : $($i.NextRunTime)"
  Write-Output "Ultima     : $($i.LastRunTime)  resultado $($i.LastTaskResult)"
  Write-Output "Omitidas   : $($i.NumberOfMissedRuns)"
}

if ($Estado) { Mostrar-Estado; exit 0 }

if ($Quitar) {
  if (Get-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $Tarea -Confirm:$false
    Write-Output "Tarea '$Tarea' eliminada. La extraccion ya no corre sola."
  } else {
    Write-Output "No habia nada que quitar."
  }
  exit 0
}

if ($Probar) {
  Write-Output "Corriendo la extraccion ahora (se abrira Chrome)..."
  & $Python $Script --programado
  Write-Output "Codigo de salida: $LASTEXITCODE"
  exit $LASTEXITCODE
}

if (-not (Test-Path $Python)) { throw "No se encontro el entorno en $Python" }
if (-not (Test-Path $Script)) { throw "No se encontro $Script" }
if ($Hora -notmatch '^([01]?\d|2[0-3]):[0-5]\d$') { throw "Hora invalida: $Hora. Usa HH:mm." }

$accion = New-ScheduledTaskAction -Execute $Python `
            -Argument "`"$Script`" --programado" -WorkingDirectory $Raiz

$disparador = New-ScheduledTaskTrigger -Daily -At $Hora

# StartWhenAvailable recupera la corrida si a esa hora la maquina estaba
# apagada. El tope de 30 minutos solo existe para que un Chrome colgado por
# el WAF no quede corriendo indefinidamente.
$opciones = New-ScheduledTaskSettingsSet `
              -StartWhenAvailable `
              -DontStopIfGoingOnBatteries `
              -AllowStartIfOnBatteries `
              -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
              -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
               -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $Tarea -Action $accion -Trigger $disparador `
  -Settings $opciones -Principal $principal -Force `
  -Description ("Extraccion diaria de valor cuota del SPP desde la SBS (pipeline pap). " +
                "Inserta lo que falte; nunca sobreescribe. " +
                "Rastro en data\spp\extraccion.log.") | Out-Null

Write-Output "Registrada: '$Tarea', todos los dias a las $Hora, apuntando a este repo."
Write-Output ""
Mostrar-Estado
Write-Output ""
Write-Output "Importante: la SBS exige un Chrome visible, asi que la sesion de Windows"
Write-Output "debe estar iniciada a esa hora. Con el equipo apagado la corrida se"
Write-Output "pospone y se recupera al volver (StartWhenAvailable)."
