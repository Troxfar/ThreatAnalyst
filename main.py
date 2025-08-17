import json, requests
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets

LM_URL = "http://localhost:1234/v1/chat/completions"
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
class ChatWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('NeonJoy — Adjutant Edition (Python)')
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
    def _append(self, who, text): self.history.append(f'<b>{who}:</b> {text}')
    def _call_lmstudio(self):
        payload = {'model': self.model_name, 'messages': self.messages[-12:], 'temperature': 0.7,
                   'response_format': {'type':'json_schema','json_schema':{'name':'EmotionTaggedReply','schema':{'type':'object','properties':{'assistant_text':{'type':'string'},'emotion':{'type':'string','enum':['neutral','joy','sad','angry','fear','surprise','disgust']},'intensity':{'type':'number','minimum':0,'maximum':1}},'required':['assistant_text','emotion','intensity'],'additionalProperties': False}}}}
        try:
            r = requests.post(LM_URL, json=payload, timeout=60); r.raise_for_status(); data = r.json()
            content = data['choices'][0]['message']['content']; tagged = json.loads(content) if isinstance(content, str) else content
            reply = tagged.get('assistant_text','…'); emotion = tagged.get('emotion','neutral'); intensity = float(tagged.get('intensity', 0.5))
            self.messages.append({'role':'assistant','content':reply}); self._append('AI', reply); self.avatar.set_emotion(emotion, intensity)
        except Exception as e: self._append('System', f"<span style='color:#ff7b7b'>Error: {e}</span>")
if __name__ == '__main__':
    app = QtWidgets.QApplication([]); w = ChatWindow(); w.show(); app.exec()
