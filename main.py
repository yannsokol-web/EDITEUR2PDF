"""
Éditeur PDF – PySide6

Copyright (c) 2026 Yann Sokol. Tous droits réservés.

Ce logiciel est la propriété exclusive de Yann Sokol.
Toute reproduction, distribution, modification ou utilisation non autorisée
de ce logiciel, en tout ou en partie, est strictement interdite sans
l'autorisation écrite préalable de l'auteur.
"""
VERSION = "1.1"
UPDATE_URL = "https://api.github.com/repos/yannsokol-web/EDITEUR2PDF/releases/latest"

import sys, os, uuid, subprocess, threading, configparser, tempfile, json
from urllib.request import urlopen, urlretrieve, Request
import fitz
fitz.TOOLS.mupdf_display_errors(False)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QScrollArea, QFrame,
    QSlider, QComboBox, QSpinBox, QCheckBox, QColorDialog,
    QDialog, QDialogButtonBox, QMessageBox, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QGraphicsTextItem,
    QGraphicsItem, QStackedWidget, QLayout, QSplitter
)
from PySide6.QtCore import (
    Qt, QSize, QRectF, QMimeData, Signal, QTimer,
    QPoint, QRect, QEvent
)
from PySide6.QtGui import (
    QPixmap, QImage, QIcon, QColor, QPainter, QPen, QBrush,
    QFont, QDrag, QTextCursor
)

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(_APP_DIR, 'logoediteurpdf.ico')

_cfg = configparser.ConfigParser()
_cfg.read(os.path.join(_APP_DIR, 'config.ini'), encoding='utf-8')
INSTALLER_PATH = _cfg.get('update', 'installer_path', fallback='')

C = {
    'bg': '#f0f2f5', 'surface': '#ffffff', 'border': '#d9d9d9',
    'primary': '#1677ff', 'primary_hover': '#0958d9',
    'danger': '#ff4d4f', 'danger_hover': '#cf1322',
    'text': '#1f1f1f', 'text2': '#595959',
    'success': '#52c41a', 'reader_bg': '#3a3a3a',
}

# ── Cache PDF global ───────────────────────────────────────
_pdf_doc_cache = {}  # id(pdf_bytes) -> fitz.Document

def get_cached_doc(pdf_bytes):
    """Return a cached fitz.Document for the given bytes, opening it once."""
    key = id(pdf_bytes)
    doc = _pdf_doc_cache.get(key)
    if doc is None:
        doc = open_pdf(pdf_bytes)
        _pdf_doc_cache[key] = doc
    return doc


# ── Données ────────────────────────────────────────────────
class PageData:
    def __init__(self, pdf_bytes, page_index, label, thumbnail):
        self.id = str(uuid.uuid4())
        self.pdf_bytes = pdf_bytes
        self.page_index = page_index
        self.label = label
        self.thumbnail = thumbnail
        self.thumb_scaled = thumbnail.scaled(200, 270, Qt.KeepAspectRatio, Qt.SmoothTransformation) if thumbnail and not thumbnail.isNull() else thumbnail
        self.hires = None
        self.hires_scale = 0

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
        # Force-read to trigger any deferred errors
        _ = len(doc)
        return doc
    except Exception:
        tmp = fitz.open(stream=data, filetype="pdf")
        clean_data = tmp.tobytes(garbage=3, clean=True)
        tmp.close()
        return fitz.open(stream=clean_data, filetype="pdf")

def render_page_pixmap(pdf_bytes, page_index, scale=2.0):
    """Render a PDF page to QPixmap at given scale."""
    doc = get_cached_doc(pdf_bytes)
    pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
    return QPixmap.fromImage(img)

# ── FlowLayout ─────────────────────────────────────────────
class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=20):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
    def addItem(self, item): self._items.append(item)
    def count(self): return len(self._items)
    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None
    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect)
    def sizeHint(self): return self.minimumSize()
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
    def __init__(self, parent):
        self.parent = parent
        self.toasts = []
    def show(self, msg, kind='info'):
        colors = {'info': C['primary'], 'success': C['success'], 'error': C['danger']}
        t = QLabel(msg, self.parent)
        t.setStyleSheet(f"background:{colors.get(kind, C['primary'])};color:#fff;padding:10px 20px;border-radius:8px;font-size:13px;")
        t.setWordWrap(True)
        t.setMaximumWidth(360)
        t.adjustSize()
        self._position(t)
        t.show(); t.raise_()
        self.toasts.append(t)
        QTimer.singleShot(3500, lambda: self._remove(t))
    def _position(self, t):
        p = self.parent
        y = p.height() - 24 - t.height()
        for ex in self.toasts:
            if ex.isVisible(): y -= ex.height() + 8
        t.move(p.width()-t.width()-24, y)
    def _remove(self, t):
        if t in self.toasts: self.toasts.remove(t)
        t.deleteLater()

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
        self._selected = v
        self._style()

    def set_index(self, i):
        self.index = i
        self.num_lbl.setText(f"p.{i+1}")

    def enterEvent(self, e):
        self.del_btn.show()
    def leaveEvent(self, e):
        self.del_btn.hide()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and hasattr(self, '_drag_pos'):
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
                pm = self.page_data.thumbnail.scaled(80, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
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
                    painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
                    painter.drawText(QRect(pm.width()-20, 0, 20, 20), Qt.AlignCenter, str(len(ids)))
                    painter.end()
                    pm = pm2
                drag.setPixmap(pm)
                drag.setHotSpot(QPoint(40, 55))
                drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if hasattr(self, '_drag_pos') and (e.position().toPoint() - self._drag_pos).manhattanLength() < 15:
                self.clicked.emit(self.page_data.id)

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
    def __init__(self, tb, pw, ph, parent=None):
        super().__init__(parent)
        self.tb = tb
        self.pw, self.ph = pw, ph
        self._updating = True  # block itemChange writeback during setup
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(Qt.SizeAllCursor)
        self.setAcceptHoverEvents(True)
        self.text_item = QGraphicsTextItem(self)
        self.text_item.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.text_item.document().setDocumentMargin(0)
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
        if QRectF(r.right()-10,r.bottom()-10,10,10).contains(e.pos()) and e.button()==Qt.LeftButton:
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
class ReaderView(QGraphicsView):
    tb_selected = Signal(object)
    tb_deselected = Signal()
    page_changed = Signal(int)

    PAGE_GAP = 40  # pixels between pages

    LOWRES_SCALE = 1.0   # fast placeholder (was 0.5 – too blurry)
    HIRES_SCALE = 3.0    # quality render

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
        self._hires_timer = QTimer(self)
        self._hires_timer.setSingleShot(True)
        self._hires_timer.timeout.connect(self._upgrade_visible)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._emit_current_page)
        # Hand-drag panning by default
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setCursor(Qt.OpenHandCursor)

    def set_data(self, pages, textboxes, start_idx=0):
        self._pages = pages
        self._textboxes = textboxes
        self._zoom = 1.0
        self._start_idx = start_idx
        # Reset hi-res cache to avoid stale oversized pixmaps
        for p in pages:
            p.hires = None
            p.hires_scale = 0
        self._render_all()

    def _render_all(self):
        """Layout all pages with low-res placeholders, then upgrade visible ones."""
        self._scene.clear()
        self._tb_items.clear()
        self._page_items.clear()
        if not self._pages:
            return

        tb_map = {}
        for tb in self._textboxes:
            tb_map.setdefault(tb.page_id, []).append(tb)

        y_offset = self.PAGE_GAP
        max_width = 0
        total = len(self._pages)

        for idx, p in enumerate(self._pages):
            pm = self._get_pixmap(p, self.LOWRES_SCALE)
            # Scale placeholder to match hi-res dimensions
            target_w = int(pm.width() * self.HIRES_SCALE / self.LOWRES_SCALE)
            target_h = int(pm.height() * self.HIRES_SCALE / self.LOWRES_SCALE)
            pw, ph = target_w, target_h
            max_width = max(max_width, pw)

            pix_item = self._scene.addPixmap(pm.scaled(pw, ph, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            pix_item.setPos(0, y_offset)

            tb_items_for_page = []
            for tb in tb_map.get(p.id, []):
                it = TextBoxItem(tb, pw, ph)
                it._updating = True
                it.setData(0, y_offset)
                it.setPos(tb.x_pct/100*pw, y_offset + tb.y_pct/100*ph)
                it._updating = False
                self._scene.addItem(it)
                self._tb_items.append(it)
                tb_items_for_page.append(it)

            lbl = self._scene.addSimpleText(f"Page {idx+1} / {total} — {p.label}")
            lbl.setBrush(QColor('#aaa'))
            lbl.setFont(QFont("Segoe UI", 10))
            lbl.setPos(4, y_offset - 20)

            self._page_items.append((pix_item, y_offset, pw, ph, p, lbl, tb_items_for_page))
            y_offset += ph + self.PAGE_GAP

        # Center pages horizontally
        for pix_item, yo, pw, ph, p, lbl, tb_items in self._page_items:
            x_off = (max_width - pw) / 2
            pix_item.setPos(x_off, yo)
            lbl.setPos(x_off + 4, yo - 20)
            for it in tb_items:
                it._updating = True
                it.setData(1, x_off)  # store x offset for itemChange
                it.setPos(it.pos().x() + x_off, it.pos().y())
                it._updating = False

        self._max_page_width = max_width
        self._scene.setSceneRect(0, 0, max_width, y_offset)
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        # Defer fit-to-width to next event loop so viewport has correct size
        QTimer.singleShot(0, self._fit_zoom)

    def _get_pixmap(self, p, scale):
        if p.hires and p.hires_scale >= scale:
            return p.hires
        p.hires = render_page_pixmap(p.pdf_bytes, p.page_index, scale)
        p.hires_scale = scale
        return p.hires

    def _fit_zoom(self):
        """Fit page width to viewport."""
        vp_w = self.viewport().width() - 40
        mw = getattr(self, '_max_page_width', 0)
        if mw > 0 and vp_w > 0:
            self._zoom = min(1.0, vp_w / mw)
        self.resetTransform()
        self.scale(self._zoom, self._zoom)
        # Scroll to start page
        start = getattr(self, '_start_idx', 0)
        if start and 0 < start < len(self._page_items):
            self.go(start)
        self._emit_current_page()
        self._schedule_hires()
        # Sync slider in main window
        w = self.window()
        if hasattr(w, '_sync_zoom_display'):
            w._sync_zoom_display()

    def _schedule_hires(self):
        self._hires_timer.start(100)

    def _upgrade_visible(self):
        """Upgrade only visible pages to high-res."""
        vp = self.mapToScene(self.viewport().rect()).boundingRect()
        margin = vp.height()  # pre-render one screen above/below
        for pix_item, yo, pw, ph, p, *_ in self._page_items:
            if yo + ph < vp.top() - margin or yo > vp.bottom() + margin:
                continue
            if p.hires_scale >= self.HIRES_SCALE:
                continue
            pm = self._get_pixmap(p, self.HIRES_SCALE)
            pix_item.setPixmap(pm)
            QApplication.processEvents()  # keep UI responsive

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
        for i, (_, yo, _, ph, *_) in enumerate(self._page_items):
            d = abs(yo + ph/2 - center_y)
            if d < best_dist:
                best_dist = d; best = i
        return best

    @property
    def total(self): return len(self._pages)
    @property
    def zoom_val(self): return self._zoom

    def set_zoom(self, z):
        self._zoom = max(0.25, min(5.0, z))
        self.resetTransform()
        self.scale(self._zoom, self._zoom)

    def go(self, idx):
        if 0 <= idx < len(self._page_items):
            _, yo, *_ = self._page_items[idx]
            self.centerOn(0, yo)
            self._emit_current_page()

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
        """Find which page a scene position belongs to. Returns (page_data, local_x, local_y, pw, ph, x_off) or None."""
        mw = getattr(self, '_max_page_width', 0)
        for _, yo, pw, ph, p, *__ in self._page_items:
            x_off = (mw - pw) / 2 if mw else 0
            if yo <= scene_pos.y() <= yo + ph and x_off <= scene_pos.x() <= x_off + pw:
                return p, scene_pos.x() - x_off, scene_pos.y() - yo, pw, ph, x_off
        return None

    def mousePressEvent(self, e):
        if self._placing and e.button() == Qt.LeftButton:
            sp = self.mapToScene(e.position().toPoint())
            hit = self._find_page_at(sp)
            if hit:
                p, lx, ly, pw, ph, x_off = hit
                tb = TextBoxData(p.id, lx/pw*100, ly/ph*100)
                self._textboxes.append(tb)
                it = TextBoxItem(tb, pw, ph)
                # Position in scene coords
                yo = next(yo for _, yo, _, _, pp, *__ in self._page_items if pp.id == p.id)
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
            e.accept()
        else:
            super().wheelEvent(e)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._scroll_timer.start(80)
        self._schedule_hires()

    def selected_tb(self):
        for it in self._scene.selectedItems():
            if isinstance(it, TextBoxItem): return it
        return None

    def delete_selected(self):
        it = self.selected_tb()
        if it:
            if it.tb in self._textboxes: self._textboxes.remove(it.tb)
            self._scene.removeItem(it)
            if it in self._tb_items: self._tb_items.remove(it)
            self.tb_deselected.emit()

    def copy_selected(self):
        it = self.selected_tb()
        if it: self._copied = it.tb

    def paste_tb(self):
        if not self._copied or not self._pages: return
        src = self._copied
        # Paste on the currently visible page
        idx = self.cur
        p = self._pages[idx]
        _, yo, pw, ph, *_ = self._page_items[idx]
        mw = getattr(self, '_max_page_width', 0)
        x_off = (mw - pw) / 2 if mw else 0
        tb = TextBoxData(p.id, src.x_pct+2, src.y_pct+2)
        for attr in ('width_pct','height_pct','text','font_family','font_size','font_color','bold','italic','border_color','border_width','bg_color'):
            setattr(tb, attr, getattr(src, attr))
        self._textboxes.append(tb)
        it = TextBoxItem(tb, pw, ph)
        it._updating = True
        it.setData(0, yo)
        it.setData(1, x_off)
        it.setPos(x_off + tb.x_pct/100*pw, yo + tb.y_pct/100*ph)
        it._updating = False
        self._scene.addItem(it)
        self._tb_items.append(it)
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
        self._hires_timer=QTimer(self); self._hires_timer.setSingleShot(True)
        self._hires_timer.timeout.connect(self._upgrade_preview)

    def _build_scene(self):
        """Build scene from current pixmap and textboxes (shared by set_page and _upgrade_preview)."""
        self._scene.clear()
        self._scene.addPixmap(self._pm)
        pw, ph = self._pm.width(), self._pm.height()
        for tb in self._textboxes:
            if tb.page_id == self._pd.id:
                it = TextBoxItem(tb, pw, ph)
                it.setFlags(QGraphicsItem.ItemIsSelectable)  # read-only in preview
                self._scene.addItem(it)
        self._scene.setSceneRect(0, 0, pw, ph)

    def set_page(self, pd, idx, total, textboxes=None):
        self._pd = pd
        self._textboxes = textboxes or []
        self.info.setText(f"Page {idx+1} / {total} — {pd.label}")
        self._render_scale = 3.0
        self._pm = render_page_pixmap(pd.pdf_bytes, pd.page_index, self._render_scale)
        self._build_scene()
        self._zoom = 1.0; self._zs.setValue(100)
        self._view.resetTransform()
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        t=self._view.transform(); self._zoom=t.m11(); self._sync()

    def _apply(self):
        self._view.resetTransform(); self._view.scale(self._zoom, self._zoom)
        self._sync()
        # Debounce hi-res re-render
        self._hires_timer.start(250)

    def _upgrade_preview(self):
        if not self._pd: return
        needed = max(3.0, self._zoom * 3.0)
        if needed <= self._render_scale: return
        self._render_scale = min(needed, 8.0)
        self._pm = render_page_pixmap(self._pd.pdf_bytes, self._pd.page_index, self._render_scale)
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


# ══════════════════════════════════════════════════════════════
#  MainWindow
# ══════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    _update_available = Signal(str)
    _update_downloaded = Signal(str)
    _update_download_failed = Signal()

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
        self._build_toolbar(); self._build_central(); self._build_reader_nav(); self._build_tb_props()
        self.toast = ToastManager(self)
        self._update_state()
        self._check_update()

    def _check_update(self):
        def _fetch():
            try:
                req = Request(UPDATE_URL, headers={"Accept": "application/vnd.github+json"})
                resp = urlopen(req, timeout=5)
                data = json.loads(resp.read().decode())
                remote = data.get("tag_name", "").lstrip("v")
                if remote and remote != VERSION:
                    self._update_available.emit(remote)
            except Exception:
                pass
        threading.Thread(target=_fetch, daemon=True).start()

    def _show_update_toast(self, remote_version):
        msg = f"Mise à jour disponible (v{remote_version})"
        t = QLabel(msg, self)
        t.setCursor(Qt.PointingHandCursor)
        t.setStyleSheet(
            f"background:{C['primary']};color:#fff;padding:12px 22px;"
            f"border-radius:8px;font-size:13px;font-weight:bold;"
        )
        t.setToolTip("Cliquez pour lancer la mise à jour")
        t.adjustSize()
        t.move(self.width() - t.width() - 24, self.height() - t.height() - 24)
        t.show(); t.raise_()
        t.mousePressEvent = lambda e: self._launch_update(t)

    def _launch_update(self, toast_label):
        toast_label.hide()
        self.toast.show("Téléchargement de la mise à jour...", 'info')
        download_url = "https://github.com/yannsokol-web/EDITEUR2PDF/releases/latest/download/InstallEditeurPDF.exe"

        def _download():
            try:
                tmp = os.path.join(tempfile.gettempdir(), "InstallEditeurPDF.exe")
                urlretrieve(download_url, tmp)
                self._update_downloaded.emit(tmp)
            except Exception:
                self._update_download_failed.emit()

        threading.Thread(target=_download, daemon=True).start()

    def _on_update_downloaded(self, path):
        subprocess.Popen([path])
        QTimer.singleShot(500, self.close)

    def _on_update_download_failed(self):
        self.toast.show("Échec du téléchargement de la mise à jour.", 'error')

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
        self.grid_scroll.setStyleSheet(f"QScrollArea{{border:none;background:{C['bg']};}}"); self.grid_scroll.setAcceptDrops(True)
        self.grid_widget=QWidget(); self.grid_layout=FlowLayout(self.grid_widget, spacing=20)
        self.grid_layout.setContentsMargins(24,24,24,24); self.grid_scroll.setWidget(self.grid_widget)
        self.splitter.addWidget(self.grid_scroll)
        self.preview=PreviewPanel(); self.preview.closed.connect(self._close_preview); self.preview.hide()
        self.splitter.addWidget(self.preview)
        self.splitter.setStretchFactor(0,1); self.splitter.setStretchFactor(1,0); self.splitter.setSizes([800,380])
        self.stack.addWidget(self.splitter)
        self.reader=ReaderView()
        self.reader.tb_selected.connect(self._on_tb_selected)
        self.reader.tb_deselected.connect(self._on_tb_deselected)
        self.reader.page_changed.connect(self._on_reader_page)
        self.stack.addWidget(self.reader)

    def _rebuild_grid(self):
        while self.grid_layout.count():
            it=self.grid_layout.takeAt(0)
            if it and it.widget(): it.widget().deleteLater()
        # Preserve valid selections
        valid_ids = {p.id for p in self.pages}
        self.selected_ids &= valid_ids
        self._update_sel_btns()
        for i, p in enumerate(self.pages):
            card=PageCard(p, i, self.textboxes)
            card.selected = p.id in self.selected_ids
            card.clicked.connect(self._on_card_click)
            card.delete_clicked.connect(self._delete_page)
            self.grid_layout.addWidget(card)
        self.grid_widget.adjustSize()

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
            start_idx = getattr(self, '_preview_page_idx', None)
            if start_idx is None: start_idx = 0
            self.stack.setCurrentIndex(2); self.rnav.show()
            self.add_btn.hide(); self.exp_sel_btn.hide(); self.del_sel_btn.hide(); self.preview.hide()
            self.reader.set_data(self.pages, self.textboxes, start_idx)
            self._sync_zoom_display(); self._update_rnav(); self._pos_rnav()
        else:
            self.stack.setCurrentIndex(1); self.rnav.hide(); self.tbprops.hide(); self.add_btn.show()
            self._rebuild_grid()
        self._update_mode_style()

    def load_files(self, paths):
        if self.mode=='read': self._switch_mode('edit')
        self.insert_files_at(paths, len(self.pages), msg_verb="chargée")

    def insert_files_at(self, paths, at_index, msg_verb="insérée"):
        """Insert PDF files at a specific index."""
        QApplication.setOverrideCursor(Qt.WaitCursor); count=0; errors=[]
        for path in paths:
            try:
                with open(path,'rb') as f: data=f.read()
                doc=get_cached_doc(data); name=os.path.basename(path)
                for i in range(len(doc)):
                    pix=doc[i].get_pixmap(matrix=fitz.Matrix(0.5,0.5),alpha=False)
                    img=QImage(pix.samples,pix.width,pix.height,pix.stride,QImage.Format_RGB888)
                    self.pages.insert(at_index+count, PageData(data,i,f"{name} – p.{i+1}",QPixmap.fromImage(img)))
                    count+=1
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")
        if count:
            self._rebuild_grid(); self._update_state()
            self.toast.show(f"{count} page(s) {msg_verb}(s).", 'success')
        for err in errors:
            self.toast.show(f"Erreur: {err}", 'error')
        QApplication.restoreOverrideCursor()

    def _on_card_click(self, page_id):
        mods=QApplication.keyboardModifiers()
        clicked_idx = next((i for i, p in enumerate(self.pages) if p.id == page_id), None)
        if clicked_idx is None: return
        if mods & Qt.ControlModifier:
            if page_id in self.selected_ids: self.selected_ids.discard(page_id)
            else: self.selected_ids.add(page_id)
            self._last_selected_idx = clicked_idx
            self._sync_card_selection(); self._update_sel_btns()
        elif mods & Qt.ShiftModifier:
            anchor = getattr(self, '_last_selected_idx', 0)
            lo, hi = min(anchor, clicked_idx), max(anchor, clicked_idx)
            for i in range(lo, hi + 1):
                self.selected_ids.add(self.pages[i].id)
            self._sync_card_selection(); self._update_sel_btns()
        else:
            self.selected_ids.clear(); self._last_selected_idx = clicked_idx
            self._sync_card_selection(); self._update_sel_btns()
            p = self.pages[clicked_idx]
            self._preview_page_idx = clicked_idx
            self.preview.set_page(p, clicked_idx, len(self.pages), self.textboxes)
            if not self.preview.isVisible():
                self.preview.show()
                self.splitter.setSizes([self.splitter.width()-380, 380])

    def _sync_card_selection(self):
        for i in range(self.grid_layout.count()):
            it=self.grid_layout.itemAt(i)
            if it and it.widget() and isinstance(it.widget(), PageCard):
                it.widget().selected = it.widget().page_data.id in self.selected_ids

    def move_pages_to(self, src_ids, target_idx):
        """Move multiple pages to a target index."""
        moving = [p for p in self.pages if p.id in src_ids]
        remaining = [p for p in self.pages if p.id not in src_ids]
        # Adjust target index
        before_count = sum(1 for p in self.pages[:target_idx] if p.id not in src_ids)
        self.pages = remaining[:before_count] + moving + remaining[before_count:]
        self._rebuild_grid()

    def _delete_page(self, pid):
        self.pages=[p for p in self.pages if p.id!=pid]
        self.textboxes=[t for t in self.textboxes if t.page_id!=pid]
        self._cleanup_cache()
        self.selected_ids.discard(pid); self._rebuild_grid(); self._update_state(); self.preview.hide(); self._preview_page_idx = None

    def _delete_selection(self):
        ids=set(self.selected_ids)
        self.pages=[p for p in self.pages if p.id not in ids]
        self.textboxes=[t for t in self.textboxes if t.page_id not in ids]
        self._cleanup_cache()
        self.selected_ids.clear(); self._rebuild_grid(); self._update_state(); self.preview.hide(); self._preview_page_idx = None

    def _cleanup_cache(self):
        """Ferme et supprime les documents PDF qui ne sont plus référencés."""
        live = {id(p.pdf_bytes) for p in self.pages}
        for key in list(_pdf_doc_cache):
            if key not in live:
                _pdf_doc_cache[key].close()
                del _pdf_doc_cache[key]

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
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out=fitz.open()
            # Font size in editor is in Qt points rendered on a HIRES_SCALE-enlarged page.
            # Scale it down so the exported PDF text matches the editor appearance.
            dpi = QApplication.primaryScreen().logicalDotsPerInch()
            font_scale = dpi / 72.0 / ReaderView.HIRES_SCALE
            for pd in plist:
                src=get_cached_doc(pd.pdf_bytes)
                out.insert_pdf(src,from_page=pd.page_index,to_page=pd.page_index)
                op=out[-1]; pw,ph=op.rect.width,op.rect.height
                for tb in self.textboxes:
                    if tb.page_id!=pd.id or not tb.text.strip(): continue
                    x,y=tb.x_pct/100*pw,tb.y_pct/100*ph
                    w,h=tb.width_pct/100*pw,tb.height_pct/100*ph
                    r=fitz.Rect(x,y,x+w,y+h)
                    if tb.bg_color!='transparent':
                        sh=op.new_shape(); sh.draw_rect(r); sh.finish(fill=self._hex2c(tb.bg_color)); sh.commit()
                    if tb.border_width>0 and tb.border_color!='transparent':
                        sh=op.new_shape(); sh.draw_rect(r); sh.finish(color=self._hex2c(tb.border_color),width=tb.border_width); sh.commit()
                    fn="helv"
                    if 'Times' in tb.font_family or 'Georgia' in tb.font_family: fn="tiro"
                    elif 'Courier' in tb.font_family: fn="cour"
                    tr=fitz.Rect(x+2,y+2,x+w-2,y+h-2)
                    pdf_fs=tb.font_size*font_scale
                    op.insert_textbox(tr,tb.text,fontsize=pdf_fs,fontname=fn,color=self._hex2c(tb.font_color))
            out.save(path); out.close()
            self.toast.show(f"Export réussi ({len(plist)} pages) !", 'success')
        except Exception as e: self.toast.show(f"Erreur export: {e}", 'error')
        finally: QApplication.restoreOverrideCursor()

    def _hex2c(self, h):
        h=h.lstrip('#'); return (int(h[0:2],16)/255,int(h[2:4],16)/255,int(h[4:6],16)/255)

    def _on_reader_page(self, num): self._update_rnav()
    def _update_rnav(self):
        t=self.reader.total; c=self.reader.cur+1
        self.rpage.setText(f"Page {c} / {t}"); self.rprev.setEnabled(c>1); self.rnext.setEnabled(c<t)

    def _toggle_placing(self):
        v=self.tb_place_btn.isChecked(); self.reader.set_placing(v)
        self.tb_place_btn.setStyleSheet(f"QPushButton{{background:{C['primary'] if v else 'none'};border:none;color:#eee;font-size:18px;padding:2px 8px;border-radius:6px;}}QPushButton:hover{{background:rgba(255,255,255,30);}}")

    def _on_tb_placed(self): self.tb_place_btn.setChecked(False); self._toggle_placing()
    def _reset_zoom(self): self.reader.set_zoom(1.0); self.rzoom.setValue(100); self.rzlbl.setText("100%")
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

    def _close_preview(self): self.preview.hide(); self._preview_page_idx = None

    def _pos_tbprops(self):
        self.tbprops.adjustSize()
        self.tbprops.move(max(10,(self.width()-self.tbprops.width())//2), self.height()-self.tbprops.height()-80); self.tbprops.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.rnav.isVisible(): self._pos_rnav()
        if self.tbprops.isVisible(): self._pos_tbprops()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith('.pdf') for u in e.mimeData().urls()):
            e.acceptProposedAction()
    def dropEvent(self, e):
        files=[u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith('.pdf')]
        if files: self.load_files(files); e.acceptProposedAction()


def main():
    app=QApplication(sys.argv); app.setStyle('Fusion')
    if os.path.exists(ICON_PATH): app.setWindowIcon(QIcon(ICON_PATH))
    app.setFont(QFont("Segoe UI", 10))
    w=MainWindow(); w.show(); sys.exit(app.exec())

if __name__=='__main__':
    main()
