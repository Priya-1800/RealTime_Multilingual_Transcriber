# 🎙️ Real-Time Multilingual Transcriber

A high-performance, multi-threaded audio transcription system built with **Python**, **PyQt6**, and the **Speechmatics RT API**. This project demonstrates real-time TCP socket streaming, concurrent client handling, and modern UI/UX design.



## 🚀 Key Features
- Real-Time Streaming: Low-latency audio transmission via TCP sockets.
- Modern UI: Dark-mode interface with reactive "Neon Glow" audio activity indicators.
- Smart Formatting: Automatic punctuation, entity recognition (dates/currency), and sentence capitalization.
- Multilingual Support: Handles multiple languages using Speechmatics' "Enhanced" operating point.
- Concurrent Handling: Threaded server-side processing to manage multiple client connections simultaneously.

## 🛠️ Tech Stack
- Language: Python 3.11+
- GUI Framework: PyQt6
- Speech-to-Text: Speechmatics SDK
- Signal Processing: NumPy (for RMS activity detection)
- Concurrency: Threading & Socket programming

## 📁 Project Structure
- `server.py`: The central hub that manages connections, processes audio signals, and displays the transcript dashboard.
- `client.py`: The user-facing application that captures local microphone input and streams it to the server.
- `requirements.txt`: Dependencies required to replicate the environment.

## ⚙️ Installation & Setup
1. Clone the repository:
   ```bash
   git clone [https://github.com/Priya-1800/RealTime_Multilingual_Transcriber.git](https://github.com/YOUR_USERNAME/RealTime-Multilingual-Transcriber.git)
2. Install dependencies:
   pip install -r requirements.txt
3. Configure API Key:
   Create a .env file and add:
   SPEECHMATICS_API_KEY=your_key_here
4. Run the Server:
   python server.py
5. Run the Client:
   python client.py   
 
   
