# disco

**Mira y libera el espacio de tu disco desde la terminal.** Funciona en macOS, Linux y
Windows.

`disco` te dice cuánto espacio te queda, qué carpetas se lo están comiendo y te deja
explorarlas para mandar a la Papelera lo que ya no necesitas, sin salir de la terminal.

```
$ disco
Macintosh HD  [█████████████████████░░░░░░░░░]  70.0%   350.0 GB usados · 150.0 GB libres · 172.5 GB disponibles · 500.0 GB total
```

```
$ disco -c -n 5
Library       [████████████████████████]   80.0 GB
Downloads     [████████████░░░░░░░░░░░░]   40.0 GB
Movies        [████████░░░░░░░░░░░░░░░░]   25.0 GB
Documents     [████░░░░░░░░░░░░░░░░░░░░]   12.0 GB
Pictures      [██░░░░░░░░░░░░░░░░░░░░░░]    6.5 GB
```

```
$ disco -i ~/Proyecto
disco — ~/Proyecto                                150.0 GB libres · 172.5 GB disponibles (70.0 % usado)
───────────────────────────────────────────────────────────────────────────────────────────────────
     9.0 MB [████████████████████]  64.7%  Videos/
>    3.0 MB [███████░░░░░░░░░░░░░]  21.6%  Fotos/
     1.2 MB [███░░░░░░░░░░░░░░░░░]   8.6%  Proyectos/
   503.8 KB [█░░░░░░░░░░░░░░░░░░░]   3.6%  Descargas/
   200.7 KB [░░░░░░░░░░░░░░░░░░░░]   1.4%  notas.txt

───────────────────────────────────────────────────────────────────────────────────────────────────
↑↓ mover  →/Enter entrar  ← subir  d a la Papelera  o ver en Finder  r reescanear  q salir
```

## Requisitos

- **Python 3.8 o más nuevo.**
- **macOS 14 (Sonoma) o más nuevo**, **cualquier Linux** o **Windows 10/11**.
- En Windows, el modo interactivo necesita el paquete `windows-curses`. Si instalas
  con pip (abajo) se instala solo.

## Instalación

Con `pip`, que instala el comando `disco` para que lo uses desde cualquier carpeta.

**macOS y Linux** (en Debian/Ubuntu, instala antes `sudo apt install git python3-pip`)

```sh
python3 -m pip install --user git+https://github.com/msucedo/disco
```

**Windows** (en PowerShell o en Terminal; necesitas [Python](https://www.python.org/downloads/)
y [Git](https://git-scm.com/download/win))

```powershell
py -m pip install --user git+https://github.com/msucedo/disco
```

Si después la terminal no encuentra `disco`, agrega a tu `PATH` la carpeta donde pip
instala los comandos: `~/.local/bin` en Linux, `~/Library/Python/3.X/bin` en macOS
(cambia `3.X` por tu versión de Python). En Windows, pip te muestra la ruta en un
aviso al terminar de instalar.

Si pip responde con el error `externally-managed-environment` (pasa con el Python de
Homebrew y en Debian/Ubuntu recientes), instálalo en un entorno virtual:

```sh
python3 -m venv ~/.venvs/disco
~/.venvs/disco/bin/pip install git+https://github.com/msucedo/disco
```

y agrega `~/.venvs/disco/bin` a tu `PATH`. O, si prefieres, añade
`--break-system-packages` al comando de instalación.

Para actualizar a la última versión (en Windows, usa `py` en vez de `python3`):

```sh
python3 -m pip install --user --upgrade git+https://github.com/msucedo/disco
```

Sin instalarlo, también puedes descargarlo y correrlo directo (en Windows, usa `py` en vez
de `python3` e instala antes `py -m pip install windows-curses`):

```sh
git clone https://github.com/msucedo/disco
cd disco
python3 disco.py
```

## Uso

| Comando | Qué hace |
|---|---|
| `disco` | Espacio de cada disco conectado: usado, libre, disponible (solo macOS) y total. |
| `disco -c [RUTA]` | Las carpetas más pesadas dentro de `RUTA` (por defecto, la carpeta actual). |
| `disco -c RUTA -n 5` | Igual, pero solo las 5 más pesadas (por defecto, 15). |
| `disco -i [RUTA]` | Navegador interactivo para explorar `RUTA` y mandar cosas a la Papelera (por defecto, la carpeta actual). |
| `disco --json` | La salida en JSON, para usarla en scripts (funciona con `disco` y `disco -c`). |
| `disco -w 50` | Cambia el ancho de las barras (por defecto, 30). |
| `disco -h` | Ayuda con todas las opciones. |
| `disco -V` | Versión instalada. |

`disco -c` puede tardar un minuto en carpetas grandes, porque tiene que medir todo lo
que hay adentro. En Windows tarda un poco más, porque no existe `du` y `disco` lo mide
por su cuenta.

En Windows, `~` también funciona: `disco -c ~\Downloads`.

### Modo interactivo (`disco -i`)

Al abrirlo, `disco` mide la carpeta completa y te muestra lo que hay adentro, de lo
más pesado a lo más ligero. Sin `RUTA`, empieza en la carpeta donde estás parado
(`cd /Users && disco -i` abre `/Users`).

Con `←` puedes subir más allá de la carpeta de inicio: desde `~` llegas a `/Users`, y
de ahí a `/`. Al subir, `disco` solo mide lo nuevo y no vuelve a medir lo que ya
tenía, así que es rápido.

| Tecla | Acción |
|---|---|
| `↑` `↓` (o `k` `j`) | Moverse por la lista |
| `→` / `Enter` (o `l`) | Entrar a la carpeta |
| `←` (o `h`) | Volver a la carpeta anterior; en la carpeta de inicio, sube a la que la contiene |
| `d` | Mandar a la Papelera lo seleccionado (pide confirmación) |
| `o` | Mostrarlo en el Finder, el Explorador de Windows o el administrador de archivos de Linux |
| `r` | Volver a medir la carpeta actual |
| `v` | Vaciar la Papelera (aparece cuando mandaste algo; pide confirmación) |
| `q` | Salir |

Cuando mandas algo a la Papelera, abajo aparece en amarillo cuánto espacio vas a
liberar. Ese espacio **no se libera hasta que vacías la Papelera**, con `v` o desde
tu sistema.

## ¿Es seguro?

- **`d` no borra nada para siempre:** solo lo manda a la Papelera (la Papelera de
  reciclaje en Windows), y lo puedes recuperar desde ahí.
- **Las carpetas del sistema están protegidas.** `disco` no te deja mover la raíz de
  un disco ni, por ejemplo:
  - macOS: `/System`, `/Applications`, `/Library`, tu `~/Library` completa.
  - Linux: `/usr`, `/etc`, `/boot`, `/var`, `/home`, tus `~/.config` y
    `~/.local/share` completas.
  - Windows: `C:\Windows`, `Program Files`, `ProgramData`, `C:\Users`, tu `AppData`
    completa.
- **Aviso para datos de apps:** si lo que vas a mover está dentro de `~/Library`
  (macOS, fuera de `Caches`), `~/.config` o `~/.local/share` (Linux) o `AppData`
  (Windows, fuera de `Temp`), te avisa en rojo de que esa app puede perder datos o su
  configuración.
- **`v` vacía TODA la Papelera,** no solo lo que mandaste con `disco`, y eso no se
  puede deshacer. Por eso te pide confirmación.
- **Ojo con las carpetas ocultas en macOS:** lo que empieza con punto (como
  `~/.ollama`) sigue oculto dentro de la Papelera, así que el Finder no lo muestra
  aunque esté ahí.
- **En Windows,** si algo es demasiado grande para la Papelera de reciclaje, Windows
  te pregunta antes de borrarlo para siempre.

## Permisos (solo macOS)

La primera vez que vacíes la Papelera con `v`, macOS te va a preguntar si tu terminal
puede controlar el Finder. Acepta: `disco` le pide al Finder que la vacíe, porque macOS
no deja que la terminal toque la Papelera directamente.

Si dices que no, puedes darle el permiso después en **Ajustes del Sistema →
Privacidad y seguridad → Automatización**.

## Libres vs. disponibles (solo macOS)

En macOS, `disco` muestra dos cifras, y es normal que no sean iguales:

- **Libres:** el espacio que está vacío ahora mismo. Es el mismo número que dan
  `df -h /` y `diskutil info /`.
- **Disponibles:** lo libre **más** lo que macOS puede borrar solo cuando le haga falta
  espacio (copias temporales del sistema, cachés, archivos de iCloud que se pueden
  volver a descargar). Es lo que macOS les dice a las apps que pueden usar.

El Finder muestra "disponible" con un cálculo propio, así que su número puede ser un
poco distinto del de `disco`. En Linux y Windows no existe esa diferencia, así que solo
se muestra "libres".

## Desinstalar

En Windows, usa `py` en vez de `python3`:

```sh
python3 -m pip uninstall disco
```

## Licencia

[MIT](LICENSE) © msucedo
