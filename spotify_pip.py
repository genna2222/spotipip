import sys
import os
import re
import ctypes
import ctypes.util
import subprocess
import requests
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, QPoint, QThread, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QLabel, QWidget, QVBoxLayout, 
    QHBoxLayout, QPushButton, QSizeGrip, QMenu
)

CACHE_DIR = Path.home() / ".cache" / "lyripip"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# --- STRUTTURE DATI X11 USATE DA ctypes ---
class _XRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
    ]


class _XClientMessageData(ctypes.Union):
    _fields_ = [
        ("b", ctypes.c_char * 20),
        ("s", ctypes.c_short * 10),
        ("l", ctypes.c_long * 5),
    ]


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", _XClientMessageData),
    ]


# --- CONTROLLO NATIVO X11/XWayland ---
class X11WindowManager:
    """Operazioni X11 che non richiedono di ricreare la finestra Qt.

    Su GNOME/Mutter con Qt su XWayland questo permette di:
      * svuotare la Input Shape della finestra per il click-through;
      * chiedere a Mutter lo stato EWMH _NET_WM_STATE_ABOVE;
    senza chiamare setWindowFlags() dopo la creazione della GUI.
    """

    ShapeInput = 2
    ClientMessage = 33
    SubstructureNotifyMask = 1 << 19
    SubstructureRedirectMask = 1 << 20
    NetWmStateAdd = 1

    def __init__(self):
        self.display = None
        self.x11 = None
        self.xfixes = None
        self.net_wm_state = None
        self.net_wm_state_above = None
        self.available = False
        self._open()

    def _open(self):
        if not os.environ.get("DISPLAY"):
            return

        try:
            x11_path = ctypes.util.find_library("X11")
            xfixes_path = ctypes.util.find_library("Xfixes")
            if not x11_path or not xfixes_path:
                return

            self.x11 = ctypes.CDLL(x11_path)
            self.xfixes = ctypes.CDLL(xfixes_path)

            self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            self.x11.XOpenDisplay.restype = ctypes.c_void_p
            self.x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            self.x11.XCloseDisplay.restype = ctypes.c_int
            self.x11.XFlush.argtypes = [ctypes.c_void_p]
            self.x11.XFlush.restype = ctypes.c_int
            self.x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            self.x11.XInternAtom.restype = ctypes.c_ulong
            self.x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
            self.x11.XSendEvent.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.c_long,
                ctypes.c_void_p,
            ]
            self.x11.XSendEvent.restype = ctypes.c_int

            self.xfixes.XFixesCreateRegion.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_XRectangle),
                ctypes.c_int,
            ]
            self.xfixes.XFixesCreateRegion.restype = ctypes.c_ulong
            self.xfixes.XFixesSetWindowShapeRegion.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_ulong,
            ]
            self.xfixes.XFixesSetWindowShapeRegion.restype = None
            self.xfixes.XFixesDestroyRegion.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            self.xfixes.XFixesDestroyRegion.restype = None

            self.display = self.x11.XOpenDisplay(None)
            if not self.display:
                self.display = None
                return

            self.net_wm_state = self.x11.XInternAtom(self.display, b"_NET_WM_STATE", False)
            self.net_wm_state_above = self.x11.XInternAtom(self.display, b"_NET_WM_STATE_ABOVE", False)
            self.available = bool(self.net_wm_state and self.net_wm_state_above)
        except Exception:
            self.display = None
            self.available = False

    def _window_id(self, win_id):
        try:
            return int(win_id)
        except (TypeError, ValueError):
            return 0

    def set_input_transparent(self, win_id, transparent, width=1, height=1):
        """Imposta una Input Shape vuota/piena senza modificare i Window Flags Qt."""
        if not self.available or not self.display:
            return False

        xid = self._window_id(win_id)
        if not xid:
            return False

        try:
            if transparent:
                rect_ptr = ctypes.POINTER(_XRectangle)()
                region = self.xfixes.XFixesCreateRegion(self.display, rect_ptr, 0)
            else:
                width = max(1, min(int(width), 65535))
                height = max(1, min(int(height), 65535))
                rect = _XRectangle(0, 0, width, height)
                region = self.xfixes.XFixesCreateRegion(self.display, ctypes.byref(rect), 1)

            if not region:
                return False

            self.xfixes.XFixesSetWindowShapeRegion(
                self.display,
                xid,
                self.ShapeInput,
                0,
                0,
                region,
            )
            self.xfixes.XFixesDestroyRegion(self.display, region)
            self.x11.XFlush(self.display)
            return True
        except Exception:
            return False

    def set_always_on_top(self, win_id):
        """Chiede a Mutter di aggiungere _NET_WM_STATE_ABOVE alla finestra."""
        if not self.available or not self.display:
            return False

        xid = self._window_id(win_id)
        if not xid:
            return False

        try:
            root = self.x11.XDefaultRootWindow(self.display)
            event = _XClientMessageEvent()
            event.type = self.ClientMessage
            event.serial = 0
            event.send_event = 1
            event.display = self.display
            event.window = xid
            event.message_type = self.net_wm_state
            event.format = 32
            event.data.l[0] = self.NetWmStateAdd
            event.data.l[1] = ctypes.c_long(self.net_wm_state_above).value
            event.data.l[2] = 0
            event.data.l[3] = 0
            event.data.l[4] = 0

            mask = self.SubstructureNotifyMask | self.SubstructureRedirectMask
            sent = self.x11.XSendEvent(
                self.display,
                root,
                False,
                mask,
                ctypes.byref(event),
            )
            self.x11.XFlush(self.display)
            return bool(sent)
        except Exception:
            return False

    def close(self):
        if self.display and self.x11:
            try:
                self.x11.XCloseDisplay(self.display)
            except Exception:
                pass
        self.display = None


# --- PULSANTE DI SBLOCCO FLUTTUANTE SEPARATO ---
class UnlockButton(QWidget):
    def __init__(self, main_window):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.main_window = main_window
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(30, 30)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.btn = QPushButton("🔓", self)
        self.btn.setFixedSize(26, 26)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setToolTip("Sblocca finestra")
        self.btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(29, 185, 84, 0.95);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.4);
                font-weight: bold;
                font-size: 14px;
                border-radius: 13px;
            }
            QPushButton:hover { background-color: #1DB954; }
        """)
        self.btn.clicked.connect(self.main_window.unlock_ui)
        layout.addWidget(self.btn)


# --- THREAD ASINCRONO CON SUPPORTO CACHE ---
class LyricsFetcherWorker(QThread):
    lyrics_found = pyqtSignal(list, str)
    lyrics_failed = pyqtSignal(str)

    def __init__(self, artist, title, duration=None, ignore_cache=False):
        super().__init__()
        self.artist = artist
        self.title = title
        self.duration = duration
        self.ignore_cache = ignore_cache
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SpotifyPiP/1.0"})

    def get_cache_filepath(self):
        raw_name = f"{self.artist}_-_{self.title}".lower()
        safe_name = re.sub(r"[^\w\-.]", "_", raw_name)
        safe_name = re.sub(r"_+", "_", safe_name).strip("_")
        return CACHE_DIR / f"{safe_name}.lrc"

    def save_to_cache(self, lrc_text):
        try:
            self.get_cache_filepath().write_text(lrc_text, encoding="utf-8")
        except Exception: pass

    def load_from_cache(self):
        try:
            cache_file = self.get_cache_filepath()
            if cache_file.exists():
                return cache_file.read_text(encoding="utf-8")
        except Exception: pass
        return None

    def clean_query(self, text):
        text = re.sub(r"\(feat\..*?\)|\[feat\..*?\]", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\(with.*?\)|\[with.*?\]", "", text, flags=re.IGNORECASE)
        text = re.sub(r" - \d{4} Remaster.*", "", text, flags=re.IGNORECASE)
        text = re.sub(r" - Remastered.*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\(Remastered.*?\)", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\(Live.*?\)|\[Live.*?\]", "", text, flags=re.IGNORECASE)
        text = re.sub(r" - Live.*", "", text, flags=re.IGNORECASE)
        return text.strip()

    def parse_lrc(self, lrc_string):
        parsed = []
        pattern = re.compile(r"\[(\d{1,2}):(\d{2}(?:\.\d{1,3})?)\](.*)")
        for line in lrc_string.splitlines():
            match = pattern.match(line.strip())
            if match:
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                text = match.group(3).strip()
                if not text.startswith(("[ar:", "[ti:", "[al:", "[by:", "[offset:")):
                    parsed.append((minutes * 60 + seconds, text))
        parsed.sort(key=lambda x: x[0])
        return parsed

    def fetch_lrclib_exact(self, clean_title):
        try:
            params = {"artist_name": self.artist, "track_name": clean_title}
            if self.duration: params["duration"] = int(self.duration)
            res = self.session.get("https://lrclib.net/api/get", params=params, timeout=3.5)
            if res.status_code == 200 and res.json().get("syncedLyrics"):
                return res.json()["syncedLyrics"]
        except Exception: pass
        return None

    def fetch_lrclib_search(self, clean_title):
        try:
            query = f"{self.artist} {clean_title}"
            res = self.session.get("https://lrclib.net/api/search", params={"q": query}, timeout=3.5)
            if res.status_code == 200:
                for item in res.json():
                    if item.get("syncedLyrics"): return item["syncedLyrics"]
        except Exception: pass
        return None

    def fetch_netease(self, clean_title):
        try:
            search_url = "https://music.163.com/api/search/get/web"
            res = self.session.post(search_url, data={"s": f"{self.artist} {clean_title}", "type": 1, "offset": 0, "limit": 3}, timeout=4)
            if res.status_code == 200:
                songs = res.json().get("result", {}).get("songs", [])
                if songs:
                    l_res = self.session.get(f"https://music.163.com/api/song/lyric?id={songs[0]['id']}&lv=1&tv=-1", timeout=4)
                    if l_res.status_code == 200:
                        return l_res.json().get("lrc", {}).get("lyric")
        except Exception: pass
        return None

    def run(self):
        if not self.ignore_cache:
            cached_lrc = self.load_from_cache()
            if cached_lrc:
                parsed = self.parse_lrc(cached_lrc)
                if parsed:
                    self.lyrics_found.emit(parsed, "Cache")
                    return

        clean_title = self.clean_query(self.title)
        raw_lrc = self.fetch_lrclib_exact(clean_title) or \
                  self.fetch_lrclib_search(clean_title) or \
                  self.fetch_netease(clean_title)

        if raw_lrc:
            self.save_to_cache(raw_lrc)
            self.lyrics_found.emit(self.parse_lrc(raw_lrc), "Rete")
        else:
            self.lyrics_failed.emit("Nessun testo sincronizzato disponibile")


# --- FINESTRA PIP GUI ---
class SpotifyPip(QWidget):
    def __init__(self):
        super().__init__()

        # Usiamo Window invece di Tool per permettere alla barra delle applicazioni (Dash to Panel)
        # di intercettare e mostrare l'icona tra le applicazioni aperte
        self.base_flags = (
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.Window
        )

        self.setWindowTitle("Lyripip")
        self.setWindowFlags(self.base_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Carica l'icona dell'app se presente nel sistema o localmente
        app_icon = QIcon.fromTheme("lyripip", QIcon("lyripip.png"))
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self.setMinimumSize(320, 150)
        self.resize(480, 180)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.container = QWidget(self)
        self.container.setObjectName("container")
        self.container.setStyleSheet("""
            #container {
                background-color: rgba(18, 18, 18, 0.45);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
        """)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(14, 10, 14, 10)
        container_layout.setSpacing(4)

        # --- BARRA SUPERIORE ---
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel("Lyripip")
        self.title_label.setStyleSheet("color: #cccccc; font-size: 11px; font-weight: bold;")
        
        self.source_badge = QLabel("")
        self.source_badge.setStyleSheet("color: #aaaaaa; font-size: 10px; padding-right: 6px;")

        btn_top_style = """
            QPushButton {
                background: transparent;
                color: #aaaaaa;
                border: none;
                font-weight: bold;
                font-size: 15px;
                border-radius: 4px;
            }
            QPushButton:hover { background: rgba(255, 255, 255, 0.15); color: white; }
        """

        self.lock_button = QPushButton("📌")
        self.lock_button.setFixedSize(26, 26)
        self.lock_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lock_button.setToolTip("Blocca e passa i click sotto")
        self.lock_button.clicked.connect(self.lock_ui)
        self.lock_button.setStyleSheet(btn_top_style)

        self.close_button = QPushButton("✕")
        self.close_button.setFixedSize(26, 26)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(QApplication.quit)
        self.close_button.setStyleSheet(btn_top_style.replace("rgba(255, 255, 255, 0.15)", "#e81123"))

        top_bar.addWidget(self.title_label)
        top_bar.addStretch()
        top_bar.addWidget(self.source_badge)
        top_bar.addWidget(self.lock_button)
        top_bar.addWidget(self.close_button)
        container_layout.addLayout(top_bar)

        # --- SEZIONE TESTI ---
        lyrics_layout = QVBoxLayout()
        lyrics_layout.setSpacing(4)
        lyrics_layout.setContentsMargins(0, 4, 0, 4)

        self.prev_label = QLabel("")
        self.prev_label.setWordWrap(True)
        self.prev_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prev_label.setStyleSheet("color: rgba(255, 255, 255, 0.5); font-size: 13px; font-weight: 500;")
        lyrics_layout.addWidget(self.prev_label)

        self.curr_label = QLabel("In attesa di riproduzione...")
        self.curr_label.setWordWrap(True)
        self.curr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.curr_label.setStyleSheet("color: #1DB954; font-size: 17px; font-weight: bold;")
        lyrics_layout.addWidget(self.curr_label)

        self.next_label = QLabel("")
        self.next_label.setWordWrap(True)
        self.next_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_label.setStyleSheet("color: rgba(255, 255, 255, 0.6); font-size: 14px; font-weight: 500;")
        lyrics_layout.addWidget(self.next_label)

        container_layout.addLayout(lyrics_layout, 1)

        # --- BARRA INFERIORE ---
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(0, 0, 0, 0)
        
        self.media_widget = QWidget()
        media_layout = QHBoxLayout(self.media_widget)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(15)

        self.btn_prev = QPushButton("⏮")
        self.btn_play = QPushButton("▶")
        self.btn_next = QPushButton("⏭")

        media_btn_style = """
            QPushButton { background: transparent; color: rgba(255, 255, 255, 0.7); font-size: 18px; border: none; }
            QPushButton:hover { color: #1DB954; }
        """
        for btn in (self.btn_prev, self.btn_play, self.btn_next):
            btn.setFixedSize(30, 30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(media_btn_style)
            media_layout.addWidget(btn)

        self.btn_prev.clicked.connect(lambda: self.run_cmd(["previous"]))
        self.btn_play.clicked.connect(lambda: self.run_cmd(["play-pause"]))
        self.btn_next.clicked.connect(lambda: self.run_cmd(["next"]))

        bottom_bar.addSpacing(20)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.media_widget)
        bottom_bar.addStretch()

        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(20, 20)
        self.size_grip.setStyleSheet("QSizeGrip { width: 16px; height: 16px; image: none; }")
        bottom_bar.addWidget(self.size_grip)
        
        container_layout.addLayout(bottom_bar)
        main_layout.addWidget(self.container)

        self.current_track = ""
        self.lyrics = []
        self.current_line_idx = -1
        self.worker = None
        self.is_locked = False
        self.drag_position = QPoint()
        self.unlock_win = None
        self.last_saved_geometry = self.geometry()
        self.active_player = None

        # Manteniamo la stessa finestra nativa per tutta la vita dell'app.
        # Il passaggio lock/unlock usa X11/XWayland invece di setWindowFlags().
        self.x11_wm = X11WindowManager()
        self._x11_window_id = None
        self._x11_geometry_timer = QTimer(self)
        self._x11_geometry_timer.timeout.connect(self.ensure_always_on_top)
        self._x11_geometry_timer.start(1500)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_state)
        self.timer.start(200)

    # --- CLICK-THROUGH STABILE SENZA RESET DELLA FINESTRA ---
    def _ensure_x11_window(self):
        if self._x11_window_id:
            return self._x11_window_id

        try:
            self._x11_window_id = int(self.winId())
        except Exception:
            self._x11_window_id = None
        return self._x11_window_id

    def _apply_input_mode(self, transparent):
        xid = self._ensure_x11_window()
        if not xid or not self.x11_wm.available:
            # Fallback per backend non-X11: evita comunque gli eventi Qt locali.
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, transparent)
            return False

        if not transparent:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        width = max(1, self.width())
        height = max(1, self.height())
        applied = self.x11_wm.set_input_transparent(
            xid,
            transparent,
            width,
            height,
        )

        if applied:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        return applied

    def ensure_always_on_top(self):
        xid = self._ensure_x11_window()
        if xid and self.x11_wm.available:
            self.x11_wm.set_always_on_top(xid)

        if self.unlock_win and self.unlock_win.isVisible():
            try:
                unlock_xid = int(self.unlock_win.winId())
            except Exception:
                unlock_xid = 0
            if unlock_xid and self.x11_wm.available:
                self.x11_wm.set_always_on_top(unlock_xid)

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_x11_window()
        self.ensure_always_on_top()
        if self.is_locked:
            self._apply_input_mode(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        QTimer.singleShot(0, self.ensure_always_on_top)

    def lock_ui(self):
        self.is_locked = True
        self.last_saved_geometry = self.geometry()
        pos = self.lock_button.mapToGlobal(QPoint(0, 0))

        self.lock_button.hide()
        self.close_button.hide()
        self.title_label.hide()
        self.source_badge.hide()
        self.media_widget.hide()
        self.size_grip.hide()
        self.container.setStyleSheet("background-color: transparent; border: none;")

        self._apply_input_mode(True)
        self.show()
        self.update()
        self.container.update()
        self.ensure_always_on_top()

        if not self.unlock_win:
            self.unlock_win = UnlockButton(self)
        self.unlock_win.move(pos)
        self.unlock_win.show()
        self.unlock_win.raise_()
        self.ensure_always_on_top()

    def unlock_ui(self):
        self.is_locked = False

        if self.unlock_win:
            self.unlock_win.hide()

        self._apply_input_mode(False)

        self.setGeometry(self.last_saved_geometry)
        self.show()
        self.raise_()
        self.activateWindow()
        self.ensure_always_on_top()

        self.lock_button.show()
        self.close_button.show()
        self.title_label.show()
        self.source_badge.show()
        self.media_widget.show()
        self.size_grip.show()

        self.container.setStyleSheet("""
            #container {
                background-color: rgba(18, 18, 18, 0.45);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
        """)
        self.update()
        self.container.update()

        QTimer.singleShot(50, self.ensure_always_on_top)
        QTimer.singleShot(100, self.ensure_always_on_top)

    def closeEvent(self, event):
        if self.x11_wm:
            self.x11_wm.close()
        super().closeEvent(event)

    # --- TRASCINAMENTO ---
    def mousePressEvent(self, event):
        if not self.is_locked and event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self.is_locked and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            self.last_saved_geometry = self.geometry()
            event.accept()

    def _detect_active_player(self):
        """Trova il player MPRIS attivo dando precedenza allo stato Playing."""
        try:
            res = subprocess.run(["playerctl", "-l"], capture_output=True, text=True, check=True)
            available = res.stdout.strip().splitlines()
        except Exception:
            return None

        # Filtra i player supportati (feishin e spotify)
        supported = [p for p in available if any(name in p.lower() for name in ("feishin", "spotify"))]
        if not supported:
            return None

        # Priorità a chi sta effettivamente riproducendo musica
        for p in supported:
            try:
                st = subprocess.run(["playerctl", "-p", p, "status"], capture_output=True, text=True)
                if st.stdout.strip() == "Playing":
                    return p
            except Exception:
                pass

        # Altrimenti restituisce il primo trovato
        return supported[0]

    def run_cmd(self, args):
        target = self.active_player or self._detect_active_player()
        if not target:
            return None
        try:
            res = subprocess.run(["playerctl", "-p", target] + args, capture_output=True, text=True, check=True)
            return res.stdout.strip()
        except Exception:
            return None

    def on_lyrics_found(self, lyrics, source):
        self.lyrics = lyrics
        self.current_line_idx = -1
        self.source_badge.setText(f"via {source}")

    def on_lyrics_failed(self, msg):
        self.lyrics = []
        self.current_line_idx = -1
        self.source_badge.setText("")
        self.prev_label.setText("")
        self.curr_label.setText(msg)
        self.next_label.setText("")

    def start_fetch(self, artist, title, length_str, ignore_cache=False):
        duration = None
        if length_str and length_str.isdigit():
            duration = int(length_str) / 1_000_000

        if self.worker and self.worker.isRunning():
            self.worker.terminate()

        self.worker = LyricsFetcherWorker(artist, title, duration, ignore_cache=ignore_cache)
        self.worker.lyrics_found.connect(self.on_lyrics_found)
        self.worker.lyrics_failed.connect(self.on_lyrics_failed)
        self.worker.start()

    def update_state(self):
        self.active_player = self._detect_active_player()

        title = self.run_cmd(["metadata", "title"])
        artist = self.run_cmd(["metadata", "artist"])
        position_str = self.run_cmd(["position"])
        length_str = self.run_cmd(["metadata", "mpris:length"])
        status = self.run_cmd(["status"])

        if status == "Playing": self.btn_play.setText("⏸")
        else: self.btn_play.setText("▶")

        if not title or not artist or position_str is None:
            if not self.is_locked: self.title_label.setText("Nessun player attivo")
            self.source_badge.setText("")
            self.prev_label.setText("")
            self.curr_label.setText("In attesa di riproduzione...")
            self.next_label.setText("")
            return

        track_id = f"{artist} - {title}"
        if track_id != self.current_track:
            self.current_track = track_id
            display_title = (track_id[:45] + "...") if len(track_id) > 45 else track_id
            if not self.is_locked: self.title_label.setText(display_title)
            self.source_badge.setText("Caricamento...")
            self.prev_label.setText("")
            self.curr_label.setText(f"Caricamento:\n{title}")
            self.next_label.setText("")
            self.lyrics = []
            self.current_line_idx = -1
            self.start_fetch(artist, title, length_str, ignore_cache=False)

        if not self.lyrics: return
        try: current_time = float(position_str)
        except ValueError: return

        idx = -1
        for i, (timestamp, text) in enumerate(self.lyrics):
            if current_time >= timestamp: idx = i
            else: break

        if idx != self.current_line_idx:
            self.current_line_idx = idx
            if idx == -1:
                self.prev_label.setText("")
                self.curr_label.setText("...")
                self.next_label.setText(self.lyrics[0][1] if len(self.lyrics) > 0 else "")
            else:
                self.prev_label.setText(self.lyrics[idx - 1][1] if idx > 0 else "")
                self.curr_label.setText(self.lyrics[idx][1] if self.lyrics[idx][1] else "...")
                self.next_label.setText(self.lyrics[idx + 1][1] if idx + 1 < len(self.lyrics) else "")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Q): 
            QApplication.quit()

    def contextMenuEvent(self, event):
        if self.is_locked: return
        menu = QMenu(self)
        reload_action = menu.addAction("Ricarica (usa cache)")
        force_reload_action = menu.addAction("Ricarica e riscarica (ignora cache)")
        menu.addSeparator()
        close_action = menu.addAction("Chiudi")
        
        action = menu.exec(self.mapToGlobal(event.pos()))
        if action == close_action: QApplication.quit()
        elif action == reload_action: self.current_track = ""
        elif action == force_reload_action:
            title, artist, length_str = self.run_cmd(["metadata", "title"]), self.run_cmd(["metadata", "artist"]), self.run_cmd(["metadata", "mpris:length"])
            if artist and title:
                cache_file = CACHE_DIR / f"{re.sub(r'[^\w\-.]', '_', f'{artist}_-_{title}'.lower())}.lrc"
                if cache_file.exists():
                    try: cache_file.unlink()
                    except Exception: pass
                self.source_badge.setText("Riscaricamento...")
                self.start_fetch(artist, title, length_str, ignore_cache=True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 1. Identificativi freedesktop / GNOME per associare la finestra a spotipip.desktop
    app.setApplicationName("Lyripip")
    app.setDesktopFileName("lyripip")
    
    # 2. Imposta l'icona globale dell'applicazione
    icon = QIcon.fromTheme("lyripip", QIcon("lyripip.png"))
    if not icon.isNull():
        app.setWindowIcon(icon)
        
    window = SpotifyPip()
    window.show()
    sys.exit(app.exec())