#!/usr/bin/env python3
"""
Client for Live Speech Transcription
- Captures audio from microphone
- Streams raw audio to the server via TCP
- Supports GUI for mic selection, mute, and visual feedback
"""

import sys
import socket
import pyaudio
import time
import argparse
import threading
import math
import numpy as np
import json
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QComboBox, 
                             QLineEdit, QMessageBox, QFrame, QProgressBar)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QSettings
from PyQt6.QtGui import QFont, QColor

# ====== CONFIGURATION ======
DEFAULT_SERVER_IP = "127.0.0.1"
DEFAULT_SERVER_PORT = 5001
DARK_STYLE = """
        QMainWindow { background-color: #121212; }
        QWidget { background-color: #121212; color: #ffffff; }
        QLineEdit, QComboBox { 
            background-color: #2c2c2c; 
            border: 1px solid #3d3d3d; 
            color: white; 
            padding: 5px; 
            border-radius: 4px; 
        }
        QLabel { color: #bbbbbb; }
        QPushButton#ConnectBtn { background-color: #4CAF50; color: white; border-radius: 5px; }
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

# Audio settings (must match server)
SAMPLE_RATE = 16000
CHUNK_SIZE = 4096
CHANNELS = 1
FORMAT = pyaudio.paInt16

class AudioStreamer(QObject):
    """Handles audio streaming in a background thread"""
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()
    audio_level = pyqtSignal(float) # 0.0 to 1.0

    def __init__(self, server_ip, server_port, device_index, client_name, lang_code):
        super().__init__()
        self.server_ip = server_ip
        self.server_port = server_port
        self.device_index = device_index
        self.client_name = client_name
        self.lang_code = lang_code
        self.running = False
        self.muted = False
        self.sock = None
        self.p = None
        self.stream = None

    def start(self):
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False

    def set_mute(self, muted):
        self.muted = muted

    def _run(self):
        retry_delay = 5  # Seconds to wait before retrying
        
        while self.running:
            try:
                self.status_changed.emit(f"Connecting to {self.server_ip}:{self.server_port}...")
                
                # 1. Create and connect socket
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(10) # Prevent indefinite hanging
                self.sock.connect((self.server_ip, self.server_port))
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                
                # 2. Handshake
                handshake_msg = f"{self.client_name}|{self.lang_code}"
                self.sock.sendall(handshake_msg.encode('utf-8'))
                time.sleep(0.1)
                
                # 3. Audio Setup
                self.p = pyaudio.PyAudio()
                self.stream = self.p.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=SAMPLE_RATE,
                    input=True,
                    input_device_index=self.device_index,
                    frames_per_buffer=CHUNK_SIZE
                )
                
                self.status_changed.emit("🔴 Streaming Audio")
                update_counter = 0
                # 4. Main Streaming Loop
                while self.running:
                    data = self.stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    update_counter += 1 

                    # Check audio levels for the "Throb" effect
                    if update_counter % 2 == 0:
                       audio_data = np.frombuffer(data, dtype=np.int16)
                       amplitude = np.max(np.abs(audio_data))
                       level = min(1.0, amplitude / 32768.0)
                       self.audio_level.emit(level)
                    
                    if not self.muted:
                        self.sock.sendall(data)

            except (socket.error, BrokenPipeError, ConnectionResetError) as e:
                self.status_changed.emit(f"Connection lost. Retrying in {retry_delay}s...")
                self._cleanup() # Clean up current failed resources
                time.sleep(retry_delay)
                continue # Jump back to the start of the 'while self.running' loop
                
            except Exception as e:
                self.error_occurred.emit(f"Fatal Error: {str(e)}")
                break # Exit loop for non-network related crashes
        
        self._cleanup()
        self.finished.emit()

    def _cleanup(self):
        try:
            if self.stream:
               self.stream.stop_stream()
               self.stream.close()
            if self.p:
               self.p.terminate()
            if self.sock:
               self.sock.close()
        except Exception:
            pass # Silent fail during cleanup is okay
        finally:
            self.stream = None
            self.p = None
            self.sock = None    

class ClientGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.streamer = None
        self.init_ui()
        self.load_devices()

    def init_ui(self):
        self.setWindowTitle("🎙️ Transcription Client")
        self.setGeometry(100, 100, 400, 450)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(15)
        
        #Toggle
        self.btn_theme = QPushButton("🌙 Dark Mode")
        self.btn_theme.setCheckable(True)
        self.btn_theme.clicked.connect(self.toggle_theme)
        layout.addWidget(self.btn_theme)

        # Set initial theme
        self.setStyleSheet(LIGHT_STYLE)

        # CREATE THE CARD
        self.card = QFrame()
        self.card.setObjectName("MainCard")
        # Default Light Style for the Card
        self.card.setStyleSheet("""
            QFrame#MainCard {
                background-color: white; 
                border-radius: 15px; 
                border: 1px solid #ddd;
            }
        """)
        
        # CARD LAYOUT (All inputs go here)
        card_layout = QVBoxLayout(self.card)
        card_layout.setSpacing(15)
        card_layout.setContentsMargins(15, 15, 15, 15)

        # Name Input
        card_layout.addWidget(QLabel("Client Name:"))
        self.name_input = QLineEdit(f"Client-{int(time.time())}")
        card_layout.addWidget(self.name_input)

        # Title
        title = QLabel("Audio Streamer")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Name
        # name_layout = QVBoxLayout()
        # name_layout.addWidget(QLabel("Client Name:"))
        # self.name_input = QLineEdit(f"Client-{int(time.time())}")
        # name_layout.addWidget(self.name_input)
        # layout.addLayout(name_layout)
        
        # Server
        server_layout = QHBoxLayout()
        server_layout.addWidget(QLabel("Server:"))
        self.ip_input = QLineEdit(DEFAULT_SERVER_IP)
        server_layout.addWidget(self.ip_input)
        self.port_input = QLineEdit(str(DEFAULT_SERVER_PORT))
        self.port_input.setFixedWidth(60)
        server_layout.addWidget(self.port_input)
        layout.addLayout(server_layout)

        # Language Selection
        lang_layout = QVBoxLayout()
        lang_layout.addWidget(QLabel("Select Language:"))
        self.lang_combo = QComboBox()
        # Add Speechmatics supported codes
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("Japanese", "ja")
        self.lang_combo.addItem("Spanish", "es")
        self.lang_combo.addItem("French", "fr")
        self.lang_combo.addItem("German", "de")
        self.lang_combo.addItem("Hindi", "hi")
        lang_layout.addWidget(self.lang_combo)
        layout.addLayout(lang_layout)
        
        # Mic Selection
        mic_layout = QVBoxLayout()
        mic_layout.addWidget(QLabel("Microphone:"))
        self.mic_combo = QComboBox()
        mic_layout.addWidget(self.mic_combo)
        layout.addLayout(mic_layout)

        # ADD CARD TO MAIN LAYOUT
        layout.addWidget(self.card)

        # Audio Meter & Buttons 
        self.audio_meter = QProgressBar() # As we added earlier
        layout.addWidget(self.audio_meter)
        
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)
        
        # Visual Indicator
        #self.audio_meter = QProgressBar()
        #self.audio_meter.setRange(0, 100)
        #self.audio_meter.setTextVisible(False)
        #self.audio_meter.setFixedHeight(20)
        # Apply a gradient stylesheet (Green to Red)
        #self.audio_meter.setStyleSheet("""
        #QProgressBar {
        #background-color: #e0e0e0;
        #border-radius: 10px;
        #}
        #QProgressBar::chunk {
        #background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
        #                 stop:0 #4CAF50, stop:0.6 #FFEB3B, stop:1 #f44336);
        #border-radius: 10px;
        #}
        #""")
        #layout.addWidget(self.audio_meter)
        
        # Replace self.audio_meter = QProgressBar() with this:
        self.pulse_container = QFrame()
        self.pulse_container.setFixedSize(80, 80)
        self.pulse_container.setObjectName("PulseCircle")
        self.pulse_container.setStyleSheet("""
            QFrame#PulseCircle {
                background-color: #f0f0f0;
                border-radius: 50px;
                border: 2px solid #ddd;
            }
        """)

        # Add a mic icon inside the throbber
        pulse_layout = QVBoxLayout(self.pulse_container)
        self.mic_icon = QLabel("🎙️")
        self.mic_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mic_icon.setStyleSheet("font-size: 40px; background: transparent; border: none;")
        pulse_layout.addWidget(self.mic_icon)

        # Add to your main layout (centered)
        layout.addWidget(self.pulse_container, alignment=Qt.AlignmentFlag.AlignCenter)

        # Status
        # self.status_label = QLabel("Ready")
        # self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # self.status_label.setStyleSheet("color: gray; font-weight: bold;")
        # layout.addWidget(self.status_label)

        def save_settings(self):
            """Saves current GUI inputs to a JSON file."""
            settings = {
                "name": self.name_input.text(),
                "ip": self.ip_input.text(),
                "port": self.port_input.text(),
                "lang_index": self.lang_combo.currentIndex()
            }
            try:
                with open("config.json", "w") as f:
                    json.dump(settings, f)
            except Exception as e:
                print(f"Error saving settings: {e}")

        def load_settings(self):
            """Loads settings from JSON and populates the GUI."""
            if os.path.exists("config.json"):
                try:
                    with open("config.json", "r") as f:
                        settings = json.load(f)
                        self.name_input.setText(settings.get("name", ""))
                        self.ip_input.setText(settings.get("ip", "127.0.0.1"))
                        self.port_input.setText(settings.get("port", "5001"))
                        self.lang_combo.setCurrentIndex(settings.get("lang_index", 0))
                except Exception as e:
                    print(f"Error loading settings: {e}")
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_connect = QPushButton("Connect & Stream")
        self.btn_connect.setMinimumHeight(40)
        self.btn_connect.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_connect.clicked.connect(self.toggle_stream)
        btn_layout.addWidget(self.btn_connect)
        
        self.btn_mute = QPushButton("Mute")
        self.btn_mute.setMinimumHeight(40)
        self.btn_mute.setCheckable(True)
        self.btn_mute.setEnabled(False)
        self.btn_mute.setStyleSheet("""
            QPushButton { background-color: #cccccc; color: black; font-weight: bold; border-radius: 5px; }
            QPushButton:checked { background-color: #f44336; color: white; }
        """)
        self.btn_mute.clicked.connect(self.toggle_mute)
        btn_layout.addWidget(self.btn_mute)
        
        layout.addLayout(btn_layout)
        
        layout.addStretch()

        self.load_settings() # Auto-fill the fields on startup

    def load_settings(self):
        settings = QSettings("Speechmatics", "LiveTranscribeClient")
        
        # Load Name
        name = settings.value("client_name", f"Client-{int(time.time())}")
        self.name_input.setText(str(name))
        
        # Load IP/Port
        ip = settings.value("server_ip", DEFAULT_SERVER_IP)
        self.ip_input.setText(str(ip))
        
        port = settings.value("server_port", DEFAULT_SERVER_PORT)
        self.port_input.setText(str(port))
        
        # Load Language
        lang = settings.value("language", "en")
        index = self.lang_combo.findData(lang)
        if index >= 0:
            self.lang_combo.setCurrentIndex(index)

    def save_settings(self):
        settings = QSettings("Speechmatics", "LiveTranscribeClient")
        settings.setValue("client_name", self.name_input.text())
        settings.setValue("server_ip", self.ip_input.text())
        settings.setValue("server_port", self.port_input.text())
        settings.setValue("language", self.lang_combo.currentData())

    def load_devices(self):
        p = pyaudio.PyAudio()
        info = p.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        
        default_device_index = p.get_default_input_device_info()['index']
        
        for i in range(0, numdevices):
            if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                name = p.get_device_info_by_host_api_device_index(0, i).get('name')
                self.mic_combo.addItem(name, i)
                if i == default_device_index:
                    self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
        
        p.terminate()

    def toggle_stream(self):
        if not self.streamer or not self.streamer.running:
            self.save_settings() # Save the details the moment the user clicks Connect
            self.start_stream()
        else:
            self.stop_stream()

    def start_stream(self):
        ip = self.ip_input.text()
        try:
            port = int(self.port_input.text())
        except ValueError:
            QMessageBox.critical(self, "Error", "Port must be a number")
            return
            
        idx = self.mic_combo.currentData()
        name = self.name_input.text()
        lang = self.lang_combo.currentData() # Get the 'en', 'es', etc. from the dropdown
        
        self.streamer = AudioStreamer(ip, port, idx, name, lang)
        self.streamer.status_changed.connect(self.update_status)
        self.streamer.error_occurred.connect(self.on_error)
        self.streamer.finished.connect(self.on_finished)
        self.streamer.audio_level.connect(self.update_indicator)
        
        self.streamer.start()
        self.btn_connect.setText("Stop Streaming")
        self.btn_connect.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; border-radius: 5px;")
        
        self.btn_mute.setEnabled(True)
        self.btn_mute.setStyleSheet("""
            QPushButton { background-color: #FF9800; color: white; font-weight: bold; border-radius: 5px; }
            QPushButton:checked { background-color: #f44336; color: white; }
        """)
        
        self.inputs_enabled(False)

    def stop_stream(self):
        if self.streamer:
            self.streamer.stop()

    def toggle_mute(self):
        if self.streamer:
            muted = self.btn_mute.isChecked()
            self.streamer.set_mute(muted)
            if muted:
                self.btn_mute.setText("Unmute")
                self.status_label.setText("🔇 Muted")
                self.indicator_frame.setStyleSheet("background-color: #ddd; border-radius: 15px;")
            else:
                self.btn_mute.setText("Mute")
                self.status_label.setText("🔴 Streaming Audio")

    def toggle_theme(self):
        if self.btn_theme.isChecked():
            self.setStyleSheet(DARK_STYLE)
            self.btn_theme.setText("☀️ Light Mode")
        else:
            self.setStyleSheet(LIGHT_STYLE)
            self.btn_theme.setText("🌙 Dark Mode")            

    def update_indicator(self, level):
        """Updates the dynamic level meter with a colorful pulsing gradient"""
        if self.btn_mute.isChecked() or level < 0.01:
            self.pulse_container.setStyleSheet("""
                QFrame#PulseCircle { 
                    background-color: #f0f0f0; 
                    border-radius: 50px; 
                    border: 2px solid #ddd; 
                }
            """)
            self.status_label.setText("⚪ Silent")
            self.status_label.setStyleSheet("color: gray; font-weight: bold;")
            return
        
        # Calculate dynamic values based on volume
        thickness = int(2 + (level * 12))
        # Map level to a vibrant color range (Cyan to Lime)
        glow_opacity = 0.2 + (level * 0.6)
        
        # Apply a Modern Gradient Style
        self.pulse_container.setStyleSheet(f"""
            QFrame#PulseCircle {{
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, 
                                  stop:0 rgba(0, 242, 254, {glow_opacity}), 
                                  stop:1 rgba(79, 255, 176, {glow_opacity}));
                border: {thickness}px solid qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 #00f2fe, stop:1 #4facfe);
                border-radius: 50px;
            }}
        """)

        # Update status text with color matching the pulse
        if level > 0.8:
            self.status_label.setText("🔴 Peak/Loud")
            self.status_label.setStyleSheet("color: #ff5252; font-weight: bold;")
        else:
            self.status_label.setText("🟢 Capturing...")
            self.status_label.setStyleSheet("color: #00f2fe; font-weight: bold;")

    def on_finished(self):
        self.btn_connect.setText("Connect & Stream")
        self.btn_connect.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_mute.setEnabled(False)
        self.btn_mute.setChecked(False)
        self.btn_mute.setText("Mute")
        self.btn_mute.setStyleSheet("""
            QPushButton { background-color: #cccccc; color: black; font-weight: bold; border-radius: 5px; }
        """)
        self.inputs_enabled(True)
        self.status_label.setText("Stopped")
        self.pulse_container.setStyleSheet("QFrame#PulseCircle { background-color: #f0f0f0; border-radius: 50px; border: 2px solid #ddd; }")
        # self.indicator_frame.setStyleSheet("background-color: #ddd; border-radius: 15px;") # Removed as it doesn't exist

    def on_error(self, msg):
        self.status_label.setText(f"Error: {msg}")
        QMessageBox.critical(self, "Error", msg)
        self.stop_stream()

    def update_status(self, msg):
        if not self.btn_mute.isChecked():
            self.status_label.setText(msg)

    def inputs_enabled(self, enabled):
        self.name_input.setEnabled(enabled)
        self.ip_input.setEnabled(enabled)
        self.port_input.setEnabled(enabled)
        self.mic_combo.setEnabled(enabled)

def list_microphones():
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    
    print("\n🎤 Available Microphones:")
    print("-" * 50)
    for i in range(0, numdevices):
        if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
            name = p.get_device_info_by_host_api_device_index(0, i).get('name')
            print(f"[{i}] {name}")
    print("-" * 50)
    p.terminate()

def main():
    parser = argparse.ArgumentParser(description="Audio Streaming Client")
    parser.add_argument("--miclist", action="store_true", help="List available microphones and exit")
    parser.add_argument("--nogui", action="store_true", help="Run in headless CLI mode")
    parser.add_argument("--name", type=str, default=f"Client-{int(time.time())}", help="Client name")
    parser.add_argument("--server", type=str, default=DEFAULT_SERVER_IP, help="Server IP")
    parser.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT, help="Server port")
    parser.add_argument("--mic", type=int, default=None, help="Microphone index (for CLI mode)")
    
    args = parser.parse_args()

    if args.miclist:
        list_microphones()
        sys.exit(0)

    if args.nogui:
        # Headless Mode
        if args.mic is None:
            print("❌ Error: --mic <index> is required for headless mode.")
            list_microphones()
            sys.exit(1)
            
        print(f"🎙️  Client: {args.name}")
        
        streamer = AudioStreamer(args.server, args.port, args.mic, args.name)
        
        # Simple event loop for CLI
        stop_event = threading.Event()
        
        def on_status(msg): print(f"ℹ️  {msg}")
        def on_error(msg): print(f"❌ {msg}"); stop_event.set()
        def on_finished(): stop_event.set()
        
        streamer.status_changed.connect(on_status)
        streamer.error_occurred.connect(on_error)
        streamer.finished.connect(on_finished)
        
        streamer.start()
        
        try:
            while not stop_event.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nStopping...")
            streamer.stop()
            
    else:
        # GUI Mode
        app = QApplication(sys.argv)
        window = ClientGUI()
        window.show()
        sys.exit(app.exec())

if __name__ == "__main__":
    main()
