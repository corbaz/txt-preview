"""Navegador tab, ported from txt.ps1 (ConvertTo-BrowserUrl, Open-BrowserUrl,
Initialize-BrowserView).

The legacy app hosts a second WebView2 inside the Navegador tab. An <iframe>
cannot clone that: most sites refuse to be framed. So the tab hosts a native
child web view placed over the page area — WebView2 on Windows, WKWebView on
macOS — driven through the same small interface.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import urllib.parse

MSG_EMPTY_ADDRESS = "Escribí una dirección para navegar."
MSG_NO_ADDRESS_TO_OPEN = "No hay una dirección para abrir."
MSG_OPENING = "Abriendo {url}"
MSG_UNAVAILABLE = "No se pudo abrir el navegador integrado: {detail}"
MSG_LOAD_FAILED = "No se pudo cargar la página ({detail}). Probá con Abrir en navegador."

_BARE_DOMAIN = re.compile(r"^[^/\\]+\.[^/\\]+")


def to_browser_url(address: str) -> str:
    """Legacy ConvertTo-BrowserUrl: full URLs, bare domains ("example.com")
    and plain words (searched on Google). '' for an empty address."""
    address = (address or "").strip()
    if not address:
        return ""
    parsed = urllib.parse.urlsplit(address)
    if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
        return address
    if not re.search(r"\s", address) and _BARE_DOMAIN.match(address):
        return f"https://{address}"
    return "https://www.google.com/search?q=" + urllib.parse.quote(address, safe="")


class BrowserState:
    """Thread-safe snapshot the UI polls: url, history flags, last error."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = {"url": "", "can_back": False, "can_forward": False, "error": ""}

    def update(self, **changes) -> None:
        with self._lock:
            self._data.update(changes)

    def snapshot(self, clear_error: bool = True) -> dict:
        with self._lock:
            data = dict(self._data)
            if clear_error:
                self._data["error"] = ""
        return data


def _scaled_bounds(rect: dict, host_width: float) -> tuple[int, int, int, int]:
    """CSS-pixel rect of the page area → host pixels. The scale is the host
    control width over the page's innerWidth, so DPI scaling needs no API."""
    inner_width = float(rect.get("inner_width") or 0)
    scale = host_width / inner_width if inner_width > 0 and host_width > 0 else 1.0
    return (round(float(rect.get("x", 0)) * scale), round(float(rect.get("y", 0)) * scale),
            max(0, round(float(rect.get("width", 0)) * scale)),
            max(0, round(float(rect.get("height", 0)) * scale)))


class _WindowsBrowser:
    """Second WebView2 control on the pywebview form (legacy Initialize-BrowserView)."""

    def __init__(self, window, data_dir: str, state: BrowserState) -> None:
        import clr  # noqa: F401  (pythonnet, loaded by pywebview)
        from webview.platforms.winforms import BrowserView
        self._form = BrowserView.instances[window.uid]
        self._state = state
        self._data_dir = data_dir
        self._view = None
        self._ready = False
        self._pending_url = ""
        self._theme = "dark"

    def _invoke(self, action) -> None:
        from System import Func, Type

        def run():
            action()  # Func[Type] must return None, whatever the action returns

        if self._form.InvokeRequired:
            self._form.Invoke(Func[Type](run))
        else:
            run()

    def _create(self) -> None:
        from Microsoft.Web.WebView2.WinForms import (CoreWebView2CreationProperties,
                                                     WebView2)
        view = WebView2()
        props = CoreWebView2CreationProperties()
        # Own profile folder, as the legacy app (settings\webview2-data).
        props.UserDataFolder = self._data_dir
        view.CreationProperties = props
        view.Visible = False
        self._form.Controls.Add(view)
        view.BringToFront()
        view.CoreWebView2InitializationCompleted += self._on_ready
        view.NavigationCompleted += self._on_navigation_completed
        self._view = view
        view.EnsureCoreWebView2Async(None)

    def _on_ready(self, sender, args) -> None:
        if not args.IsSuccess:
            self._state.update(error=MSG_UNAVAILABLE.format(
                detail=str(args.InitializationException.Message)))
            return
        core = sender.CoreWebView2
        core.SourceChanged += self._on_changed
        core.HistoryChanged += self._on_changed
        core.NewWindowRequested += self._on_new_window
        self._ready = True
        self._apply_theme()
        if self._pending_url:
            core.Navigate(self._pending_url)
            self._pending_url = ""

    def _apply_theme(self) -> None:
        """Pages follow the app theme through prefers-color-scheme."""
        try:
            from Microsoft.Web.WebView2.Core import CoreWebView2PreferredColorScheme as Scheme
            self._view.CoreWebView2.Profile.PreferredColorScheme = (
                Scheme.Dark if self._theme == "dark" else Scheme.Light)
        except Exception:
            pass  # older WebView2 runtime: pages keep their default scheme

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self._invoke(lambda: self._ready and self._apply_theme())

    def _on_changed(self, sender, args) -> None:
        self._state.update(url=str(self._view.Source.AbsoluteUri),
                           can_back=bool(self._view.CanGoBack),
                           can_forward=bool(self._view.CanGoForward))

    def _on_new_window(self, sender, args) -> None:
        # Keep target="_blank" links inside the same browser tab.
        args.set_Handled(True)
        self._view.CoreWebView2.Navigate(str(args.get_Uri()))

    def _on_navigation_completed(self, sender, args) -> None:
        status = str(args.WebErrorStatus)
        if not args.IsSuccess and status != "OperationCanceled":
            self._state.update(error=MSG_LOAD_FAILED.format(detail=status))

    def navigate(self, url: str) -> None:
        def action():
            if self._view is None:
                self._create()
            if self._ready:
                self._view.CoreWebView2.Navigate(url)
            else:
                self._pending_url = url
        self._invoke(action)

    def back(self) -> None:
        self._invoke(lambda: self._view is not None and self._view.CanGoBack
                     and self._view.GoBack())

    def forward(self) -> None:
        self._invoke(lambda: self._view is not None and self._view.CanGoForward
                     and self._view.GoForward())

    def place(self, rect: dict, visible: bool) -> None:
        def action():
            if self._view is None:
                return
            if visible:
                from System.Drawing import Rectangle
                x, y, width, height = _scaled_bounds(rect, self._form.webview.Width)
                self._view.Bounds = Rectangle(x, y, width, height)
                self._view.BringToFront()
            self._view.Visible = bool(visible)
        self._invoke(action)


class _MacBrowser:
    """WKWebView subview of the pywebview host view."""

    def __init__(self, window, data_dir: str, state: BrowserState) -> None:
        from webview.platforms.cocoa import BrowserView
        self._host = BrowserView.instances[window.uid].webview
        self._state = state
        self._view = None
        self._delegate = None
        self._theme = "dark"

    def _on_main(self, action) -> None:
        from PyObjCTools import AppHelper

        def guarded():
            try:
                action()
            except Exception as error:  # surfaced by the UI's state poll
                self._state.update(error=MSG_UNAVAILABLE.format(detail=error))

        AppHelper.callAfter(guarded)

    def _sync(self) -> None:
        url = self._view.URL()
        self._state.update(url=str(url.absoluteString()) if url else "",
                           can_back=bool(self._view.canGoBack()),
                           can_forward=bool(self._view.canGoForward()))

    def _create(self) -> None:
        import AppKit
        import WebKit
        config = WebKit.WKWebViewConfiguration.alloc().init()
        view = WebKit.WKWebView.alloc().initWithFrame_configuration_(
            AppKit.NSMakeRect(0, 0, 10, 10), config)
        view.setHidden_(True)
        self._delegate = _mac_delegate_class().alloc().init()
        self._delegate.owner = self  # plain Python attribute on the instance
        view.setNavigationDelegate_(self._delegate)
        view.setUIDelegate_(self._delegate)
        self._view = view
        self._apply_theme()
        self._host.addSubview_(view)

    def _apply_theme(self) -> None:
        """The view's appearance drives prefers-color-scheme in WebKit."""
        import AppKit
        name = (AppKit.NSAppearanceNameDarkAqua if self._theme == "dark"
                else AppKit.NSAppearanceNameAqua)
        self._view.setAppearance_(AppKit.NSAppearance.appearanceNamed_(name))

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self._on_main(lambda: self._view is not None and self._apply_theme())

    def navigate(self, url: str) -> None:
        def action():
            import Foundation
            if self._view is None:
                self._create()
            target = Foundation.NSURL.URLWithString_(url)
            if target is None:  # characters NSURL rejects: percent-encode them
                import urllib.parse
                target = Foundation.NSURL.URLWithString_(
                    urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%"))
            if target is None:
                raise ValueError(f"dirección no válida: {url}")
            self._view.loadRequest_(Foundation.NSURLRequest.requestWithURL_(target))
        self._on_main(action)

    def back(self) -> None:
        self._on_main(lambda: self._view is not None and self._view.goBack())

    def forward(self) -> None:
        self._on_main(lambda: self._view is not None and self._view.goForward())

    def place(self, rect: dict, visible: bool) -> None:
        def action():
            if self._view is None:
                return
            if visible:
                import AppKit
                host = self._host.frame().size
                x, y, width, height = _scaled_bounds(rect, host.width)
                # The host view is flipped (web coordinates): y grows downwards.
                self._view.setFrame_(AppKit.NSMakeRect(x, y, width, height))
            self._view.setHidden_(not visible)
        self._on_main(action)


_MAC_DELEGATE = None


def _report_mac_failure(owner, error) -> None:
    """Module-level on purpose: an NSObject subclass may only hold methods
    whose signature matches an Objective-C selector."""
    if error is not None and error.code() == -999:  # NSURLErrorCancelled
        return
    detail = str(error.localizedDescription()) if error is not None else "error"
    owner._state.update(error=MSG_LOAD_FAILED.format(detail=detail))


def _mac_delegate_class():
    """Navigation/UI delegate, defined lazily so importing this module never
    needs pyobjc."""
    global _MAC_DELEGATE
    if _MAC_DELEGATE is not None:
        return _MAC_DELEGATE
    import Foundation

    class TxtBrowserDelegate(Foundation.NSObject):

        def webView_didCommitNavigation_(self, view, navigation):
            self.owner._sync()

        def webView_didFinishNavigation_(self, view, navigation):
            self.owner._sync()

        def webView_didFailProvisionalNavigation_withError_(self, view, navigation, error):
            _report_mac_failure(self.owner, error)

        def webView_didFailNavigation_withError_(self, view, navigation, error):
            _report_mac_failure(self.owner, error)

        def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(
                self, view, config, action, features):
            # Keep target="_blank" links inside the same browser tab.
            view.loadRequest_(action.request())
            return None

    _MAC_DELEGATE = TxtBrowserDelegate
    return _MAC_DELEGATE


class EmbeddedBrowser:
    """Platform-neutral facade used by the Api bridge. The native view is
    created on the first navigation (legacy lazy Initialize-BrowserView)."""

    def __init__(self, window, settings_dir: str, platform: str | None = None,
                 backend=None) -> None:
        self.state = BrowserState()
        self._backend = backend
        self._window = window
        self._data_dir = os.path.join(settings_dir, "webview2-data")
        self._platform = platform or sys.platform
        self._theme = "dark"

    def set_theme(self, theme: str) -> None:
        """Web pages follow the app theme (dark or light)."""
        self._theme = "light" if theme == "light" else "dark"
        if self._backend is not None:
            self._backend.set_theme(self._theme)

    def _ensure_backend(self):
        if self._backend is None:
            factory = _WindowsBrowser if self._platform == "win32" else _MacBrowser
            if self._platform not in ("win32", "darwin"):
                raise RuntimeError("plataforma sin navegador integrado")
            self._backend = factory(self._window, self._data_dir, self.state)
            self._backend.set_theme(self._theme)
        return self._backend

    def navigate(self, url: str) -> None:
        self.state.update(url=url, error="")
        self._ensure_backend().navigate(url)

    def back(self) -> None:
        if self._backend is not None:
            self._backend.back()

    def forward(self) -> None:
        if self._backend is not None:
            self._backend.forward()

    def place(self, rect: dict, visible: bool) -> None:
        if self._backend is not None:
            self._backend.place(rect or {}, visible)
