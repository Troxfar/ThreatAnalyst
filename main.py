import json, requests, re
try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - optional dependency
    BeautifulSoup = None
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets
import google.generativeai as genai

# default LM Studio endpoint used if no setting has been saved yet
DEFAULT_LM_URL = "http://localhost:1234/v1/chat/completions"
EMOTION_MAP = {
    "neutral": {"eyes":"eyes_neutral.png", "mouth":"mouth_neutral.png", "brows":"brows_neutral.png"},
    "joy":     {"eyes":"eyes_happy.png",   "mouth":"mouth_smile.png",   "brows":"brows_up.png"},
    "sad":     {"eyes":"eyes_sad.png",     "mouth":"mouth_frown.png",   "brows":"brows_down.png"},
    "angry":   {"eyes":"eyes_angry.png",   "mouth":"mouth_frown.png",   "brows":"brows_down.png"},
    "surprise":{"eyes":"eyes_happy.png",   "mouth":"mouth_smile.png",   "brows":"brows_up.png"},
    "fear":    {"eyes":"eyes_sad.png",     "mouth":"mouth_frown.png",   "brows":"brows_up.png"},
    "disgust": {"eyes":"eyes_angry.png",   "mouth":"mouth_frown.png",   "brows":"brows_down.png"},
}
class AvatarView(QtWidgets.QGraphicsView):
    def __init__(self, assets_dir: Path):
        super().__init__()
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#0b0f1a")))
        self.scene = QtWidgets.QGraphicsScene(self); self.setScene(self.scene)
        self.assets = assets_dir
        self.base_item   = self._add_layer("base.png")
        self.brows_item  = self._add_layer("brows_neutral.png")
        self.eyes_item   = self._add_layer("eyes_neutral.png")
        self.mouth_item  = self._add_layer("mouth_neutral.png")
        self.setSceneRect(self.base_item.boundingRect())
        self.setFixedSize(int(self.scene.width()), int(self.scene.height()))
        self.blink_timer = QtCore.QTimer(self); self.blink_timer.timeout.connect(self._blink_tick)
        self.blink_timer.start(2800); self._blinking=False
    def _add_layer(self, fname):
        pix = QtGui.QPixmap(str(self.assets / fname)); item = self.scene.addPixmap(pix)
        item.setZValue(self.scene.items().__len__()); return item
    def set_emotion(self, emotion:str, intensity:float):
        m = EMOTION_MAP.get((emotion or 'neutral').lower(), EMOTION_MAP['neutral'])
        self.eyes_item.setPixmap(QtGui.QPixmap(str(self.assets / m['eyes'])))
        self.mouth_item.setPixmap(QtGui.QPixmap(str(self.assets / m['mouth'])))
        self.brows_item.setPixmap(QtGui.QPixmap(str(self.assets / m['brows'])))
        scale = 1.0 + 0.02 * max(0.0, min(1.0, float(intensity)))
        for layer in (self.base_item, self.brows_item, self.eyes_item, self.mouth_item): layer.setScale(scale)
    def _blink_tick(self):
        if self._blinking: return
        self._blinking=True
        self.eyes_item.setTransform(QtGui.QTransform().scale(1.0, 0.1))
        QtCore.QTimer.singleShot(120, lambda: (self.eyes_item.setTransform(QtGui.QTransform()), setattr(self, '_blinking', False)))
class ChatTab(QtWidgets.QWidget):
    def __init__(self, settings: 'SettingsTab'):
        super().__init__()
        self.settings = settings
        self.setStyleSheet('QTextEdit { background:#0f1630; color:#e6f0ff; } QLineEdit { background:#101a3a; color:#e6f0ff; padding:6px; } QPushButton { padding:6px 12px; }')
        assets = Path(__file__).parent / 'assets'; self.avatar = AvatarView(assets)
        self.history = QtWidgets.QTextEdit(readOnly=True); self.input = QtWidgets.QLineEdit(placeholderText='Say something…'); self.sendBtn = QtWidgets.QPushButton('Send')
        hl = QtWidgets.QHBoxLayout(); hl.addWidget(self.avatar); hl.addWidget(self.history, 1)
        bl = QtWidgets.QHBoxLayout(); bl.addWidget(self.input, 1); bl.addWidget(self.sendBtn)
        layout = QtWidgets.QVBoxLayout(self); layout.addLayout(hl); layout.addLayout(bl)
        self.sendBtn.clicked.connect(self.on_send); self.input.returnPressed.connect(self.on_send)
        self.model_name = 'qwen2.5-7b-instruct'; self.messages = [{'role':'system','content':'Return STRICT JSON only, matching the schema.'}]

    def on_send(self):
        text = self.input.text().strip()
        if not text: return
        self.input.clear(); self._append('You', text); self.messages.append({'role':'user','content':text})
        QtCore.QTimer.singleShot(0, self._call_lmstudio)

    def _append(self, who, text):
        self.history.append(f'<b>{who}:</b> {text}')

    def _call_lmstudio(self):
        url = self.settings.get_lm_endpoint() or DEFAULT_LM_URL
        payload = {'model': self.model_name, 'messages': self.messages[-12:], 'temperature': 0.7,
                   'response_format': {'type':'json_schema','json_schema':{'name':'EmotionTaggedReply','schema':{'type':'object','properties':{'assistant_text':{'type':'string'},'emotion':{'type':'string','enum':['neutral','joy','sad','angry','fear','surprise','disgust']},'intensity':{'type':'number','minimum':0,'maximum':1}},'required':['assistant_text','emotion','intensity'],'additionalProperties': False}}}}
        try:
            r = requests.post(url, json=payload, timeout=60); r.raise_for_status(); data = r.json()
            content = data['choices'][0]['message']['content']; tagged = json.loads(content) if isinstance(content, str) else content
            reply = tagged.get('assistant_text','…'); emotion = tagged.get('emotion','neutral'); intensity = float(tagged.get('intensity', 0.5))
            self.messages.append({'role':'assistant','content':reply}); self._append('AI', reply); self.avatar.set_emotion(emotion, intensity)
            
        except Exception as e:
            self._append('System', f"<span style='color:#ff7b7b'>Error: {e}</span>")


class SettingsTab(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QtCore.QSettings('ThreatAnalyst', 'NeonJoy')
        self.lm_endpoint_edit = QtWidgets.QLineEdit()
        self.api_key_edit = QtWidgets.QLineEdit()
        form = QtWidgets.QFormLayout(self)
        form.addRow('LM Studio Endpoint', self.lm_endpoint_edit)
        form.addRow('Gemini API Key', self.api_key_edit)
        self.load_settings()
        self.lm_endpoint_edit.editingFinished.connect(self.save_settings)
        self.api_key_edit.editingFinished.connect(self.save_settings)

    def load_settings(self):
        self.lm_endpoint_edit.setText(self.settings.value('lm_endpoint', DEFAULT_LM_URL))
        default_key = 'AIzaSyAwIloDIfDzd5OXTX2U_wPtOsW0cPuXPDs'
        saved_key = self.settings.value('gemini_api_key')
        self.api_key_edit.setText(saved_key if saved_key else default_key)

    def save_settings(self):
        self.settings.setValue('lm_endpoint', self.lm_endpoint_edit.text().strip())
        self.settings.setValue('gemini_api_key', self.api_key_edit.text().strip())

    def get_api_key(self) -> str:
        return self.api_key_edit.text().strip()

    def get_lm_endpoint(self) -> str:
        return self.lm_endpoint_edit.text().strip()


class GeminiTab(QtWidgets.QWidget):
    def __init__(self, settings: 'SettingsTab'):
        super().__init__()
        self.settings = settings
        instructions_path = Path(__file__).parent / 'resources' / 'instructions.txt'
        self.instructions_edit = QtWidgets.QTextEdit()
        self.instructions_edit.setPlainText(instructions_path.read_text(encoding='utf-8'))
        self.response_edit = QtWidgets.QTextEdit(readOnly=True)
        self.timer_label = QtWidgets.QLabel('00:00')
        self.duration_combo = QtWidgets.QComboBox()
        self.duration_combo.addItems(['1', '5', '10'])
        self.duration_combo.currentIndexChanged.connect(self.update_duration)
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel('Minutes:'))
        controls.addWidget(self.duration_combo)
        controls.addStretch(1)
        controls.addWidget(self.timer_label)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.instructions_edit, 1)
        layout.addLayout(controls)
        layout.addWidget(self.response_edit, 1)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.duration_minutes = int(self.duration_combo.currentText())
        self.start_timer()

    def start_timer(self):
        self.remaining = self.duration_minutes * 60
        self._update_display()
        self.timer.start(1000)

    def set_duration(self, minutes: int):
        idx = self.duration_combo.findText(str(minutes))
        if idx == -1:
            self.duration_combo.addItem(str(minutes))
            idx = self.duration_combo.count() - 1
        self.duration_combo.setCurrentIndex(idx)

    def update_duration(self):
        self.duration_minutes = int(self.duration_combo.currentText())
        self.start_timer()

    def _update_display(self):
        m, s = divmod(self.remaining, 60)
        self.timer_label.setText(f'{m:02d}:{s:02d}')

    def _tick(self):
        self.remaining -= 1
        self._update_display()
        if self.remaining <= 0:
            self.timer.stop()
            QtCore.QTimer.singleShot(0, self._send_to_gemini)
            self.start_timer()

    def _send_to_gemini(self):
        key = self.settings.get_api_key()
        if not key:
            self.response_edit.setPlainText('No API key set.')
            return
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            resp = model.generate_content(self.instructions_edit.toPlainText())
            self.response_edit.setPlainText(resp.text)
        except Exception as e:
            self.response_edit.setPlainText(f'Error: {e}')


class FeedScraperTab(QtWidgets.QWidget):
    def __init__(self, settings_tab, content_tab):
        super().__init__()
        self.settings_tab = settings_tab
        self.content_tab = content_tab
        self.settings = QtCore.QSettings('ThreatAnalyst', 'NeonJoy')
        self.default_urls = [
            "https://feeds.feedburner.com/TheHackersNews",
            "https://www.bleepingcomputer.com/feed/",
            "https://krebsonsecurity.com/feed/",
            "https://www.darkreading.com/rss.xml",
            "https://www.securityweek.com/feed/",
            "https://threatpost.com/feed/",
            "https://us-cert.cisa.gov/ncas/all.xml",
            "https://www.schneier.com/blog/atom.xml",
            "https://www.csoonline.com/index.rss",
            "https://www.cisecurity.org/feed/advisories",
        ]
        self.url_label = QtWidgets.QLabel("News Feeds")
        self.url_edit = QtWidgets.QPlainTextEdit()
        self.save_btn = QtWidgets.QPushButton('Save URLs')
        self.save_btn.clicked.connect(self.save_urls)
        self.load_urls()
        self.output_label = QtWidgets.QLabel("Contents")
        self.output = QtWidgets.QTextEdit(readOnly=True)
        self.timestamp_label = QtWidgets.QLabel("Time Stamp")
        self.gemini_label = QtWidgets.QLabel("New URLs")
        self.gemini_output = QtWidgets.QTextEdit(readOnly=True)
        self.scrape_btn = QtWidgets.QPushButton("Scrape URLs")
        self.scrape_btn.clicked.connect(self._scrape_new_urls)
        self.last_scrape_edit = QtWidgets.QLineEdit()
        self.last_scrape_edit.setReadOnly(True)
        self.last_scrape_edit.setFixedHeight(24)
        self.last_scrape_edit.setText("Never")
        self.interval_combo = QtWidgets.QComboBox()
        self.interval_combo.addItems(["5", "15", "60"])
        self.interval_combo.setCurrentText("5")
        self.interval_combo.currentTextChanged.connect(lambda t: self.set_interval(int(t)))
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel('Refresh (min):'))
        controls.addWidget(self.interval_combo)
        self.countdown_label = QtWidgets.QLabel("00:00")
        controls.addWidget(self.countdown_label)
        controls.addStretch(1)
        layout = QtWidgets.QVBoxLayout(self)
        url_layout = QtWidgets.QHBoxLayout()
        url_layout.addWidget(self.url_edit, 1)
        url_layout.addWidget(self.save_btn)
        layout.addWidget(self.url_label)
        layout.addLayout(url_layout)
        layout.addWidget(self.output_label)
        layout.addWidget(self.output, 1)
        layout.addWidget(self.timestamp_label)
        layout.addWidget(self.last_scrape_edit)
        layout.addWidget(self.gemini_label)
        gemini_layout = QtWidgets.QHBoxLayout()
        gemini_layout.addWidget(self.gemini_output, 1)
        gemini_layout.addWidget(self.scrape_btn)
        layout.addLayout(gemini_layout)
        layout.addLayout(controls)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.scrape)
        self.countdown_timer = QtCore.QTimer(self)
        self.countdown_timer.timeout.connect(self._countdown_tick)
        self.set_interval(5)
        self.countdown_timer.start(1000)
        self.scrape()

    def save_urls(self):
        self.settings.setValue('feed_urls', self.url_edit.toPlainText())

    def load_urls(self):
        stored = self.settings.value('feed_urls')
        if stored:
            self.url_edit.setPlainText(stored)
        else:
            self.url_edit.setPlainText("\n".join(self.default_urls))

    def closeEvent(self, event):
        self.save_urls()
        super().closeEvent(event)

    def set_interval(self, minutes: int):
        self.timer.stop()
        self.interval_seconds = max(1, minutes) * 60
        self.timer.start(self.interval_seconds * 1000)
        self.remaining_seconds = self.interval_seconds
        self._update_countdown_label()

    def _update_countdown_label(self):
        m, s = divmod(self.remaining_seconds, 60)
        self.countdown_label.setText(f"{m:02d}:{s:02d}")

    def _countdown_tick(self):
        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
        self._update_countdown_label()

    def _send_to_gemini(self):
        text = self.output.toPlainText()
        if not text.strip():
            self.gemini_output.setPlainText("")
            return
        api_key = self.settings_tab.get_api_key()
        if not api_key:
            self.gemini_output.setPlainText("No API key configured.")
            return
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = (
                "Look at the time stamp and ignore anything older than 24 hours "
                "then strip out the URLs that are left and just list the URLs and nothing else.\n\n"
                + text
            )
            response = model.generate_content(prompt)
            resp_text = response.text or ""
            self.gemini_output.setPlainText(resp_text)
            if re.search(r"https?://", resp_text):
                self._scrape_new_urls()
        except Exception as e:
            self.gemini_output.setPlainText(f"Error: {e}")

    def _scrape_new_urls(self) -> None:
        QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
        if hasattr(self, "scrape_btn"):
            self.scrape_btn.setEnabled(False)
            self.scrape_btn.setText("Scraping...")
        try:
            urls = [line.strip() for line in self.gemini_output.toPlainText().splitlines() if line.strip()]
            snippets = []
            for url in urls:
                try:
                    r = requests.get(url, timeout=10)
                    r.raise_for_status()
                    if BeautifulSoup:
                        soup = BeautifulSoup(r.text, "html.parser")
                        text = soup.get_text(separator="\n")
                    else:
                        text = r.text
                    snippets.append(text.strip())
                except Exception as e:
                    snippets.append(f"Error fetching {url}: {e}")
            combined = "\n\n".join(snippets)
            self.content_tab.update_webscraps(combined)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            if hasattr(self, "scrape_btn"):
                self.scrape_btn.setEnabled(True)
                self.scrape_btn.setText("Scrape URLs")

    def scrape(self):
        urls = [u.strip() for u in self.url_edit.toPlainText().splitlines() if u.strip()]
        lines = []

        def _parse_date(text: str):
            if not text:
                return None
            text = text.strip()
            for parser in (
                parsedate_to_datetime,
                lambda s: datetime.fromisoformat(s.replace('Z', '+00:00')),
            ):
                try:
                    return parser(text)
                except Exception:
                    continue
            return None

        for url in urls:
            try:
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                root = ET.fromstring(r.content)
                items = root.findall('.//item')
                if not items:
                    items = root.findall('.//{http://www.w3.org/2005/Atom}entry')
                # TODO: Add a user-configurable limit or pagination to avoid
                # excessive output for very long feeds.
                for item in items:
                    title = (
                        item.findtext('title')
                        or item.findtext('{http://www.w3.org/2005/Atom}title')
                        or item.get('title')
                    )
                    if not title:
                        title_elem = item.find('{*}title')
                        if title_elem is not None:
                            title = (
                                title_elem.get('value')
                                or title_elem.get('label')
                                or title_elem.text
                            )
                    link = item.findtext('link') or item.get('link')
                    if not link:
                        link_elem = (
                            item.find('{http://www.w3.org/2005/Atom}link')
                            or item.find('{*}link')
                        )
                        if link_elem is not None:
                            link = (
                                link_elem.get('href')
                                or link_elem.get('url')
                                or link_elem.text
                                or ''
                            )
                    if not link:
                        link = item.findtext('guid', '')

                    # Fallbacks capture URLs from guid elements, namespaced links, or
                    # attribute-based fields when standard tags are missing.

                    date_text = (
                        item.findtext('pubDate')
                        or item.findtext('published')
                        or item.findtext('updated')
                        or item.findtext('{http://www.w3.org/2005/Atom}published')
                        or item.findtext('{http://www.w3.org/2005/Atom}updated')
                    )
                    dt = _parse_date(date_text)
                    date_str = dt.strftime('%Y-%m-%d %H:%M') if dt else 'Unknown date'

                    if title and link:
                        lines.append(f"{date_str} - {title.strip()}: {link.strip()}")
            except Exception as e:
                lines.append(f"Error fetching {url}: {e}")
        self.output.setPlainText("\n".join(lines))
        self._send_to_gemini()
        self.remaining_seconds = self.interval_seconds
        self._update_countdown_label()
        self.last_scrape_edit.setText(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

class ContentTab(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Web Scraps"))
        self.webscraps = QtWidgets.QTextEdit()
        self.webscraps.setReadOnly(True)
        layout.addWidget(self.webscraps, 1)

    def update_webscraps(self, text: str) -> None:
        self.webscraps.setPlainText(text)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('NeonJoy — Adjutant Edition (Python)')
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)

        self.settings_tab = SettingsTab()
        self.chat_tab = ChatTab(self.settings_tab)
        self.content_tab = ContentTab()
        self.feed_tab = FeedScraperTab(self.settings_tab, self.content_tab)
        self.tabs.addTab(self.chat_tab, "Chat")
        self.tabs.addTab(self.feed_tab, "Feeds")
        self.tabs.addTab(self.content_tab, "Content")
        self.tabs.addTab(self.settings_tab, "Settings")


if __name__ == '__main__':
    app = QtWidgets.QApplication([])
    w = MainWindow()
    w.show()
    app.exec()
