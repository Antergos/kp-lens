#
# Copyright 2012-2014 "Korora Project" <dev@kororaproject.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the temms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

import json
import logging
import os
import signal

import sys
from lens.thread import ThreadManager
from lens.view import View


# Qt5
from dbus.mainloop.qt import DBusQtMainLoop
# PyCharm import bug workaround for code completion
from PyQt5.QtCore.__init__ import *
from PyQt5.QtWidgets.__init__ import QApplication, QMainWindow, QAction, qApp
from PyQt5.QtGui.__init__ import QIcon
from PyQt5 import QtWebEngineWidgets as QtWebEng
from PyQt5.QtWebChannel import *

logger = logging.getLogger('Lens.Backend.Qt5')


class ThreadManagerQt5(ThreadManager):
    def __init__(self, app=None, max_concurrent_threads=10):
        super(ThreadManagerQt5, self).__init__(self, max_concurrent_threads)

        self._app = app

        if self._app is not None:
            # watch the queue for updates
            _fd = self.queue_in._reader.fileno()

            _notifier = QSocketNotifier(_fd, QSocketNotifier.Read, self._app)
            _notifier.activated.connect(self._on_cb)

    def _on_cb(self, fd):
        while not self.queue_in.empty():
            data = self.queue_in.get()

            if data['name'] == '__completed':
                self._thread_completed(self.threads[data['uuid']]['t'])

            else:
                self.emit('__thread_%s_%s' % (data['uuid'], data['name']),
                          self.threads[data['uuid']], *data['args'])

        return True


class CustomNetworkAccessManager(QObject):
    process_url = pyqtSignal(str)

    def __init__(self, page=None, uri_app_base='', uri_lens_base='', *args, **kwargs):
        super(CustomNetworkAccessManager, self).__init__(*args, **kwargs)
        self.uri_app_base = uri_app_base
        self.uri_lens_base = uri_lens_base
        self.process_url.connect(self.process_request_url)
        self.page = page

    @pyqtSlot(str)
    def process_request_url(self, request_url):
        path = req = str(request_url)

        if path.startswith('app://') or path.startswith('lens://'):
            if path == 'app:///':
                path = 'file://' + self.uri_app_base + 'app.html'
                logger.debug('Loading app resource: {0} ({1})'.format(req, path))

            elif path.startswith('app://'):
                path = path.replace('app://', 'file://' + self.uri_app_base)
                logger.debug('Loading app resource: {0} ({1})'.format(req, path))

                # variable substitution
                path = path.replace('$backend', 'qt5')

            elif path.startswith('lens://'):
                path = path.replace('lens://', 'file://' + self.uri_lens_base)
                logger.debug('Loading lens resource: {0} ({1})'.format(req, path))

                # make lens.css backend specific
                path = path.replace('lens.css', 'lens-qt5.css')

        self.page.url_for_request.emit(path)


class LensQWebEngineView(QtWebEng.QWebEngineView):
    def __init__(self, *args, **kwargs):
        super(LensQWebEngineView, self).__init__(*args, **kwargs)

        self.setContextMenuPolicy(Qt.NoContextMenu)


class LensQWebEnginePage(QtWebEng.QWebEnginePage):
    url_for_request = pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super(LensQWebEnginePage, self).__init__(*args, **kwargs)
        self.cnam = None
        self.global_settings = self.globalSettings()

        self.global_settings.setAttribute(
            QtWebEng.QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.global_settings.setAttribute(
            QtWebEng.QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.global_settings.setAttribute(QtWebEng.QWebEngineSettings.ScrollAnimatorEnabled, True)

        self.url_for_request.connect(self.url_for_request_cb)

    def set_network_access_manager(self, cnam):
        if cnam:
            self.cnam = cnam
        else:
            logger.debug('Invalid Value for cnam')

    def acceptNavigationRequest(self, url):
        # Emit signal to have our cnam process the URL.
        self.cnam.process_url.emit(url)

        # Returning False will make chromium ignore the request (we'll handle it in signal cb)
        return False

    @pyqtSlot(str)
    def url_for_request_cb(self, url):
        # Navigate to the processed url.
        self.load(QUrl(url))


class LensMainWindow(QMainWindow):
    def __init__(self, *args, title=None, width=966, height=605, **kwargs):
        super(LensMainWindow, self).__init__(*args, **kwargs)

        self.title = title
        self.width = width
        self.height = height
        self.setAttribute(Qt.WA_DeleteOnClose)



        self.init_window()

        self.web_view.show()
        self.setCentralWidget(self.web_view)

    def init_window(self):
        self.setWindowTitle(self.title)
        # self.setWindowIcon(QtGui.QIcon(os.path.join(DATA_DIR, 'img/fav.png')))
        self.setFixedSize(self.width, self.height)
        self.init_menu_bar()


        self.init_bridge_channel()

        self.web_page.load(QUrl('qrc:///static/view_wrap.html'))

    def init_bridge_channel(self):
        self.web_page.setWebChannel(self.channel)
        # self.channel.registerObject('PoodleBridge', self.bridge)
        # self.channel.registerObject('PoodleBridgeViews', self.views)
        self.channel.registerObject('PoodleBridgeRouter', self.router)

    def init_menu_bar(self):
        exit_action = QAction(QIcon('exit.png'), '&Exit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.setStatusTip('Exit application')
        exit_action.triggered.connect(qApp.quit)

        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu('&File')
        file_menu.addAction(exit_action)
        edit_menu = menu_bar.addMenu('&Edit')
        edit_menu.addAction(exit_action)
        view_menu = menu_bar.addMenu('&View')
        view_menu.addAction(exit_action)
        about_menu = menu_bar.addMenu('&About')
        about_menu.addAction(exit_action)


class LensViewQt5(View):
    def __init__(self, name="MyLensApp", width=640, height=480, inspector=False,
                 start_maximized=False, *args, **kwargs):
        super(LensViewQt5, self).__init__(name=name, width=width, height=height, *args, **kwargs)

        # prepare Qt dbus mainloop
        DBusQtMainLoop(set_as_default=True)
        self._app = QApplication(*args, **kwargs)

        self.app_loaded = False
        self.view = None
        self.page = None

        self._manager = ThreadManagerQt5(app=self._app)

        self.start_maximized = start_maximized
        self.inspector = inspector
        self._build_app()

    def _build_app(self):
        if self.inspector:
            os.environ.update({'QTWEBENGINE_REMOTE_DEBUGGING': '127.0.0.1:23654'})
        # build webkit container
        self.view = lv = LensQWebEngineView()
        self.page = LensQWebEnginePage()
        self.window = LensMainWindow(title=self._app_name, width=self.width, height=self.height)

        self.page.setView(self.view)

        # connect to Qt signals
        lv.loadFinished.connect(self._loaded_cb)
        lv.titleChanged.connect(self._title_changed_cb)
        self._app.lastWindowClosed.connect(self._last_window_closed_cb)

        self.channel = QWebChannel(self.page)

        self._cnam = CustomNetworkAccessManager(page=self.page)
        self.page.set_network_access_manager(self._cnam)

        # connect to Lens signals
        self.on('__close_app', self._close_cb)

        # center on screen
        frame_geometry = self.window.frameGeometry()
        active_screen = self._app.desktop().screenNumber(self._app.desktop().cursor().pos())

        if self.start_maximized:
            self.window.showMaximized()
        _center = self.app.desktop().screenGeometry(active_screen).center()
        frame_geometry.moveCenter(_center)
        self.window.move(frame_geometry.topLeft())

    def _close_cb(self):
        self.emit('app.close')
        self.app.exit()

    def _last_window_closed_cb(self, *args):
        self.emit('__close_app', *args)

    def _loaded_cb(self, success):
        # show window once some page has loaded
        self._lensview.show()
        if self.start_maximized:
            self.toggle_window_maximize()

        if not self.app_loaded:
            self.app_loaded = True
            self.emit('app.loaded')

    def _title_changed_cb(self, title):
        _in = str(title)

        # check for "_BR::" leader to determine we're crossing
        # the python/JS bridge
        if _in is None or not _in.startswith('_BR::'):
            return

        try:
            _in = json.loads(_in[5:])

            _name = _in.setdefault('name', '')
            _args = _in.setdefault('args', [])

        except:
            return

        # emit our python/js bridge signal
        self.emit(_name, *_args)

    def _run(self):
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        self.app.exec_()

    def emit_js(self, name, *args):
        self._frame.evaluateJavaScript(str(self._javascript % json.dumps([name] + list(args))))

    def load_uri(self, uri):
        uri_base = os.path.dirname(uri) + '/'
        self.set_uri_app_base(uri_base)
        path = uri_base + 'app.html'

        stream = QFile(path)
        if stream.open(QFile.ReadOnly):
            data = str(stream.readAll(), 'utf-8')
            self._lensview.setHtml(data, QUrl('file://' + uri_base))

    def set_inspector(self, state):
        self._lensview.set_inspector(state)

    def set_size(self, width, height):
        self._lensview.setMinimumSize(width, height)
        self._lensview.resize(width, height)

    def set_title(self, title):
        self._lensview.setWindowTitle(str(title))

    def set_uri_app_base(self, uri):
        self._cnam.uri_app_base = uri

    def set_uri_lens_base(self, uri):
        self._cnam.uri_lens_base = uri

    def toggle_window_maximize(self):
        if self._lensview.windowState() & Qt.WindowMaximized:
            self._lensview.setWindowState(self._lensview.windowState() ^ Qt.WindowMaximized)
            self.emit_js('window-unmaximized')
        else:
            self._lensview.setWindowState(self._lensview.windowState() | Qt.WindowMaximized)
            self.emit_js('window-maximized')

    def toggle_window_fullscreen(self):
        if self._lensview.windowState() & Qt.WindowFullScreen:
            self._lensview.setWindowState(self._lensview.windowState() ^ Qt.WindowFullScreen)
            self.emit_js('window-unfullscreen')
        else:
            self._lensview.setWindowState(self._lensview.windowState() | Qt.WindowFullScreen)
            self.emit_js('window-fullscreen')
