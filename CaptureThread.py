from PyQt5.QtCore import QThread, QTime, QMutexLocker, QMutex, pyqtSignal, qDebug
from PyQt5.QtWidgets import QMessageBox
import cv2
from queue import Queue
import os

from Structures import *
from Config import *
from datetime import datetime,timedelta
import av


class CaptureThread(QThread):
    updateStatisticsInGUI = pyqtSignal(ThreadStatisticsData)
    end = pyqtSignal()

    def __init__(self, sharedImageBuffer, deviceUrl, dropFrameIfBufferFull, apiPreference, width, height, setting, parent=None):
        super(CaptureThread, self).__init__(parent)
        self.t = QTime()
        self.doStopMutex = QMutex()
        self.fps = Queue()
        # Save passed parameters
        self.sharedImageBuffer = sharedImageBuffer
        self.dropFrameIfBufferFull = dropFrameIfBufferFull
        self.deviceUrl = deviceUrl
        self._deviceUrl = int(deviceUrl) if deviceUrl.isdigit() else deviceUrl
        self.localVideo = True if os.path.exists(self._deviceUrl) else False
        self.apiPreference = apiPreference
        self.width = width
        self.height = height
        # Initialize variables(s)
        self.captureTime = 0
        self.doStop = False
        self.sampleNumber = 0
        self.fpsSum = 0.0
        self.statsData = ThreadStatisticsData()
        self.defaultTime = 0
        t = datetime.strptime(setting.skip_duration, '%H:%M:%S')
        self.skip_duration = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
        self.video_date_time = datetime.strptime("{} {}".format(setting.video_date, setting.video_time), '%d/%m/%Y %H:%M:%S')
        self.starting_time = self.video_date_time 
        self.remain_video = None
        self.pause = False

    def update(self,frame):
        current_frame = frame.index
        process_time_second = round(current_frame / self.videofps)
        self.video_date_time = self.starting_time + timedelta(seconds=process_time_second)
        if round(current_frame%self.videofps) == 0:
            self.remain_video = self.video_date_time - self.starting_time

        self.sharedImageBuffer.video_date_time = self.video_date_time
        self.sharedImageBuffer.remain_video = self.remain_video

    def run(self):
        pause = False
        while True:
            if self.pause:
                continue
            ################################
            # Stop thread if doStop = TRUE #
            ################################
            self.doStopMutex.lock()
            if self.doStop:
                self.doStop = False
                self.doStopMutex.unlock()
                break
            self.doStopMutex.unlock()
            ################################
            ################################

            # Synchronize with other streams (if enabled for this stream)
            self.sharedImageBuffer.sync(self.deviceUrl)

            # Capture frame ( if available)
            try:
                frame = next(self.frames)
            except StopIteration:
                self.doStop = True
                self.end.emit()
                continue

            # Retrieve frame
            self.update(frame)
            frame = frame.to_ndarray(format='bgr24')
            # Add frame to buffer
            self.sharedImageBuffer.getByDeviceUrl(self.deviceUrl).add(frame, self.dropFrameIfBufferFull)

            self.statsData.nFramesProcessed += 1
            # Inform GUI of updated statistics
            self.updateStatisticsInGUI.emit(self.statsData)

            # Limit fps
            delta = self.defaultTime - self.t.elapsed()
            # delta = self.defaultTime - self.captureTime
            if delta > 0:
                self.msleep(delta)
            # Save capture time
            self.captureTime = self.t.elapsed()

            # Update statistics
            self.updateFPS(self.captureTime)

            # Start timer (used to calculate capture rate)
            self.t.start()

        qDebug("Stopping capture thread...")

    def stop(self):
        with QMutexLocker(self.doStopMutex):
            self.doStop = True

    def connectToCamera(self):
        # Open camera
        # self.ctx = av.Codec('h264_cuvid', 'r').create()
        # hwaccel = {'device_type_name': 'cuda'}
        # self.video = av.open(self._deviceUrl,hwaccel=hwaccel)
        self.video = av.open(self._deviceUrl)
        streams = [s for s in self.video.streams if s.type == 'video']
        streams = [streams[0]]
        self.frames = self.frame_iter(self.video,streams)
        self.total_frames = streams[0].frames
        self.videofps = streams[0].average_rate
        # self.ctx.extradata = streams[0].codec_context.extradata
        # if self.skip_duration:
        #     self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.videofps * self.skip_duration.total_seconds())
        #     self.video_date_time = self.video_date_time + self.skip_duration

        # Set resolution

        try:
            self.defaultTime = int(1000 / self.videofps)
        except:
            self.defaultTime = 40
        # Return result
        return True

    def disconnectCamera(self):
        # Camera is connected
        if self.cap.isOpened():
            # Disconnect camera
            self.cap.release()
            return True
        # Camera is NOT connected
        else:
            return False

    def isCameraConnected(self):
        return self.cap.isOpened()

    def getInputSourceWidth(self):
        return self.video.streams.video[0].width

    def getInputSourceHeight(self):
        return self.video.streams.video[0].height

    def updateFPS(self, timeElapsed):
        # Add instantaneous FPS value to queue
        if timeElapsed > 0:
            self.fps.put(1000 / timeElapsed)
            # Increment sample Number
            self.sampleNumber += 1

        # Maximum size of queue is DEFAULT_CAPTURE_FPS_STAT_QUEUE_LENGTH
        if self.fps.qsize() > CAPTURE_FPS_STAT_QUEUE_LENGTH:
            self.fps.get()
        # Update FPS value every DEFAULT_CAPTURE_FPS_STAT_QUEUE_LENGTH samples
        if self.fps.qsize() == CAPTURE_FPS_STAT_QUEUE_LENGTH and self.sampleNumber == CAPTURE_FPS_STAT_QUEUE_LENGTH:
            # Empty queue and store sum
            while not self.fps.empty():
                self.fpsSum += self.fps.get()
            # Calculate average FPS
            self.statsData.averageFPS = self.fpsSum / CAPTURE_FPS_STAT_QUEUE_LENGTH
            # Reset sum
            self.fpsSum = 0.0
            # Reset sample Number
            self.sampleNumber = 0

    def frame_iter(self,video,streams):
        for packet in video.demux(streams):
            for frame in packet.decode():
                yield frame