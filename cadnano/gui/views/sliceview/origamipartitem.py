from PyQt5.QtCore import QPointF, Qt, QLineF, QRectF, QEvent, pyqtSignal, pyqtSlot, QObject
from PyQt5.QtGui import QBrush, QColor, QPainterPath, QPen
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsEllipseItem
from PyQt5.QtWidgets import QGraphicsRectItem
from PyQt5.QtWidgets import QApplication

from cadnano import util
from cadnano import getReopen
from cadnano.gui.controllers.itemcontrollers.origamipartitemcontroller import OrigamiPartItemController
from cadnano.gui.views.abstractpartitem import AbstractPartItem
from . import slicestyles as styles
from .emptyhelixitem import EmptyHelixItem
from .virtualhelixitem import VirtualHelixItem
from .activesliceitem import ActiveSliceItem


_RADIUS = styles.SLICE_HELIX_RADIUS
_DEFAULT_RECT = QRectF(0, 0, 2 * _RADIUS, 2 * _RADIUS)
HIGHLIGHT_WIDTH = styles.SLICE_HELIX_MOD_HILIGHT_WIDTH
DELTA = (HIGHLIGHT_WIDTH - styles.SLICE_HELIX_STROKE_WIDTH)/2.
_HOVER_RECT = _DEFAULT_RECT.adjusted(-DELTA, -DELTA, DELTA, DELTA)
_MOD_PEN = QPen(styles.BLUE_STROKE, HIGHLIGHT_WIDTH)

_BOUNDING_RECT_PADDING = 10

class OrigamiPartItem(QGraphicsItem, AbstractPartItem):
    _RADIUS = styles.SLICE_HELIX_RADIUS

    def __init__(self, model_part_instance, parent=None):
        """
        Parent should be either a SliceRootItem, or an AssemblyItem.

        Invariant: keys in _empty_helix_hash = range(_nrows) x range(_ncols)
        where x is the cartesian product.

        Order matters for deselector, probe, and setlattice
        """
        super(OrigamiPartItem, self).__init__(parent)
        self._model_instance = model_part_instance
        self._model_part = m_p = model_part_instance.object()
        self._model_props = m_props = m_p.getPropertyDict()
        self._controller = OrigamiPartItemController(self, m_p)
        self._active_slice_item = ActiveSliceItem(self, m_p.activeBaseIndex())
        self._scaleFactor = self._RADIUS/m_p.radius()
        self._empty_helix_hash = {}
        self._virtual_helix_hash = {}
        self._nrows, self._ncols = 0, 0
        self._rect = QRectF(0, 0, 0, 0)
        self._initDeselector()
        # Cache of VHs that were active as of last call to activeSliceChanged
        # If None, all slices will be redrawn and the cache will be filled.
        # Connect destructor. This is for removing a part from scenes.
        self.probe = self.IntersectionProbe(self)
        # initialize the OrigamiPartItem with an empty set of old coords
        self._setLattice([], m_p.generatorFullLattice())
        self.setFlag(QGraphicsItem.ItemHasNoContents)  # never call paint
        self.setZValue(styles.ZPARTITEM)
        self._initModifierCircle()

        _p = _BOUNDING_RECT_PADDING
        self._outlinerect = _orect = self.childrenBoundingRect().adjusted(-_p, -_p, _p, _p)
        self._outline = QGraphicsRectItem(_orect, self)
        self._outline.setPen(QPen(QColor(m_props["color"])))

        self._drag_handle = OrigamiDragHandle(QRectF(_orect), self)

        # move down
        if len(m_p.document().children()) > 1:
            p = parent.childrenBoundingRect().bottomLeft()
            self.setPos(p.x() + _p, p.y() + _p*2)

        # select upon creation
        for _part in m_p.document().children():
            if _part is m_p:
                _part.setSelected(True)
            else:
                _part.setSelected(False)
    # end def

    def _initDeselector(self):
        """
        The deselector grabs mouse events that missed a slice and clears the
        selection when it gets one.
        """
        self.deselector = ds = OrigamiPartItem.Deselector(self)
        ds.setParentItem(self)
        ds.setFlag(QGraphicsItem.ItemStacksBehindParent)
        ds.setZValue(styles.ZDESELECTOR)

    def _initModifierCircle(self):
        self._can_show_mod_circ = False
        self._mod_circ = m_c = QGraphicsEllipseItem(_HOVER_RECT, self)
        m_c.setPen(_MOD_PEN)
        m_c.hide()
    # end def

    ### SIGNALS ###

    ### SLOTS ###
    def partActiveVirtualHelixChangedSlot(self, part, virtualHelix):
        pass

    def partPropertyChangedSlot(self, model_part, property_key, new_value):
        if self._model_part == model_part:
            if property_key == "color":
                pass
                # color = QColor(new_value)
                # self._outer_line.updateColor(color)
                # self._inner_line.updateColor(color)
                # self._hover_region.dummy.updateColor(color)
                # for dsi in self._selection_items:
                #     dsi.updateColor(color)
            elif property_key == "circular":
                pass
            elif property_key == "dna_sequence":
                pass
                # self.updateRects()
    # end def

    def partRemovedSlot(self, sender):
        """docstring for partRemovedSlot"""
        self._active_slice_item.removed()
        self.parentItem().removeOrigamiPartItem(self)

        scene = self.scene()

        self._virtual_helix_hash = None

        for item in list(self._empty_helix_hash.items()):
            key, val = item
            scene.removeItem(val)
            del self._empty_helix_hash[key]
        self._empty_helix_hash = None

        scene.removeItem(self)

        self._model_part = None
        self.probe = None
        self._mod_circ = None

        self.deselector = None
        self._controller.disconnectSignals()
        self._controller = None
    # end def

    def partVirtualHelicesReorderedSlot(self, sender, orderedCoordList):
        pass
    # end def

    def partPreDecoratorSelectedSlot(self, sender, row, col, baseIdx):
        """docstring for partPreDecoratorSelectedSlot"""
        vhi = self.getVirtualHelixItemByCoord(row, col)
        view = self.window().slice_graphics_view
        view.scene_root_item.resetTransform()
        view.centerOn(vhi)
        view.zoomIn()
        mC = self._mod_circ
        x,y = self._model_part.latticeCoordToPositionXY(row, col, self.scaleFactor())
        mC.setPos(x,y)
        if self._can_show_mod_circ:
            mC.show()
    # end def

    def partVirtualHelixAddedSlot(self, sender, virtual_helix):
        vh = virtual_helix
        coords = vh.coord()

        empty_helix_item = self._empty_helix_hash[coords]
        # TODO test to see if self._virtual_helix_hash is necessary
        vhi = VirtualHelixItem(vh, empty_helix_item)
        self._virtual_helix_hash[coords] = vhi
    # end def

    def partVirtualHelixRenumberedSlot(self, sender, coord):
        pass
    # end def

    def partVirtualHelixResizedSlot(self, sender, coord):
        pass
    # end def

    def updatePreXoverItemsSlot(self, sender, virtualHelix):
        pass
    # end def

    def partColorChangedSlot(self):
        print("sliceview origamipart partColorChangedSlot")
    # end def

    def partSelectedChangedSlot(self, model_part, is_selected):
        if is_selected:
            self._drag_handle.resetBrush(styles.SELECTED_ALPHA)
            self.setZValue(styles.ZPARTITEM+1)
        else:
            self._drag_handle.resetBrush(styles.DEFAULT_ALPHA)
            self.setZValue(styles.ZPARTITEM)

    ### ACCESSORS ###
    def boundingRect(self):
        return self._rect
    # end def

    def part(self):
        return self._model_part
    # end def

    def scaleFactor(self):
        return self._scaleFactor
    # end def

    def setPart(self, new_part):
        self._model_part = new_part
    # end def

    def window(self):
        return self.parentItem().window()
    # end def

    ### PRIVATE SUPPORT METHODS ###
    def _upperLeftCornerForCoords(self, row, col):
        pass  # subclass
    # end def

    def _updateGeometry(self):
        self._rect = QRectF(0, 0, *self.part().dimensions())
    # end def

    def _spawnEmptyHelixItemAt(self, row, column):
        helix = EmptyHelixItem(row, column, self)
        # helix.setFlag(QGraphicsItem.ItemStacksBehindParent, True)
        self._empty_helix_hash[(row, column)] = helix
    # end def

    def _killHelixItemAt(row, column):
        s = self._empty_helix_hash[(row, column)]
        s.scene().removeItem(s)
        del self._empty_helix_hash[(row, column)]
    # end def

    def _setLattice(self, old_coords, new_coords):
        """A private method used to change the number of rows,
        cols in response to a change in the dimensions of the
        part represented by the receiver"""
        old_set = set(old_coords)
        old_list = list(old_set)
        new_set = set(new_coords)
        new_list = list(new_set)
        for coord in old_list:
            if coord not in new_set:
                self._killHelixItemAt(*coord)
        # end for
        for coord in new_list:
            if coord not in old_set:
                self._spawnEmptyHelixItemAt(*coord)
        # end for
        # self._updateGeometry(newCols, newRows)
        # self.prepareGeometryChange()
        # the Deselector copies our rect so it changes too
        self.deselector.prepareGeometryChange()
        if not getReopen():
            self.zoomToFit()
    # end def

    ### PUBLIC SUPPORT METHODS ###
    def getVirtualHelixItemByCoord(self, row, column):
        if (row, column) in self._empty_helix_hash:
            return self._virtual_helix_hash[(row, column)]
        else:
            return None
    # end def

    def paint(self, painter, option, widget=None):
        pass
    # end def

    def selectionWillChange(self, newSel):
        if self.part() is None:
            return
        if self.part().selectAllBehavior():
            return
        for sh in self._empty_helix_hash.values():
            sh.setSelected(sh.virtualHelix() in newSel)
    # end def

    def setModifyState(self, bool):
        """Hides the mod_rect when modify state disabled."""
        self._can_show_mod_circ = bool
        if bool == False:
            self._mod_circ.hide()

    def updateStatusBar(self, statusString):
        """Shows statusString in the MainWindow's status bar."""
        pass  # disabled for now.
        # self.window().statusBar().showMessage(statusString, timeout)

    def vhAtCoordsChanged(self, row, col):
        self._empty_helix_hash[(row, col)].update()
    # end def

    def zoomToFit(self):
        thescene = self.scene()
        theview = thescene.views()[0]
        theview.zoomToFit()
    # end def

    ### EVENT HANDLERS ###
    def mousePressEvent(self, event):
        # self.createOrAddBasesToVirtualHelix()
        self.part().setSelected(True)
        QGraphicsItem.mousePressEvent(self, event)
    # end def


    class Deselector(QGraphicsItem):
        """The deselector lives behind all the slices and observes mouse press
        events that miss slices, emptying the selection when they do"""
        def __init__(self, parent_HGI):
            super(OrigamiPartItem.Deselector, self).__init__()
            self.parent_HGI = parent_HGI
        def mousePressEvent(self, event):
            self.parent_HGI.part().setSelection(())
            super(OrigamiPartItem.Deselector, self).mousePressEvent(event)
        def boundingRect(self):
            return self.parent_HGI.boundingRect()
        def paint(self, painter, option, widget=None):
            pass


    class IntersectionProbe(QGraphicsItem):
        def boundingRect(self):
            return QRectF(0, 0, .1, .1)
        def paint(self, painter, option, widget=None):
            pass


class OrigamiDragHandle(QGraphicsRectItem):
    def __init__(self, rect, parent=None):
        super(QGraphicsRectItem, self).__init__(rect, parent)
        self._parent = parent
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setPen(QPen(Qt.NoPen))
        self.resetBrush(styles.DEFAULT_ALPHA)
    # end def

    def updateRect(self, rect):
        """docstring for updateRect"""
        w = rect.width()*.6
        self.setRect(rect.adjusted(w,w,-w,-w).normalized())
    # end def

    def resetBrush(self, alpha):
        col = QColor(self._parent._model_props["color"])
        col.setAlpha(alpha)
        self.setBrush(QBrush(col))
    # end def

    def getCursor(self, pos):
        _r = self._parent._outlinerect
        _x, _y = pos.x(), pos.y()
        _width = 6
        _atLeft = True if abs(_x - _r.left()) < _width else False
        _atRight = True if abs(_x - _r.right()) < _width else False
        _atTop = True  if abs(_y - _r.top()) < _width else False
        _atBottom = True  if abs(_y - _r.bottom()) < _width else False
        if ((_atLeft and _atBottom) or (_atRight and _atTop)):
            _cursor = Qt.SizeBDiagCursor
        elif ((_atLeft and _atTop) or (_atRight and _atBottom)):
            _cursor = Qt.SizeFDiagCursor
        elif ((_atLeft or _atRight) and not (_atTop or _atBottom)):
            _cursor = Qt.SizeHorCursor 
        elif ((_atTop or _atBottom) and not (_atLeft or _atRight)):
            _cursor = Qt.SizeVerCursor 
        else:
            _cursor = Qt.OpenHandCursor
        return _cursor

    def hoverEnterEvent(self, event):
        _cursor = self.getCursor(event.pos())
        self.setCursor(_cursor)
    # end def

    def hoverMoveEvent(self, event):
        _cursor = self.getCursor(event.pos())
        self.setCursor(_cursor)
    # end def

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
    # end def

    def mousePressEvent(self, event):
        self.setCursor(Qt.ClosedHandCursor)
        # select this part and deselect everything else
        for _part in self._parent.part().document().children():
            if _part is self._parent.part():
                _part.setSelected(True)
            else:
                _part.setSelected(False)
        self._drag_mousedown_pos = event.pos()

        # _startZ = _maxZ = self.zValue()
        # _colliding = self.collidingItems(Qt.IntersectsItemBoundingRect)
        # # print(self, _startZ)
        # for item in _colliding:
        #     # print(item, item.zValue(), _maxZ)
        #     if item.zValue() >= _maxZ:
        #         _maxZ = item.zValue() + 1
        # if _maxZ > _startZ:
        #     self.setZValue(_maxZ)
        #     # print (_startZ, _maxZ)


    # end def

    def mouseMoveEvent(self, event):
        m = QLineF(event.screenPos(), event.buttonDownScreenPos(Qt.LeftButton))
        if m.length() < QApplication.startDragDistance():
            return
        p = self.mapToScene(QPointF(event.pos()) - QPointF(self._drag_mousedown_pos))
        # still need to correct for qgraphicsview translation
        self._parent.setPos(p)

        # eventAngle = self.updateDragHandleLine(event)
        # # Record initial direction before calling getSpanAngle
        # if self._clockwise is None:
        #     self._clockwise = False if eventAngle > self._startAngle else True
        # spanAngle = self.getSpanAngle(eventAngle)
        # self.dummy.updateAngle(self._startAngle, spanAngle)
    # end def

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.OpenHandCursor)

        # self.dummy.hide()
        # endAngle = self.updateDragHandleLine(event)
        # spanAngle = self.getSpanAngle(endAngle)
        # 
        # if self._startPos != None and self._clockwise != None:
        #     self.parentItem().addSelection(self._startAngle, spanAngle)
        #     self._startPos = self._clockwise = None
        # 
        # mark the end
        # x = self._DragHandleLine.x()
        # y = self._DragHandleLine.y()
        # f = QGraphicsEllipseItem(x, y, 6, 6, self)
        # f.setPen(QPen(Qt.NoPen))
        # f.setBrush(QBrush(QColor(204, 0, 0, 128)))
    # end def
# end class
