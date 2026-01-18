#!/usr/bin/env python3
"""
Server for Live Speech Transcription
- Listens for TCP connections from clients
- Transcribes audio from each client using Speechmatics
- Displays transcripts in a GUI
- Visualizes connected clients with circular icons and audio indicators
"""
import os
from dotenv import load_dotenv
import sys
import socket
import threading
import time
import queue
import math
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QTextEdit, QLabel, 
                             QStatusBar, QListWidget, QGridLayout, QFrame,
                             QScrollArea)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QRect
from PyQt6.QtGui import QFont, QTextCursor, QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient
from speechmatics.client import WebsocketClient
from speechmatics.models import ConnectionSettings, AudioSettings, TranscriptionConfig
from PyQt6.QtWidgets import QGraphicsDropShadowEffect 
from PyQt6.QtWidgets import QFileDialog, QMessageBox

# ====== CONFIGURATION ======
load_dotenv()
API_KEY = os.getenv("SPEECHMATICS_API_KEY")
DEFAULT_LANGUAGE = "en"
CONNECTION_URL = "wss://eu2.rt.speechmatics.com/v2"
SERVER_PORT = 5001

DARK_STYLE = """
    QMainWindow { background-color: #121212; }
    QWidget { background-color: #121212; color: #ffffff; }
    QTextEdit { 
        background-color: #1e1e1e; 
        color: #e0e0e0; 
        border: 1px solid #333333; 
        border-radius: 8px; 
    }
    QLabel { color: #ffffff; font-weight: bold; }
    QScrollArea { border: none; background-color: #121212; }
    QScrollBar:vertical { background: #2c2c2c; width: 10px; }
"""

LIGHT_STYLE = """
    QMainWindow { 
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #a1c4fd, stop:1 #c2e9fb); 
    }
    QFrame#MainCard {
        background-color: rgba(255, 255, 255, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.3);
        border-radius: 20px;
    }
"""
# ===========================

# Audio settings (must match client)
SAMPLE_RATE = 16000
CHUNK_SIZE = 4096

class SentenceBuffer:
    """Buffer to stream words immediately (Per Client)"""
    def __init__(self, client_name, signals):
        self.client_name = client_name
        self.signals = signals
        self.lock = threading.Lock()
        self.new_sentence = True 
        
    def add_word(self, word):
        with self.lock:
            word = word.strip()
            if not word: return
            
            # 1. Capitalization Logic (Start of sentence)
            if self.new_sentence and len(word) > 0 and word[0].isalnum():
                word = word[0].upper() + word[1:]
            
            # 2. Spacing Logic
            # Punctuation marks that should NOT have a preceding space
            no_space_punct = {'.', ',', '!', '?', ':', ';', ')', ']', '}', '"'}
            
            # Check if we should add a space before this word
            # We add a space unless it's a punctuation mark or it's the very start (managed by UI block mostly)
            # or if it's a currency symbol maybe?
            
            prefix = " "
            if word in no_space_punct or word.startswith("'"):
                prefix = ""
            
            # Special case: If it's the very first word of a sentence, we might still want a space 
            # if it's not the start of the block. But since we stream, we can't easily know.
            # We'll default to prepending space for words, which HTML collapses if redundant.
            # But we must be careful with punctuation.
            
            text_to_emit = f"{prefix}{word}"
            
            self.signals.new_transcript.emit(self.client_name, text_to_emit)
            
            # 3. Update State
            # Check if this word acts as a sentence terminator
            if word.endswith(('.', '!', '?')):
                self.new_sentence = True
            else:
                self.new_sentence = False

    def force_flush(self):
        pass

class TranscriptSignals(QObject):
    """Signals for updating GUI from background threads"""
    new_transcript = pyqtSignal(str, str)  # client_name, text
    update_building = pyqtSignal(str, str) # client_name, text
    client_connected = pyqtSignal(str, str) # client_name, lang_code
    client_disconnected = pyqtSignal(str)
    log_message = pyqtSignal(str)
    audio_activity = pyqtSignal(str, bool) # client_name, is_active

class ClientWidget(QWidget):
    """Circular widget representing a connected client"""
    def __init__(self, name, lang_code="en"):
        super().__init__()
        self.name = name
        self.lang_code = lang_code
        self.is_active = False
        self.setFixedSize(120, 140) # Increased size for glow
        
        # Pulse Animation
        self.pulse_timer = QTimer(self)
        self.pulse_timer.timeout.connect(self.update_pulse)
        self.pulse_alpha = 0
        self.pulse_direction = 1
        
    def set_active(self, active):
        if self.is_active != active:
            self.is_active = active
            
            if self.is_active:
                self.pulse_timer.start(50) # 20fps
            else:
                self.pulse_timer.stop()
                self.pulse_alpha = 0
                
            self.update()
            
    def update_pulse(self):
        self.pulse_alpha += 10 * self.pulse_direction
        if self.pulse_alpha >= 100:
            self.pulse_alpha = 100
            self.pulse_direction = -1
        elif self.pulse_alpha <= 0:
            self.pulse_alpha = 0
            self.pulse_direction = 1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Geometry constants
        center_x = self.width() // 2
        center_y = 60
        radius = 40
        
        # 1. Draw Pulsing Glow (if active)
        if self.is_active:
            # We use a soft radial gradient for the glow to make it look realistic
            glow_radius = radius + 15
            glow_grad = QRadialGradient(center_x, center_y, glow_radius)
            glow_grad.setColorAt(0, QColor(76, 175, 80, 100)) # Stronger green in center
            glow_grad.setColorAt(1, QColor(76, 175, 80, 0))   # Fades to transparent
            
            painter.setBrush(glow_grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center_x - glow_radius, center_y - glow_radius, 
                                glow_radius * 2, glow_radius * 2)

        # 2. Main Circle Background (Modern Gradient)
        gradient = QLinearGradient(0, center_y - radius, 0, center_y + radius)
        gradient.setColorAt(0, QColor("#37474F")) # Light slate
        gradient.setColorAt(1, QColor("#101416")) # Near black for depth
    
        painter.setBrush(gradient)
        
        # Border: Glowing Green if active, subtle Slate if idle
        if self.is_active:
            pen = QPen(QColor("#4CAF50"), 3)
        else:
            pen = QPen(QColor("#546E7A"), 2)
        painter.setPen(pen)
        painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)

        # 3. Draw Initial (Centered)
        painter.setPen(QColor("white")) # White text looks best on dark bubbles
        painter.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        initial = self.name[0].upper() if self.name else "?"
        painter.drawText(QRect(center_x - radius, center_y - radius, radius * 2, radius * 2), 
                         Qt.AlignmentFlag.AlignCenter, initial)
        
        # 4. Draw Language Badge (Corner overlap)
        lang_map = {"hi": "🇮🇳", "ja": "🇯🇵", "en": "🇬🇧", "es": "🇪🇸", "fr": "🇫🇷", "de": "🇩🇪"}
        flag = lang_map.get(self.lang_code, "🌐")

        badge_size = 28
        badge_x = center_x + radius - 20
        badge_y = center_y + radius - 20
        
        # Badge background (White ring for contrast)
        painter.setPen(QPen(QColor("#263238"), 2))
        painter.setBrush(QColor("white"))
        painter.drawEllipse(badge_x, badge_y, badge_size, badge_size)
        
        # Badge Emoji
        painter.setFont(QFont("Segoe UI Emoji", 12))
        painter.drawText(QRect(badge_x, badge_y, badge_size, badge_size), 
                         Qt.AlignmentFlag.AlignCenter, flag)

        # 5. Draw Client Name Label (Below the circle)
        # Handle theme-based label color
        is_dark = False
        try:
            if hasattr(self.window(), 'btn_theme'):
                is_dark = self.window().btn_theme.isChecked()
        except: pass
        
        painter.setPen(QColor("white") if is_dark else QColor("black"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        
        # Truncate long names to keep UI clean
        display_name = (self.name[:12] + '..') if len(self.name) > 12 else self.name
        painter.drawText(QRect(0, center_y + radius + 5, self.width(), 25), 
                         Qt.AlignmentFlag.AlignCenter, display_name)    


class ClientHandler(threading.Thread):
    """Handles a single client connection and speech-to-text pipeline"""
    def __init__(self, conn, addr, signals):
        super().__init__()
        self.conn = conn
        self.addr = addr
        self.signals = signals
        self.client_name = f"Client-{addr[1]}" 
        self.buffer = SentenceBuffer(self.client_name, self.signals)
        self.running = True
        self.ws = None
        
    def handle_transcript(self, message):
        """Callback for Speechmatics AddTranscript event"""
        if "results" in message:
            for result in message["results"]:
                # Speechmatics returns a list of alternatives; we take the most confident one
                word = result["alternatives"][0]["content"]
                # Feed the word into our sentence buffer for UI processing
                self.buffer.add_word(word)

    def run(self):
        try:
            # 1. Handshake: Extract Client Info
            try:
                # Receive metadata packet (Name|Lang)
                raw_data = self.conn.recv(1024).decode('utf-8').strip()
                if "|" in raw_data:
                    self.client_name, selected_lang = raw_data.split("|", 1)
                else:
                    self.client_name = raw_data
                    selected_lang = "en"
            except Exception:
                self.client_name = f"Client-{self.addr[1]}"
                selected_lang = "en"
            
            # Sync buffer with actual client name
            self.buffer.client_name = self.client_name
            
            self.signals.client_connected.emit(self.client_name, selected_lang)
            self.signals.log_message.emit(f"New connection: {self.client_name} (Lang: {selected_lang})")
            
            # 2. Configure Speechmatics Connection
            self.ws = WebsocketClient(
                ConnectionSettings(url=CONNECTION_URL, auth_token=API_KEY)
            )
            self.ws.add_event_handler(
                event_name="AddTranscript",
                event_handler=self.handle_transcript
            )
            
            # Audio configuration for PCM 16-bit mono
            settings = AudioSettings(sample_rate=SAMPLE_RATE, chunk_size=CHUNK_SIZE, encoding="pcm_s16le")
            conf = TranscriptionConfig(
                operating_point="enhanced", 
                language=selected_lang, 
                enable_partials=False, 
                max_delay=1,
                enable_entities=True,
                enable_punctuation=True
                # Punctuation overrides removed to allow natural full punctuation
            )
            
            # 3. Reactive Socket Stream
            class SocketStream:
                def __init__(self, conn, signals, client_name):
                    self.conn = conn
                    self.signals = signals
                    self.client_name = client_name
                    
                def read(self, size):
                    try:
                        data = self.conn.recv(size)
                        if not data: return b''
                        
                        # Real-time Activity Detection for the Modern UI
                        count = len(data) // 2
                        if count > 0:
                            sum_squares = 0
                            # Sampling for performance
                            for i in range(0, len(data), 20): 
                                if i+2 <= len(data):
                                    sample = int.from_bytes(data[i:i+2], byteorder='little', signed=True)
                                    sum_squares += sample * sample
                            
                            rms = math.sqrt(sum_squares / (count / 10))
                            # Trigger the "Neon Glow" on the server dashboard
                            is_active = rms > 150 
                            self.signals.audio_activity.emit(self.client_name, is_active)
                        
                        return data
                    except Exception:
                        return b''
            
            # Start the synchronous streaming process
            stream = SocketStream(self.conn, self.signals, self.client_name)
            self.ws.run_synchronously(stream, conf, settings)
            
        except Exception as e:
            self.signals.log_message.emit(f"Error with {self.client_name}: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        """Securely closes connections and flushes remaining text"""
        self.running = False
        if self.buffer:
            self.buffer.force_flush()
        
        self.signals.client_disconnected.emit(self.client_name)
        self.signals.log_message.emit(f"Disconnected: {self.client_name}")
        
        try:
            self.conn.close()
        except:
            pass

class ServerThread(threading.Thread):
    """TCP Server to accept connections"""
    def __init__(self, signals):
        super().__init__()
        self.signals = signals
        self.running = True
        self.server_socket = None
        self.clients = []

    def run(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind(('0.0.0.0', SERVER_PORT))
            self.server_socket.listen(5)
            self.signals.log_message.emit(f"Server listening on port {SERVER_PORT}...")
            
            while self.running:
                try:
                    conn, addr = self.server_socket.accept()
                    client = ClientHandler(conn, addr, self.signals)
                    client.daemon = True
                    client.start()
                    self.clients.append(client)
                except OSError:
                    break
        except Exception as e:
            self.signals.log_message.emit(f"Server error: {e}")
        finally:
            if self.server_socket:
                self.server_socket.close()

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        for client in self.clients:
            client.cleanup()

class ServerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.signals = TranscriptSignals()
        self.server_thread = None
        self.client_widgets = {} # name -> ClientWidget
        self.last_client = None
        self.client_paragraphs = {}
        self.init_ui()
        
        # Connect signals
        self.signals.new_transcript.connect(self.add_transcript)
        self.signals.update_building.connect(self.update_building)
        self.signals.client_connected.connect(self.on_client_connect)
        self.signals.client_disconnected.connect(self.on_client_disconnect)
        self.signals.log_message.connect(self.log)
        self.signals.audio_activity.connect(self.on_audio_activity)
        
        # Start Server
        self.server_thread = ServerThread(self.signals)
        self.server_thread.daemon = True
        self.server_thread.start()

    def export_transcript(self):
        # 1. Check if there is actually content to save
        content = self.transcript_area.toPlainText().strip()
        if not content:
           QMessageBox.warning(self, "Export Failed", "The transcript is empty.")
           return

        # 2. Open a "Save File" dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Transcript",
            f"transcript_{int(time.time())}.txt",
            "Text Files (*.txt);;All Files (*)"
        )

        # 3. If a path was chosen, write the file
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                   f.write("=== SESSION TRANSCRIPT ===\n")
                   f.write(f"Date: {time.ctime()}\n")
                   f.write("-" * 30 + "\n\n")
                   f.write(content)
            
                   QMessageBox.information(self, "Success", f"Transcript saved to:\n{file_path}")
            except Exception as e:
                   QMessageBox.critical(self, "Error", f"Could not save file: {str(e)}")

    def init_ui(self):
        self.setWindowTitle("🎙️ Transcription Server")
        self.setGeometry(100, 100, 1100, 800)
        
        self.setStyleSheet(LIGHT_STYLE) # Default theme
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)


        
        # Left: Transcripts
        left_layout = QVBoxLayout()
        
        # Header with Title and Theme Toggle
        header_layout = QHBoxLayout()
        
        title = QLabel("Live Transcripts")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        self.btn_theme = QPushButton("🌙 Dark Mode")
        self.btn_theme.setCheckable(True)
        self.btn_theme.setFixedSize(120, 30)
        self.btn_theme.clicked.connect(self.toggle_theme)
        header_layout.addWidget(self.btn_theme)
        
        left_layout.addLayout(header_layout)
        
        self.transcript_area = QTextEdit()
        self.transcript_area.setReadOnly(True)
        self.transcript_area.setFont(QFont("Arial", 12))
        left_layout.addWidget(self.transcript_area)
        
        layout.addLayout(left_layout, stretch=2)
        
        # Right: Clients & Logs
        right_layout = QVBoxLayout()

        self.btn_export = QPushButton("💾 Export Transcript")
        self.btn_export.setMinimumHeight(35)
        self.btn_export.clicked.connect(self.export_transcript)
        right_layout.addWidget(self.btn_export)
        
        # Clients Area (Grid)
        lbl_clients = QLabel("Connected Clients")
        lbl_clients.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        right_layout.addWidget(lbl_clients)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(300)
        
        self.clients_container = QWidget()
        self.clients_grid = QGridLayout(self.clients_container)
        self.clients_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.clients_container)
        
        right_layout.addWidget(scroll)
        
        # Logs
        lbl_logs = QLabel("Server Logs")
        lbl_logs.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        right_layout.addWidget(lbl_logs)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Courier New", 10))
        right_layout.addWidget(self.log_area)
        
        layout.addLayout(right_layout, stretch=1)

    def toggle_theme(self):
        if self.btn_theme.isChecked():
            self.setStyleSheet(DARK_STYLE)
            self.btn_theme.setText("☀️ Light Mode")
        else:
            self.setStyleSheet(LIGHT_STYLE)
            self.btn_theme.setText("🌙 Dark Mode")       

    def add_transcript(self, client_name, text):
        # Merge if same client speaks consecutively
        if self.last_client == client_name:
            # Append to valid existing block
            cursor = self.transcript_area.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.transcript_area.setTextCursor(cursor)
            
            # Handle leading space explicitly to avoid HTML collapsing it
            if text.startswith(" "):
                self.transcript_area.insertPlainText(" ")
                text = text.lstrip()
                
            if text:
                self.transcript_area.insertHtml(f"<span style='font-family: \"Segoe UI\", sans-serif; line-height: 1.5;'>{text}</span>")
            
            self.transcript_area.moveCursor(QTextCursor.MoveOperation.End) # Ensure scrolling
        else:
            # New Block
            self.last_client = client_name
            timestamp = datetime.now().strftime("%H:%M")
            
            # For a new block, we don't want a leading space
            clean_text = text.lstrip()
            
            formatted_html = f"""
                <div style='margin-bottom: 10px;'>
                    <span style='color: #888; font-size: 10px;'>[{timestamp}]</span>
                    <b style='color: #4CAF50;'> {client_name}:</b>
                    <span style='font-family: "Segoe UI", sans-serif; line-height: 1.5;'>{clean_text}</span>
                </div>
            """
            self.transcript_area.append(formatted_html)
            
        self.statusBar().showMessage(f"Last message received from {client_name}")

    def update_building(self, client_name, text):
        html = f"<div style='color: gray; font-style: italic;' id='building_{client_name}'>... {text}</div>"
        self.transcript_area.append(html)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        c = self.transcript_area.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        self.transcript_area.setTextCursor(c)

    def on_client_connect(self, name, lang_code):
        if name not in self.client_widgets:
            widget = ClientWidget(name, lang_code)
            self.client_widgets[name] = widget
            
            # Add to grid
            count = self.clients_grid.count()
            row = count // 3
            col = count % 3
            self.clients_grid.addWidget(widget, row, col)

    def on_client_disconnect(self, name):
        if name in self.client_widgets:
            widget = self.client_widgets[name]
            self.clients_grid.removeWidget(widget)
            widget.deleteLater()
            del self.client_widgets[name]

    def on_audio_activity(self, name, is_active):
        if name in self.client_widgets:
            self.client_widgets[name].set_active(is_active)

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_area.append(f"[{ts}] {msg}")

    def closeEvent(self, event):
        if self.server_thread:
            self.server_thread.stop()
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = ServerApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
