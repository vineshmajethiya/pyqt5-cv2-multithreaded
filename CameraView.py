from PyQt5.QtWidgets import QWidget, QMessageBox, QDialog
from PyQt5.QtCore import qDebug, QRect, pyqtSignal, QTimer,QPoint, Qt
from PyQt5.QtGui import QPixmap, QBrush, QPen, QPainter, QPolygon
from PyQt5 import QtCore, QtGui, QtWidgets

from ui_CameraView import Ui_CameraView
from CaptureThread import CaptureThread
from ImageProcessingSettingsDialog import ImageProcessingSettingsDialog
from ProcessingThread import ProcessingThread
from Structures import *
from PolygonDrawing import PolygonDrawing
import pandas as pd
import time

class CameraView(QWidget, Ui_CameraView):
    newImageProcessingFlags = pyqtSignal(ImageProcessingFlags)
    setROI = pyqtSignal(QRect)

    def __init__(self, parent, deviceUrl, sharedImageBuffer, cameraId):
        super(CameraView, self).__init__(parent)
        self.sharedImageBuffer = sharedImageBuffer
        self.cameraId = cameraId
        # Create image processing settings dialog
        self.imageProcessingSettingsDialog = ImageProcessingSettingsDialog(self)
        # Setup UI
        self.setupUi(self)
        # Save Device Url
        self.deviceUrl = deviceUrl
        # Initialize internal flag
        self.isCameraConnected = False
        # Set initial GUI state
        self.frameLabel.setText("No camera connected.")
        self.imageBufferBar.setValue(0)
        self.imageBufferLabel.setText("[000/000]")
        self.captureRateLabel.setText("")
        self.processingRateLabel.setText("")
        self.deviceUrlLabel.setText("")
        self.cameraResolutionLabel.setText("")
        self.roiLabel.setText("")
        self.mouseCursorPosLabel.setText("")
        self.clearImageBufferButton.setDisabled(True)
        # Initialize ImageProcessingFlags structure
        self.imageProcessingFlags = ImageProcessingFlags()
        # Connect signals/slots
        self.clearImageBufferButton.released.connect(self.clearImageBuffer)
        self.frameLabel.onMouseMoveEvent.connect(self.updateMouseCursorPosLabel)
        self.frameLabel.menu.triggered.connect(self.handleContextMenuAction)
        self.startButton.released.connect(self.startThread)
        self.pauseButton.released.connect(self.pauseThread)
        self.add_vehicle.released.connect(self.addVehicle)
        self.remove_vehicle.released.connect(self.remove_from_vehicle_list)
        self.save_and_quit.released.connect(self.save_quit)
        self.vehicle_up.toggled.connect(lambda:self.btnstate(self.vehicle_up))
        self.vehicle_down.toggled.connect(lambda:self.btnstate(self.vehicle_down))

        self.startButton.setEnabled(False)
        self.pauseButton.setEnabled(True)

        self.direction = "Up"
        self.add_vehicle_to_vehicle_list()
        self.group = QtWidgets.QButtonGroup()
        self.group.addButton(self.vehicle_up)
        self.group.addButton(self.vehicle_down)

        self.video_speed.currentIndexChanged.connect(self.change_speed)
        self.draw_polygon.released.connect(self.draw_polygon_f)
        self.polygon = PolygonDrawing()

    def draw_polygon_f(self):
        self.polygon.updateImage(self.frameLabel.pixmap())
        if self.polygon.exec() == QDialog.Accepted:
            print("Ok Karo")
        else:
            print("Not Okay")

    def change_speed(self):
        self.processingThread.speed = int(self.video_speed.currentText())

    def add_vehicle_to_vehicle_list(self):
        self.vehicle_select.addItems(["2 Wheeler", "Auto Rick", "Car-PVT", "Car-Taxi", "Car-Share", "Bus-Govt.", "Bus-2 Axle Private","Bus-3 Axle Private", "Bus-Institution", "Bus-Mini Bus", "Bus-2 Axle", "Bus-MAV", "Govt. Cars/ Jeep/ Vans","Army Vehicles/ Ambulance", "Govt trucks", "Cycle", "Animal Drawn", "Truck-2 Axle", "Truck-3 Axle","Truck-4 Axle", "Truck-5 Axle", "Truck-Axle>=6", "Truck-HC,EME", "LCV-4 Tyre", "LCV-6 Tyre", "LCV-Tata Ace","LCV-Mini LCV", "LCV-Goods Auto", "Const.-2 Axle Truck", "Const.-3 Axle Truck", "Const.-MAV up to 6 Axle","Tractor & Trailer", "Chakra"])

    def remove_from_vehicle_list(self):
        self.vehicle_list.takeItem(self.vehicle_list.currentRow())

    def save_quit(self):
        opt_list = []
        n = self.vehicle_list.count()
        i = 0
        while i < n:
            opt_list.append(self.vehicle_list.item(i).text())
            i+=1

        # print(opt_list)
        list_df = pd.DataFrame(opt_list)
        path = f"{time.time()}.xlsx"
        with pd.ExcelWriter(path) as writer:
            list_df.to_excel(writer, index=False, header=False)

        self.delete()
        self.close()

    def addVehicle(self):
        dt_string = self.sharedImageBuffer.video_date_time.strftime('%Y-%m-%d_%H:%M:%S')
        item = QtWidgets.QListWidgetItem()
        font = QtGui.QFont()
        font.setBold(False)
        font.setItalic(False)
        font.setUnderline(False)
        font.setWeight(50)
        font.setStrikeOut(False)
        font.setKerning(False)
        item.setFont(font)
        brush = QtGui.QBrush(QtGui.QColor(0, 0, 0))
        brush.setStyle(QtCore.Qt.NoBrush)
        item.setBackground(brush)
        brush = QtGui.QBrush(QtGui.QColor(0, 0, 255))
        brush.setStyle(QtCore.Qt.NoBrush)
        item.setForeground(brush)
        item.setText(f"{dt_string}_{self.direction}_{self.vehicle_select.currentText()}")
        self.vehicle_list.insertItem(0,item)

    def btnstate(self,b):
        self.direction = b.text()

    def delete(self):
        if self.isCameraConnected:
            # Stop processing thread
            if self.processingThread.isRunning():
                self.stopProcessingThread()
            # Stop capture thread
            if self.captureThread.isRunning():
                self.stopCaptureThread()

            # Automatically start frame processing (for other streams)
            if self.sharedImageBuffer.isSyncEnabledForDeviceUrl(self.deviceUrl):
                self.sharedImageBuffer.setSyncEnabled(True)

            # Disconnect camera
            if self.captureThread.disconnectCamera():
                qDebug("[%s] Camera successfully disconnected." % self.deviceUrl)
            else:
                qDebug("[%s] WARNING: Camera already disconnected." % self.deviceUrl)

    def afterCaptureThreadFinshed(self):
        # Delete Buffer
        self.sharedImageBuffer.removeByDeviceUrl(self.deviceUrl)

    def afterProcessingThreadFinshed(self):
        qDebug("[%s] WARNING: SQL already disconnected." % self.deviceUrl)

    def connectToCamera(self, dropFrameIfBufferFull, apiPreference, capThreadPrio,
                        procThreadPrio, enableFrameProcessing, width, height, setting):
        # Set frame label text
        if self.sharedImageBuffer.isSyncEnabledForDeviceUrl(self.deviceUrl):
            self.frameLabel.setText("Camera connected. Waiting...")
        else:
            self.frameLabel.setText("Connecting to camera...")

        # Create capture thread
        self.captureThread = CaptureThread(self.sharedImageBuffer, self.deviceUrl, dropFrameIfBufferFull,
                                           apiPreference, width, height, setting)
        # Attempt to connect to camera
        if self.captureThread.connectToCamera():
            # Create processing thread
            self.processingThread = ProcessingThread(self.sharedImageBuffer, self.deviceUrl, self.cameraId ,self)
            self.roi = [
                (0,self.processingThread.currentROI.height()*50/100),
                (self.processingThread.currentROI.width(),self.processingThread.currentROI.height()*50/100),
                (self.processingThread.currentROI.width(),self.processingThread.currentROI.height()*70/100),
                (0,self.processingThread.currentROI.height()*70/100),
            ]
            self.processingThread.app.setRoi(self.roi)
            self.polygon.processingThread = self.processingThread

            # Setup signal/slot connections
            self.processingThread.newFrame.connect(self.updateFrame)
            self.processingThread.updateStatisticsInGUI.connect(self.updateProcessingThreadStats)
            self.captureThread.updateStatisticsInGUI.connect(self.updateCaptureThreadStats)
            self.imageProcessingSettingsDialog.newImageProcessingSettings.connect(
                self.processingThread.updateImageProcessingSettings)
            self.newImageProcessingFlags.connect(self.processingThread.updateImageProcessingFlags)
            self.setROI.connect(self.processingThread.setROI)

            # Remove imageBuffer from shared buffer by deviceUrl after captureThread stop/finished
            self.captureThread.finished.connect(self.afterCaptureThreadFinshed)
            self.processingThread.finished.connect(self.afterProcessingThreadFinshed)

            # Only enable ROI setting/resetting if frame processing is enabled
            if enableFrameProcessing:
                self.frameLabel.newMouseData.connect(self.newMouseData)

            # Set initial data in processing thread
            self.setROI.emit(
                QRect(0, 0, self.captureThread.getInputSourceWidth(), self.captureThread.getInputSourceHeight()))
            self.newImageProcessingFlags.emit(self.imageProcessingFlags)
            self.imageProcessingSettingsDialog.updateStoredSettingsFromDialog()

            # Start capturing frames from camera
            self.captureThread.start(capThreadPrio)
            # Start processing captured frames (if enabled)
            if enableFrameProcessing:
                self.processingThread.start(procThreadPrio)

            # Setup imageBufferBar with minimum and maximum values
            self.imageBufferBar.setMinimum(0)
            self.imageBufferBar.setMaximum(self.sharedImageBuffer.getByDeviceUrl(self.deviceUrl).maxSize())

            # Enable "Clear Image Buffer" push button
            self.clearImageBufferButton.setEnabled(True)

            # Set text in labels
            self.deviceUrlLabel.setText(self.deviceUrl)
            self.cameraResolutionLabel.setText("%dx%d" % (self.captureThread.getInputSourceWidth(),
                                                          self.captureThread.getInputSourceHeight()))
            # Set internal flag and return
            self.isCameraConnected = True
            # Set frame label text
            if not enableFrameProcessing:
                self.frameLabel.setText("Frame processing disabled.")
            return True
        # Failed to connect to camera
        else:
            return False

    def stopCaptureThread(self):
        qDebug("[%s] About to stop capture thread..." % self.deviceUrl)
        self.captureThread.stop()
        self.sharedImageBuffer.wakeAll()  # This allows the thread to be stopped if it is in a wait-state
        # Take one frame off a FULL queue to allow the capture thread to finish
        if self.sharedImageBuffer.getByDeviceUrl(self.deviceUrl).isFull():
            self.sharedImageBuffer.getByDeviceUrl(self.deviceUrl).get()
        self.captureThread.wait()
        qDebug("[%s] Capture thread successfully stopped." % self.deviceUrl)

    def stopProcessingThread(self):
        qDebug("[%s] About to stop processing thread..." % self.deviceUrl)
        self.processingThread.stop()
        self.sharedImageBuffer.wakeAll()  # This allows the thread to be stopped if it is in a wait-state
        self.processingThread.wait()
        qDebug("[%s] Processing thread successfully stopped." % self.deviceUrl)

    def startThread(self):
        self.processingThread.pause = False
        self.captureThread.pause = False
        self.startButton.setEnabled(False)
        self.pauseButton.setEnabled(True)

    def pauseThread(self):
        self.processingThread.pause = True
        self.captureThread.pause = True
        self.startButton.setEnabled(True)
        self.pauseButton.setEnabled(False)

    def updateCaptureThreadStats(self, statData):
        imageBuffer = self.sharedImageBuffer.getByDeviceUrl(self.deviceUrl)
        # Show [number of images in buffer / image buffer size] in imageBufferLabel
        self.imageBufferLabel.setText("[%d/%d]" % (imageBuffer.size(), imageBuffer.maxSize()))
        # Show percentage of image buffer full in imageBufferBar
        self.imageBufferBar.setValue(imageBuffer.size())

        # Show processing rate in captureRateLabel
        self.captureRateLabel.setText("{:>6,.2f} fps".format(statData.averageFPS))
        # Show number of frames captured in nFramesCapturedLabel
        self.nFramesCapturedLabel.setText("[%d]" % statData.nFramesProcessed)

    def updateProcessingThreadStats(self, statData):
        # Show processing rate in processingRateLabel
        self.processingRateLabel.setText("{:>6,.2f} fps".format(statData.averageFPS))
        # Show ROI information in roiLabel
        self.roiLabel.setText("(%d,%d) %dx%d" % (self.processingThread.getCurrentROI().x(),
                                                 self.processingThread.getCurrentROI().y(),
                                                 self.processingThread.getCurrentROI().width(),
                                                 self.processingThread.getCurrentROI().height()))
        # Show number of frames processed in nFramesProcessedLabel
        self.nFramesProcessedLabel.setText("[%d]" % statData.nFramesProcessed)

    def updateFrame(self, frame):
        # Display frame
        pixmap = QPixmap.fromImage(frame).scaled(self.frameLabel.width(), self.frameLabel.height(), Qt.KeepAspectRatio)
        pixmap = self.draw_something(pixmap)
        self.frameLabel.setPixmap(pixmap)

    def clearImageBuffer(self):
        if self.sharedImageBuffer.getByDeviceUrl(self.deviceUrl).clear():
            qDebug("[%s] Image buffer successfully cleared." % self.deviceUrl)
        else:
            qDebug("[%s] WARNING: Could not clear image buffer." % self.deviceUrl)

    def setImageProcessingSettings(self):
        # Prompt user:
        # If user presses OK button on dialog, update image processing settings
        if self.imageProcessingSettingsDialog.exec() == QDialog.Accepted:
            self.imageProcessingSettingsDialog.updateStoredSettingsFromDialog()
        # Else, restore dialog state
        else:
            self.imageProcessingSettingsDialog.updateDialogSettingsFromStored()

    def updateMouseCursorPosLabel(self):
        # Update mouse cursor position in mouseCursorPosLabel
        self.mouseCursorPosLabel.setText(
            "(%d,%d)" % (self.frameLabel.getMouseCursorPos().x(), self.frameLabel.getMouseCursorPos().y()))

        # Show pixel cursor position if camera is connected (image is being shown)
        if self.frameLabel.pixmap():
            # Scaling factor calculation depends on whether frame is scaled to fit label or not
            if not self.frameLabel.hasScaledContents():
                xScalingFactor = (self.frameLabel.getMouseCursorPos().x() - (
                        self.frameLabel.width() - self.frameLabel.pixmap().width()) / 2) / self.frameLabel.pixmap().width()
                yScalingFactor = (self.frameLabel.getMouseCursorPos().y() - (
                        self.frameLabel.height() - self.frameLabel.pixmap().height()) / 2) / self.frameLabel.pixmap().height()
            else:
                xScalingFactor = self.frameLabel.getMouseCursorPos().x() / self.frameLabel.width()
                yScalingFactor = self.frameLabel.getMouseCursorPos().y() / self.frameLabel.height()

            self.mouseCursorPosLabel.setText(
                '%s [%d,%d]' % (self.mouseCursorPosLabel.text(),
                                xScalingFactor * self.processingThread.getCurrentROI().width(),
                                yScalingFactor * self.processingThread.getCurrentROI().height()))

    def newMouseData(self, mouseData):
        # Local variable(s)
        selectionBox = QRect()
        # Set ROI
        if mouseData.leftButtonRelease and self.frameLabel.pixmap():
            # Selection box calculation depends on whether frame is scaled to fit label or not
            if not self.frameLabel.hasScaledContents():
                xScalingFactor = (mouseData.selectionBox.x() - (
                        self.frameLabel.width() - self.frameLabel.pixmap().width()) / 2) / self.frameLabel.pixmap().width()
                yScalingFactor = (mouseData.selectionBox.y() - (
                        self.frameLabel.height() - self.frameLabel.pixmap().height()) / 2) / self.frameLabel.pixmap().height()
                wScalingFactor = self.processingThread.getCurrentROI().width() / self.frameLabel.pixmap().width()
                hScalingFactor = self.processingThread.getCurrentROI().height() / self.frameLabel.pixmap().height()
            else:
                xScalingFactor = mouseData.selectionBox.x() / self.frameLabel.width()
                yScalingFactor = mouseData.selectionBox.y() / self.frameLabel.height()
                wScalingFactor = self.processingThread.getCurrentROI().width() / self.frameLabel.width()
                hScalingFactor = self.processingThread.getCurrentROI().height() / self.frameLabel.height()

            # Set selection box properties (new ROI)
            selectionBox.setX(
                xScalingFactor * self.processingThread.getCurrentROI().width() + self.processingThread.getCurrentROI().x())
            selectionBox.setY(
                yScalingFactor * self.processingThread.getCurrentROI().height() + self.processingThread.getCurrentROI().y())
            selectionBox.setWidth(wScalingFactor * mouseData.selectionBox.width())
            selectionBox.setHeight(hScalingFactor * mouseData.selectionBox.height())

            # Check if selection box has NON-ZERO dimensions
            if selectionBox.width() != 0 and selectionBox.height() != 0:
                # Selection box can also be drawn from bottom-right to top-left corner
                if selectionBox.width() < 0:
                    x_temp = selectionBox.x()
                    width_temp = selectionBox.width()
                    selectionBox.setX(x_temp + selectionBox.width())
                    selectionBox.setWidth(width_temp * -1)
                if selectionBox.height() < 0:
                    y_temp = selectionBox.y()
                    height_temp = selectionBox.height()
                    selectionBox.setY(y_temp + selectionBox.height())
                    selectionBox.setHeight(height_temp * -1)

                # Check if selection box is not outside window
                if (selectionBox.x() < 0 or selectionBox.y() < 0 or
                        selectionBox.x() + selectionBox.width() > self.processingThread.getCurrentROI().x() + self.processingThread.getCurrentROI().width() or
                        selectionBox.y() + selectionBox.height() > self.processingThread.getCurrentROI().y() + self.processingThread.getCurrentROI().height() or
                        selectionBox.x() < self.processingThread.getCurrentROI().x() or
                        selectionBox.y() < self.processingThread.getCurrentROI().y()):
                    # Display error message
                    QMessageBox.warning(self,
                                        "ERROR:",
                                        "Selection box outside range. Please try again.")
                # Set ROI
                else:
                    self.setROI.emit(selectionBox)

    def handleContextMenuAction(self, action):
        if action.text() == "Reset ROI":
            self.setROI.emit(
                QRect(0, 0, self.captureThread.getInputSourceWidth(), self.captureThread.getInputSourceHeight()))
        elif action.text() == "Scale to Fit Frame":
            self.frameLabel.setScaledContents(action.isChecked())
        elif action.text() == "Grayscale":
            self.imageProcessingFlags.grayscaleOn = action.isChecked()
            self.newImageProcessingFlags.emit(self.imageProcessingFlags)
        elif action.text() == "Smooth":
            self.imageProcessingFlags.smoothOn = action.isChecked()
            self.newImageProcessingFlags.emit(self.imageProcessingFlags)
        elif action.text() == "Dilate":
            self.imageProcessingFlags.dilateOn = action.isChecked()
            self.newImageProcessingFlags.emit(self.imageProcessingFlags)
        elif action.text() == "Erode":
            self.imageProcessingFlags.erodeOn = action.isChecked()
            self.newImageProcessingFlags.emit(self.imageProcessingFlags)
        elif action.text() == "Flip":
            self.imageProcessingFlags.flipOn = action.isChecked()
            self.newImageProcessingFlags.emit(self.imageProcessingFlags)
        elif action.text() == "Canny":
            self.imageProcessingFlags.cannyOn = action.isChecked()
            self.newImageProcessingFlags.emit(self.imageProcessingFlags)
        elif action.text() == "Yolo":
            self.imageProcessingFlags.yoloOn = action.isChecked()
            self.newImageProcessingFlags.emit(self.imageProcessingFlags)
        elif action.text() == "Settings...":
            self.setImageProcessingSettings()

    def draw_something(self,pixmap):
        painter = QPainter(pixmap)
        painter.setPen(QPen(Qt.black, 5, Qt.SolidLine))
        painter.setBrush(QBrush(Qt.red, Qt.VerPattern)) 
        points = QPolygon([QPoint(*i) for i in self.roi])
        painter.drawPolygon(points)
        return pixmap