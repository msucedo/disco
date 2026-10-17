#!/usr/bin/env python3
"""disco — muestra el espacio total, usado y libre de cada volumen montado,
las carpetas más pesadas, y un navegador interactivo para limpiar el disco."""

__version__ = "0.1.0"

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys

VERDE, AMARILLO, ROJO, GRIS, NEGRITA, RESET = (
    "\033[32m", "\033[33m", "\033[31m", "\033[90m", "\033[1m", "\033[0m"
)


def nombre_raiz():
    """Nombre real del volumen de arranque según diskutil (p. ej. 'Macintosh HD')."""
    try:
        salida = subprocess.run(
            ["diskutil", "info", "-plist", "/"],
            capture_output=True, timeout=5, check=True,
        ).stdout
        return plistlib.loads(salida).get("VolumeName") or "Macintosh HD"
    except Exception:
        return "Macintosh HD"


def volumenes():
    """Devuelve [(nombre, ruta)] sin duplicados: '/' más /Volumes/*."""
    candidatos = [(nombre_raiz(), "/")]
    try:
        for entrada in sorted(os.listdir("/Volumes")):
            ruta = os.path.join("/Volumes", entrada)
            if not os.path.islink(ruta) and os.path.isdir(ruta):
                candidatos.append((entrada, ruta))
    except OSError:
        pass

    vistos, resultado = set(), []
    for nombre, ruta in candidatos:
        try:
            dev = os.stat(ruta).st_dev
        except OSError:
            continue
        if dev not in vistos:
            vistos.add(dev)
            resultado.append((nombre, ruta))
    return resultado


# Lo que macOS considera disponible: lo libre más lo que puede purgar (copias
# temporales, cachés, iCloud). Python no lo expone, así que se pide a Foundation.
JXA_DISPONIBLE = """
ObjC.import("Foundation");
function run(argv) {
    var v = Ref();
    $.NSURL.fileURLWithPath(argv[0]).getResourceValueForKeyError(
        v, "NSURLVolumeAvailableCapacityForImportantUsageKey", null);
    return ObjC.unwrap(v[0]);
}
"""


def disponible(ruta):
    """Bytes disponibles según macOS, o None si no se puede saber."""
    try:
        r = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", JXA_DISPONIBLE, ruta],
            capture_output=True, text=True, timeout=5,
        )
        return int(r.stdout.strip()) if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def medir(nombre, ruta, con_disponible=True):
    try:
        uso = shutil.disk_usage(ruta)
    except OSError:
        return None
    if uso.total == 0:
        return None
    usado = uso.total - uso.free
    return {
        "nombre": nombre,
        "ruta": ruta,
        "total": uso.total,
        "usado": usado,
        "libre": uso.free,
        "disponible": disponible(ruta) if con_disponible else None,
        "porcentaje": round(usado / uso.total * 100, 1),
    }


def legible(n):
    """Bytes a texto con unidades decimales, como Finder."""
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unidad == "TB":
            return f"{n:.0f} {unidad}" if unidad == "B" else f"{n:.1f} {unidad}"
        n /= 1000


def barra(pct, ancho, color):
    llenos = round(pct / 100 * ancho)
    if not color:
        return "[" + "█" * llenos + "░" * (ancho - llenos) + "]"
    tono = VERDE if pct < 70 else AMARILLO if pct < 90 else ROJO
    return f"[{tono}{'█' * llenos}{GRIS}{'░' * (ancho - llenos)}{RESET}]"


def carpetas(ruta):
    """Tamaño de cada subcarpeta directa de `ruta`, de mayor a menor, usando du."""
    if sys.stderr.isatty():
        print(f"Escaneando {ruta} … (puede tardar un minuto)", file=sys.stderr)
    salida = subprocess.run(
        ["du", "-x", "-d", "1", "-k", ruta],
        capture_output=True, text=True,
    ).stdout
    raiz = os.path.normpath(ruta)
    resultado = []
    for linea in salida.splitlines():
        kb, _, path = linea.partition("\t")
        if path and os.path.normpath(path) != raiz:
            resultado.append({"ruta": path, "bytes": int(kb) * 1024})
    resultado.sort(key=lambda c: c["bytes"], reverse=True)
    return resultado


def mostrar_carpetas(ruta, top, ancho, color, como_json):
    datos = carpetas(ruta)[:top]
    if como_json:
        print(json.dumps(datos, indent=2, ensure_ascii=False))
        return
    if not datos:
        print(f"No se pudo leer nada en {ruta}")
        return
    mayor = datos[0]["bytes"] or 1
    nombres = [os.path.basename(c["ruta"].rstrip("/")) for c in datos]
    ancho_nombre = max(len(n) for n in nombres)
    for nombre, c in zip(nombres, datos):
        pct = c["bytes"] / mayor * 100
        if color:
            nombre_txt = f"{NEGRITA}{nombre.ljust(ancho_nombre)}{RESET}"
        else:
            nombre_txt = nombre.ljust(ancho_nombre)
        print(f"{nombre_txt}  {barra(pct, ancho, color)} {legible(c['bytes']):>9}")


# ---------------------------------------------------------------------------
# Navegador interactivo (disco -i)

HOME = os.path.realpath(os.path.expanduser("~"))
LIBRARY = os.path.join(HOME, "Library")
PROTEGIDAS = {
    "/", "/Users", "/Volumes", HOME, LIBRARY,
    os.path.join(LIBRARY, "Keychains"), os.path.join(HOME, ".Trash"),
}
PROTEGIDAS_CON_CONTENIDO = (
    "/System", "/usr", "/bin", "/sbin", "/private", "/etc", "/var",
    "/Library", "/Applications",
)


def dentro_de(ruta, carpeta):
    return ruta == carpeta or ruta.startswith(carpeta.rstrip("/") + "/")


class Arbol:
    """Tamaños de todas las carpetas bajo `raiz` (en bytes), sacados de du."""

    def __init__(self, raiz):
        self.raiz = raiz
        self.tam = {}

    def escanear(self, ruta, progreso=None):
        """Escanea `ruta` con du y reemplaza lo que hubiera debajo. Devuelve el
        cambio de tamaño de `ruta` y lo propaga a las carpetas padre."""
        antes = self.tam.get(ruta, 0)
        nuevos = {}
        proc = subprocess.Popen(
            ["du", "-x", "-k", ruta],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            errors="surrogateescape",
        )
        for i, linea in enumerate(proc.stdout):
            kb, _, path = linea.rstrip("\n").partition("\t")
            if path:
                nuevos[os.path.normpath(path)] = int(kb) * 1024
            if progreso and i % 2000 == 0:
                progreso(i)
        proc.wait()
        self.quitar(ruta, propagar=False)
        self.tam.update(nuevos)
        self._sumar_a_padres(ruta, self.tam.get(ruta, 0) - antes)

    def quitar(self, ruta, propagar=True, tam=None):
        """Quita `ruta` (y todo lo de debajo) del árbol."""
        tam = self.tam.get(ruta, 0) if tam is None else tam
        prefijo = ruta.rstrip("/") + "/"
        for clave in [c for c in self.tam if c == ruta or c.startswith(prefijo)]:
            del self.tam[clave]
        if propagar:
            self._sumar_a_padres(ruta, -tam)

    def _sumar_a_padres(self, ruta, delta):
        padre = os.path.dirname(ruta)
        while delta and dentro_de(padre, self.raiz) and padre != ruta:
            if padre in self.tam:
                self.tam[padre] += delta
            ruta, padre = padre, os.path.dirname(padre)

    def listar(self, carpeta):
        """[(nombre, ruta, bytes, es_carpeta)] de mayor a menor."""
        items = []
        with os.scandir(carpeta) as it:
            for e in it:
                try:
                    es_dir = e.is_dir(follow_symlinks=False)
                    if es_dir:
                        tam = self.tam.get(os.path.normpath(e.path), 0)
                    else:
                        tam = e.stat(follow_symlinks=False).st_blocks * 512
                except OSError:
                    es_dir, tam = False, 0
                items.append((e.name, os.path.normpath(e.path), tam, es_dir))
        items.sort(key=lambda x: (-x[2], x[0].lower()))
        return items


def motivo_protegida(ruta, raiz):
    if ruta == raiz:
        return "Es la carpeta de inicio del escaneo; no se puede mover."
    if ruta in PROTEGIDAS:
        return "Carpeta del sistema protegida; no se puede mover."
    if any(dentro_de(ruta, p) for p in PROTEGIDAS_CON_CONTENIDO):
        return "Está dentro de una carpeta del sistema; no se puede mover."
    return None


def aviso_extra(ruta):
    if dentro_de(ruta, LIBRARY) and not dentro_de(ruta, os.path.join(LIBRARY, "Caches")):
        return "Ojo: pertenece a una app; borrarlo puede hacerle perder datos o configuración."
    return None


def mover_a_papelera(ruta):
    """Devuelve (error, destino): error es None si salió bien; destino es dónde
    quedó dentro de la Papelera (None si trash no lo dijo)."""
    r = subprocess.run(["/usr/bin/trash", "-v", ruta], capture_output=True, text=True)
    if r.returncode != 0 or os.path.lexists(ruta):
        return (r.stderr or r.stdout or "no se pudo mover").strip().splitlines()[-1], None
    # trash -v escribe: # Moved "/origen" to "/destino"
    _, sep, resto = r.stdout.strip().rpartition('" to "')
    return None, (resto[:-1] if sep and resto.endswith('"') else None)



def vaciar_papelera():
    """Vacía toda la Papelera con el Finder (sin Acceso total al disco no se puede
    borrar ~/.Trash directamente). Devuelve None si salió bien, o el texto del error."""
    try:
        r = subprocess.run(
            ["osascript", "-e", 'tell application "Finder" to empty trash'],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return "el Finder tardó demasiado"
    if r.returncode != 0:
        return (r.stderr or "no se pudo vaciar").strip().splitlines()[-1]
    return None


def interactivo(stdscr, raiz):
    import curses

    curses.curs_set(0)
    curses.use_default_colors()
    for n, c in enumerate((curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_RED,
                           curses.COLOR_CYAN), start=1):
        curses.init_pair(n, c, -1)
    VERDE_, AMARILLO_, ROJO_, CIAN_ = (curses.color_pair(i) for i in range(1, 5))

    def poner(y, x, texto, attr=0):
        alto, ancho = stdscr.getmaxyx()
        if 0 <= y < alto and x < ancho - 1:
            try:
                stdscr.addnstr(y, x, texto, ancho - 1 - x, attr)
            except curses.error:
                pass

    def progreso(i):
        stdscr.erase()
        poner(0, 0, f"Escaneando {raiz} … {i:,} carpetas (Ctrl-C para cancelar)")
        stdscr.refresh()

    arbol = Arbol(raiz)
    arbol.escanear(raiz, progreso)

    actual, cursor, arriba = raiz, 0, 0
    pila = []          # [(carpeta, cursor, arriba)] para volver con ←
    en_papelera = []   # [(destino, bytes)] enviados a la Papelera en esta sesión
    estado = ""
    items = None
    disponibles = None  # cifra de macOS; se recalcula al inicio, con r y con d

    def confirmar(lineas):
        alto, _ = stdscr.getmaxyx()
        for i, (texto, attr) in enumerate(lineas):
            y = alto - len(lineas) + i
            stdscr.move(y, 0)
            stdscr.clrtoeol()
            poner(y, 0, texto, attr)
        stdscr.refresh()
        return stdscr.getch() in (ord("s"), ord("S"))

    while True:
        if items is None:
            try:
                items = arbol.listar(actual)
            except OSError as e:
                items, estado = [], f"No se pudo leer: {e.strerror}"
        alto, ancho = stdscr.getmaxyx()
        filas = max(alto - 5, 1)
        cursor = max(0, min(cursor, len(items) - 1))
        if cursor < arriba:
            arriba = cursor
        elif cursor >= arriba + filas:
            arriba = cursor - filas + 1

        stdscr.erase()
        disco_ = medir("", actual, con_disponible=False)
        if disponibles is None:
            disponibles = disponible(actual) or 0
        libre = ""
        if disco_:
            libre = f"{legible(disco_['libre'])} libres"
            if disponibles > disco_["libre"]:
                libre += f" · {legible(disponibles)} disponibles"
            libre += f" ({disco_['porcentaje']} % usado)"
        # La ruta se recorta por la izquierda para no pisar las cifras de la derecha.
        titulo = "~" + actual[len(HOME):] if dentro_de(actual, HOME) else actual
        cabe = ancho - len(libre) - len("disco — ") - 3
        if len(titulo) > cabe:
            titulo = "…" + titulo[-max(cabe - 1, 1):]
        poner(0, 0, f"disco — {titulo}", curses.A_BOLD)
        poner(0, max(ancho - len(libre) - 1, 0), libre, CIAN_)
        poner(1, 0, "─" * ancho)

        mayor = items[0][2] if items and items[0][2] else 1
        total = arbol.tam.get(actual) or sum(i[2] for i in items) or 1
        ancho_barra = 20
        for fila, (nombre, ruta, tam, es_dir) in enumerate(items[arriba:arriba + filas]):
            y = 2 + fila
            sel = arriba + fila == cursor
            peso = tam / total * 100
            tono = VERDE_ if peso < 10 else AMARILLO_ if peso < 30 else ROJO_
            llenos = round(tam / mayor * ancho_barra)
            attr = curses.A_REVERSE if sel else 0
            poner(y, 0, f"{'>' if sel else ' '} {legible(tam):>9} [", attr)
            poner(y, 13, "█" * llenos, tono | attr)
            poner(y, 13 + llenos, "░" * (ancho_barra - llenos), attr | curses.A_DIM)
            poner(y, 13 + ancho_barra, f"] {peso:5.1f}%  ", attr)
            poner(y, 23 + ancho_barra, nombre + ("/" if es_dir else ""),
                  attr | (curses.A_BOLD if es_dir else 0))
        if not items:
            poner(2, 2, "(carpeta vacía)", curses.A_DIM)

        poner(alto - 3, 0, "─" * ancho)
        poner(alto - 2, 0, "↑↓ mover  →/Enter entrar  ← subir  d a la Papelera  "
                           "o ver en Finder  r reescanear  q salir", curses.A_DIM)
        pie = estado or ""
        movido = sum(t for _, t in en_papelera)
        if movido:
            pie = (pie + "   " if pie else "") + \
                f"A la Papelera: {legible(movido)} (se libera al vaciarla)  v vaciar"
        poner(alto - 1, 0, pie, AMARILLO_)
        stdscr.refresh()

        tecla = stdscr.getch()
        estado = ""
        sel = items[cursor] if items else None

        if tecla in (ord("q"), ord("Q")):
            return sum(t for _, t in en_papelera)
        elif tecla in (curses.KEY_UP, ord("k")):
            cursor -= 1
        elif tecla in (curses.KEY_DOWN, ord("j")):
            cursor += 1
        elif tecla == curses.KEY_PPAGE:
            cursor -= filas
        elif tecla == curses.KEY_NPAGE:
            cursor += filas
        elif tecla == curses.KEY_HOME:
            cursor = 0
        elif tecla == curses.KEY_END:
            cursor = len(items) - 1
        elif tecla in (curses.KEY_RIGHT, curses.KEY_ENTER, 10, 13, ord("l")):
            if sel and sel[3]:
                pila.append((actual, cursor, arriba))
                actual, cursor, arriba, items = sel[1], 0, 0, None
        elif tecla in (curses.KEY_LEFT, curses.KEY_BACKSPACE, 127, 8, ord("h")):
            if pila:
                actual, cursor, arriba = pila.pop()
                items = None
        elif tecla in (ord("o"), ord("O")) and sel:
            subprocess.run(["open", "-R", sel[1]])
        elif tecla in (ord("r"), ord("R")):
            arbol.escanear(actual, progreso)
            items = disponibles = None
            estado = "Reescaneado."
            # Lo que ya no está en la Papelera es porque se vació (o se restauró).
            # Se revisa por ruta: el Finder no cuenta lo oculto, como .ollama.
            quedan = [(d, t) for d, t in en_papelera if d is None or os.path.lexists(d)]
            if len(quedan) < len(en_papelera):
                en_papelera = quedan
                estado = "Reescaneado. Quité del aviso lo que ya se vació de la Papelera."
        elif tecla in (ord("v"), ord("V")) and en_papelera:
            if not confirmar([("¿Vaciar TODA la Papelera? Se borra para siempre todo lo que "
                               "tenga, no solo lo de esta sesión. (s/N)",
                               ROJO_ | curses.A_BOLD)]):
                estado = "Cancelado."
                continue
            y = stdscr.getmaxyx()[0] - 1
            stdscr.move(y, 0)
            stdscr.clrtoeol()
            poner(y, 0, "Vaciando la Papelera…", AMARILLO_ | curses.A_BOLD)
            stdscr.refresh()
            error = vaciar_papelera()
            if error:
                estado = f"Error: {error}"
            else:
                en_papelera = []
                disponibles = None
                estado = "Papelera vaciada."
        elif tecla in (ord("d"), ord("D")) and sel:
            nombre, ruta, tam, es_dir = sel
            motivo = motivo_protegida(ruta, raiz)
            if motivo:
                estado = motivo
                continue
            lineas = []
            extra = aviso_extra(ruta)
            if extra:
                lineas.append((extra, ROJO_ | curses.A_BOLD))
            lineas.append((f'¿Mover "{nombre}{"/" if es_dir else ""}" ({legible(tam)}) '
                           f"a la Papelera? (s/N)", AMARILLO_ | curses.A_BOLD))
            if not confirmar(lineas):
                estado = "Cancelado."
                continue
            error, destino = mover_a_papelera(ruta)
            if error:
                estado = f"Error: {error}"
            else:
                if es_dir:
                    arbol.quitar(ruta)
                else:
                    arbol._sumar_a_padres(ruta, -tam)
                en_papelera.append((destino, tam))
                estado = f'"{nombre}" se movió a la Papelera.'
                items = disponibles = None


# argparse trae sus textos en inglés; estos son los que se ven en la ayuda y los errores.
TEXTOS_ARGPARSE = {
    "usage: ": "uso: ",
    "options": "opciones",
    "optional arguments": "opciones",
    "show this help message and exit": "muestra esta ayuda y sale",
    "argument %(argument_name)s: %(message)s": "opción %(argument_name)s: %(message)s",
    "unrecognized arguments: %s": "opciones no reconocidas: %s",
    "expected one argument": "falta un valor",
    "invalid %(type)s value: %(value)r": "valor no válido: %(value)r",
    "%(prog)s: error: %(message)s\n": "%(prog)s: error: %(message)s\n",
}

EJEMPLOS = """\
ejemplos:
  disco                    espacio de cada disco
  disco -c                 carpetas más pesadas de tu carpeta personal
  disco -c ~/Library -n 5  las 5 más pesadas de ~/Library
  disco -i                 explorar ~ y mandar cosas a la Papelera
  disco --json             salida en JSON
"""


def main():
    argparse._ = lambda texto: TEXTOS_ARGPARSE.get(texto, texto)
    parser = argparse.ArgumentParser(
        prog="disco", description="Muestra el espacio de tus discos.", epilog=EJEMPLOS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"disco {__version__}",
                        help="muestra la versión y sale")
    parser.add_argument("--json", action="store_true", help="salida en JSON")
    parser.add_argument("-w", "--width", type=int, default=30, metavar="ANCHO",
                        help="ancho de la barra (30)")
    parser.add_argument(
        "-c", "--carpetas", nargs="?", const=os.path.expanduser("~"), metavar="RUTA",
        help="muestra las carpetas más pesadas dentro de RUTA (por defecto, tu carpeta personal)",
    )
    parser.add_argument("-n", type=int, default=15, help="con -c: cuántas carpetas mostrar (15)")
    parser.add_argument(
        "-i", "--interactivo", nargs="?", const=os.path.expanduser("~"), metavar="RUTA",
        help="navegador para explorar RUTA y mover cosas a la Papelera (por defecto, ~)",
    )
    args = parser.parse_args()

    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ

    if args.interactivo:
        ruta = os.path.realpath(os.path.expanduser(args.interactivo))
        if not os.path.isdir(ruta):
            parser.error(f"no existe la carpeta: {ruta}")
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            parser.error("el modo interactivo necesita una terminal")
        import curses
        import locale
        locale.setlocale(locale.LC_ALL, "")
        try:
            movido = curses.wrapper(interactivo, ruta)
        except KeyboardInterrupt:
            return
        if movido:
            print(f"Moviste {legible(movido)} a la Papelera. Vacíala para liberar el espacio.")
        return

    if args.carpetas:
        ruta = os.path.expanduser(args.carpetas)
        if not os.path.isdir(ruta):
            parser.error(f"no existe la carpeta: {ruta}")
        mostrar_carpetas(ruta, max(args.n, 1), max(args.width, 1), color, args.json)
        return

    datos = [d for d in (medir(n, r) for n, r in volumenes()) if d]

    if args.json:
        print(json.dumps(datos, indent=2, ensure_ascii=False))
        return

    ancho_nombre = max((len(d["nombre"]) for d in datos), default=0)
    for d in datos:
        nombre = d["nombre"].ljust(ancho_nombre)
        if color:
            nombre = f"{NEGRITA}{nombre}{RESET}"
        print(
            f"{nombre}  {barra(d['porcentaje'], max(args.width, 1), color)} "
            f"{d['porcentaje']:5.1f}%   "
            f"{legible(d['usado'])} usados · {legible(d['libre'])} libres · "
            + (f"{legible(d['disponible'])} disponibles · "
               if (d["disponible"] or 0) > d["libre"] else "")
            + f"{legible(d['total'])} total"
        )


if __name__ == "__main__":
    main()
