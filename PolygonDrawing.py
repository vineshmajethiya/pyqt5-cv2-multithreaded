from PyQt5.QtWidgets import QWidget, QMessageBox, QDialog
from PyQt5.QtCore import qDebug, QRect, pyqtSignal, QPoint, Qt
from PyQt5.QtGui import QPixmap, QBrush, QPen, QPainter, QPolygon
from PyQt5 import QtCore, QtGui, QtWidgets

from ui_PolygonDrawing import Ui_PolygonDrawing

class PolygonDrawing(QDialog, Ui_PolygonDrawing):
    def __init__(self,parent=None):
        super(PolygonDrawing, self).__init__(parent)
        self.setupUi(self)
        self.frame_label.onMouseMoveEvent.connect(self.updateMouseCursorPosLabel)
        self.frame_label.onMouseClickEvent.connect(self.addPoint)
        self.frame_label.setScaledContents(True)

    def updateImage(self,pixmap):
        # self.pixmap = pixmap
        self.points = []
        self.pixmap_points = []
        self.frame_label.setPixmap(pixmap)
    
    def updateMouseCursorPosLabel(self):
        # Update mouse cursor position in info_label
        self.info_label.setText(
            "(%d,%d)" % (self.frame_label.getMouseCursorPos().x(), self.frame_label.getMouseCursorPos().y()))

        # Show pixel cursor position if camera is connected (image is being shown)
        if self.frame_label.pixmap():
            # Scaling factor calculation depends on whether frame is scaled to fit label or not
            if not self.frame_label.hasScaledContents():
                xScalingFactor = (self.frame_label.getMouseCursorPos().x() - (
                        self.frame_label.width() - self.frame_label.pixmap().width()) / 2) / self.frame_label.pixmap().width()
                yScalingFactor = (self.frame_label.getMouseCursorPos().y() - (
                        self.frame_label.height() - self.frame_label.pixmap().height()) / 2) / self.frame_label.pixmap().height()
            else:
                xScalingFactor = self.frame_label.getMouseCursorPos().x() / self.frame_label.width()
                yScalingFactor = self.frame_label.getMouseCursorPos().y() / self.frame_label.height()

            self.info_label.setText(
                '%s [%d,%d]' % (self.info_label.text(),
                                xScalingFactor * self.processingThread.getCurrentROI().width(),
                                yScalingFactor * self.processingThread.getCurrentROI().height()))

    def addPoint(self):
        if self.frame_label.pixmap():
            # Scaling factor calculation depends on whether frame is scaled to fit label or not
            if not self.frame_label.hasScaledContents():
                xScalingFactor = (self.frame_label.getMouseCursorPos().x() - (
                        self.frame_label.width() - self.frame_label.pixmap().width()) / 2) / self.frame_label.pixmap().width()
                yScalingFactor = (self.frame_label.getMouseCursorPos().y() - (
                        self.frame_label.height() - self.frame_label.pixmap().height()) / 2) / self.frame_label.pixmap().height()
            else:
                xScalingFactor = self.frame_label.getMouseCursorPos().x() / self.frame_label.width()
                yScalingFactor = self.frame_label.getMouseCursorPos().y() / self.frame_label.height()

            x = round(xScalingFactor * self.processingThread.getCurrentROI().width(),0)
            y = round(yScalingFactor * self.processingThread.getCurrentROI().height(),0)
            self.points.append((x,y))
            self.frame_label.pixmap_points.append(self.frame_label.getMouseCursorPos())