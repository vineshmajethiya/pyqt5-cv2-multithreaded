import time
import os
import tensorflow as tf
from datetime import timedelta,datetime
from PyQt5 import QtCore, QtGui, QtWidgets
from shapely.geometry import Point, Polygon

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
physical_devices = tf.config.experimental.list_physical_devices('GPU')
if len(physical_devices) > 0:
    tf.config.experimental.set_memory_growth(physical_devices[0], True)

import core.utils as utils
from core.yolov4 import filter_boxes
from tensorflow.python.saved_model import tag_constants
from core.config import cfg
import cv2
import numpy as np
import pandas as pd

from deep_sort import preprocessing, nn_matching
from deep_sort.detection import Detection
from deep_sort.tracker import Tracker
from tools import generate_detections as gdet

class FLAGS:
    framework = 'tf'
    weights = './checkpoints/yolov4-416'
    size = 416
    tiny = False
    model = 'yolov4'
    iou = 0.45
    score = 0.50

class Rectangle:
    def __init__(self, xmin, ymin, xmax, ymax):
        self.thickness_weight = 2
        self.xmin = int(xmin)
        self.xmax = int(xmax)
        self.ymin = int(ymin)
        self.ymax = int(ymax)

    def contain(self, rectangle):
        return self.xmin < rectangle.xmin < rectangle.xmax < self.xmax and self.ymin < rectangle.ymin < rectangle.ymax < self.ymax

    def center(self):
        x = (self.xmin + self.xmax)//2
        y = (self.ymin + self.ymax)//2
        return x,y

    def getThickness(self,f_width):
        width = self.xmax - self.xmin
        height = self.ymax - self.ymin
        average = (width+height)/2
        thickness = int((average/f_width)*100*self.thickness_weight)
        return thickness

    def getUpperAndLowerBound(self,width):
        thickness = self.getThickness(width)
        upper_bbox = Rectangle(self.xmin-thickness,self.xmax+thickness,self.ymin-thickness,self.ymax+thickness)
        lower_bbox = Rectangle(self.xmin+thickness,self.xmax-thickness,self.ymin+thickness,self.ymax-thickness)
        return upper_bbox,lower_bbox


class CustomTrackerList:
    def __init__(self):
        self.tracker_list = {}
        self.ignore = {}
        self.age_limit = 500

    def update(self,tracker_id,rectangle):
        tracker = self.tracker_list[tracker_id]['tracker']
        tracker.update(rectangle)

    def create(self,tracker,width):
        for tracker_id,data in self.tracker_list.items():
            upper_bbox,lower_bbox = data['tracker'].rectangle.getUpperAndLowerBound(width)
            if upper_bbox.contain(tracker.rectangle) and tracker.rectangle.contain(lower_bbox):
                tracker.capture()
                l = {tracker.tracker_id:{'tracker':tracker,'age':0}}
                self.ignore.update(l)
        l = {tracker.tracker_id:{'tracker':tracker,'age':0}}
        self.tracker_list.update(l)

    def isAvailable(self,track_id):
        return track_id in self.tracker_list or track_id in self.ignore

    def age(self):
        for key,value in self.tracker_list.copy().items():
            if value['age'] > self.age_limit:
                del self.tracker_list[key]
            else:
                self.tracker_list[key]['age'] = self.tracker_list[key]['age'] + 1

        for key,value in self.ignore.copy().items():
            if value['age'] > self.age_limit:
                del self.ignore[key]
            else:
                self.ignore[key]['age'] = self.ignore[key]['age'] + 1

    def getTracker(self,track_id):
        if track_id in self.tracker_list:
            return self.tracker_list[track_id]['tracker']
        if track_id in self.ignore:
            return self.ignore[track_id]['tracker']
        return None

    def __iter__(self):
        for key, value in self.tracker_list.items():
            yield value['tracker']


class CustomTracker:
    def __init__(self,rectangle,tracker_id):
        self.rectangle = rectangle
        self.x,self.y = rectangle.center()
        self.last_rectangle = rectangle
        self.last_x,self.last_y = rectangle.center()
        self.captured = False
        self.tracker_id = tracker_id
        self.direction = 0

    def update(self,rectangle):
        self.last_rectangle = self.rectangle
        self.last_x,self.last_y = self.rectangle.center()
        self.rectangle = rectangle
        self.x,self.y = rectangle.center()
        self.direction += -1 if self.last_y < self.y else 1

    def capture(self):
        self.captured = True

    def getDirection(self):
        return "up" if 0 <= self.direction else "down"


def snapshot(frame,direction,counter,bbox,tm,tempimgdir):
    frame = frame.copy()
    color = (0,255,255)
    # frame = frame[int(bbox[1]):int(bbox[3]),int(bbox[0]):int(bbox[2])]
    cv2.rectangle(frame, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), color, 2)
    dt_string = tm.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(tempimgdir, f"{dt_string}_{counter}_{direction}.png")
    status = cv2.imwrite(path, frame)

def vehicle_entry(counter,tm,direction,class_name):
    dt_string = tm.strftime('%Y-%m-%d_%H:%M:%S')
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
    brush = QtGui.QBrush(QtGui.QColor(255, 0, 0))
    brush.setStyle(QtCore.Qt.NoBrush)
    item.setForeground(brush)
    item.setText(f"{dt_string}_{direction}_{class_name}")
    self.camera_view.vehicle_list.insertItem(0,item)
    return f"{dt_string}_{direction}_{class_name}"

class DeepSortApp:
    def __init__(self,camera_view):
        # Definition of the parameters
        self.max_cosine_distance = 0.4
        self.nn_budget = None
        self.nms_max_overlap = 1.0
        self.thickness_weight = 2
        self.fps = 0
        self.tracker_list = CustomTrackerList()
        # initialize deep sort
        self.model_filename = 'model_data/mars-small128.pb'
        self.encoder = gdet.create_box_encoder(self.model_filename, batch_size=1)
        # calculate cosine distance metric
        self.metric = nn_matching.NearestNeighborDistanceMetric("cosine", self.max_cosine_distance, self.nn_budget)
        # initialize tracker
        self.tracker = Tracker(self.metric)
        self.input_size = 416
        self.camera_view = camera_view

        # load tflite model if flag is set
        if FLAGS.framework == 'tflite':
            self.interpreter = tf.lite.Interpreter(model_path=FLAGS.weights)
            self.interpreter.allocate_tensors()
            self.input_details = self.interpreter.get_input_details()
            self.output_details = self.interpreter.get_output_details()
        # otherwise load standard tensorflow saved model
        else:
            self.saved_model_loaded = tf.saved_model.load(FLAGS.weights, tags=[tag_constants.SERVING])
            self.infer = self.saved_model_loaded.signatures['serving_default']


        self.tempimgdir = "tempimgdir"
        if not os.path.exists(self.tempimgdir):
            os.mkdir(self.tempimgdir)

        self.counter = 1
        self.stopped = False

        self.class_names = utils.read_class_names(cfg.YOLO.CLASSES)

    def setRoi(self,roi):
        self.roi = Polygon(roi)

    def process(self, frame, process_time):
        self.frame = frame
        vehicle_detail = []

        self.height, self.width = self.frame.shape[:2]
        image_data = cv2.resize(self.frame, (self.input_size, self.input_size))
        image_data = image_data / 255.
        image_data = image_data[np.newaxis, ...].astype(np.float32)
        start_time = time.time()

        # run detections on tflite if flag is set
        if FLAGS.framework == 'tflite':
            self.interpreter.set_tensor(self.input_details[0]['index'], image_data)
            self.interpreter.invoke()
            pred = [self.interpreter.get_tensor(self.output_details[i]['index']) for i in range(len(self.output_details))]
            # run detections using yolov3 if flag is set
            if FLAGS.model == 'yolov3' and FLAGS.tiny == True:
                boxes, pred_conf = filter_boxes(pred[1], pred[0], score_threshold=0.25,
                                                input_shape=tf.constant([self.input_size, self.input_size]))
            else:
                boxes, pred_conf = filter_boxes(pred[0], pred[1], score_threshold=0.25,
                                                input_shape=tf.constant([self.inv_idput_size, self.input_size]))
        else:
            batch_data = tf.constant(image_data)
            pred_bbox = self.infer(batch_data)
            # self.pbar.write(str(pred_bbox))
            for key, value in pred_bbox.items():
                boxes = value[:, :, 0:4]
                pred_conf = value[:, :, 4:]

        boxes, scores, classes, valid_detections = tf.image.combined_non_max_suppression(
            boxes=tf.reshape(boxes, (tf.shape(boxes)[0], -1, 1, 4)),
            scores=tf.reshape(
                pred_conf, (tf.shape(pred_conf)[0], -1, tf.shape(pred_conf)[-1])),
            max_output_size_per_class=50,
            max_total_size=50,
            iou_threshold=FLAGS.iou,
            score_threshold=FLAGS.score
        )

        # convert data to numpy arrays and slice out unused elements
        num_objects = valid_detections.numpy()[0]
        bboxes = boxes.numpy()[0]
        bboxes = bboxes[0:int(num_objects)]
        scores = scores.numpy()[0]
        scores = scores[0:int(num_objects)]
        classes = classes.numpy()[0]
        classes = classes[0:int(num_objects)]

        # format bounding boxes from normalized ymin, xmin, ymax, xmax ---> xmin, ymin, width, height
        original_h, original_w, _ = self.frame.shape
        bboxes = utils.format_boxes(bboxes, original_h, original_w)

        # store all predictions in one parameter for simplicity when calling functions
        pred_bbox = [bboxes, scores, classes, num_objects]

        # by default allow all classes in .names file
        allowed_classes = list(self.class_names.values())

        # custom allowed classes (uncomment line below to customize tracker for only people)
        allowed_classes = ['bicycle','car','motorbike','bus','truck']

        # loop through objects and use class index to get class name, allow only classes in allowed_classes list
        names = []
        deleted_indx = []
        for i in range(num_objects):
            class_indx = int(classes[i])
            class_name = self.class_names[class_indx]
            if class_name not in allowed_classes:
                deleted_indx.append(i)
            else:
                names.append(class_name)
        names = np.array(names)

        # delete detections that are not in allowed_classes
        bboxes = np.delete(bboxes, deleted_indx, axis=0)
        scores = np.delete(scores, deleted_indx, axis=0)

        # encode yolo detections and feed to tracker
        features = self.encoder(self.frame, bboxes)
        detections = [Detection(bbox, score, class_name, feature) for bbox, score, class_name, feature in zip(bboxes, scores, names, features)]

        # run non-maxima supression
        boxs = np.array([d.tlwh for d in detections])
        scores = np.array([d.confidence for d in detections])
        classes = np.array([d.class_name for d in detections])
        indices = preprocessing.non_max_suppression(boxs, classes, self.nms_max_overlap, scores)
        detections = [detections[i] for i in indices]

        # Call the tracker
        self.tracker.predict()
        self.tracker.update(detections)

        # update tracks
        for track in self.tracker.tracks:
            if not track.is_confirmed() or track.time_since_update > 1:
                continue
            bbox = track.to_tlbr()
            rectangle = Rectangle(*bbox)
            class_name = track.get_class()

            if not self.tracker_list.isAvailable(track.track_id):
                self.tracker_list.create(CustomTracker(rectangle,track.track_id),self.width)

            else:
                try:
                    custom_tracker = self.tracker_list.getTracker(track.track_id)
                    p1 = Point(custom_tracker.x,custom_tracker.y)
                    if p1.within(self.roi):
                        if not custom_tracker.captured:
                            direction = custom_tracker.getDirection()
                            snapshot(self.frame,direction,self.counter,bbox,process_time,self.tempimgdir)
                            vehicle_entry(self.counter,process_time,direction,class_name,self.camera_view)
                            self.counter+=1
                            custom_tracker.capture()
                            print(p1)

                except Exception as e:
                    print(e)

            self.tracker_list.update(track.track_id,rectangle)

        self.tracker_list.age()

        # draw bbox on screen
        for track in self.tracker.tracks:
            if not track.is_confirmed() or track.time_since_update > 2:
                continue
            bbox = track.to_tlbr()
            class_name = track.get_class()
            tracker = self.tracker_list.getTracker(track.track_id)

            if tracker:
                color = (0,0,255) if tracker.captured else (0,255,0)
                cv2.rectangle(self.frame, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), color, 2)
                cv2.rectangle(self.frame, (int(bbox[0]), int(bbox[1]-30)), (int(bbox[0])+(len(class_name)+len(str(track.track_id)))*17, int(bbox[1])), color, -1)
                class_name = track.get_class()
                cv2.putText(self.frame, class_name + "-" + str(track.track_id),(int(bbox[0]), int(bbox[1]-10)),0, 0.60, (255,255,255),2)


        # calculate frames per second of running detections
        self.fps = 1.0 / (time.time() - start_time)

        # result = np.asarray(frame)
        # result = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        return self.frame
