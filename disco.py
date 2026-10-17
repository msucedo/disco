#!/usr/bin/env python3
"""disco — muestra el espacio total, usado y libre de cada disco, las carpetas más
pesadas, y un navegador interactivo para limpiar el disco. Corre en macOS, Linux y
Windows."""

__version__ = "0.2.0"

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

VERDE, AMARILLO, ROJO, GRIS, NEGRITA, RESET = (
    "\033[32m", "\033[33m", "\033[31m", "\033[90m", "\033[1m", "\033[0m"
)

SISTEMA = platform.system()
MAC, LINUX, WINDOWS = SISTEMA == "Darwin", SISTEMA == "Linux", SISTEMA == "Windows"


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


def candidatos_mac():
    """'/' más /Volumes/*."""
    candidatos = [(nombre_raiz(), "/")]
    try:
        for entrada in sorted(os.listdir("/Volumes")):
            ruta = os.path.join("/Volumes", entrada)
            if not os.path.islink(ruta) and os.path.isdir(ruta):
                candidatos.append((entrada, ruta))
    except OSError:
        pass
    return candidatos


# Sistemas de archivos de discos de verdad; se saltan tmpfs, proc, overlay, squashfs…
FS_REALES = {
    "ext2", "ext3", "ext4", "xfs", "btrfs", "vfat", "exfat", "ntfs", "ntfs3", "f2fs",
    "zfs", "fuseblk", "hfsplus", "jfs", "reiserfs", "bcachefs",
}


def candidatos_linux():
    """Puntos de montaje de /proc/mounts, uno por dispositivo y con '/' primero
    (los subvolúmenes de btrfs comparten dispositivo y se verían repetidos)."""
    montajes = []
    try:
        with open("/proc/mounts") as f:
            for linea in f:
                partes = linea.split()
                if len(partes) < 3 or partes[2] not in FS_REALES:
                    continue
                # /proc/mounts escapa espacios y otros caracteres como \040
                ruta = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), partes[1])
                if ruta.startswith(("/snap/", "/boot")):
                    continue
                montajes.append((partes[0], ruta))
    except OSError:
        return [("/", "/")]
    montajes.sort(key=lambda m: (m[1] != "/", m[1]))
    vistos, candidatos = set(), []
    for dispositivo, ruta in montajes:
        if dispositivo not in vistos:
            vistos.add(dispositivo)
            candidatos.append((ruta, ruta))
    return candidatos or [("/", "/")]


def candidatos_windows():
    """Unidades C:, D:… con su etiqueta, p. ej. 'Windows (C:)'."""
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.SetErrorMode(1)  # sin ventanas de "inserte un disco" en lectores vacíos
    mascara = k32.GetLogicalDrives()
    candidatos = []
    for i in range(26):
        if not mascara >> i & 1:
            continue
        letra = f"{chr(ord('A') + i)}:"
        raiz = letra + "\\"
        if k32.GetDriveTypeW(raiz) not in (2, 3, 4, 6):  # extraíble, fijo, red, RAM
            continue
        etiqueta = ctypes.create_unicode_buffer(261)
        ok = k32.GetVolumeInformationW(raiz, etiqueta, 261, None, None, None, None, 0)
        nombre = etiqueta.value if ok and etiqueta.value else "Disco local"
        candidatos.append((f"{nombre} ({letra})", raiz))
    return candidatos


def volumenes():
    """Devuelve [(nombre, ruta)] de cada disco, sin duplicados."""
    if WINDOWS:
        candidatos = candidatos_windows()
    elif LINUX:
        candidatos = candidatos_linux()
    else:
        candidatos = candidatos_mac()

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
    """Bytes disponibles según macOS, o None si no se puede saber (o no es macOS)."""
    if not MAC:
        return None
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


def tamano_archivo(st):
    """Lo que ocupa en disco (bloques, como du); en Windows no hay bloques."""
    bloques = getattr(st, "st_blocks", None)
    return bloques * 512 if bloques is not None else st.st_size


def tamanos(ruta, progreso=None):
    """{carpeta: bytes} de `ruta` y todas sus subcarpetas, sin cruzar a otros discos.
    Usa du si existe (mucho más rápido); si no (Windows), lo mide en Python."""
    if not WINDOWS and shutil.which("du"):
        return tamanos_du(ruta, progreso)
    return tamanos_python(ruta, progreso)


def tamanos_du(ruta, progreso=None):
    resultado = {}
    proc = subprocess.Popen(
        ["du", "-x", "-k", ruta],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        errors="surrogateescape",
    )
    for i, linea in enumerate(proc.stdout):
        kb, _, path = linea.rstrip("\n").partition("\t")
        if path:
            resultado[os.path.normpath(path)] = int(kb) * 1024
        if progreso and i % 2000 == 0:
            progreso(i)
    proc.wait()
    return resultado


REPARSE_POINT = 0x400  # en Windows: enlaces, junctions y puntos de montaje


def tamanos_python(ruta, progreso=None):
    """Como `du -x`: no sigue enlaces ni entra a otros discos, y cuenta una sola vez
    cada archivo con enlaces duros."""
    raiz = os.path.normpath(ruta)
    try:
        dev = os.stat(raiz).st_dev
    except OSError:
        return {}
    resultado, vistos, orden, pila = {}, set(), [], [raiz]
    while pila:
        carpeta = pila.pop()
        orden.append(carpeta)
        total = 0
        try:
            with os.scandir(carpeta) as it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                        es_dir = e.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    if es_dir:
                        # En Windows, DirEntry.stat no trae st_dev; ahí los otros
                        # discos montados en carpetas son puntos de reanálisis.
                        if getattr(st, "st_file_attributes", 0) & REPARSE_POINT:
                            continue
                        if not WINDOWS and st.st_dev != dev:
                            continue
                        pila.append(os.path.normpath(e.path))
                        continue
                    if st.st_nlink > 1:
                        if (st.st_dev, st.st_ino) in vistos:
                            continue
                        vistos.add((st.st_dev, st.st_ino))
                    total += tamano_archivo(st)
        except OSError:
            pass
        resultado[carpeta] = total
        if progreso and len(orden) % 2000 == 0:
            progreso(len(orden))
    for carpeta in reversed(orden):  # de las más hondas hacia arriba
        if carpeta != raiz:
            resultado[os.path.dirname(carpeta)] += resultado[carpeta]
    return resultado


def carpetas(ruta):
    """Tamaño de cada subcarpeta directa de `ruta`, de mayor a menor."""
    if sys.stderr.isatty():
        print(f"Escaneando {ruta} … (puede tardar un minuto)", file=sys.stderr)
    raiz = os.path.normpath(ruta)
    resultado = [
        {"ruta": path, "bytes": tam} for path, tam in tamanos(raiz).items()
        if path != raiz and os.path.dirname(path) == raiz
    ]
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
    nombres = [os.path.basename(c["ruta"].rstrip(os.sep)) for c in datos]
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

# Por sistema:
#   PROTEGIDAS: no se pueden mover (pero sí lo que tienen adentro).
#   PROTEGIDAS_CON_CONTENIDO: ni ellas ni nada de adentro.
#   DATOS_DE_APPS / EXCEPTO: dentro de DATOS_DE_APPS (salvo EXCEPTO) sale un aviso rojo.
#   NOMBRES_PROTEGIDOS: carpetas que no se tocan estén donde estén.
if WINDOWS:
    APPDATA = os.path.join(HOME, "AppData")
    PROTEGIDAS = {os.path.dirname(HOME), HOME, APPDATA}
    PROTEGIDAS_CON_CONTENIDO = tuple(
        os.path.normpath(p) for p in (
            os.environ.get("SystemRoot") or r"C:\Windows",
            os.environ.get("ProgramFiles") or r"C:\Program Files",
            os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)",
            os.environ.get("ProgramData") or r"C:\ProgramData",
        )
    )
    DATOS_DE_APPS = (APPDATA,)
    EXCEPTO = (os.path.join(APPDATA, "Local", "Temp"),)
    NOMBRES_PROTEGIDOS = {"$recycle.bin", "system volume information"}
    NOMBRE_EXPLORADOR = "en el Explorador"
elif LINUX:
    DATOS_XDG = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
    PAPELERA_LINUX = os.path.join(DATOS_XDG, "Trash")
    PROTEGIDAS = {"/home", HOME, os.path.join(HOME, ".config"), DATOS_XDG}
    PROTEGIDAS_CON_CONTENIDO = (
        "/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/libx32", "/opt",
        "/proc", "/root", "/run", "/sbin", "/snap", "/srv", "/sys", "/usr", "/var",
        PAPELERA_LINUX,
    )
    DATOS_DE_APPS = (os.path.join(HOME, ".config"), DATOS_XDG)
    EXCEPTO = ()
    NOMBRES_PROTEGIDOS = set()
    NOMBRE_EXPLORADOR = "su carpeta"
else:
    LIBRARY = os.path.join(HOME, "Library")
    PROTEGIDAS = {
        "/Users", "/Volumes", HOME, LIBRARY,
        os.path.join(LIBRARY, "Keychains"), os.path.join(HOME, ".Trash"),
    }
    PROTEGIDAS_CON_CONTENIDO = (
        "/System", "/usr", "/bin", "/sbin", "/private", "/etc", "/var",
        "/Library", "/Applications",
    )
    DATOS_DE_APPS = (LIBRARY,)
    EXCEPTO = (os.path.join(LIBRARY, "Caches"),)
    NOMBRES_PROTEGIDOS = set()
    NOMBRE_EXPLORADOR = "en Finder"

PROTEGIDAS = {os.path.normcase(p) for p in PROTEGIDAS}


def dentro_de(ruta, carpeta):
    ruta, carpeta = os.path.normcase(ruta), os.path.normcase(carpeta)
    return ruta == carpeta or ruta.startswith(carpeta.rstrip(os.sep) + os.sep)


class Arbol:
    """Tamaños de todas las carpetas bajo `raiz` (en bytes)."""

    def __init__(self, raiz):
        self.raiz = raiz
        self.tam = {}

    def escanear(self, ruta, progreso=None):
        """Escanea `ruta` y reemplaza lo que hubiera debajo; el cambio de tamaño de
        `ruta` se propaga a las carpetas padre."""
        antes = self.tam.get(ruta, 0)
        nuevos = tamanos(ruta, progreso)
        self.quitar(ruta, propagar=False)
        self.tam.update(nuevos)
        self._sumar_a_padres(ruta, self.tam.get(ruta, 0) - antes)

    def quitar(self, ruta, propagar=True, tam=None):
        """Quita `ruta` (y todo lo de debajo) del árbol."""
        tam = self.tam.get(ruta, 0) if tam is None else tam
        prefijo = ruta.rstrip(os.sep) + os.sep
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

    def subir(self, padre, progreso=None):
        """Cambia la raíz a `padre` sin volver a medir la raíz anterior: solo mide lo
        que tiene `padre` alrededor de ella (mismas reglas que tamanos_python)."""
        vieja = self.raiz
        dev = os.stat(padre).st_dev
        total = self.tam.get(vieja, 0)
        carpetas = []
        with os.scandir(padre) as it:
            for e in it:
                ruta = os.path.normpath(e.path)
                if ruta == vieja:
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                    es_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if not es_dir:
                    total += tamano_archivo(st)
                elif not (getattr(st, "st_file_attributes", 0) & REPARSE_POINT) and \
                        (WINDOWS or st.st_dev == dev):
                    carpetas.append(ruta)
        self.raiz = padre
        self.tam[padre] = total
        for ruta in carpetas:
            self.escanear(ruta, progreso)  # suma su tamaño a `padre`

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
                        tam = tamano_archivo(e.stat(follow_symlinks=False))
                except OSError:
                    es_dir, tam = False, 0
                items.append((e.name, os.path.normpath(e.path), tam, es_dir))
        items.sort(key=lambda x: (-x[2], x[0].lower()))
        return items


def motivo_protegida(ruta, raiz):
    if ruta == raiz:
        return "Es la carpeta de inicio del escaneo; no se puede mover."
    if os.path.dirname(ruta) == ruta:
        return "Es la raíz del disco; no se puede mover."
    if os.path.normcase(ruta) in PROTEGIDAS:
        return "Carpeta del sistema protegida; no se puede mover."
    if any(dentro_de(ruta, p) for p in PROTEGIDAS_CON_CONTENIDO) or \
            NOMBRES_PROTEGIDOS & set(os.path.normcase(ruta).split(os.sep)):
        return "Está dentro de una carpeta del sistema; no se puede mover."
    return None


def aviso_extra(ruta):
    if any(dentro_de(ruta, d) for d in DATOS_DE_APPS) and \
            not any(dentro_de(ruta, e) for e in EXCEPTO):
        return "Ojo: pertenece a una app; borrarlo puede hacerle perder datos o configuración."
    return None


# --- Papelera ---------------------------------------------------------------
# mover_a_papelera(ruta) -> (error, destino): error es None si salió bien; destino es
#   dónde quedó dentro de la Papelera (None si no se sabe), para notar cuando se vacía.
# vaciar_papelera() -> None si salió bien, o el texto del error.
# papelera_vacia() -> True si se sabe que está vacía (solo Windows lo puede saber).


def ultima_linea(r, por_defecto):
    return (r.stderr or r.stdout or por_defecto).strip().splitlines()[-1]


def mover_a_papelera(ruta):
    if WINDOWS:
        return mover_a_papelera_windows(ruta)
    if LINUX:
        return mover_a_papelera_linux(ruta)
    r = subprocess.run(["/usr/bin/trash", "-v", ruta], capture_output=True, text=True)
    if r.returncode != 0 or os.path.lexists(ruta):
        return ultima_linea(r, "no se pudo mover"), None
    # trash -v escribe: # Moved "/origen" to "/destino"
    _, sep, resto = r.stdout.strip().rpartition('" to "')
    return None, (resto[:-1] if sep and resto.endswith('"') else None)


def vaciar_papelera():
    if WINDOWS:
        return vaciar_papelera_windows()
    if LINUX:
        return vaciar_papelera_linux()
    # Con el Finder: sin Acceso total al disco no se puede borrar ~/.Trash directamente.
    try:
        r = subprocess.run(
            ["osascript", "-e", 'tell application "Finder" to empty trash'],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return "el Finder tardó demasiado"
    if r.returncode != 0:
        return ultima_linea(r, "no se pudo vaciar")
    return None


def papelera_vacia():
    if WINDOWS:
        return papelera_vacia_windows()
    return None


# Linux: estándar freedesktop.org (lo que usan GNOME, KDE, XFCE…).
# https://specifications.freedesktop.org/trash-spec/latest/

def mover_a_papelera_linux(ruta):
    try:
        mismo_disco = os.lstat(ruta).st_dev == os.stat(HOME).st_dev
    except OSError as e:
        return e.strerror, None
    if not mismo_disco:
        # Cada disco tiene su propia Papelera; gio sabe cuál usar.
        if not shutil.which("gio"):
            return "está en otro disco y no encontré gio para mandarlo a su Papelera", None
        r = subprocess.run(["gio", "trash", "--", ruta], capture_output=True, text=True)
        if r.returncode != 0 or os.path.lexists(ruta):
            return ultima_linea(r, "no se pudo mover"), None
        return None, None
    archivos = os.path.join(PAPELERA_LINUX, "files")
    info = os.path.join(PAPELERA_LINUX, "info")
    try:
        os.makedirs(archivos, mode=0o700, exist_ok=True)
        os.makedirs(info, mode=0o700, exist_ok=True)
        base = os.path.basename(ruta.rstrip(os.sep))
        nombre, n = base, 1
        while True:  # si ya hay uno con ese nombre: "foto.2", "foto.3"…
            info_ruta = os.path.join(info, nombre + ".trashinfo")
            try:
                fd = os.open(info_ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                if not os.path.lexists(os.path.join(archivos, nombre)):
                    break
                os.close(fd)
                os.remove(info_ruta)
            except FileExistsError:
                pass
            n += 1
            nombre = f"{base}.{n}"
        with os.fdopen(fd, "w") as f:
            f.write("[Trash Info]\n"
                    f"Path={urllib.parse.quote(ruta)}\n"
                    f"DeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
        destino = os.path.join(archivos, nombre)
        try:
            os.rename(ruta, destino)
        except OSError:
            os.remove(info_ruta)
            raise
    except OSError as e:
        return e.strerror or "no se pudo mover", None
    return None, destino


def vaciar_papelera_linux():
    if shutil.which("gio"):
        r = subprocess.run(["gio", "trash", "--empty"], capture_output=True, text=True)
        return None if r.returncode == 0 else ultima_linea(r, "no se pudo vaciar")
    try:
        for sub in ("files", "info"):
            carpeta = os.path.join(PAPELERA_LINUX, sub)
            if not os.path.isdir(carpeta):
                continue
            for e in os.scandir(carpeta):
                if e.is_dir(follow_symlinks=False):
                    shutil.rmtree(e.path)
                else:
                    os.remove(e.path)
        cache = os.path.join(PAPELERA_LINUX, "directorysizes")
        if os.path.exists(cache):
            os.remove(cache)
    except OSError as e:
        return e.strerror or "no se pudo vaciar"
    return None


# Windows: Papelera de reciclaje con la API del shell, por ctypes.

def mover_a_papelera_windows(ruta):
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    # Sin diálogos, a la Papelera (ALLOWUNDO), y si algo no cabe en ella Windows
    # pregunta antes de borrarlo para siempre (WANTNUKEWARNING).
    flags = 0x0004 | 0x0010 | 0x0040 | 0x0400 | 0x4000
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=ruta + "\0", fFlags=flags)
    res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if op.fAnyOperationsAborted:
        return "cancelado", None
    if res != 0 or os.path.lexists(ruta):
        return f"no se pudo mover (código {res:#x})", None
    return None, None


def info_papelera_windows():
    import ctypes
    from ctypes import wintypes

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong),
                    ("i64NumItems", ctypes.c_longlong)]

    info = SHQUERYRBINFO(cbSize=ctypes.sizeof(SHQUERYRBINFO))
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) != 0:
        return None
    return info


def papelera_vacia_windows():
    info = info_papelera_windows()
    return None if info is None else info.i64NumItems == 0


def vaciar_papelera_windows():
    import ctypes
    # Sin confirmación (ya la pidió disco), sin barra de progreso y sin sonido.
    res = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    if res != 0 and not papelera_vacia_windows():
        return f"no se pudo vaciar (código {res & 0xFFFFFFFF:#x})"
    return None


def mostrar_en_carpeta(ruta):
    """Abre el explorador de archivos en `ruta`. Devuelve el texto del error, o None."""
    try:
        if MAC:
            subprocess.run(["open", "-R", ruta])
        elif WINDOWS:
            subprocess.Popen(f'explorer /select,"{ruta}"')
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(ruta)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return "no encontré con qué abrir el explorador de archivos"
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
    ayuda = ("↑↓ mover  →/Enter entrar  ← subir  d a la Papelera  "
             f"o ver {NOMBRE_EXPLORADOR}  r reescanear  q salir")

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
        poner(alto - 2, 0, ayuda, curses.A_DIM)
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
            elif os.path.dirname(raiz) != raiz:
                # En la carpeta de inicio: sube a la que la contiene.
                padre = os.path.dirname(raiz)
                try:
                    arbol.subir(padre, progreso)
                except OSError as e:
                    estado = f"No se pudo leer {padre}: {e.strerror}"
                else:
                    try:
                        nombres = [it[1] for it in arbol.listar(padre)]
                    except OSError:
                        nombres = []
                    cursor = nombres.index(raiz) if raiz in nombres else 0
                    raiz = actual = padre
                    arriba, items, disponibles = 0, None, None
        elif tecla in (ord("o"), ord("O")) and sel:
            error = mostrar_en_carpeta(sel[1])
            if error:
                estado = f"Error: {error}"
        elif tecla in (ord("r"), ord("R")):
            arbol.escanear(actual, progreso)
            items = disponibles = None
            estado = "Reescaneado."
            # Lo que ya no está en la Papelera es porque se vació (o se restauró).
            # Se revisa por ruta: el Finder no cuenta lo oculto, como .ollama. Si no se
            # sabe la ruta (Windows), se pregunta si la Papelera quedó vacía.
            quedan = [(d, t) for d, t in en_papelera if d is None or os.path.lexists(d)]
            if any(d is None for d, _ in quedan) and papelera_vacia():
                quedan = [(d, t) for d, t in quedan if d is not None]
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
  disco                      espacio de cada disco
  disco -c                   carpetas más pesadas de la carpeta actual
  disco -c ~/Downloads -n 5  las 5 más pesadas de ~/Downloads
  disco -i                   explorar la carpeta actual y mandar cosas a la Papelera
  disco -i ~                 lo mismo, pero en tu carpeta personal
  disco --json               salida en JSON
"""


def preparar_consola():
    """En Windows activa los colores ANSI de la consola; en todos, que un carácter
    que la terminal no pueda mostrar (█ ░ …) salga como '?' en vez de romper."""
    if WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            salida, modo = k32.GetStdHandle(-11), wintypes.DWORD()
            if k32.GetConsoleMode(salida, ctypes.byref(modo)):
                k32.SetConsoleMode(salida, modo.value | 0x4)  # VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main():
    preparar_consola()
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
        "-c", "--carpetas", nargs="?", const=".", metavar="RUTA",
        help="muestra las carpetas más pesadas dentro de RUTA (por defecto, la carpeta actual)",
    )
    parser.add_argument("-n", type=int, default=15, help="con -c: cuántas carpetas mostrar (15)")
    parser.add_argument(
        "-i", "--interactivo", nargs="?", const=".", metavar="RUTA",
        help="navegador para explorar RUTA y mover cosas a la Papelera "
             "(por defecto, la carpeta actual)",
    )
    args = parser.parse_args()

    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ

    if args.interactivo:
        ruta = os.path.realpath(os.path.expanduser(args.interactivo))
        if not os.path.isdir(ruta):
            parser.error(f"no existe la carpeta: {ruta}")
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            parser.error("el modo interactivo necesita una terminal")
        try:
            import curses
        except ImportError:
            parser.error("falta el módulo curses; en Windows instálalo con: "
                         "py -m pip install windows-curses")
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
        ruta = os.path.realpath(os.path.expanduser(args.carpetas))
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
