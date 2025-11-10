# main.py
import os
import sys
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.metrics import dp

IS_ANDROID = False
try:
    import android
    from jnius import autoclass, cast
    IS_ANDROID = True
except Exception:
    IS_ANDROID = False

DEFAULT_URL = os.environ.get("APP_START_URL", "https://example.com")
ENABLE_AI = os.environ.get("ENABLE_AI", "0") == "1"
AI_ENDPOINT = os.environ.get("AI_ENDPOINT", "")
AI_API_KEY = os.environ.get("AI_API_KEY", "")

class AndroidWebView(Widget):
    def __init__(self, start_url, **kwargs):
        super().__init__(**kwargs)
        self.start_url = start_url
        self.webview = None
        self.activity = None
        self.loaded = False
        if IS_ANDROID:
            Clock.schedule_once(self._init_webview, 0)

    def _init_webview(self, _dt):
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        self.activity = PythonActivity.mActivity

        # Layout params
        ViewGroupLayoutParams = autoclass('android.view.ViewGroup$LayoutParams')
        MATCH_PARENT = ViewGroupLayoutParams.MATCH_PARENT

        # Create WebView
        WebView = autoclass('android.webkit.WebView')
        self.webview = WebView(self.activity)
        self.webview.getSettings().setJavaScriptEnabled(True)
        self.webview.getSettings().setDomStorageEnabled(True)
        self.webview.getSettings().setUseWideViewPort(True)
        self.webview.getSettings().setLoadWithOverviewMode(True)
        self.webview.getSettings().setMediaPlaybackRequiresUserGesture(False)

        # Enable file uploads and mixed content (optional)
        self.webview.getSettings().setAllowFileAccess(True)
        self.webview.getSettings().setMixedContentMode(0)  # MIXED_CONTENT_ALWAYS_ALLOW

        # Handle navigation inside WebView
        WebViewClient = autoclass('android.webkit.WebViewClient')
        class PyWebViewClient(WebViewClient):
            def shouldOverrideUrlLoading(_self, view, request):
                return False  # Keep inside WebView
        self.webview.setWebViewClient(PyWebViewClient())

        # Add to Activity
        layout = self.activity.getWindow().getDecorView().findViewById(android.R.id.content)
        self.webview.setLayoutParams(ViewGroupLayoutParams(MATCH_PARENT, MATCH_PARENT))
        layout.addView(self.webview)

        # Load URL
        self.webview.loadUrl(self.start_url)
        self.loaded = True

    def load_url(self, url):
        if IS_ANDROID and self.webview:
            self.webview.loadUrl(url)

    def go_back(self):
        if IS_ANDROID and self.webview and self.webview.canGoBack():
            self.webview.goBack()

    def go_forward(self):
        if IS_ANDROID and self.webview and self.webview.canGoForward():
            self.webview.goForward()

    def on_kv_post(self, base_widget):
        # Reserve space so Kivy layout exists (Android WebView is layered under decor view)
        self.size_hint = (1, 1)

class Toolbar(BoxLayout):
    def __init__(self, webview_component, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(48)
        self.web = webview_component

        self.back_btn = Button(text="⟵", size_hint_x=None, width=dp(56))
        self.forward_btn = Button(text="⟶", size_hint_x=None, width=dp(56))
        self.reload_btn = Button(text="⟳", size_hint_x=None, width=dp(56))
        self.url_input = TextInput(text=DEFAULT_URL, multiline=False)

        self.back_btn.bind(on_release=lambda _b: self.web.go_back())
        self.forward_btn.bind(on_release=lambda _b: self.web.go_forward())
        self.reload_btn.bind(on_release=lambda _b: self.web.load_url(self.url_input.text))
        self.url_input.bind(on_text_validate=lambda _t: self.web.load_url(self.url_input.text))

        self.add_widget(self.back_btn)
        self.add_widget(self.forward_btn)
        self.add_widget(self.reload_btn)
        self.add_widget(self.url_input)

class AIOverlay(AnchorLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (1, None)
        self.height = dp(56)
        self.anchor_x = 'right'
        self.anchor_y = 'bottom'

        box = BoxLayout(orientation='horizontal', size_hint=(None, None), height=dp(56), width=Window.width)
        self.prompt = TextInput(hint_text="Ask AI...", multiline=False, size_hint_x=1)
        self.send = Button(text="Send", size_hint_x=None, width=dp(100))
        box.add_widget(self.prompt)
        box.add_widget(self.send)
        self.add_widget(box)

        self.send.bind(on_release=self.on_send)

    def on_send(self, _btn):
        text = self.prompt.text.strip()
        if not text or not AI_ENDPOINT:
            return
        # Minimal non-blocking call
        from threading import Thread
        Thread(target=self._call_ai, args=(text,), daemon=True).start()

    def _call_ai(self, prompt):
        import json, urllib.request
        try:
            req = urllib.request.Request(
                AI_ENDPOINT,
                data=json.dumps({"prompt": prompt}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {AI_API_KEY}" if AI_API_KEY else ""
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                answer = data.get("answer") or data.get("output") or str(data)
        except Exception as e:
            answer = f"AI error: {e}"

        # Show a simple toast using Android Toast if available, else print
        if IS_ANDROID:
            Toast = autoclass('android.widget.Toast')
            String = autoclass('java.lang.String')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Toast.makeText(PythonActivity.mActivity, String(answer), Toast.LENGTH_LONG).show()
        else:
            print("AI:", answer)

class Website2ApkApp(App):
    def build(self):
        root = BoxLayout(orientation="vertical")
        self.webview = AndroidWebView(DEFAULT_URL)
        toolbar = Toolbar(self.webview)
        root.add_widget(toolbar)
        root.add_widget(self.webview)
        if ENABLE_AI:
            root.add_widget(AIOverlay())
        return root

    def on_stop(self):
        # Clean up webview if needed
        pass

if __name__ == "__main__":
    Website2ApkApp().run()
