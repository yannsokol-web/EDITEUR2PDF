"""
Éditeur PDF – PySide6

Copyright (c) 2026 Yann Sokol. Tous droits réservés.

Ce logiciel est la propriété exclusive de Yann Sokol.
Toute reproduction, distribution, modification ou utilisation non autorisée
de ce logiciel, en tout ou en partie, est strictement interdite sans
l'autorisation écrite préalable de l'auteur.
"""
VERSION = "1.7"
UPDATE_URL = "https://api.github.com/repos/yannsokol-web/EDITEUR2PDF/releases/latest"

import sys, os, uuid, subprocess, threading, tempfile, json, hashlib, logging, re  # subprocess: used by _on_update_downloaded for auto-update
from collections import OrderedDict
from dataclasses import dataclass
from urllib.request import urlopen, Request
import fitz
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s'
)
_logger = logging.getLogger('EditeurPDF')
fitz.TOOLS.mupdf_display_errors(True)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QScrollArea, QFrame,
    QSlider, QComboBox, QSpinBox, QCheckBox, QColorDialog,
    QDialog, QDialogButtonBox, QMessageBox, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QGraphicsTextItem,
    QGraphicsItem, QStackedWidget, QLayout, QSplitter,
    QProgressBar
)
from PySide6.QtCore import (
    Qt, QSize, QRectF, QMimeData, Signal, QTimer,
    QPoint, QRect, QEvent, QThread
)
from PySide6.QtGui import (
    QPixmap, QImage, QIcon, QColor, QPainter, QPen, QBrush,
    QFont, QDrag, QTextCursor, QTransform
)

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(_APP_DIR, 'logoediteurpdf.ico')

C = {
    'bg': '#f0f2f5', 'surface': '#ffffff', 'border': '#d9d9d9',
    'primary': '#1677ff', 'primary_hover': '#0958d9',
    'danger': '#ff4d4f', 'danger_hover': '#cf1322',
    'text': '#1f1f1f', 'text2': '#595959',
    'success': '#52c41a', 'reader_bg': '#3a3a3a',
}

def get_system_font():
    if sys.platform == 'win32':
        return QFont("Segoe UI", 10)
    elif sys.platform == 'darwin':
        return QFont("SF Pro Text", 10)
    else:
        return QFont("Noto Sans", 10)

# ── Cache PDF global ───────────────────────────────────────
MAX_CACHED_DOCS = 32
_pdf_doc_cache = OrderedDict()  # sha256(pdf_bytes) -> fitz.Document
_pinned_doc_keys = set()        # hashes encore references par une page : jamais evinces

def close_doc(doc):
    """Close a fitz.Document, tolerating an already-closed one."""
    try:
        doc.close()
    except Exception:
        _logger.debug("close() a echoue sur un document PDF", exc_info=True)

def get_cached_doc(source):
    """Return a cached fitz.Document. Accepts PdfSource or raw bytes."""
    if isinstance(source, PdfSource):
        key = source.hash
        raw = source.pdf_bytes
    else:
        key = hashlib.sha256(source).hexdigest()
        raw = source
    doc = _pdf_doc_cache.get(key)
    if doc is not None:
        _pdf_doc_cache.move_to_end(key)  # LRU: marquer comme récemment utilisé
        return doc
    doc = open_pdf(raw)
    _pdf_doc_cache[key] = doc
    _evict_unpinned()
    return doc

def _evict_unpinned():
    """Drop least-recently-used documents, never one a loaded page still needs.

    Closing a pinned document would force a reparse mid-scroll and could pull the
    rug from under a render already in flight.
    """
    for key in list(_pdf_doc_cache):
        if len(_pdf_doc_cache) <= MAX_CACHED_DOCS:
            return
        if key not in _pinned_doc_keys:
            close_doc(_pdf_doc_cache.pop(key))


# ── Données ────────────────────────────────────────────────
class PdfSource:
    """Stores PDF bytes once and pre-computes the SHA-256 hash."""
    def __init__(self, pdf_bytes):
        self.pdf_bytes = pdf_bytes
        self.hash = hashlib.sha256(pdf_bytes).hexdigest()

class PageData:
    def __init__(self, pdf_source, page_index, label, thumbnail, page_rect=None):
        self.id = str(uuid.uuid4())
        self.source = pdf_source
        self.page_index = page_index
        self.label = label
        # fitz.Rect : laisse le lecteur composer la scene sans rouvrir le document
        self.page_rect = page_rect
        app = QApplication.instance()
        dpr = app.primaryScreen().devicePixelRatio() if app and app.primaryScreen() else 1.0
        # Seule la vignette 200x270 est conservee : le rendu pleine page (~2 Mo par
        # page) ne sert qu'a la produire et est relache en sortant d'ici.
        self.thumb_scaled = thumbnail.scaled(int(200 * dpr), int(270 * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation) if thumbnail and not thumbnail.isNull() else thumbnail
        if self.thumb_scaled and not self.thumb_scaled.isNull():
            self.thumb_scaled.setDevicePixelRatio(dpr)
        self.hires_scale = 0

    @property
    def pdf_bytes(self):
        return self.source.pdf_bytes

    def scene_size(self, scale):
        """Pixel size of this page at `scale`, matching get_pixmap's rounding.

        int(rect.width * scale) is off by one on A4: MuPDF rounds the transformed
        rect (floor/ceil), it does not truncate.
        """
        if self.page_rect is None:
            self.page_rect = get_cached_doc(self.source)[self.page_index].rect
        ir = (self.page_rect * fitz.Matrix(scale, scale)).irect
        return ir.width, ir.height

class TextBoxData:
    def __init__(self, page_id, x_pct, y_pct):
        self.id = str(uuid.uuid4())
        self.page_id = page_id
        self.x_pct = x_pct
        self.y_pct = y_pct
        self.width_pct = 15.0
        self.height_pct = 5.0
        self.text = ''
        self.font_family = 'Arial'
        self.font_size = 25
        self.font_color = '#000000'
        self.bold = False
        self.italic = False
        self.border_color = 'transparent'
        self.border_width = 0
        self.bg_color = 'transparent'

def open_pdf(data):
    """Open a PDF, repairing it if the first attempt fails."""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        _ = len(doc)
    except Exception as first_err:
        broken = repair_doc = None
        try:
            broken = fitz.open(stream=data, filetype="pdf")
            repair_doc = fitz.open()  # Empty document
            repair_doc.insert_pdf(broken)
            clean_data = repair_doc.tobytes(garbage=4, clean=True, deflate=True)
            doc = fitz.open(stream=clean_data, filetype="pdf")
            _ = len(doc)
        except Exception:
            raise ValueError(f"PDF illisible ou corrompu : {first_err}") from first_err
        finally:
            for d in (broken, repair_doc):
                if d is not None:
                    close_doc(d)
    if doc.needs_pass:
        close_doc(doc)
        raise ValueError("PDF protege par mot de passe")
    return doc

def pixmap_samples(pix):
    """Zero-copy view on a fitz.Pixmap buffer, falling back to the bytes copy."""
    return pix.samples_mv if hasattr(pix, 'samples_mv') else pix.samples

def render_page_pixmap(source, page_index, scale=2.0):
    """Render a PDF page to QPixmap at given scale (raw pixels, no DPR)."""
    doc = get_cached_doc(source)
    pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    # QImage borrows the buffer and QPixmap.fromImage copies it: no extra .copy().
    img = QImage(pixmap_samples(pix), pix.width, pix.height, pix.stride, QImage.Format_RGB888)
    pm = QPixmap.fromImage(img)
    del img  # must not outlive `pix`
    return pm

# ── FlowLayout ─────────────────────────────────────────────
class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=20):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
    def addItem(self, item):
        self._items.append(item)
        self.invalidate()
    def count(self): return len(self._items)
    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None
    def takeAt(self, index):
        if not 0 <= index < len(self._items):
            return None
        item = self._items.pop(index)
        self.invalidate()
        return item
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect)
    def sizeHint(self):
        # Must reflect the flow height: returning minimumSize() here made
        # QWidget.adjustSize() collapse the grid and wipe the scroll position.
        w = self.minimumSize().width()
        return QSize(w, self.heightForWidth(self.geometry().width() or w))
    def minimumSize(self):
        s = QSize(0, 0)
        for item in self._items:
            s = s.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left()+m.right(), m.top()+m.bottom())
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)
    def _do_layout(self, rect, test_only=False):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, rh = eff.x(), eff.y(), 0
        for item in self._items:
            sz = item.sizeHint()
            nx = x + sz.width() + self._spacing
            if nx - self._spacing > eff.right() and rh > 0:
                x, y = eff.x(), y + rh + self._spacing
                nx = x + sz.width() + self._spacing
                rh = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), sz))
            x = nx
            rh = max(rh, sz.height())
        return y + rh - rect.y() + m.bottom()

# ── Toast ──────────────────────────────────────────────────
class ToastManager:
    MARGIN = 24
    GAP = 8

    def __init__(self, parent):
        self.parent = parent
        self.toasts = []

    def show(self, msg, kind='info', sticky=False, on_click=None, tooltip=None):
        """Stack a toast bottom-right. A sticky one stays until removed."""
        colors = {'info': C['primary'], 'success': C['success'], 'error': C['danger']}
        weight = 'font-weight:bold;' if sticky else ''
        t = QLabel(msg, self.parent)
        t.setStyleSheet(f"background:{colors.get(kind, C['primary'])};color:#fff;padding:10px 20px;border-radius:8px;font-size:13px;{weight}")
        t.setWordWrap(True)
        t.setMaximumWidth(360)
        t.adjustSize()
        if tooltip:
            t.setToolTip(tooltip)
        if on_click is not None:
            t.setCursor(Qt.PointingHandCursor)
            t.mousePressEvent = lambda e, lbl=t: on_click(lbl)
        self.toasts.append(t)
        self.reposition()
        t.show(); t.raise_()
        if not sticky:
            QTimer.singleShot(3500, lambda: self.remove(t))
        return t

    def remove(self, t):
        if t in self.toasts:
            self.toasts.remove(t)
        try:
            t.deleteLater()
        except RuntimeError:
            pass  # parent window already destroyed
        self.reposition()

    def reposition(self):
        """Re-stack live toasts: keeps them anchored after a resize or a removal."""
        p = self.parent
        y = p.height() - self.MARGIN
        alive = []
        for t in self.toasts:
            try:
                y -= t.height()
                t.move(p.width() - t.width() - self.MARGIN, y)
                y -= self.GAP
                alive.append(t)
            except RuntimeError:
                pass
        self.toasts = alive

# ── PageCard ───────────────────────────────────────────────
class PageCard(QFrame):
    clicked = Signal(str)
    delete_clicked = Signal(str)

    def __init__(self, page_data, index, textboxes=None, parent=None):
        super().__init__(parent)
        self.page_data = page_data
        self.index = index
        self._selected = False
        self._drop_side = None  # 'left' or 'right'
        self._drag_pos = None
        self.setFixedSize(210, 320)
        self.setCursor(Qt.OpenHandCursor)
        self.setAcceptDrops(True)

        # Thumbnail
        self.thumb = QLabel(self)
        self.thumb.setGeometry(5, 5, 200, 270)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background:#f5f5f5;border-radius:4px;")
        self._set_thumbnail()

        # Text box indicator (small "T" badge)
        has_tb = bool(textboxes) and any(t.page_id == page_data.id for t in textboxes)
        self.tb_badge = QLabel("T", self)
        self.tb_badge.setStyleSheet(f"background:{C['primary']};color:#fff;font-size:10px;font-weight:bold;padding:1px 5px;border-radius:8px;")
        self.tb_badge.adjustSize()
        self.tb_badge.move(170, 248)
        self.tb_badge.setVisible(has_tb)

        # Page number
        self.num_lbl = QLabel(f"p.{index+1}", self)
        self.num_lbl.setStyleSheet("background:rgba(0,0,0,140);color:#fff;font-size:11px;padding:2px 7px;border-radius:10px;")
        self.num_lbl.adjustSize()
        self.num_lbl.move(10, 248)

        # Label
        self.label = QLabel(self)
        self.label.setGeometry(5, 280, 200, 35)
        self.label.setStyleSheet(f"font-size:12px;color:{C['text2']};border-top:1px solid {C['border']};padding:8px 4px;")
        fm = self.label.fontMetrics()
        self.label.setText(fm.elidedText(page_data.label, Qt.ElideRight, 190))
        self.label.setToolTip(page_data.label)

        # Drop indicators (left/right bars)
        self.drop_left = QFrame(self)
        self.drop_left.setGeometry(0, 0, 4, 320)
        self.drop_left.setStyleSheet(f"background:{C['primary']};border-radius:2px;")
        self.drop_left.hide()
        self.drop_right = QFrame(self)
        self.drop_right.setGeometry(206, 0, 4, 320)
        self.drop_right.setStyleSheet(f"background:{C['primary']};border-radius:2px;")
        self.drop_right.hide()

        # Delete button
        self.del_btn = QPushButton("×", self)
        self.del_btn.setGeometry(178, 8, 26, 26)
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.setStyleSheet(f"QPushButton{{background:{C['danger']};color:#fff;border:none;border-radius:13px;font-size:16px;font-weight:bold;}}QPushButton:hover{{background:{C['danger_hover']};}}")
        self.del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.page_data.id))
        self.del_btn.hide()

        self._style()

    def _set_thumbnail(self):
        pm = self.page_data.thumb_scaled
        if pm and not pm.isNull():
            self.thumb.setPixmap(pm)

    def _style(self):
        border = f"2px solid {C['primary']}" if self._selected else f"1px solid {C['border']}"
        self.setStyleSheet(f"PageCard{{background:{C['surface']};border-radius:8px;border:{border};}}")

    @property
    def selected(self): return self._selected
    @selected.setter
    def selected(self, v):
        v = bool(v)
        if v == self._selected:
            return   # skip a pointless QSS re-parse on every rebuild
        self._selected = v
        self._style()

    def set_index(self, i):
        # Must stay in sync on every rebuild: dropEvent derives its target from it.
        if i == self.index:
            return
        self.index = i
        self.num_lbl.setText(f"p.{i+1}")
        self.num_lbl.adjustSize()   # sized once for "p.1"; "p.10" would be clipped

    def set_has_textbox(self, v):
        self.tb_badge.setVisible(bool(v))

    def enterEvent(self, e):
        self.del_btn.show()
        super().enterEvent(e)
    def leaveEvent(self, e):
        self.del_btn.hide()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and self._drag_pos is not None:
            if (e.position().toPoint() - self._drag_pos).manhattanLength() > 15:
                # Gather all selected IDs including this one
                win = self.window()
                ids = list(getattr(win, 'selected_ids', set()))
                if self.page_data.id not in ids:
                    ids = [self.page_data.id]
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData('application/x-page-ids', ','.join(ids).encode())
                drag.setMimeData(mime)
                # Thumbnail
                pm = self.page_data.thumb_scaled.scaled(80, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pm.setDevicePixelRatio(1.0)
                if len(ids) > 1:
                    # Draw badge with count
                    pm2 = QPixmap(pm.size())
                    pm2.fill(Qt.transparent)
                    painter = QPainter(pm2)
                    painter.drawPixmap(0, 0, pm)
                    painter.setBrush(QColor(C['primary']))
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(pm.width()-20, 0, 20, 20)
                    painter.setPen(QColor('#fff'))
                    painter.setFont(QFont(get_system_font().family(), 9, QFont.Bold))
                    painter.drawText(QRect(pm.width()-20, 0, 20, 20), Qt.AlignCenter, str(len(ids)))
                    painter.end()
                    pm = pm2
                drag.setPixmap(pm)
                drag.setHotSpot(QPoint(40, 55))
                drag.exec(Qt.MoveAction)
                self._drag_pos = None

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._drag_pos is not None and (e.position().toPoint() - self._drag_pos).manhattanLength() < 15:
                self.clicked.emit(self.page_data.id)
            self._drag_pos = None
        super().mouseReleaseEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat('application/x-page-ids') or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        """Show left/right indicator based on cursor position."""
        if e.mimeData().hasFormat('application/x-page-ids') or e.mimeData().hasUrls():
            mid = self.width() / 2
            if e.position().x() < mid:
                self.drop_left.show(); self.drop_right.hide()
                self._drop_side = 'left'
            else:
                self.drop_left.hide(); self.drop_right.show()
                self._drop_side = 'right'
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.drop_left.hide(); self.drop_right.hide()
        self._drop_side = None

    def dropEvent(self, e):
        self.drop_left.hide(); self.drop_right.hide()
        side = self._drop_side
        self._drop_side = None
        target_idx = self.index
        if side == 'right':
            target_idx += 1

        if e.mimeData().hasFormat('application/x-page-ids'):
            src_ids = bytes(e.mimeData().data('application/x-page-ids')).decode().split(',')
            w = self.window()
            if hasattr(w, 'move_pages_to'):
                w.move_pages_to(src_ids, target_idx)
            e.acceptProposedAction()
        elif e.mimeData().hasUrls():
            files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith('.pdf')]
            if files:
                w = self.window()
                if hasattr(w, 'insert_files_at'):
                    w.insert_files_at(files, target_idx)
            e.acceptProposedAction()

# ── TextBoxItem (QGraphicsScene) ───────────────────────────
class TextBoxItem(QGraphicsRectItem):
    def __init__(self, tb, pw, ph, parent=None, read_only=False):
        super().__init__(parent)
        self.tb = tb
        self.pw, self.ph = pw, ph
        self.read_only = read_only
        self._updating = True  # block itemChange writeback during setup
        flags = QGraphicsItem.ItemIsSelectable
        if not read_only:
            flags |= QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges
        self.setFlags(flags)
        self.setCursor(Qt.ArrowCursor if read_only else Qt.SizeAllCursor)
        self.setAcceptHoverEvents(not read_only)
        self.text_item = QGraphicsTextItem(self)
        self.text_item.document().setDocumentMargin(0)
        if not read_only:
            # read_only really means it: no text editing and no resize handle,
            # so the preview panel can no longer silently mutate a text box.
            self.text_item.setTextInteractionFlags(Qt.TextEditorInteraction)
            self.text_item.document().contentsChanged.connect(self._sync_text)
        self._resizing = False
        self._res_start = None
        self._res_rect = None
        self.refresh()
        self._updating = False

    PAD = 8  # padding around text for grab zone

    def refresh(self, reposition=True):
        tb = self.tb
        w = tb.width_pct/100*self.pw
        if reposition:
            x, y = tb.x_pct/100*self.pw, tb.y_pct/100*self.ph
            self.setPos(x, y)
        pen = QPen(Qt.NoPen)
        if tb.border_width > 0 and tb.border_color != 'transparent':
            pen = QPen(QColor(tb.border_color), tb.border_width)
        self.setPen(pen)
        brush = QBrush(Qt.NoBrush)
        if tb.bg_color != 'transparent':
            brush = QBrush(QColor(tb.bg_color))
        self.setBrush(brush)
        font = QFont(tb.font_family, tb.font_size)
        font.setBold(tb.bold); font.setItalic(tb.italic)
        self.text_item.setFont(font)
        self.text_item.setDefaultTextColor(QColor(tb.font_color))
        self.text_item.setTextWidth(w - self.PAD * 2)
        self.text_item.setPos(self.PAD, self.PAD)
        if self.text_item.toPlainText() != tb.text:
            self.text_item.blockSignals(True)
            self.text_item.setPlainText(tb.text)
            self.text_item.blockSignals(False)
        # Auto-fit height to text content + padding
        text_h = self.text_item.boundingRect().height() + self.PAD * 2
        h = max(tb.height_pct/100*self.ph, text_h)
        self.setRect(0, 0, w, h)
        if not self.read_only:
            tb.height_pct = h/self.ph*100

    def _sync_text(self):
        self.tb.text = self.text_item.toPlainText()
        # Auto-grow height if text overflows
        text_h = self.text_item.boundingRect().height() + self.PAD * 2
        r = self.rect()
        if text_h > r.height():
            self.setRect(0, 0, r.width(), text_h)
            self.tb.height_pct = text_h/self.ph*100

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and not self._updating:
            yo = self.data(0) or 0  # page y offset in scene
            xo = self.data(1) or 0  # page x offset (centering)
            self.tb.x_pct = (value.x() - xo)/self.pw*100
            self.tb.y_pct = (value.y() - yo)/self.ph*100
        return super().itemChange(change, value)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        r = self.rect()
        if self.isSelected():
            painter.setPen(QPen(QColor(C['primary']), 2, Qt.DashLine))
            painter.drawRect(r)
            painter.fillRect(QRectF(r.right()-8, r.bottom()-8, 8, 8), QColor(C['primary']))
        else:
            painter.setPen(QPen(QColor(22,119,255,80), 1, Qt.DashLine))
            painter.drawRect(r)

    def hoverMoveEvent(self, e):
        r = self.rect()
        self.setCursor(Qt.SizeFDiagCursor if QRectF(r.right()-10,r.bottom()-10,10,10).contains(e.pos()) else Qt.SizeAllCursor)

    def mousePressEvent(self, e):
        r = self.rect()
        if not self.read_only and QRectF(r.right()-10,r.bottom()-10,10,10).contains(e.pos()) and e.button()==Qt.LeftButton:
            self._resizing=True; self._res_start=e.scenePos(); self._res_rect=QRectF(self.rect())
            self.setFlag(QGraphicsItem.ItemIsMovable, False)
            e.accept(); return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._resizing:
            d=e.scenePos()-self._res_start
            w,h=max(30,self._res_rect.width()+d.x()),max(20,self._res_rect.height()+d.y())
            self.setRect(0,0,w,h); self.text_item.setTextWidth(w - self.PAD * 2)
            self.tb.width_pct=w/self.pw*100; self.tb.height_pct=h/self.ph*100
            e.accept(); return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._resizing:
            self._resizing=False
            self.setFlag(QGraphicsItem.ItemIsMovable, True)
            e.accept(); return
        super().mouseReleaseEvent(e)


# ── ReaderView (all pages, scrollable) ─────────────────────
@dataclass
class _PageItem:
    """One page laid out in the reader scene.

    Geometry (`y`, `x`, `pw`, `ph`) is authoritative and computed at BASE_SCALE:
    everything else — hit testing, navigation, text-box placement — reads it from
    here and never from the pixmap, which may be absent or at another scale.
    """
    pix: object      # QGraphicsPixmapItem – empty until the page is rasterised
    paper: object    # QGraphicsRectItem – white page background
    y: float         # top of the page, scene coordinates
    pw: float        # page width in scene units
    ph: float        # page height in scene units
    page: object     # PageData
    lbl: object      # QGraphicsSimpleTextItem
    tbs: list        # TextBoxItem belonging to this page
    x: float = 0.0   # horizontal centring offset


class ReaderView(QGraphicsView):
    tb_selected = Signal(object)
    tb_deselected = Signal()
    page_changed = Signal(int)

    PAGE_GAP = 40  # pixels between pages

    BASE_SCALE = 2.0          # 144 DPI – scene coordinate unit
    MAX_SCALE = 6.0           # ceiling for hi-res upgrades
    MAX_RENDERED_PAGES = 8    # hard cap on simultaneously rasterised pages

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setStyleSheet(f"background:{C['reader_bg']};border:none;")
        self._pages = []
        self._textboxes = []
        self._zoom = 1.0
        self._tb_items = []
        self._placing = False
        self._copied = None
        self._page_items = []
        self._max_page_width = 0
        self._start_id = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh_visible_pages)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._emit_current_page)
        # Hand-drag panning by default
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setCursor(Qt.OpenHandCursor)

    def set_data(self, pages, textboxes, start_id=None):
        self._pages = pages
        self._textboxes = textboxes
        self._copied = None
        self._zoom = 1.0
        self._start_id = start_id
        self._refresh_timer.stop()
        for p in pages:
            p.hires_scale = 0
        self._render_all()

    def _render_all(self):
        """Lay every page out at its BASE_SCALE size; pixmaps come on demand.

        Rendering the whole document up front froze the UI and pinned ~8 MB per A4
        page in memory, so pages start as an empty pixmap over a white rectangle
        and _refresh_visible_pages fills in only what is on screen.
        """
        self._scene.clear()
        self._tb_items.clear()
        self._page_items.clear()
        if not self._pages:
            self._max_page_width = 0
            self._scene.setSceneRect(0, 0, 0, 0)
            return

        tb_map = {}
        for tb in self._textboxes:
            tb_map.setdefault(tb.page_id, []).append(tb)

        y_offset = self.PAGE_GAP
        max_width = 0
        total = len(self._pages)
        paper_brush = QBrush(QColor('#ffffff'))
        no_pen = QPen(Qt.NoPen)

        for idx, p in enumerate(self._pages):
            pw, ph = p.scene_size(self.BASE_SCALE)
            max_width = max(max_width, pw)

            paper = self._scene.addRect(0, 0, pw, ph, no_pen, paper_brush)
            paper.setPos(0, y_offset)
            paper.setZValue(-1)

            pix_item = self._scene.addPixmap(QPixmap())
            # QGraphicsPixmapItem overrides the view's SmoothPixmapTransform hint
            # with its own transformation mode, which defaults to Fast.
            pix_item.setTransformationMode(Qt.SmoothTransformation)
            pix_item.setPos(0, y_offset)

            tb_items_for_page = []
            for tb in tb_map.get(p.id, []):
                it = TextBoxItem(tb, pw, ph)
                it._updating = True
                it.setData(0, y_offset)
                it.setPos(tb.x_pct / 100 * pw, y_offset + tb.y_pct / 100 * ph)
                it._updating = False
                self._scene.addItem(it)
                self._tb_items.append(it)
                tb_items_for_page.append(it)

            lbl = self._scene.addSimpleText(f"Page {idx+1} / {total} — {p.label}")
            lbl.setBrush(QColor('#aaa'))
            lbl.setFont(get_system_font())
            lbl.setPos(4, y_offset - 20)

            self._page_items.append(
                _PageItem(pix_item, paper, y_offset, pw, ph, p, lbl, tb_items_for_page))
            y_offset += ph + self.PAGE_GAP

        # Center pages horizontally
        for pi in self._page_items:
            pi.x = (max_width - pi.pw) / 2
            pi.paper.setPos(pi.x, pi.y)
            pi.pix.setPos(pi.x, pi.y)
            pi.lbl.setPos(pi.x + 4, pi.y - 20)
            for it in pi.tbs:
                it._updating = True
                it.setData(1, pi.x)  # store x offset for itemChange
                it.setPos(it.pos().x() + pi.x, it.pos().y())
                it._updating = False

        self._max_page_width = max_width
        self._scene.setSceneRect(0, 0, max_width, y_offset)
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        # Defer fit-to-width to next event loop so viewport has correct size
        QTimer.singleShot(0, self._fit_zoom)

    def _screen_dpr(self):
        """Device pixel ratio for HiDPI support."""
        screen = self.screen()
        return screen.devicePixelRatio() if screen else 1.0

    def _page_index(self, page_id):
        for i, pi in enumerate(self._page_items):
            if pi.page.id == page_id:
                return i
        return 0

    def _fit_zoom(self):
        """Fit page width to viewport."""
        vp_w = self.viewport().width() - 40
        mw = self._max_page_width
        if mw > 0 and vp_w > 0:
            self._zoom = min(1.0, vp_w / mw)
        self.resetTransform()
        self.scale(self._zoom, self._zoom)
        # Scroll to the requested start page
        if self._start_id is not None:
            start = self._page_index(self._start_id)
            self._start_id = None
            if start:
                self.go(start)
        self._emit_current_page()
        # Render what is on screen right away: waiting for the timer would show
        # blank pages for ~150 ms, one page per tick.
        self._refresh_visible_pages(render_all_visible=True)
        # Sync slider in main window
        w = self.window()
        if hasattr(w, '_sync_zoom_display'):
            w._sync_zoom_display()

    def fit_to_width(self):
        """Re-apply the initial fit-to-width zoom."""
        self._start_id = None
        self._fit_zoom()

    def _schedule_refresh(self):
        self._refresh_timer.start(100)

    def _release_page(self, pi):
        """Drop a page's pixels. Only clearing the item actually frees them."""
        if pi.page.hires_scale:
            pi.pix.setPixmap(QPixmap())
            pi.pix.setTransform(QTransform())
            pi.page.hires_scale = 0

    def _render_into(self, pi, scale):
        pm = render_page_pixmap(pi.page.source, pi.page.page_index, scale)
        # Scene geometry wins: a devicePixelRatio is a single scalar and cannot
        # absorb a different rounding on each axis, an item transform can.
        pi.pix.setTransform(QTransform.fromScale(pi.pw / pm.width(), pi.ph / pm.height()))
        pi.pix.setPixmap(pm)
        pi.page.hires_scale = scale

    def _refresh_visible_pages(self, render_all_visible=False):
        """Match on-screen pages to the current zoom/DPR, free the distant ones."""
        if not self._page_items:
            return
        dpr = self._screen_dpr()
        effective_scale = max(self.BASE_SCALE, self._zoom * self.BASE_SCALE * dpr)
        effective_scale = min(effective_scale, self.MAX_SCALE)

        vp = self.mapToScene(self.viewport().rect()).boundingRect()
        margin = vp.height()
        margin_free = margin * 2

        visible, keep = [], []
        for pi in self._page_items:
            if not (pi.y + pi.ph < vp.top() - margin or pi.y > vp.bottom() + margin):
                visible.append(pi)
            elif not (pi.y + pi.ph < vp.top() - margin_free or pi.y > vp.bottom() + margin_free):
                keep.append(pi)
            else:
                self._release_page(pi)

        # Hard cap: the keep zone is measured in scene units, so zooming out would
        # otherwise retain arbitrarily many pages. Furthest from the centre goes first.
        center = vp.center().y()
        keep.sort(key=lambda pi: abs(pi.y + pi.ph / 2 - center))
        for pi in keep[max(0, self.MAX_RENDERED_PAGES - len(visible)):]:
            self._release_page(pi)

        upgraded = False
        needs_more = False
        for pi in visible:
            scale = pi.page.hires_scale
            # Re-render when too coarse, but also when far too fine: after zooming
            # in then out a page would otherwise stay pinned at MAX_SCALE.
            if scale >= effective_scale and scale <= effective_scale * 2:
                continue
            if upgraded and not render_all_visible:
                needs_more = True  # one per tick, re-schedule for the rest
                continue
            self._render_into(pi, effective_scale)
            upgraded = True

        if needs_more:
            self._refresh_timer.start(10)

    def _emit_current_page(self):
        """Determine which page is most visible and emit signal."""
        self.page_changed.emit(self.cur + 1)

    @property
    def cur(self):
        """Current page index (0-based) based on scroll position."""
        vp = self.mapToScene(self.viewport().rect()).boundingRect()
        center_y = vp.center().y()
        best = 0
        best_dist = float('inf')
        for i, pi in enumerate(self._page_items):
            d = abs(pi.y + pi.ph / 2 - center_y)
            if d < best_dist:
                best_dist = d; best = i
        return best

    def current_page_id(self):
        if not self._page_items:
            return None
        return self._page_items[self.cur].page.id

    @property
    def total(self): return len(self._pages)
    @property
    def zoom_val(self): return self._zoom

    def set_zoom(self, z):
        self._zoom = max(0.25, min(5.0, z))
        self.resetTransform()
        self.scale(self._zoom, self._zoom)
        self._schedule_refresh()   # otherwise the page stays blurry until you scroll

    def go(self, idx):
        if 0 <= idx < len(self._page_items):
            self.centerOn(0, self._page_items[idx].y)
            self._emit_current_page()
            # Jumping is discrete: render now instead of leaving the page blank
            # for the 100 ms scroll debounce.
            self._refresh_visible_pages(render_all_visible=True)

    def go_to_id(self, page_id):
        for i, pi in enumerate(self._page_items):
            if pi.page.id == page_id:
                self.go(i)
                return

    def next_page(self):
        c = self.cur
        if c < len(self._pages) - 1:
            self.go(c + 1)

    def prev_page(self):
        c = self.cur
        if c > 0:
            self.go(c - 1)

    def set_placing(self, v):
        self._placing = v
        if v:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.OpenHandCursor)

    def _find_page_at(self, scene_pos):
        """Find which page a scene position belongs to. Returns (_PageItem, local_x, local_y) or None."""
        for pi in self._page_items:
            if pi.y <= scene_pos.y() <= pi.y + pi.ph and pi.x <= scene_pos.x() <= pi.x + pi.pw:
                return pi, scene_pos.x() - pi.x, scene_pos.y() - pi.y
        return None

    def mousePressEvent(self, e):
        if self._placing and e.button() == Qt.LeftButton:
            sp = self.mapToScene(e.position().toPoint())
            hit = self._find_page_at(sp)
            if hit:
                pi, lx, ly = hit
                pw, ph, x_off, yo = pi.pw, pi.ph, pi.x, pi.y
                tb = TextBoxData(pi.page.id, lx/pw*100, ly/ph*100)
                self._textboxes.append(tb)
                it = TextBoxItem(tb, pw, ph)
                # Position in scene coords
                it._updating = True
                it.setData(0, yo)
                it.setData(1, x_off)
                sx = x_off + lx - tb.width_pct/100*pw/2
                sy = yo + ly - tb.height_pct/100*ph/2
                it.setPos(sx, sy)
                it._updating = False
                # Store final position as percentages
                tb.x_pct = (sx - x_off)/pw*100
                tb.y_pct = (sy - yo)/ph*100
                self._scene.addItem(it)
                self._tb_items.append(it)
                pi.tbs.append(it)
                it.setSelected(True)
                it.text_item.setFocus()
                tc = it.text_item.textCursor()
                tc.movePosition(QTextCursor.MoveOperation.End)
                it.text_item.setTextCursor(tc)
                self._placing = False
                self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                self.setCursor(Qt.OpenHandCursor)
                self.tb_selected.emit(tb)
                w = self.window()
                if hasattr(w, '_on_tb_placed'):
                    w._on_tb_placed()
                return
        super().mousePressEvent(e)
        sel = [i for i in self._scene.selectedItems() if isinstance(i, TextBoxItem)]
        if sel:
            self.tb_selected.emit(sel[0].tb)
        else:
            self.tb_deselected.emit()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            f = 1.15 if e.angleDelta().y() > 0 else 1/1.15
            self._zoom = max(0.25, min(5.0, self._zoom * f))
            self.resetTransform()
            self.scale(self._zoom, self._zoom)
            w = self.window()
            if hasattr(w, '_sync_zoom_display'):
                w._sync_zoom_display()
            self._schedule_refresh()
            e.accept()
        else:
            super().wheelEvent(e)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._scroll_timer.start(80)
        self._schedule_refresh()

    def selected_tb(self):
        for it in self._scene.selectedItems():
            if isinstance(it, TextBoxItem): return it
        return None

    def delete_selected(self):
        it = self.selected_tb()
        if it:
            if self._copied and self._copied.page_id == it.tb.page_id:
                self._copied = None
            if it.tb in self._textboxes: self._textboxes.remove(it.tb)
            self._scene.removeItem(it)
            if it in self._tb_items: self._tb_items.remove(it)
            for pi in self._page_items:
                if it in pi.tbs:
                    pi.tbs.remove(it)
                    break
            self.tb_deselected.emit()

    def copy_selected(self):
        it = self.selected_tb()
        if it: self._copied = it.tb

    def paste_tb(self):
        if not self._copied or not self._page_items: return
        src = self._copied
        # Paste on the currently visible page
        pi = self._page_items[self.cur]
        tb = TextBoxData(pi.page.id, src.x_pct+2, src.y_pct+2)
        for attr in ('width_pct','height_pct','text','font_family','font_size','font_color','bold','italic','border_color','border_width','bg_color'):
            setattr(tb, attr, getattr(src, attr))
        self._textboxes.append(tb)
        it = TextBoxItem(tb, pi.pw, pi.ph)
        it._updating = True
        it.setData(0, pi.y)
        it.setData(1, pi.x)
        it.setPos(pi.x + tb.x_pct/100*pi.pw, pi.y + tb.y_pct/100*pi.ph)
        it._updating = False
        self._scene.addItem(it)
        self._tb_items.append(it)
        pi.tbs.append(it)
        it.setSelected(True)
        self.tb_selected.emit(tb)

    def refresh_tb(self, tb):
        for it in self._tb_items:
            if it.tb.id == tb.id:
                it.refresh(reposition=False)
                break


# ── DropZone ───────────────────────────────────────────────
class DropZone(QWidget):
    files_dropped = Signal(list)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        frame = QFrame()
        frame.setStyleSheet(f"QFrame{{border:2px dashed {C['border']};border-radius:16px;background:{C['surface']};padding:48px;}}")
        fl = QVBoxLayout(frame)
        fl.setAlignment(Qt.AlignCenter); fl.setSpacing(8)
        icon = QLabel("📄"); icon.setStyleSheet("font-size:64px;border:none;"); icon.setAlignment(Qt.AlignCenter)
        fl.addWidget(icon)
        t = QLabel("Glissez vos fichiers PDF ici"); t.setStyleSheet(f"font-size:20px;font-weight:600;color:{C['text']};border:none;"); t.setAlignment(Qt.AlignCenter)
        fl.addWidget(t)
        s = QLabel("ou cliquez pour sélectionner des fichiers"); s.setStyleSheet(f"font-size:14px;color:{C['text2']};border:none;"); s.setAlignment(Qt.AlignCenter)
        fl.addWidget(s)
        btn = QPushButton("Sélectionner des PDFs"); btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"QPushButton{{background:{C['primary']};color:#fff;padding:10px 24px;border-radius:8px;font-size:14px;font-weight:500;border:none;}}QPushButton:hover{{background:{C['primary_hover']};}}")
        btn.clicked.connect(self._browse)
        fl.addWidget(btn, alignment=Qt.AlignCenter)
        layout.addWidget(frame)
    def _browse(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Sélectionner des PDFs", "", "PDF (*.pdf)")
        if files: self.files_dropped.emit(files)
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith('.pdf') for u in e.mimeData().urls()):
            e.acceptProposedAction()
    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith('.pdf')]
        if files: self.files_dropped.emit(files); e.acceptProposedAction()

# ── TBProps ────────────────────────────────────────────────
class TBProps(QFrame):
    changed = Signal(object)
    delete_req = Signal(object)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"TBProps{{background:{C['surface']};border:1px solid {C['border']};border-radius:8px;}}")
        self.setFixedWidth(420); self._tb=None; self._block=False
        layout = QVBoxLayout(self); layout.setContentsMargins(12,10,12,10); layout.setSpacing(6)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Police"))
        self.font_cb = QComboBox(); self.font_cb.addItems(['Arial','Times New Roman','Courier New','Verdana','Georgia'])
        self.font_cb.currentTextChanged.connect(lambda v: self._set('font_family', v)); r1.addWidget(self.font_cb)
        r1.addWidget(QLabel("Taille"))
        self.size_sp = QSpinBox(); self.size_sp.setRange(6,72)
        self.size_sp.valueChanged.connect(lambda v: self._set('font_size', v)); r1.addWidget(self.size_sp)
        r1.addWidget(QLabel("Couleur"))
        self.color_btn = self._cbtn('#000000'); self.color_btn.clicked.connect(lambda: self._pick('font_color', self.color_btn)); r1.addWidget(self.color_btn)
        layout.addLayout(r1)
        r2 = QHBoxLayout()
        self.bold_btn = QPushButton("G"); self.bold_btn.setFixedSize(30,26); self.bold_btn.setCheckable(True)
        self.bold_btn.clicked.connect(lambda: self._set('bold', self.bold_btn.isChecked())); r2.addWidget(self.bold_btn)
        self.ital_btn = QPushButton("I"); self.ital_btn.setFixedSize(30,26); self.ital_btn.setCheckable(True)
        self.ital_btn.clicked.connect(lambda: self._set('italic', self.ital_btn.isChecked())); r2.addWidget(self.ital_btn)
        r2.addSpacing(8)
        self.no_border = QCheckBox("Sans bordure"); self.no_border.setChecked(True)
        self.no_border.stateChanged.connect(self._tborder); r2.addWidget(self.no_border)
        self.bcol_btn = self._cbtn('#000000'); self.bcol_btn.setEnabled(False)
        self.bcol_btn.clicked.connect(lambda: self._pick('border_color', self.bcol_btn)); r2.addWidget(self.bcol_btn)
        self.bw_sp = QSpinBox(); self.bw_sp.setRange(0,5); self.bw_sp.setEnabled(False)
        self.bw_sp.valueChanged.connect(lambda v: self._set('border_width', v)); r2.addWidget(self.bw_sp)
        layout.addLayout(r2)
        r3 = QHBoxLayout()
        self.no_fill = QCheckBox("Sans remplissage"); self.no_fill.setChecked(True)
        self.no_fill.stateChanged.connect(self._tfill); r3.addWidget(self.no_fill)
        self.bg_btn = self._cbtn('#ffffff'); self.bg_btn.setEnabled(False)
        self.bg_btn.clicked.connect(lambda: self._pick('bg_color', self.bg_btn)); r3.addWidget(self.bg_btn)
        r3.addStretch()
        db = QPushButton("Supprimer"); db.setCursor(Qt.PointingHandCursor)
        db.setStyleSheet(f"QPushButton{{background:{C['danger']};color:#fff;padding:4px 12px;border-radius:4px;font-size:12px;border:none;}}QPushButton:hover{{background:{C['danger_hover']};}}")
        db.clicked.connect(lambda: self.delete_req.emit(self._tb) if self._tb else None); r3.addWidget(db)
        layout.addLayout(r3)
    def _cbtn(self, color):
        b=QPushButton(); b.setFixedSize(28,24); b.setCursor(Qt.PointingHandCursor)
        b.setProperty('hex',color); b.setStyleSheet(f"QPushButton{{background:{color};border:1px solid {C['border']};border-radius:4px;}}"); return b
    def _set(self, attr, val):
        if self._tb and not self._block: setattr(self._tb, attr, val); self.changed.emit(self._tb)
    def _pick(self, attr, btn):
        if not self._tb: return
        cur = getattr(self._tb, attr)
        if cur=='transparent': cur='#000000'
        col = QColorDialog.getColor(QColor(cur), self)
        if col.isValid():
            setattr(self._tb, attr, col.name())
            btn.setProperty('hex', col.name()); btn.setStyleSheet(f"QPushButton{{background:{col.name()};border:1px solid {C['border']};border-radius:4px;}}")
            self.changed.emit(self._tb)
    def _tborder(self, state):
        if self._block: return
        no=bool(state); self.bcol_btn.setEnabled(not no); self.bw_sp.setEnabled(not no)
        if self._tb:
            if no: self._tb.border_color='transparent'; self._tb.border_width=0
            else: self._tb.border_color=self.bcol_btn.property('hex') or '#000000'; self._tb.border_width=max(1,self.bw_sp.value()); self.bw_sp.setValue(self._tb.border_width)
            self.changed.emit(self._tb)
    def _tfill(self, state):
        if self._block: return
        no=bool(state); self.bg_btn.setEnabled(not no)
        if self._tb: self._tb.bg_color='transparent' if no else (self.bg_btn.property('hex') or '#ffffff'); self.changed.emit(self._tb)
    def set_tb(self, tb):
        self._block=True; self._tb=tb
        self.font_cb.setCurrentText(tb.font_family); self.size_sp.setValue(tb.font_size)
        c=tb.font_color; self.color_btn.setProperty('hex',c); self.color_btn.setStyleSheet(f"QPushButton{{background:{c};border:1px solid {C['border']};border-radius:4px;}}")
        self.bold_btn.setChecked(tb.bold); self.ital_btn.setChecked(tb.italic)
        hb=tb.border_color!='transparent' and tb.border_width>0
        self.no_border.setChecked(not hb); self.bcol_btn.setEnabled(hb); self.bw_sp.setEnabled(hb); self.bw_sp.setValue(tb.border_width)
        hf=tb.bg_color!='transparent'; self.no_fill.setChecked(not hf); self.bg_btn.setEnabled(hf)
        self._block=False

# ── ExportRangeDialog ──────────────────────────────────────
class ExportRangeDialog(QDialog):
    def __init__(self, max_p, parent=None):
        super().__init__(parent); self.setWindowTitle("Exporter une plage de pages"); self.setFixedWidth(300)
        l=QVBoxLayout(self); l.addWidget(QLabel("Pages"))
        r=QHBoxLayout()
        self.fr=QSpinBox(); self.fr.setRange(1,max_p); self.fr.setValue(1); r.addWidget(self.fr)
        r.addWidget(QLabel("à"))
        self.to=QSpinBox(); self.to.setRange(1,max_p); self.to.setValue(max_p); r.addWidget(self.to)
        l.addLayout(r)
        bb=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Exporter"); bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); l.addWidget(bb)
    def get_range(self): return self.fr.value(), self.to.value()

# ── PreviewPanel ───────────────────────────────────────────
class PreviewPanel(QFrame):
    closed = Signal()
    BASE_SCALE = 2.0
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(250)
        self.setStyleSheet(f"PreviewPanel{{background:{C['surface']};border-left:1px solid {C['border']};}}")
        l = QVBoxLayout(self); l.setContentsMargins(0,0,0,0); l.setSpacing(0)
        h = QHBoxLayout(); h.setContentsMargins(16,12,16,12)
        title=QLabel("Aperçu"); title.setStyleSheet("font-size:15px;font-weight:600;"); h.addWidget(title); h.addStretch()
        cb=QPushButton("×"); cb.setFixedSize(28,28); cb.setCursor(Qt.PointingHandCursor)
        cb.setStyleSheet("QPushButton{background:transparent;border:none;font-size:18px;border-radius:14px;}QPushButton:hover{background:#f0f0f0;}")
        cb.clicked.connect(self.closed.emit); h.addWidget(cb)
        hw=QWidget(); hw.setLayout(h); hw.setStyleSheet(f"border-bottom:1px solid {C['border']};"); l.addWidget(hw)
        self._scene=QGraphicsScene(self)
        self._view=QGraphicsView(self._scene)
        self._view.setRenderHints(QPainter.Antialiasing|QPainter.SmoothPixmapTransform)
        self._view.setDragMode(QGraphicsView.ScrollHandDrag)
        self._view.setStyleSheet("border:none;background:#f5f5f5;")
        self._view.viewport().installEventFilter(self)
        l.addWidget(self._view, 1)
        self.info=QLabel(); self.info.setAlignment(Qt.AlignCenter)
        self.info.setStyleSheet(f"padding:8px;font-size:13px;color:{C['text2']};"); l.addWidget(self.info)
        fw=QWidget(); fw.setStyleSheet(f"border-top:1px solid {C['border']};")
        fl=QHBoxLayout(fw); fl.setContentsMargins(12,6,12,6); fl.setSpacing(8)
        rb=QPushButton("Reset"); rb.setCursor(Qt.PointingHandCursor)
        rb.setStyleSheet(f"QPushButton{{padding:4px 10px;font-size:12px;border:1px solid {C['border']};border-radius:4px;background:{C['surface']};}}QPushButton:hover{{background:#f0f0f0;}}")
        rb.clicked.connect(self._reset_zoom); fl.addWidget(rb)
        self._zs=QSlider(Qt.Horizontal); self._zs.setRange(25,500); self._zs.setValue(100)
        self._zs.valueChanged.connect(self._on_slider); fl.addWidget(self._zs)
        self._zl=QLabel("100%"); self._zl.setStyleSheet(f"font-size:12px;color:{C['text2']};min-width:40px;")
        self._zl.setAlignment(Qt.AlignRight|Qt.AlignVCenter); fl.addWidget(self._zl)
        l.addWidget(fw)
        self._pm=None; self._zoom=1.0; self._pd=None; self._render_scale=2.0
        self._textboxes=[]
        self._hires_timer=QTimer(self); self._hires_timer.setSingleShot(True)
        self._hires_timer.timeout.connect(self._upgrade_preview)

    def _build_scene(self):
        """Build scene from current pixmap and textboxes (shared by set_page and _upgrade_preview)."""
        self._scene.clear()
        dpr_ratio = self._render_scale / self.BASE_SCALE
        pw = self._pm.width() / dpr_ratio
        ph = self._pm.height() / dpr_ratio
        pix_item = self._scene.addPixmap(self._pm)
        pix_item.setTransformationMode(Qt.SmoothTransformation)
        # An item transform instead of setDevicePixelRatio: the latter detaches the
        # pixmap, i.e. deep-copies it, since self._pm keeps a reference.
        pix_item.setTransform(QTransform.fromScale(1.0 / dpr_ratio, 1.0 / dpr_ratio))
        for tb in self._textboxes:
            if tb.page_id == self._pd.id:
                self._scene.addItem(TextBoxItem(tb, pw, ph, read_only=True))
        self._scene.setSceneRect(0, 0, pw, ph)

    def set_page(self, pd, idx, total, textboxes=None):
        self._pd = pd
        self._textboxes = textboxes or []
        self.info.setText(f"Page {idx+1} / {total} — {pd.label}")
        self._render_scale = self.BASE_SCALE
        self._pm = render_page_pixmap(pd.source, pd.page_index, self._render_scale)
        self._build_scene()
        self._zoom = 1.0; self._zs.setValue(100)
        self._view.resetTransform()
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        t=self._view.transform(); self._zoom=t.m11(); self._sync()

    def update_info(self, idx, total):
        """Refresh the caption only - the rendered page itself has not changed,
        so the user's zoom survives a delete or a reorder elsewhere."""
        if self._pd is not None:
            self.info.setText(f"Page {idx+1} / {total} — {self._pd.label}")

    def _apply(self):
        self._view.resetTransform(); self._view.scale(self._zoom, self._zoom)
        self._sync()
        # Debounce hi-res re-render
        self._hires_timer.start(250)

    def _upgrade_preview(self):
        if not self._pd: return
        dpr = self.screen().devicePixelRatio() if self.screen() else 1.0
        effective_scale = max(self.BASE_SCALE, self._zoom * self.BASE_SCALE * dpr)
        effective_scale = min(effective_scale, 6.0)
        if self._render_scale >= effective_scale: return
        self._render_scale = effective_scale
        self._pm = render_page_pixmap(self._pd.source, self._pd.page_index, self._render_scale)
        self._build_scene()
        self._view.resetTransform(); self._view.scale(self._zoom, self._zoom)

    def _sync(self):
        pct=int(self._zoom*100)
        self._zs.blockSignals(True); self._zs.setValue(pct); self._zs.blockSignals(False)
        self._zl.setText(f"{pct}%")

    def _on_slider(self, v): self._zoom=v/100.0; self._apply()
    def _reset_zoom(self):
        if self._pm:
            self._view.resetTransform()
            self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
            self._zoom=self._view.transform().m11(); self._sync()

    def eventFilter(self, obj, event):
        if obj==self._view.viewport() and event.type()==QEvent.Wheel:
            delta=event.angleDelta().y()
            factor=1.15 if delta>0 else 1/1.15
            self._zoom=max(0.1,min(10.0,self._zoom*factor))
            self._apply(); return True
        return super().eventFilter(obj, event)


# ── PreviewHandle ──────────────────────────────────────────
class PreviewHandle(QFrame):
    """Thin strip pinned to the right edge that unfolds the preview panel.

    Clicking a page only selects it: the preview is opened on demand from here,
    which also makes it recoverable after being closed with its own x.
    """
    clicked = Signal()
    WIDTH = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Afficher l'aperçu de la page sélectionnée")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        self.arrow = QLabel("◀")
        self.arrow.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.arrow)
        self._paint(False)

    def _paint(self, hover):
        bg = '#e9eef7' if hover else C['surface']
        col = C['primary'] if hover else C['text2']
        self.setStyleSheet(f"PreviewHandle{{background:{bg};border-left:1px solid {C['border']};}}")
        self.arrow.setStyleSheet(f"color:{col};font-size:11px;border:none;background:transparent;")

    def enterEvent(self, e):
        self._paint(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._paint(False)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


# ══════════════════════════════════════════════════════════════
#  ExportWorker – heavy PDF work off the UI thread
# ══════════════════════════════════════════════════════════════
class ExportWorker(QThread):
    progress = Signal(int, int)   # current, total
    done     = Signal(str)        # success message - not `finished`, QThread owns that
    error    = Signal(str)        # error message

    def __init__(self, plist, textboxes, path, base_scale, screen_dpi):
        super().__init__()
        self.plist = plist
        self.textboxes = textboxes
        self.path = path
        self.base_scale = base_scale
        self.screen_dpi = screen_dpi

    @staticmethod
    def _hex2c(h):
        h = h.lstrip('#')
        return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)

    @staticmethod
    def _get_pdf_font(font_family, bold, italic):
        """Map Qt font settings to PyMuPDF base14 font names."""
        family = font_family.lower()
        if any(x in family for x in ('courier', 'mono', 'consolas')):
            if bold and italic: return "cobi"
            if bold: return "cobo"
            if italic: return "coit"
            return "cour"
        elif any(x in family for x in ('times', 'georgia', 'serif', 'garamond')):
            if bold and italic: return "tibi"
            if bold: return "tibo"
            if italic: return "tiit"
            return "tiro"
        else:
            if bold and italic: return "hebi"
            if bold: return "hebo"
            if italic: return "heit"
            return "helv"

    def run(self):
        tmp_path = None
        out = None
        # PyMuPDF documents are not safe to share across threads, and the global
        # cache may close one under us, so this thread opens its own copies.
        docs = {}
        try:
            out = fitz.open()
            # Qt rasterises a point at the screen's logical DPI, inside a scene whose
            # unit is BASE_SCALE * 72 DPI: a 25 pt box really covers 25 * dpi/72 scene
            # units, hence pdf_pt = qt_pt * (dpi / 72) / base_scale. Dividing by
            # base_scale alone exported text ~25% smaller than what was displayed.
            font_scale = (self.screen_dpi / 72.0) / self.base_scale
            tb_count = 0
            total = len(self.plist)
            for i, pd in enumerate(self.plist):
                src = docs.get(pd.source.hash)
                if src is None:
                    src = open_pdf(pd.source.pdf_bytes)
                    docs[pd.source.hash] = src
                out.insert_pdf(src, from_page=pd.page_index, to_page=pd.page_index)
                op = out[-1]; pw, ph = op.rect.width, op.rect.height
                for tb in self.textboxes:
                    if tb.page_id != pd.id or not tb.text.strip():
                        continue
                    x, y = tb.x_pct / 100 * pw, tb.y_pct / 100 * ph
                    w, h = tb.width_pct / 100 * pw, tb.height_pct / 100 * ph
                    r = fitz.Rect(x, y, x + w, y + h)
                    if tb.bg_color != 'transparent':
                        sh = op.new_shape(); sh.draw_rect(r); sh.finish(fill=self._hex2c(tb.bg_color)); sh.commit()
                    if tb.border_width > 0 and tb.border_color != 'transparent':
                        sh = op.new_shape(); sh.draw_rect(r); sh.finish(color=self._hex2c(tb.border_color), width=tb.border_width); sh.commit()
                    fn = self._get_pdf_font(tb.font_family, tb.bold, tb.italic)
                    tr = fitz.Rect(x + 2, y + 2, x + w - 2, y + h - 2)
                    if tr.is_empty or not tr.is_valid:
                        continue
                    pdf_fs = tb.font_size * font_scale
                    tw = fitz.TextWriter(op.rect)
                    font = fitz.Font(fn)
                    rc = tw.fill_textbox(tr, tb.text, font=font, fontsize=pdf_fs)
                    if rc:
                        attempts = 0
                        while rc and pdf_fs > 4 and attempts < 20:
                            pdf_fs *= 0.85
                            tw = fitz.TextWriter(op.rect)
                            rc = tw.fill_textbox(tr, tb.text, font=font, fontsize=pdf_fs)
                            attempts += 1
                    tw.write_text(op, overlay=True, color=self._hex2c(tb.font_color))
                    tb_count += 1
                self.progress.emit(i + 1, total)
            fd, tmp_path = tempfile.mkstemp(suffix='.pdf', dir=os.path.dirname(os.path.abspath(self.path)))
            os.close(fd)
            out.save(tmp_path, garbage=4, deflate=True, clean=True)
            close_doc(out); out = None
            verify_doc = fitz.open(tmp_path); len(verify_doc); verify_doc.close()
            os.replace(tmp_path, self.path)
            tmp_path = None
            self.done.emit(f"Export réussi ({len(self.plist)} pages, {tb_count} zone(s) de texte) !")
        except Exception as e:
            _logger.exception("export failed")
            self.error.emit(f"Erreur export: {e}")
        finally:
            for d in docs.values():
                close_doc(d)
            if out is not None:
                close_doc(out)
            if tmp_path is not None and os.path.exists(tmp_path):
                os.remove(tmp_path)


class ExportProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export en cours...")
        self.setFixedSize(350, 100)
        self.setModal(True)
        layout = QVBoxLayout(self)
        self.label = QLabel("Préparation...")
        layout.addWidget(self.label)
        self.bar = QProgressBar()
        layout.addWidget(self.bar)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)

    def reject(self):
        pass  # no cancellation: closing here would orphan the export thread

    def update_progress(self, current, total):
        self.bar.setMaximum(total)
        self.bar.setValue(current)
        self.label.setText(f"Page {current}/{total}...")


# ══════════════════════════════════════════════════════════════
#  MainWindow
# ══════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    _update_available = Signal(str)
    _update_downloaded = Signal(str)
    _update_download_failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._update_available.connect(self._show_update_toast)
        self._update_downloaded.connect(self._on_update_downloaded)
        self._update_download_failed.connect(self._on_update_download_failed)
        self.setWindowTitle("Éditeur PDF")
        if os.path.exists(ICON_PATH): self.setWindowIcon(QIcon(ICON_PATH))
        self.setMinimumSize(900, 600); self.resize(1200, 800)
        self.setAcceptDrops(True)
        self.pages: list[PageData] = []
        self.textboxes: list[TextBoxData] = []
        self.mode = 'edit'
        self.selected_ids: set[str] = set()
        # Tracked by page id, never by index: indices go stale on delete/reorder.
        self._preview_page_id = None
        self._last_selected_id = None
        self._reader_target = None
        self._reader_dirty = True
        self._preview_open = False
        self._pending_grid_anchor = None
        self._export_workers = set()
        self._build_toolbar(); self._build_central(); self._build_reader_nav(); self._build_tb_props()
        self.toast = ToastManager(self)
        self._update_state()
        self._check_update()

    @staticmethod
    def _version_tuple(v):
        return tuple(int(x) for x in re.findall(r'\d+', v)) or (0,)

    def _check_update(self):
        self._expected_hash = None
        def _fetch():
            try:
                req = Request(UPDATE_URL, headers={"Accept": "application/vnd.github+json"})
                resp = urlopen(req, timeout=5)
                data = json.loads(resp.read().decode())
                remote = data.get("tag_name", "").lstrip("v")
                # Strictly newer only: `!=` also fired on a dev build running ahead
                # of the latest release, offering a downgrade.
                if remote and self._version_tuple(remote) > self._version_tuple(VERSION):
                    body = data.get("body", "")
                    m = re.search(r'SHA256:\s*([a-fA-F0-9]{64})', body)
                    self._expected_hash = m.group(1).lower() if m else None
                    self._update_available.emit(remote)
            except Exception:
                _logger.warning("update check failed", exc_info=True)
        threading.Thread(target=_fetch, daemon=True).start()

    def _show_update_toast(self, remote_version):
        self.toast.show(
            f"Mise à jour disponible (v{remote_version})", 'info',
            sticky=True, on_click=self._launch_update,
            tooltip="Cliquez pour lancer la mise à jour",
        )

    def _launch_update(self, toast_label):
        # Checked before downloading: without the signature there is nothing we
        # could verify, so 60 MB would be fetched only to be thrown away.
        if not self._expected_hash:
            self.toast.remove(toast_label)
            self.toast.show(
                "Signature (SHA-256) absente des notes de version : "
                "mise à jour impossible à vérifier.", 'error')
            return
        self.toast.remove(toast_label)
        self.toast.show("Téléchargement de la mise à jour...", 'info')
        download_url = "https://github.com/yannsokol-web/EDITEUR2PDF/releases/latest/download/InstallEditeurPDF.exe"

        def _download():
            tmp = os.path.join(tempfile.gettempdir(), "InstallEditeurPDF.exe")
            try:
                req = Request(download_url, headers={"User-Agent": "EditeurPDF"})
                digest = hashlib.sha256()
                with urlopen(req, timeout=60) as resp, open(tmp, 'wb') as f:
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)
                        digest.update(chunk)
                if digest.hexdigest() != self._expected_hash:
                    os.remove(tmp)
                    self._update_download_failed.emit(
                        "Le fichier téléchargé ne correspond pas à la signature attendue.")
                    return
                self._update_downloaded.emit(tmp)
            except Exception as e:
                _logger.warning("update download failed", exc_info=True)
                self._update_download_failed.emit(f"Échec du téléchargement : {e}")

        threading.Thread(target=_download, daemon=True).start()

    def _on_update_downloaded(self, path):
        if not path.startswith(tempfile.gettempdir()) or not path.endswith('.exe'):
            self.toast.show("Chemin d'installeur invalide.", 'error')
            return
        reply = QMessageBox.question(
            self, "Mise à jour téléchargée",
            f"L'installeur a été téléchargé.\n\nLancer la mise à jour maintenant ?\n\n({path})",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            subprocess.Popen([path])
            QTimer.singleShot(500, self.close)
        else:
            self.toast.show("Mise à jour reportée.", 'info')

    def _on_update_download_failed(self, msg):
        self.toast.show(msg, 'error')

    def _build_toolbar(self):
        tb=QWidget(); tb.setFixedHeight(56)
        tb.setStyleSheet(f"background:{C['surface']};border-bottom:1px solid {C['border']};")
        h=QHBoxLayout(tb); h.setContentsMargins(24,0,24,0); h.setSpacing(12)
        h.addWidget(QLabel("<b style='font-size:18px;'>Éditeur PDF</b>"))
        self.pg_count=QLabel()
        self.pg_count.setStyleSheet(f"font-size:13px;color:{C['text2']};background:#f5f5f5;padding:2px 10px;border-radius:10px;border:1px solid {C['border']};")
        h.addWidget(self.pg_count)
        self.mode_w=QWidget(); ml=QHBoxLayout(self.mode_w); ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)
        self.btn_edit=QPushButton("Édition"); self.btn_edit.setCursor(Qt.PointingHandCursor); self.btn_edit.setFixedHeight(30)
        self.btn_edit.clicked.connect(lambda: self._switch_mode('edit')); ml.addWidget(self.btn_edit)
        self.btn_read=QPushButton("Lecture"); self.btn_read.setCursor(Qt.PointingHandCursor); self.btn_read.setFixedHeight(30)
        self.btn_read.clicked.connect(lambda: self._switch_mode('read')); ml.addWidget(self.btn_read)
        self.mode_w.hide(); h.addWidget(self.mode_w)
        h.addStretch()
        self.exp_sel_btn=QPushButton("Exporter la sélection"); self.exp_sel_btn.setCursor(Qt.PointingHandCursor)
        self.exp_sel_btn.setStyleSheet(f"QPushButton{{background:{C['primary']};color:#fff;padding:8px 18px;border-radius:8px;font-size:14px;border:none;}}QPushButton:hover{{background:{C['primary_hover']};}}")
        self.exp_sel_btn.clicked.connect(self._export_selection); self.exp_sel_btn.hide(); h.addWidget(self.exp_sel_btn)
        self.del_sel_btn=QPushButton("Supprimer la sélection"); self.del_sel_btn.setCursor(Qt.PointingHandCursor)
        self.del_sel_btn.setStyleSheet(f"QPushButton{{background:{C['danger']};color:#fff;padding:8px 18px;border-radius:8px;font-size:14px;border:none;}}QPushButton:hover{{background:{C['danger_hover']};}}")
        self.del_sel_btn.clicked.connect(self._delete_selection); self.del_sel_btn.hide(); h.addWidget(self.del_sel_btn)
        h.addStretch()
        self.add_btn=QPushButton("+ Ajouter des PDFs"); self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setStyleSheet(f"QPushButton{{background:{C['surface']};color:{C['text']};border:1px solid {C['border']};padding:8px 18px;border-radius:8px;font-size:14px;}}QPushButton:hover{{border-color:{C['primary']};color:{C['primary']};}}")
        self.add_btn.clicked.connect(self._browse); h.addWidget(self.add_btn)
        self.exp_btn=QPushButton("Exporter PDF"); self.exp_btn.setCursor(Qt.PointingHandCursor)
        self.exp_btn.setStyleSheet(f"QPushButton{{background:{C['primary']};color:#fff;padding:8px 18px;border-radius:8px;font-size:14px;border:none;}}QPushButton:hover{{background:{C['primary_hover']};}}QPushButton:disabled{{background:#aaa;}}")
        self.exp_btn.setEnabled(False); self.exp_btn.clicked.connect(self._export_pdf); h.addWidget(self.exp_btn)
        about_btn=QPushButton("?"); about_btn.setCursor(Qt.PointingHandCursor); about_btn.setFixedSize(32,32)
        about_btn.setToolTip("À propos")
        about_btn.setStyleSheet(f"QPushButton{{background:none;color:{C['text2']};border:1px solid {C['border']};border-radius:16px;font-size:16px;font-weight:bold;}}QPushButton:hover{{border-color:{C['primary']};color:{C['primary']};}}")
        about_btn.clicked.connect(self._show_about); h.addWidget(about_btn)
        self.setMenuWidget(tb)

    def _show_about(self):
        QMessageBox.about(self, "À propos — Éditeur PDF",
            f"<h2>Éditeur PDF v{VERSION}</h2>"
            f"<p><b>Auteur :</b> Yann Sokol</p>"
            f"<p>&copy; 2026 Yann Sokol. Tous droits réservés.</p>"
            f"<hr>"
            f"<p style='font-size:11px;color:#666;'>"
            f"Ce logiciel est la propriété exclusive de Yann Sokol. "
            f"Toute reproduction, distribution, modification ou utilisation "
            f"non autorisée de ce logiciel, en tout ou en partie, est "
            f"strictement interdite sans l'autorisation écrite préalable "
            f"de l'auteur.</p>"
        )

    def _build_central(self):
        self.stack=QStackedWidget(); self.setCentralWidget(self.stack)
        self.drop=DropZone(); self.drop.files_dropped.connect(self.load_files); self.stack.addWidget(self.drop)
        # Splitter = Grid + Preview
        self.splitter=QSplitter(Qt.Horizontal); self.splitter.setHandleWidth(5)
        self.splitter.setStyleSheet(f"QSplitter::handle{{background:{C['border']};}}QSplitter::handle:hover{{background:{C['primary']};}}")
        self.grid_scroll=QScrollArea(); self.grid_scroll.setWidgetResizable(True)
        # Always on: a bar that appears/disappears changes the viewport width, hence
        # the column count, hence the content height - a classic hfw oscillation.
        self.grid_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.grid_scroll.setStyleSheet(f"QScrollArea{{border:none;background:{C['bg']};}}"); self.grid_scroll.setAcceptDrops(True)
        self.grid_widget=QWidget(); self.grid_layout=FlowLayout(self.grid_widget, spacing=20)
        self.grid_layout.setContentsMargins(24,24,24,24); self.grid_scroll.setWidget(self.grid_widget)
        self.splitter.addWidget(self.grid_scroll)
        self.preview=PreviewPanel(); self.preview.closed.connect(self._close_preview); self.preview.hide()
        self.preview_handle=PreviewHandle(); self.preview_handle.clicked.connect(self._open_preview)
        # Poignée et panneau partagent le côté droit du splitter : replié, il ne
        # reste que la bande de 22 px, sans widget flottant par-dessus la grille.
        self.right_panel=QWidget()
        rl=QHBoxLayout(self.right_panel); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        rl.addWidget(self.preview_handle); rl.addWidget(self.preview, 1)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setCollapsible(1, False)
        self.splitter.setStretchFactor(0,1); self.splitter.setStretchFactor(1,0)
        self.stack.addWidget(self.splitter)
        self._collapse_preview()
        self.reader=ReaderView()
        self.reader.tb_selected.connect(self._on_tb_selected)
        self.reader.tb_deselected.connect(self._on_tb_deselected)
        self.reader.page_changed.connect(self._on_reader_page)
        self.stack.addWidget(self.reader)

    def _card_for(self, page_id):
        for i in range(self.grid_layout.count()):
            it = self.grid_layout.itemAt(i)
            w = it.widget() if it else None
            if isinstance(w, PageCard) and w.page_data.id == page_id:
                return w
        return None

    def _grid_anchor(self, anchor_id=None, fallback_id=None):
        """(page id, offset inside that card) to keep on screen across a rebuild.

        A pixel offset alone is meaningless: after an insertion upstream the same
        offset shows different pages.
        """
        if anchor_id is not None:
            return (anchor_id, 0)
        top = self.grid_scroll.verticalScrollBar().value()
        valid = {p.id for p in self.pages}
        best = None
        for i in range(self.grid_layout.count()):
            it = self.grid_layout.itemAt(i)
            w = it.widget() if it else None
            if not isinstance(w, PageCard) or w.page_data.id not in valid:
                continue
            y = w.y()
            if y + w.height() > top and (best is None or y < best[1]):
                best = (w.page_data.id, y)
        if best is None:
            return (fallback_id, 0) if fallback_id else None
        return (best[0], top - best[1])   # how far the card sits above the viewport top

    def _restore_grid_anchor(self, anchor):
        if not anchor:
            return
        card = self._card_for(anchor[0])
        if card is None:
            return
        vbar = self.grid_scroll.verticalScrollBar()
        vbar.setValue(max(0, min(card.y() + anchor[1], vbar.maximum())))

    PREVIEW_WIDTH = 380

    def _open_preview(self):
        """Unfold the preview on the selected page (falls back to the first one)."""
        if not self.pages:
            return
        idx = next((i for i, p in enumerate(self.pages)
                    if p.id == self._preview_page_id), None)
        if idx is None:
            idx = 0
            self._preview_page_id = self.pages[0].id
        self.preview.set_page(self.pages[idx], idx, len(self.pages), self.textboxes)
        self._preview_open = True
        self.preview_handle.hide()
        self.preview.show()
        self.right_panel.setMaximumWidth(16777215)
        self._set_splitter_grip(True)
        self.splitter.setSizes([max(1, self.splitter.width() - self.PREVIEW_WIDTH),
                                self.PREVIEW_WIDTH])

    def _collapse_preview(self):
        """Fold the panel back to its handle. Capped width so the splitter cannot
        be dragged open onto an empty strip."""
        self._preview_open = False
        self.preview.hide()
        self.preview_handle.show()
        self.right_panel.setMaximumWidth(PreviewHandle.WIDTH)
        self._set_splitter_grip(False)
        self.splitter.setSizes([max(1, self.splitter.width() - PreviewHandle.WIDTH),
                                PreviewHandle.WIDTH])

    def _set_splitter_grip(self, on):
        """Replié, la largeur du panneau est verrouillée : la poignée du splitter
        ne doit ni s'illuminer au survol ni afficher un curseur de redimensionnement
        pour une action impossible."""
        h = self.splitter.handle(1)
        if h is not None:
            h.setEnabled(on)
            h.setCursor(Qt.SplitHCursor if on else Qt.ArrowCursor)

    def _rebuild_grid(self, anchor_id=None, fallback_id=None):
        """Sync the card grid with self.pages, keeping the scroll position.

        Cards are reused rather than destroyed and rebuilt: that keeps the flow
        height stable, so QScrollArea never clamps the scroll value to 0 - which is
        what used to send the view back to the top on every add or delete.
        """
        anchor = self._grid_anchor(anchor_id, fallback_id)
        self.grid_widget.setUpdatesEnabled(False)
        try:
            # Reuse the QLayoutItems, not just the widgets: no reparenting at all.
            items = {}
            while self.grid_layout.count():
                it = self.grid_layout.takeAt(0)
                w = it.widget() if it else None
                if isinstance(w, PageCard):
                    items[w.page_data.id] = it

            # Preserve valid selections
            valid_ids = {p.id for p in self.pages}
            self.selected_ids &= valid_ids
            self._update_sel_btns()

            tb_pages = {t.page_id for t in self.textboxes}
            for i, p in enumerate(self.pages):
                it = items.pop(p.id, None)
                if it is not None:
                    card = it.widget()
                    card.set_index(i)
                    self.grid_layout.addItem(it)
                else:
                    card = PageCard(p, i, self.textboxes)
                    # Connected here only: reconnecting a reused card would make
                    # Ctrl+click toggle twice and silently do nothing.
                    card.clicked.connect(self._on_card_click)
                    card.delete_clicked.connect(self._delete_page)
                    self.grid_layout.addWidget(card)
                card.set_has_textbox(p.id in tb_pages)
                card.selected = p.id in self.selected_ids

            for it in items.values():          # pages that went away
                w = it.widget()
                if w is not None:
                    w.setParent(None)          # unparent first, else it stays painted
                    w.deleteLater()
        finally:
            self.grid_widget.setUpdatesEnabled(True)
        self.grid_layout.invalidate()
        self.grid_layout.activate()
        # Held on self so that two rebuilds in the same tick cannot have the older
        # deferred restore land last and move the view to a stale position.
        self._pending_grid_anchor = anchor
        self._restore_grid_anchor(anchor)
        # Again next tick: posted LayoutRequest/DeferredDelete events can still
        # reclamp the scroll value after we return.
        QTimer.singleShot(0, self._restore_pending_grid_anchor)
        self._refresh_preview()

    def _restore_pending_grid_anchor(self):
        self._restore_grid_anchor(self._pending_grid_anchor)

    def _refresh_preview(self):
        """Keep the preview's 'Page X / Y' honest after pages moved or went away."""
        if not self._preview_open or self._preview_page_id is None:
            return
        idx = next((i for i, p in enumerate(self.pages)
                    if p.id == self._preview_page_id), None)
        if idx is None:
            self._collapse_preview(); self._preview_page_id = None
            return
        self.preview.update_info(idx, len(self.pages))

    def _build_reader_nav(self):
        self.rnav=QFrame(self)
        self.rnav.setStyleSheet("QFrame{background:rgba(20,20,20,225);border-radius:24px;border:1px solid rgba(255,255,255,25);}")
        self.rnav.setFixedHeight(48); self.rnav.hide()
        h=QHBoxLayout(self.rnav); h.setContentsMargins(16,4,16,4); h.setSpacing(12)
        ns="QPushButton{background:none;border:none;color:#eee;font-size:18px;padding:2px 8px;border-radius:6px;}QPushButton:hover{background:rgba(255,255,255,30);}QPushButton:disabled{color:rgba(255,255,255,60);}"
        ts="QPushButton{background:none;border:none;color:#eee;font-size:13px;padding:4px 10px;border-radius:6px;}QPushButton:hover{background:rgba(255,255,255,30);}"
        self.rprev=QPushButton("←"); self.rprev.setStyleSheet(ns); self.rprev.setCursor(Qt.PointingHandCursor)
        self.rprev.clicked.connect(lambda: self.reader.prev_page()); h.addWidget(self.rprev)
        self.rpage=QLabel("Page 1 / 1"); self.rpage.setStyleSheet("color:#eee;font-size:14px;min-width:90px;border:none;")
        self.rpage.setAlignment(Qt.AlignCenter); h.addWidget(self.rpage)
        self.rnext=QPushButton("→"); self.rnext.setStyleSheet(ns); self.rnext.setCursor(Qt.PointingHandCursor)
        self.rnext.clicked.connect(lambda: self.reader.next_page()); h.addWidget(self.rnext)
        self._sep(h)
        self.tb_place_btn=QPushButton("T+"); self.tb_place_btn.setStyleSheet(ns); self.tb_place_btn.setCursor(Qt.PointingHandCursor)
        self.tb_place_btn.setCheckable(True); self.tb_place_btn.clicked.connect(self._toggle_placing); h.addWidget(self.tb_place_btn)
        self._sep(h)
        b1=QPushButton("Exporter la page"); b1.setStyleSheet(ts); b1.setCursor(Qt.PointingHandCursor); b1.clicked.connect(self._export_current); h.addWidget(b1)
        b2=QPushButton("Exporter pages…"); b2.setStyleSheet(ts); b2.setCursor(Qt.PointingHandCursor); b2.clicked.connect(self._export_range); h.addWidget(b2)
        self._sep(h)
        rb=QPushButton("Reset"); rb.setStyleSheet(ts); rb.setCursor(Qt.PointingHandCursor); rb.clicked.connect(self._reset_zoom); h.addWidget(rb)
        self.rzoom=QSlider(Qt.Horizontal); self.rzoom.setRange(25,500); self.rzoom.setValue(100); self.rzoom.setFixedWidth(100)
        self.rzoom.setStyleSheet(f"QSlider{{border:none;}}QSlider::groove:horizontal{{height:4px;background:rgba(255,255,255,50);border-radius:2px;}}QSlider::handle:horizontal{{background:{C['primary']};width:12px;margin:-4px 0;border-radius:6px;}}")
        self.rzoom.valueChanged.connect(self._on_zoom_slider); h.addWidget(self.rzoom)
        self.rzlbl=QLabel("100%"); self.rzlbl.setStyleSheet("color:#ccc;font-size:12px;border:none;min-width:40px;")
        self.rzlbl.setAlignment(Qt.AlignRight|Qt.AlignVCenter); h.addWidget(self.rzlbl)

    def _sep(self, layout):
        s=QFrame(); s.setFixedSize(1,20); s.setStyleSheet("background:rgba(255,255,255,50);"); layout.addWidget(s)

    def _build_tb_props(self):
        self.tbprops=TBProps(self)
        self.tbprops.changed.connect(lambda tb: self.reader.refresh_tb(tb))
        self.tbprops.delete_req.connect(self._on_tb_delete); self.tbprops.hide()

    def _update_state(self):
        n=len(self.pages)
        self.pg_count.setText(f"{n} page{'s' if n>1 else ''}" if n else ""); self.pg_count.setVisible(n>0)
        self.exp_btn.setEnabled(n>0); self.mode_w.setVisible(n>0)
        if not n: self.stack.setCurrentIndex(0)
        elif self.mode=='edit': self.stack.setCurrentIndex(1)
        else: self.stack.setCurrentIndex(2)
        self._update_mode_style()

    def _update_mode_style(self):
        act=f"background:{C['primary']};color:#fff;border:1px solid {C['primary']};padding:5px 16px;font-size:13px;font-weight:500;"
        ina=f"background:transparent;color:{C['text2']};border:1px solid {C['border']};padding:5px 16px;font-size:13px;font-weight:500;"
        self.btn_edit.setStyleSheet(f"QPushButton{{{act if self.mode=='edit' else ina}}}")
        self.btn_read.setStyleSheet(f"QPushButton{{{act if self.mode=='read' else ina}}}")

    def _update_sel_btns(self):
        n=len(self.selected_ids)
        if n:
            self.exp_sel_btn.setText(f"Exporter la sélection ({n})"); self.del_sel_btn.setText(f"Supprimer la sélection ({n})")
            self.exp_sel_btn.show(); self.del_sel_btn.show()
        else: self.exp_sel_btn.hide(); self.del_sel_btn.hide()

    def _switch_mode(self, m):
        if m==self.mode: return
        self.mode=m
        if m=='read':
            self.stack.setCurrentIndex(2); self.rnav.show()
            self.add_btn.hide(); self.exp_sel_btn.hide(); self.del_sel_btn.hide()
            # Where to land: the page just clicked in the grid, else wherever the
            # reader already was - it no longer restarts from page 1 every time.
            target = self._reader_target or self.reader.current_page_id()
            self._reader_target = None
            if self._reader_dirty or self.reader.total != len(self.pages):
                self.reader.set_data(self.pages, self.textboxes, target)
                self._reader_dirty = False
            elif target:
                self.reader.go_to_id(target)
            self._sync_zoom_display(); self._update_rnav(); self._pos_rnav()
        else:
            self.stack.setCurrentIndex(1); self.rnav.hide(); self.tbprops.hide(); self.add_btn.show()
            self._rebuild_grid()
        self._update_mode_style()

    def load_files(self, paths):
        if self.mode=='read': self._switch_mode('edit')
        self.insert_files_at(paths, len(self.pages), msg_verb="chargée")
        self._cleanup_cache()

    def insert_files_at(self, paths, at_index, msg_verb="insérée"):
        """Insert PDF files at a specific index."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        count=0; errors=[]; starts=[]
        try:
            for path in paths:
                try:
                    with open(path,'rb') as f: data=f.read()
                    source=PdfSource(data)
                    _pinned_doc_keys.add(source.hash)
                    doc=get_cached_doc(source); name=os.path.basename(path)
                    for i in range(len(doc)):
                        page=doc[i]
                        pix=page.get_pixmap(matrix=fitz.Matrix(1.0,1.0),alpha=False)
                        img=QImage(pixmap_samples(pix),pix.width,pix.height,pix.stride,QImage.Format_RGB888)
                        pd=PageData(source,i,f"{name} – p.{i+1}",QPixmap.fromImage(img),page.rect)
                        del img
                        self.pages.insert(at_index+count, pd)
                        if i == 0: starts.append(pd.id)   # début de ce PDF-là
                        count+=1
                except Exception as e:
                    errors.append(f"{os.path.basename(path)}: {e}")
            if count:
                self._reader_dirty = True
                # Liseré bleu sur la première page de chaque PDF inséré : c'est le
                # repère qui montre où commence ce qui vient d'être ajouté.
                if starts:
                    self.selected_ids = set(starts)
                    self._last_selected_id = starts[0]
                # Aucune ancre forcée : la vue ne saute pas sur l'insertion, elle
                # garde les pages déjà à l'écran exactement où elles sont.
                self._rebuild_grid(); self._update_state()
                self.toast.show(f"{count} page(s) {msg_verb}(s).", 'success')
            for err in errors:
                self.toast.show(f"Erreur: {err}", 'error')
            self._cleanup_cache()
        finally:
            QApplication.restoreOverrideCursor()

    def _on_card_click(self, page_id):
        mods=QApplication.keyboardModifiers()
        clicked_idx = next((i for i, p in enumerate(self.pages) if p.id == page_id), None)
        if clicked_idx is None: return
        if mods & Qt.ControlModifier:
            if page_id in self.selected_ids: self.selected_ids.discard(page_id)
            else: self.selected_ids.add(page_id)
            self._last_selected_id = page_id
            self._sync_card_selection(); self._update_sel_btns()
        elif mods & Qt.ShiftModifier:
            # Anchor by id: a stale index used to run past the end of self.pages
            # after a deletion and crash with IndexError.
            anchor = next((i for i, p in enumerate(self.pages)
                           if p.id == self._last_selected_id), 0)
            lo, hi = min(anchor, clicked_idx), max(anchor, clicked_idx)
            for i in range(lo, hi + 1):
                self.selected_ids.add(self.pages[i].id)
            self._sync_card_selection(); self._update_sel_btns()
        else:
            self.selected_ids.clear()
            self.selected_ids.add(page_id)
            self._last_selected_id = page_id
            self._sync_card_selection(); self._update_sel_btns()
            p = self.pages[clicked_idx]
            self._preview_page_id = page_id
            self._reader_target = page_id
            # L'aperçu ne s'impose plus au clic : il suit la sélection uniquement
            # s'il a été ouvert depuis la poignée de droite.
            if self._preview_open:
                self.preview.set_page(p, clicked_idx, len(self.pages), self.textboxes)

    def _sync_card_selection(self):
        for i in range(self.grid_layout.count()):
            it=self.grid_layout.itemAt(i)
            if it and it.widget() and isinstance(it.widget(), PageCard):
                it.widget().selected = it.widget().page_data.id in self.selected_ids

    def move_pages_to(self, src_ids, target_idx):
        """Move multiple pages to a target index."""
        moving = [p for p in self.pages if p.id in src_ids]
        if not moving: return
        remaining = [p for p in self.pages if p.id not in src_ids]
        # Adjust target index
        before_count = sum(1 for p in self.pages[:target_idx] if p.id not in src_ids)
        self.pages = remaining[:before_count] + moving + remaining[before_count:]
        self._reader_dirty = True
        # Comme pour l'insertion : on repositionne les pages sans bouger la vue.
        self._rebuild_grid()

    def _drop_pages(self, ids, first_idx):
        """Remove pages by id and return the id of the page to keep in view."""
        # Hide the preview *before* rebuilding: doing it after changes the splitter
        # width, which reflows the grid and reclamps the scroll position.
        if self._preview_page_id in ids:
            if self._preview_open:
                self._collapse_preview()
            self._preview_page_id = None
        self.pages=[p for p in self.pages if p.id not in ids]
        self.textboxes=[t for t in self.textboxes if t.page_id not in ids]
        if self._last_selected_id in ids: self._last_selected_id = None
        if self._reader_target in ids: self._reader_target = None
        self.selected_ids -= ids
        self._cleanup_cache()
        self._reader_dirty = True
        if not self.pages: return None
        return self.pages[min(first_idx, len(self.pages) - 1)].id

    def _delete_page(self, pid):
        idx = next((i for i, p in enumerate(self.pages) if p.id == pid), None)
        if idx is None: return
        # No forced anchor: the natural one keeps the rows already on screen exactly
        # where they are. The neighbour is only a fallback for a delete that wipes
        # out everything currently visible.
        fallback = self._drop_pages({pid}, idx)
        self._rebuild_grid(fallback_id=fallback); self._update_state()

    def _delete_selection(self):
        ids = set(self.selected_ids)
        if not ids: return
        first_idx = next((i for i, p in enumerate(self.pages) if p.id in ids), 0)
        fallback = self._drop_pages(ids, first_idx)
        self._rebuild_grid(fallback_id=fallback); self._update_state()

    def _cleanup_cache(self):
        """Ferme et supprime les documents PDF qui ne sont plus référencés."""
        live = {p.source.hash for p in self.pages}
        _pinned_doc_keys.clear(); _pinned_doc_keys.update(live)
        for key in list(_pdf_doc_cache):
            if key not in live:
                close_doc(_pdf_doc_cache.pop(key))

    def _browse(self):
        files,_=QFileDialog.getOpenFileNames(self, "Sélectionner des PDFs","","PDF (*.pdf)")
        if files: self.load_files(files)

    def _export_pdf(self):
        if not self.pages: return
        path,_=QFileDialog.getSaveFileName(self,"Exporter","edited.pdf","PDF (*.pdf)")
        if path: self._do_export(self.pages,path)

    def _export_selection(self):
        sel=[p for p in self.pages if p.id in self.selected_ids]
        if not sel: return
        path,_=QFileDialog.getSaveFileName(self,"Exporter la sélection","selection.pdf","PDF (*.pdf)")
        if path: self._do_export(sel,path)

    def _export_current(self):
        if not self.pages: return
        p=self.pages[self.reader.cur]
        path,_=QFileDialog.getSaveFileName(self,"Exporter",f"page-{self.reader.cur+1}.pdf","PDF (*.pdf)")
        if path: self._do_export([p],path)

    def _export_range(self):
        if not self.pages: return
        dlg=ExportRangeDialog(len(self.pages),self)
        if dlg.exec()==QDialog.Accepted:
            a,b=dlg.get_range(); s,e=min(a,b)-1,max(a,b)
            path,_=QFileDialog.getSaveFileName(self,"Exporter",f"pages-{s+1}-{e}.pdf","PDF (*.pdf)")
            if path: self._do_export(self.pages[s:e],path)

    def _do_export(self, plist, path):
        # Sync text from any active TextBoxItem editors before exporting
        for it in self.reader._tb_items:
            it.tb.text = it.text_item.toPlainText()

        page_ids = {pd.id for pd in plist}
        textboxes = [tb for tb in self.textboxes if tb.page_id in page_ids]

        dlg = ExportProgressDialog(self)
        dlg.show()

        screen = QApplication.primaryScreen()
        dpi = screen.logicalDotsPerInch() if screen else 96.0
        worker = ExportWorker(plist, textboxes, path, ReaderView.BASE_SCALE, dpi)
        worker.progress.connect(dlg.update_progress)
        worker.done.connect(lambda msg: self._on_export_end(dlg, msg, 'success'))
        worker.error.connect(lambda msg: self._on_export_end(dlg, msg, 'error'))
        # Kept in a set until the thread really finished: a single attribute was
        # overwritten by a second export, leaving a QThread destroyed while running.
        worker.finished.connect(lambda w=worker, d=dlg: self._on_export_thread_done(w, d))
        self._export_workers.add(worker)
        worker.start()

    def _on_export_end(self, dlg, msg, kind):
        dlg.done(QDialog.Accepted)
        self.toast.show(msg, kind)

    def _on_export_thread_done(self, worker, dlg):
        # Safety net: the dialog is modal and cannot be dismissed by hand, so it
        # must go away whatever happened inside the thread.
        if dlg.isVisible():
            dlg.done(QDialog.Accepted)
        self._export_workers.discard(worker)
        worker.deleteLater()

    def _on_reader_page(self, num): self._update_rnav()
    def _update_rnav(self):
        t=self.reader.total; c=self.reader.cur+1
        self.rpage.setText(f"Page {c} / {t}"); self.rprev.setEnabled(c>1); self.rnext.setEnabled(c<t)

    def _toggle_placing(self):
        v=self.tb_place_btn.isChecked(); self.reader.set_placing(v)
        self.tb_place_btn.setStyleSheet(f"QPushButton{{background:{C['primary'] if v else 'none'};border:none;color:#eee;font-size:18px;padding:2px 8px;border-radius:6px;}}QPushButton:hover{{background:rgba(255,255,255,30);}}")

    def _on_tb_placed(self): self.tb_place_btn.setChecked(False); self._toggle_placing()
    def _reset_zoom(self):
        # Back to the opening fit-to-width, like the preview panel's Reset - not
        # to a raw 100% the document was never displayed at.
        self.reader.fit_to_width(); self._sync_zoom_display()
    def _on_zoom_slider(self, v): self.reader.set_zoom(v/100); self.rzlbl.setText(f"{v}%")
    def _sync_zoom_display(self):
        v=int(self.reader.zoom_val*100)
        self.rzoom.blockSignals(True); self.rzoom.setValue(v); self.rzoom.blockSignals(False); self.rzlbl.setText(f"{v}%")

    def _on_tb_selected(self, tb): self.tbprops.set_tb(tb); self.tbprops.show(); self.tbprops.raise_(); self._pos_tbprops()
    def _on_tb_deselected(self): self.tbprops.hide()
    def _on_tb_delete(self, tb): self.reader.delete_selected(); self.tbprops.hide()

    def keyPressEvent(self, e):
        if self.mode=='read':
            if e.key() in (Qt.Key_Right,Qt.Key_Down,Qt.Key_PageDown): self.reader.next_page(); return
            if e.key() in (Qt.Key_Left,Qt.Key_Up,Qt.Key_PageUp): self.reader.prev_page(); return
            if e.key()==Qt.Key_Delete:
                if self.reader.selected_tb(): self.reader.delete_selected(); self.tbprops.hide(); return
            if e.key()==Qt.Key_Escape:
                if self.tb_place_btn.isChecked(): self.tb_place_btn.setChecked(False); self._toggle_placing()
                self.tbprops.hide(); return
            if e.modifiers()&Qt.ControlModifier:
                if e.key()==Qt.Key_C: self.reader.copy_selected(); self.toast.show("Zone copiée",'info'); return
                if e.key()==Qt.Key_V: self.reader.paste_tb(); self.toast.show("Zone collée",'success'); return
        super().keyPressEvent(e)

    def _pos_rnav(self):
        self.rnav.adjustSize()
        self.rnav.move((self.width()-self.rnav.width())//2, self.height()-self.rnav.height()-28); self.rnav.raise_()

    def _close_preview(self):
        # La page reste mémorisée : rouvrir depuis la poignée y revient.
        self._collapse_preview()

    def _pos_tbprops(self):
        self.tbprops.adjustSize()
        self.tbprops.move(max(10,(self.width()-self.tbprops.width())//2), self.height()-self.tbprops.height()-80); self.tbprops.raise_()

    def closeEvent(self, event):
        """Demander confirmation si des pages sont chargées."""
        if any(w.isRunning() for w in self._export_workers):
            QMessageBox.information(
                self, "Export en cours",
                "Un export est en cours.\nAttendez qu'il se termine avant de quitter.")
            event.ignore()
            return
        if self.pages:
            reply = QMessageBox.question(
                self, "Quitter l'éditeur",
                "Des pages sont en cours d'édition.\nLes modifications non exportées seront perdues.\n\nQuitter quand même ?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
        # Nettoyer le cache avant de quitter
        for doc in _pdf_doc_cache.values():
            close_doc(doc)
        _pdf_doc_cache.clear()
        _pinned_doc_keys.clear()
        event.accept()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.rnav.isVisible(): self._pos_rnav()
        if self.tbprops.isVisible(): self._pos_tbprops()
        self.toast.reposition()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith('.pdf') for u in e.mimeData().urls()):
            e.acceptProposedAction()
    def dropEvent(self, e):
        files=[u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith('.pdf')]
        if files: self.load_files(files); e.acceptProposedAction()


def main():
    app=QApplication(sys.argv); app.setStyle('Fusion')
    if os.path.exists(ICON_PATH): app.setWindowIcon(QIcon(ICON_PATH))
    app.setFont(get_system_font())
    w=MainWindow(); w.show(); sys.exit(app.exec())

if __name__=='__main__':
    main()
