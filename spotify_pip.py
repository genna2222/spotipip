import sys
import os
import re
import subprocess
import requests
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, QPoint, QThread, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QLabel, QWidget, QVBoxLayout, 
    QHBoxLayout, QPushButton, QSizeGrip, QMenu
)

CACHE_DIR = Path.home() / ".cache" / "spotify-pip"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
FAVORITES_FILE = CACHE_DIR / "favorites.txt"


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

        self.base_flags = (
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.Window
        )

        self.setWindowTitle("Spotipip")
        self.setWindowFlags(self.base_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        app_icon = QIcon.fromTheme("spotipip", QIcon("spotipip.png"))
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

        self.title_label = QLabel("Spotipip")
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

        # Pulsante Preferiti
        self.fav_button = QPushButton("🤍")
        self.fav_button.setFixedSize(26, 26)
        self.fav_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fav_button.setToolTip("Aggiungi ai preferiti locali")
        self.fav_button.clicked.connect(self.toggle_favorite)
        self.fav_button.setStyleSheet(btn_top_style)

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
        top_bar.addWidget(self.fav_button)
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

        self.curr_label = QLabel("In attesa di Spotify...")
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

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_state)
        self.timer.start(200)

    # --- FUNZIONE PREFERITI LOCALI ---
    def toggle_favorite(self):
        if not self.current_track:
            return
            
        try:
            favorites = []
            if FAVORITES_FILE.exists():
                favorites = FAVORITES_FILE.read_text(encoding="utf-8").splitlines()

            if self.current_track in favorites:
                favorites.remove(self.current_track)
                self.fav_button.setText("🤍")
            else:
                favorites.append(self.current_track)
                self.fav_button.setText("❤️")

            FAVORITES_FILE.write_text("\n".join(favorites), encoding="utf-8")
        except Exception:
            pass

    def check_is_favorite(self, track_id):
        try:
            if FAVORITES_FILE.exists():
                favorites = FAVORITES_FILE.read_text(encoding="utf-8").splitlines()
                if track_id in favorites:
                    self.fav_button.setText("❤️")
                    return
        except Exception:
            pass
        self.fav_button.setText("🤍")

    # --- CLICK-THROUGH STABILE E PRIMO PIANO FIX ---
    def lock_ui(self):
        self.is_locked = True
        self.last_saved_geometry = self.geometry()
        pos = self.lock_button.mapToGlobal(QPoint(0, 0))

        # Nascondi elementi accessori, compreso il pulsante cuore
        self.fav_button.hide()
        self.lock_button.hide()
        self.close_button.hide()
        self.title_label.hide()
        self.source_badge.hide()
        self.media_widget.hide()
        self.size_grip.hide()
        self.container.setStyleSheet("background-color: transparent; border: none;")

        # Fix per XWayland: Nascondi la finestra per forzare l'aggiornamento pulito dei Flag
        self.hide()
        self.setWindowFlags(self.base_flags | Qt.WindowType.WindowTransparentForInput)
        self.setGeometry(self.last_saved_geometry)
        self.show()
        self.raise_()

        if not self.unlock_win:
            self.unlock_win = UnlockButton(self)
        self.unlock_win.move(pos)
        self.unlock_win.show()
        self.unlock_win.raise_()

    def unlock_ui(self):
        self.is_locked = False

        if self.unlock_win:
            self.unlock_win.hide()

        # Rimuove il TransparentForInput e ristabilisce AlwaysOnTop rinegoziando con il Window Manager
        self.hide()
        self.setWindowFlags(self.base_flags)
        self.setGeometry(self.last_saved_geometry)
        self.show()
        self.raise_()
        self.activateWindow()

        # Ripristina la visibilità degli elementi
        self.fav_button.show()
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

    def run_cmd(self, args):
        try:
            res = subprocess.run(["playerctl", "-p", "spotify"] + args, capture_output=True, text=True, check=True)
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
        title = self.run_cmd(["metadata", "title"])
        artist = self.run_cmd(["metadata", "artist"])
        position_str = self.run_cmd(["position"])
        length_str = self.run_cmd(["metadata", "mpris:length"])
        status = self.run_cmd(["status"])

        if status == "Playing": self.btn_play.setText("⏸")
        else: self.btn_play.setText("▶")

        if not title or not artist or position_str is None:
            if not self.is_locked: self.title_label.setText("Spotify disconnesso")
            self.source_badge.setText("")
            self.prev_label.setText("")
            self.curr_label.setText("Spotify in pausa o non attivo")
            self.next_label.setText("")
            self.fav_button.setText("🤍")
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
            
            # Controlla se il nuovo brano è tra i preferiti per aggiornare l'icona del cuore
            self.check_is_favorite(track_id)
            
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
    
    app.setApplicationName("Spotipip")
    app.setDesktopFileName("spotipip")
    
    icon = QIcon.fromTheme("spotipip", QIcon("spotipip.png"))
    if not icon.isNull():
        app.setWindowIcon(icon)
        
    window = SpotifyPip()
    window.show()
    sys.exit(app.exec())