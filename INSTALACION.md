# Instalar el tablero SPP en otra computadora

Guía para dejar el tablero —**Valor Cuota SPP** y **Tradebook**—
funcionando en una máquina de la red interna, **todo por descarga**: sin
USB, sin git y sin acceso a PyPI.

Al terminar tendrás el tablero abriéndose con doble clic, el libro de
valor cuota completo desde 1993, el Tradebook listo para recibir
operaciones y la extracción diaria automática a las 16:00 (con
reintentos a las 16:30 y 17:00), a cargo del scheduler del proyecto.

Verificado el 2026-09-14 reproduciendo ese entorno completo (Python
3.10.6 portable + los wheels de `pypro_packs`): los tests pasan, la
API levanta, crea el esquema, registra las series y sirve el tablero.
Los cambios posteriores se prueban en la máquina de desarrollo y
viajan con el mismo zip; la base se pone al día con `Crear base.bat`
(sección «Actualizar el proyecto»).

---

## 0. Qué descargar

Cuatro descargas, todas desde el navegador de esa misma máquina:

| Qué | De dónde |
|---|---|
| **El proyecto** | `https://github.com/RicardoSachs/pap/archive/refs/heads/cambios_vc.zip` (2 MB — incluye el tablero ya compilado) |
| **Python 3.10** | `https://github.com/gabdejo/py_versions` → carpeta `3106`. Si esa máquina ya tiene Python 3.10, sáltatelo |
| **Las librerías** | `https://github.com/gabdejo/pypro_packs` — el wheelhouse que ya usas |
| **Lo que falta** | `https://github.com/RicardoSachs/pap/releases/download/deps-py310/dependencias-faltantes-py310.zip` (44 MB) |

Esa última descarga trae los paquetes que **no están** en
`pypro_packs` y el proyecto necesita:

- **`python-multipart`** — sin él la API ni siquiera arranca: FastAPI lo
  exige para recibir archivos, y de eso depende la carga del XLS
  histórico.
- **`playwright`** (con `pyee` y `greenlet`) — la extracción de la SBS.
- **`blpapi`** — la API de Bloomberg, que usan los pipelines de precios
  del repositorio base. Se instala en todas las máquinas (el wheel trae
  su propia DLL) y solo trabaja donde el `.env` dice `BLOOMBERG_ENABLED=true`.

Descomprime cada zip en una carpeta que puedas ubicar; el instalador
del paso 3 las busca solo si están junto al proyecto o en *Descargas*.

## 1. Programas base

1. **PostgreSQL** — anota la contraseña del usuario `postgres`; deja el
   puerto en 5432.
2. **Google Chrome** — obligatorio: el WAF de la SBS rechaza navegadores
   headless y el Chromium que trae Playwright. Tiene que ser Chrome real.

Python no hace falta instalarlo: el del paso 0 (`py_versions/3106`) es
portable y se usa tal cual.

## 2. Descomprimir el proyecto en su lugar definitivo

Extrae el zip y **renombra la carpeta a `pap`**, en la ruta donde va a
vivir — por ejemplo `C:\Proyectos\pap`.

Que sea una ruta **local y fija**, fuera de `Documentos`: en estas
máquinas Windows redirige *Documentos* a OneDrive, y una carpeta que se
sincroniza cambia de sitio sin avisar (ya pasó: la tarea programada
quedó apuntando a una ruta que dejó de existir).

Muévelo *ahora*, no después: la tarea de Windows del paso 7 guarda la
ruta absoluta, y los datos (`data\`) nacen como carpeta hermana del
proyecto.

## 3. Crear el entorno de Python

Doble clic en **`scripts\Instalar entorno.bat`**. Crea el `.venv` con el
Python 3.10 portable e instala todo desde las carpetas del paso 0, sin
tocar internet.

Si no encuentra alguna carpeta te lo dice; en ese caso pásale las rutas:

```
scripts\"Instalar entorno.bat" C:\ruta\pypro_packs C:\ruta\dependencias-faltantes-py310
```

Termina comprobando que todo importa. Las versiones son las de
`requirements-oficina.txt`, alineadas con el wheelhouse (pandas 2.3.3,
FastAPI 0.137.1…).

Las rutas pueden tener espacios (`Program Files`, `Mis Documentos`) y
pueden ser de red (`\\servidor\...`). Las librerías desde la red van
bien: pip las copia dentro del `.venv`. El **Python** conviene tenerlo
en local — el `.venv` recuerda dónde está su intérprete y lo necesita en
cada arranque, también en el scheduler que corre al iniciar sesión. Y si la
carpeta venía con un `.venv` de otra máquina, bórralo antes: un entorno
no se puede copiar, sigue apuntando al Python de donde nació.

> `requirements.lock.txt` es **otra cosa**: describe la máquina de
> desarrollo (Python 3.14, pandas 3.x). Esos wheels no existen en
> `pypro_packs` y aquí no hay de dónde bajarlos.

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
DATA_DIR=C:\Proyectos\data
MACHINE_ID=LAPTOP-NUEVA
SCRAPER_ENABLED=true
```

Este es **el único archivo que tienes que escribir** en la máquina
nueva. Las dos últimas líneas dicen qué puede hacer esta computadora:
`SCRAPER_ENABLED=true` es lo que habilita la extracción de la SBS, y
`MACHINE_ID` es solo el nombre con el que aparece en los registros.

Si **esa** máquina tiene terminal Bloomberg, agrega también:

```
BLOOMBERG_ENABLED=true
```

para los pipelines de precios del repositorio base. El tablero SPP no lo
necesita: los benchmarks se componen de series del propio libro de
precios.

`DATA_DIR` es opcional pero conviene fijarlo: vacío significa "la
carpeta `data` hermana del proyecto", y si algún día mueves la carpeta
se te quedan atrás el rastro de las extracciones y el perfil de Chrome.

## 5. Crear la base y llenarla

Doble clic en **`scripts\Crear base.bat`**. Lee el `.env`, crea la base
con ese nombre si no existe, le aplica el esquema y registra las series
del SPP. Si ya existe no borra nada: solo agrega lo que falte, y se puede
repetir sin miedo. Es también el paso que se corre **después de cada
actualización** del proyecto.

<details>
<summary>A mano, si prefieres</summary>

Desde **pgAdmin**: en el árbol de la izquierda, clic derecho sobre
*Databases* → *Create* → *Database…*, escribe `pap` en **Database** y
*Save*.

Desde la **consola** (el `bin` de PostgreSQL no suele estar en el PATH,
así que conviene la ruta completa):

```
"C:\Program Files\PostgreSQL\18\bin\createdb.exe" -U postgres pap
```

Te pedirá la contraseña del usuario `postgres`. El nombre tiene que ser
el mismo que pusiste en `PG_DBNAME`. El esquema lo aplica después
`Crear base.bat` (o `.venv\Scripts\python.exe scripts\crear_base.py`).
</details>

El libro de valor cuota **se reconstruye desde la fuente**, que es
pública:

1. Abre el tablero (paso 6) y ve a **Registro y carga → Valor cuota**.
2. Pulsa *Abrir la página de la SBS* y descarga el Excel
   «Valores cuota desde Agosto 1993».
3. Súbelo en **carga histórica por Excel**. Revisa lo que muestra y
   confirma con *Cargar lo que falta*.

Eso deja el libro completo desde 1993. La extracción diaria se encarga
del resto.

> Lo que no viaja por esta vía es lo que solo existe en la otra
> computadora: las correcciones hechas a mano y las versiones de los
> benchmarks. Son pocas y se vuelven a declarar desde el tablero en
> minutos. Si algún día quieres moverlas tal cual y tienes cómo pasar un
> archivo, está `scripts\respaldo_spp.py --exportar` / `--importar`.

## 6. Abrir el tablero

Doble clic en **`Tablero SPP.bat`**. Levanta la API, espera a que
responda y abre el navegador en `http://127.0.0.1:8000/spp/`.

Si algo falta, el `.bat` lo dice antes de abrir nada (entorno, `.env`,
dashboard sin compilar). Si la API muere al arrancar, su ventana queda
abierta con el error.

Comprueba: el **Panel** muestra el gráfico y las tablas de rentabilidad
(vacías hasta cargar el histórico), **Libro** trae fechas desde 1993
una vez cargado, y **Tradebook → Registro y carga** descarga su
plantilla XLSX.

Las vistas de cada módulo (Panel, Libro, Registro...) se cambian en la
**barra flotante** de arriba, la misma de los demás tableros: a la
izquierda el tipo de fondo, al centro la ventana de tiempo (1M, 3M,
YTD, 1Y o Custom con dos fechas) y a la derecha la lista de vistas.

**Benchmarks** tiene su propia entrada en el menú: **Panel** y **Libro**
muestran los índices compuestos y **Registro** los declara y versiona
sus canastas; el rebalanceo es manual: cada versión fija los pesos desde
su fecha de vigencia hasta la siguiente. La canasta se arma buscando series de
precios por código, nombre, ticker o ISIN entre todo lo que los
pipelines cargan en la base (Bloomberg, vector SBS, valor cuota SPP):
con el `.env` apuntando al servidor de la oficina aparecen sin
configurar nada más. Si un ticker de Bloomberg no está, el bloque
"¿No aparece el ticker?" del mismo editor lo registra; queda "pendiente
de histórico" hasta la siguiente corrida de backfill de la máquina con
terminal Bloomberg (`run_prices.py --source bloomberg --backfill`), y
hasta entonces no tiene precios y una canasta que lo use no se puede
recalcular.

## 7. Extracción diaria automática

La extracción no es una tarea propia: es un trabajo (`acquire_spp`) del
**scheduler** del proyecto, `scripts\scheduler.py`, el mismo proceso que
en la oficina corre Bloomberg, la adquisición SBS y FMS. Qué trabajos
corre cada máquina lo deciden las banderas de su `.env`
(`SCRAPER_ENABLED=true` habilita el valor cuota); a qué hora, el archivo
`config\schedules.yaml`: 16:00 con reintentos a las 16:30 y 17:00, de
lunes a viernes. La SBS publica el valor cuota de **t-2 días hábiles**;
cada intento mira primero si el libro ya lo tiene y, si es así, no abre
Chrome. Si a las 17:00 la SBS aún no publicó, se queda así hasta el día
siguiente.

Doble clic en **`scripts\Programar scheduler.bat`**. Registra la tarea
de Windows *pgetl scheduler*, que arranca el scheduler al iniciar sesión
y lo reinicia si muere, y lo arranca en ese momento. Queda una ventana
abierta llamada *scheduler*: es el proceso, no la cierres.

La tarea se registra para correr **también con batería**: las tareas de
Windows traen por defecto "no iniciar con batería" y "detener al pasar a
batería", y con eso desenchufar la laptop mataba el scheduler y la tarea
quedaba en *Queued* sin volver a arrancar. Si una tarea registrada antes
de este cambio aparece en ese estado, vuelve a correr el `.bat`: la
re-registra con las condiciones correctas.

Si esta máquina solo hace el valor cuota (no tiene chromedriver ni ve la
carpeta de red de la adquisición SBS), agrega al `.env`:

```
AUTOMATED_SCRAPER_ENABLED=false
```

Y ahora lo importante, **la primera vez en esta máquina**:

```
.venv\Scripts\python.exe scripts\run_sbs_valor_cuota.py --scheduled
```

Quédate mirando. Se abre Chrome; si el WAF de la SBS muestra una
verificación, resuélvela a mano. Esa cookie queda guardada en el perfil
y las corridas siguientes trabajan solas. Mientras no hagas esto, el
trabajo de las 16:00 fallará contra el WAF.

Otros comandos del mismo archivo: `-Estado` (la tarea, la última señal
de vida del scheduler y las últimas corridas) y `-Quitar`.

> La SBS exige un Chrome **visible**, así que la sesión de Windows debe
> estar iniciada a esa hora. Con el equipo apagado el scheduler arranca
> al volver a iniciar sesión y recupera la corrida perdida si está dentro
> de la ventana de gracia (25 minutos).

---

## Comprobación final

| Señal | Dónde |
|---|---|
| El libro llega hasta la semana pasada | Pestaña **Libro** |
| Profuturo aparece en color y el resto en grises | Pestaña **Panel** |
| El scheduler late (visto hace menos de 10 minutos) y lista `acquire_spp` | `scripts\"Programar scheduler.bat" -Estado` |
| Cada corrida queda registrada | la misma pantalla, o `SELECT * FROM job_runs ORDER BY started_at DESC` |
| El reporte PDF se genera | **Panel**, icono de descarga junto a las pestañas |

Prueba opcional de que el código está sano en esta máquina (necesita
`pytest`, que no viene en el wheelhouse):

```
.venv\Scripts\python.exe -m pytest tests\prices tests\shared tests\web tests\tradebook tests\analytics -q
```

Deben pasar los 132 (siete más se saltan: piden una base de pruebas
que aquí no hace falta).

---

## Si algo sale mal

| Síntoma | Causa y arreglo |
|---|---|
| El navegador abre y el tablero está vacío | Falta `.env` o la base no existe. La ventana de la API tiene el error exacto. |
| `MissingSecret: PG_PASSWORD is not set` | El `.env` quedó con la línea en blanco (paso 4). |
| `No se encontro pg_dump` | Agrega `C:\Program Files\PostgreSQL\18\bin` al PATH. |
| `El scraper no esta habilitado en esta maquina` | Falta `SCRAPER_ENABLED=true` en el `.env` (paso 4). Reinicia el tablero después: la configuración se lee al arrancar. |
| La extracción falla con "El WAF de la SBS bloqueo la peticion" | Haz el paso 7 con el operador delante. |
| "Google Chrome no esta instalado" | Instala Chrome real (paso 1.2). |
| `ModuleNotFoundError: multipart` o la API no arranca | Falta la descarga de `dependencias-faltantes-py310` (paso 0). Vuelve a correr el instalador con las dos carpetas. |
| `Could not find a version that satisfies...` al instalar | La carpeta de `pypro_packs` está incompleta, o el Python no es 3.10 de 64 bits. |
| `there is no unique or exclusion constraint matching the ON CONFLICT specification` | A la base le faltan restricciones que el código necesita, porque la creó una versión anterior. Doble clic en **`scripts\Verificar esquema.bat`**: compara tu base con el esquema del proyecto, dice exactamente qué falta y se ofrece a agregarlo. |
| `-Estado` dice que ningún scheduler ha latido, o la tarea apunta a otra carpeta | El scheduler no corre, o corre desde una copia vieja del proyecto. Vuelve a correr `scripts\Programar scheduler.bat` desde la carpeta definitiva. |
| En `job_runs` el trabajo `acquire_spp` termina en segundos con "The book already holds aaaa-mm-dd ... the SBS is not scraped" en el log | No es un error: la SBS publica t-2 días hábiles y ese día ya estaba cargado. Los reintentos de las 16:30 y 17:00 dicen lo mismo cuando el de las 16:00 acertó. |
| A las 08:30 suena un pitido y `job_runs` registra `acquire_sbs` con error | Esta máquina no hace la adquisición SBS del extranet: pon `AUTOMATED_SCRAPER_ENABLED=false` en el `.env` y reinicia el scheduler. |
| Al registrar un valor: `No series registered for ...` | La base es nueva o se actualizó sin correr **`scripts\Crear base.bat`**, que registra las series del SPP. Córrelo y reinicia el tablero. |
| La página se ve vieja tras actualizar el proyecto | Ctrl+F5 una vez. (La API ya pide revalidar el HTML; solo pasa si el navegador guardó algo de antes de esta versión.) |
| Tras actualizar, el tablero sigue con el comportamiento viejo o da 404 en alguna acción | El tablero que estaba abierto sigue corriendo el código anterior: `Tablero SPP.bat` no reemplaza uno que ya responde. Cierra su ventana y vuelve a lanzarlo. |

## Actualizar el proyecto más adelante

La dinámica es de dos pasos, sin git en esta máquina:

1. En la computadora donde se trabaja: subir los cambios a GitHub.
2. Aquí: bajar otra vez el mismo zip

   ```
   https://github.com/RicardoSachs/pap/archive/refs/heads/cambios_vc.zip
   ```

   y descomprimirlo **encima** de la carpeta `pap`, aceptando reemplazar.
   **Antes, cierra la ventana del tablero** si está abierta: el `.bat`
   no reemplaza un tablero que ya responde, y uvicorn no recarga el
   código de Python por sí solo.

`.env`, `.venv\` y la carpeta `data\` sobreviven: los dos primeros
porque el zip no los trae, la tercera porque vive fuera del proyecto.
Las librerías tampoco hay que reinstalarlas, salvo que el proyecto
estrene alguna dependencia nueva.
Después de descomprimir, **doble clic en `scripts\Crear base.bat`**:
aplica a la base los cambios de esquema que traiga la versión nueva y
registra las series que falten. El contenido del libro no se toca. Luego
vuelve a abrir `Tablero SPP.bat`.

Dos pasos más, solo **al pasar a la versión de octubre de 2026** (la que
reorganizó el pipeline y los benchmarks):

1. La extracción ya no es una tarea propia sino un trabajo del
   scheduler: quita la tarea vieja *Profuturo - Valor cuota SPP*
   (`schtasks /Delete /TN "Profuturo - Valor cuota SPP" /F`) y corre
   `scripts\Programar scheduler.bat`.
2. Si la base la creó una versión anterior (tiene las tablas `benchmark`
   y `benchmark_composicion`), conviértela una sola vez:

   ```
   .venv\Scripts\python.exe scripts\migrate\migrate_fork_benchmarks.py --apply --drop-legacy
   ```

   Sin `--apply` solo muestra lo que haría.

Un detalle: descomprimir encima **no borra** los archivos que
desaparezcan del proyecto. En la práctica solo significa que se van
acumulando piezas viejas del tablero compilado (llevan un código en el
nombre, así que no estorban). Si alguna vez quieres dejarlo limpio,
borra la carpeta `pap` entera salvo `.env` y `.venv`, y descomprime.
