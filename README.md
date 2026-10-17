# disco

**Mira y libera el espacio de tu Mac desde la terminal.**

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

- **macOS 14 (Sonoma) o más nuevo.** `disco` usa herramientas de macOS (`trash`,
  `diskutil`, el Finder), así que no funciona en Linux ni en Windows.
- **Python 3.8 o más nuevo.** No necesita ninguna librería extra.

## Instalación

Con [pipx](https://pipx.pypa.io) (recomendado), que instala el comando `disco` para
que lo uses desde cualquier carpeta:

```sh
brew install pipx
pipx ensurepath          # solo la primera vez; luego abre una terminal nueva
pipx install git+https://github.com/msucedo/disco
```

Para actualizar a la última versión:

```sh
pipx upgrade disco
```

Sin pipx, también puedes descargarlo y correrlo directo:

```sh
git clone https://github.com/msucedo/disco
cd disco
python3 disco.py
```

## Uso

| Comando | Qué hace |
|---|---|
| `disco` | Espacio de cada disco conectado: usado, libre, disponible y total. |
| `disco -c [RUTA]` | Las carpetas más pesadas dentro de `RUTA` (por defecto, tu carpeta personal). |
| `disco -c RUTA -n 5` | Igual, pero solo las 5 más pesadas (por defecto, 15). |
| `disco -i [RUTA]` | Navegador interactivo para explorar `RUTA` y mandar cosas a la Papelera (por defecto, `~`). |
| `disco --json` | La salida en JSON, para usarla en scripts (funciona con `disco` y `disco -c`). |
| `disco -w 50` | Cambia el ancho de las barras (por defecto, 30). |
| `disco -h` | Ayuda con todas las opciones. |
| `disco -V` | Versión instalada. |

`disco -c` puede tardar un minuto en carpetas grandes, porque tiene que medir todo lo
que hay adentro.

### Modo interactivo (`disco -i`)

Al abrirlo, `disco` mide la carpeta completa y te muestra lo que hay adentro, de lo
más pesado a lo más ligero.

| Tecla | Acción |
|---|---|
| `↑` `↓` (o `k` `j`) | Moverse por la lista |
| `→` / `Enter` (o `l`) | Entrar a la carpeta |
| `←` (o `h`) | Volver a la carpeta anterior |
| `d` | Mandar a la Papelera lo seleccionado (pide confirmación) |
| `o` | Mostrarlo en el Finder |
| `r` | Volver a medir la carpeta actual |
| `v` | Vaciar la Papelera (aparece cuando mandaste algo; pide confirmación) |
| `q` | Salir |

Cuando mandas algo a la Papelera, abajo aparece en amarillo cuánto espacio vas a
liberar. Ese espacio **no se libera hasta que vacías la Papelera**, con `v` o desde
el Finder.

## ¿Es seguro?

- **`d` no borra nada para siempre:** solo lo manda a la Papelera, y lo puedes
  recuperar desde ahí.
- **Las carpetas del sistema están protegidas:** `disco` no te deja mover `/System`,
  `/Applications`, `/Library`, tu carpeta `~/Library` completa, etc.
- **Aviso para datos de apps:** si lo que vas a mover está dentro de `~/Library`
  (fuera de `Caches`), te avisa en rojo de que esa app puede perder datos o su
  configuración.
- **`v` vacía TODA la Papelera,** no solo lo que mandaste con `disco`, y eso no se
  puede deshacer. Por eso te pide confirmación.
- **Ojo con las carpetas ocultas:** lo que empieza con punto (como `~/.ollama`) sigue
  oculto dentro de la Papelera, así que el Finder no lo muestra aunque esté ahí.

## Permisos

La primera vez que vacíes la Papelera con `v`, macOS te va a preguntar si tu terminal
puede controlar el Finder. Acepta: `disco` le pide al Finder que la vacíe, porque macOS
no deja que la terminal toque la Papelera directamente.

Si dices que no, puedes darle el permiso después en **Ajustes del Sistema →
Privacidad y seguridad → Automatización**.

## Libres vs. disponibles

`disco` muestra dos cifras, y es normal que no sean iguales:

- **Libres:** el espacio que está vacío ahora mismo. Es el mismo número que dan
  `df -h /` y `diskutil info /`.
- **Disponibles:** lo libre **más** lo que macOS puede borrar solo cuando le haga falta
  espacio (copias temporales del sistema, cachés, archivos de iCloud que se pueden
  volver a descargar). Es lo que macOS les dice a las apps que pueden usar.

El Finder muestra "disponible" con un cálculo propio, así que su número puede ser un
poco distinto del de `disco`.

## Desinstalar

```sh
pipx uninstall disco
```

## Licencia

[MIT](LICENSE) © msucedo
