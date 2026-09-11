# Instalar el tablero SPP en otra computadora

Guía para dejar el tablero de **Valor Cuota SPP** funcionando en una
máquina nueva, partiendo del zip del repositorio (sin git) más un
respaldo de la base de datos.

Al terminar tendrás: el tablero abriéndose con doble clic, el libro
completo desde 1993, el registro Bloomberg, las series manuales, las
composiciones del benchmark y la extracción diaria automática a las
18:00.

Verificado el 2026-09-11 sobre Windows 11, Python 3.14.7 y
PostgreSQL 18.6.

---

## 0. Qué llevar en el USB

Tres cosas, desde la máquina que hoy tiene todo:

| Qué | Cómo se obtiene | Por qué |
|---|---|---|
| El repo | *Download ZIP* desde GitHub (rama `cambios_vc`) | El código y el tablero ya compilado (`web/apps/dashboards/out`) |
| El respaldo de la base | `python scripts/respaldo_spp.py --exportar` | El libro, las correcciones a mano, Bloomberg, series manuales y composiciones. **Nada de esto se puede volver a raspar.** |
| Los instaladores | Python, PostgreSQL y Google Chrome | La otra red puede bloquear las descargas |

Si la máquina destino **no llega a PyPI**, agrega un cuarto elemento —
las ruedas de Python, preparadas desde esta máquina:

```
python -m pip download -r requirements.lock.txt -d wheelhouse
```

y copia la carpeta `wheelhouse` junto al zip.

**No copies** `data\browser_profile_spp`: Chrome cifra sus cookies con
una clave ligada al usuario de Windows, así que el perfil no es
portable. El paso 8 lo resuelve.

---

## 1. Programas base

1. **Python 3** (3.14 recomendado, el probado) — marca *Add python.exe
   to PATH* en el instalador.
2. **PostgreSQL 18** — anota la contraseña del usuario `postgres`; deja
   el puerto en 5432.
3. **Google Chrome** — obligatorio: el WAF de la SBS rechaza navegadores
   headless y el Chromium que trae Playwright. Tiene que ser Chrome real.

## 2. Descomprimir el proyecto en su lugar definitivo

Extrae el zip y **renombra la carpeta a `pap`**, en la ruta donde va a
vivir — por ejemplo `C:\Users\<usuario>\Documents\Proyectos\pap`.

Muévelo *ahora*, no después: la tarea programada del paso 8 guarda la
ruta absoluta, y los datos (`data\`) nacen como carpeta hermana del
proyecto.

## 3. Crear el entorno de Python

Desde la carpeta del proyecto, en una consola:

```
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
```

Sin acceso a PyPI, usando el `wheelhouse` del paso 0:

```
.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse -r requirements.lock.txt
```

## 4. Configurar la conexión a la base (`.env`)

`.env` no viaja en el zip (contiene credenciales). Créalo copiando la
plantilla:

```
copy .env.example .env
```

y llena al menos:

```
PG_HOST=localhost
PG_PORT=5432
PG_DBNAME=pap
PG_USER=postgres
PG_PASSWORD=<la contraseña de PostgreSQL>
DATA_DIR=C:\Users\<usuario>\Documents\Proyectos\data
```

`DATA_DIR` es opcional pero conviene fijarlo: vacío significa "la
carpeta `data` hermana del proyecto", y si algún día mueves la carpeta
se te quedan atrás el rastro de las extracciones y el perfil de Chrome.

## 5. Traer la base de datos

Con el `.dump` del paso 0:

```
.venv\Scripts\python.exe scripts\respaldo_spp.py --importar "C:\ruta\al\pap_AAAAMMDD_HHMM.dump" --crear
```

Al terminar imprime cuántas filas quedaron en cada tabla. Debe decir
decenas de miles en `fact_prices`; si dice 0, algo falló y no sigas.

<details>
<summary>¿Y si no tienes respaldo?</summary>

Se puede arrancar de cero, aceptando que se pierden las correcciones
manuales y el registro Bloomberg:

```
.venv\Scripts\python.exe -c "from src.db.connection import get_connection; from src.db.bootstrap import create_schema; conn=get_connection().__enter__(); create_schema(conn); conn.commit()"
```

(`scripts\bootstrap_db.py` no sirve aquí: exige archivos de semillas que
no vienen en el repo.)

Después crea la base `pap` en PostgreSQL, abre el tablero y carga el XLS
histórico de la SBS desde **Registro y carga → Valor cuota → carga
histórica**.
</details>

## 6. Configuración de máquina

El proyecto lee un archivo fuera del repo para saber qué puede hacer
esta computadora:

```
copy config\machine_config.yaml "%USERPROFILE%\Documents\Tools\config\market_data_config.yaml"
```

Crea la carpeta si no existe y edita el archivo copiado:

```yaml
machine_id: 'LAPTOP-NUEVA'   # como quieras llamarla en los logs
scraper_enabled: true        # imprescindible para la extracción SPP
timezone: 'America/Lima'
```

Las demás banderas (`bloomberg_enabled`, `fms_enabled`) quedan en
`false` salvo que esa máquina tenga terminal Bloomberg o acceso a FMS.

## 7. Abrir el tablero

Doble clic en **`Tablero SPP.bat`**. Levanta la API, espera a que
responda y abre el navegador en `http://127.0.0.1:8000/spp/`.

Si algo falta, el `.bat` lo dice antes de abrir nada (entorno, `.env`,
dashboard sin compilar). Si la API muere al arrancar, su ventana queda
abierta con el error.

Comprueba: el Panel muestra los KPIs y el gráfico, y **Libro** trae
fechas desde 1993.

## 8. Extracción diaria automática

Doble clic en **`scripts\Programar extraccion SPP.bat`**. Registra la
tarea de Windows *Profuturo - Valor cuota SPP*, todos los días a las
18:00, apuntando a esta copia del proyecto.

Y ahora lo importante, **la primera vez en esta máquina**:

```
scripts\"Programar extraccion SPP.bat" -Probar
```

Quédate mirando. Se abre Chrome; si el WAF de la SBS muestra una
verificación, resuélvela a mano. Esa cookie queda guardada en el perfil
y las corridas siguientes trabajan solas. Mientras no hagas esto, la
tarea de las 18:00 fallará contra el WAF.

Otros comandos del mismo archivo: `-Estado` (qué hay registrado),
`-Hora 19:30` (cambiar la hora), `-Quitar`.

> La SBS exige un Chrome **visible**, así que la sesión de Windows debe
> estar iniciada a esa hora. Con el equipo apagado la corrida se pospone
> y se recupera al volver.

---

## Comprobación final

| Señal | Dónde |
|---|---|
| El libro llega hasta la semana pasada | Pestaña **Libro** |
| Profuturo aparece en color y el resto en grises | Pestaña **Panel** |
| La tarea dice *Ready* y una próxima ejecución | **Registro y carga → Valor cuota**, cuadro "Corrida automática" |
| La extracción escribe rastro | `data\spp\extraccion.log` |

Prueba opcional de que el código está sano en esta máquina:

```
.venv\Scripts\python.exe -m pip install pytest
.venv\Scripts\python.exe -m pytest tests\prices tests\shared -q
```

---

## Si algo sale mal

| Síntoma | Causa y arreglo |
|---|---|
| El navegador abre y el tablero está vacío | Falta `.env` o la base no existe. La ventana de la API tiene el error exacto. |
| `MissingSecret: PG_PASSWORD is not set` | El `.env` quedó con la línea en blanco (paso 4). |
| `No se encontro pg_dump` | Agrega `C:\Program Files\PostgreSQL\18\bin` al PATH. |
| La extracción falla con "El WAF de la SBS bloqueo la peticion" | Haz el paso 8 con el operador delante. |
| "Google Chrome no esta instalado" | Instala Chrome real (paso 1.3). |
| El tablero dice que la tarea apunta a otra copia del proyecto | Quedaron dos carpetas del zip. Vuelve a correr `scripts\Programar extraccion SPP.bat` desde la definitiva. |
| La página se ve vieja tras actualizar el proyecto | Ctrl+F5 una vez. (La API ya pide revalidar el HTML; solo pasa si el navegador guardó algo de antes de esta versión.) |

## Actualizar el proyecto más adelante

Descarga el zip nuevo, descomprime **encima** de la carpeta `pap`
conservando `.env` y `.venv`, y vuelve a abrir `Tablero SPP.bat`. Si el
zip trae tablas o restricciones nuevas, se aplican solas al arrancar la
API; la base y su contenido no se tocan.
