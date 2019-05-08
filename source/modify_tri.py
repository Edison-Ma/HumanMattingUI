import sys
import json
import os
import numpy as np
import cv2

from PySide2.QtWidgets import (QApplication, QLabel, QPushButton,
                               QVBoxLayout, QWidget, QHBoxLayout)
from PySide2.QtCore import Slot, Qt, QSize
from PySide2.QtGui import QPixmap, QImage, QCursor

from utils import numpytoPixmap, ImageInputs, addBlankToLayout
from tools import painterTools, Concater
import config

import algorithm

from matting.deep_matting import load_model, deep_matting
from matting.closed_form_matting import closed_form_matting_with_trimap

class ClickLabel(QLabel):
    def __init__(self, widget, id, text):
        super(ClickLabel, self).__init__(text)
        self.widget = widget
        self.id = id

    def mousePressEvent(self, QMouseEvent):
        self.widget.click(QMouseEvent.pos(), self.id)

    def mouseMoveEvent(self, QMouseEvent):
        self.widget.drag(QMouseEvent.pos(), self.id)

    def mouseReleaseEvent(self, QMouseEvent):
        self.widget.release(QMouseEvent.pos(), self.id)
    
class MyButton(QPushButton):
    def __init__(self, widget, text, command = None):
        if command is None:
            command = text

        super(MyButton, self).__init__(text)
        self.text = command
        self.widget = widget
        self.buttons = {
            'Undo':         self.widget.undo,
            'Run':          self.widget.run,
            'Save':         self.widget.save,
            'SaveAlpha':    self.widget.saveAlpha,
            'Previous':     lambda : self.widget.newSet(True),
            'Next':         self.widget.newSet,
            'FillUnknown':  self.widget.fillUnknown,
        }
        if self.text in config.painterColors:
            self.button = lambda : self.widget.setColor(self.text)
        elif self.text in painterTools:
            self.button = lambda : self.widget.setTool(self.text)
        else:
            assert self.text in self.buttons, self.text + " not implement!"
            self.button = self.buttons[self.text]

    def mouseReleaseEvent(self, QMouseEvent):
        super(MyButton, self).mouseReleaseEvent(QMouseEvent)
        self.button()


class MyWidget(QWidget):
    def setImage(self, x, pixmap = None, array = None, resize = False, grid = False):
        assert pixmap is None or not grid, "Pixmap cannot draw grid."

        array = array.astype('uint8')
        if pixmap is None:
            if grid:
                k = self.splitK
                n, m = array.shape[:2]
                dx = (n - 1) // k + 1
                dy = (m - 1) // k + 1

                array[dx::dx] = np.array((255, 0, 0))
                array[:, dy::dy] = np.array((255, 0, 0))
                array = cv2.resize(array, None, fx = self.f, fy = self.f)
                resize = False

            pixmap = numpytoPixmap(array)
        imgx, imgy = self.scale
        if resize:
            pixmap = pixmap.scaled(imgx, imgy, Qt.KeepAspectRatio)
        self.texts[x].setPixmap(pixmap)

    def setSet(self):
        self.setImage(0, array = self.image)
        self.setImage(1, array = self.trimap)
        show = self.image * 0.7 + self.trimap * 0.3
        self.setImage(2, array = show)
        self.setImage(-1, array = self.final, resize = True)

    def setResult(self):
        for i, output in enumerate(self.outputs):
            self.setImage(i + 3, array = output, resize = True, grid = True)
        self.setImage(-1, array = self.final, resize = True)

    def newSet(self, prev = False):
        if prev:
            self.image, self.trimap, self.final = self.imageList.previous()
        else:
            self.image, self.trimap, self.final = self.imageList()

        if len(self.trimap.shape) == 2:
            self.trimap = np.stack([self.trimap] * 3, axis = 2)
        assert self.image.shape == self.trimap.shape

        h, w = self.image.shape[:2]
        imgw, imgh = self.scale
        self.f = min(imgw / w, imgh / h)

        self.image = cv2.resize(self.image, None, fx = self.f, fy = self.f)
        self.trimap = cv2.resize(self.trimap, None, fx = self.f, fy = self.f)
        self.history = []
        self.setSet()
        self.getGradient()

    def getGradient(self):
        self.grad = algorithm.calcGradient(self.image)

    def resizeToNormal(self):
        f = 1 / self.f
        image = cv2.resize(self.image, None, fx = f, fy = f)
        trimap = cv2.resize(self.trimap, None, fx = f, fy = f)
        return image, trimap

    def fillUnknown(self):
        algorithm.fillUnknown(self.trimap, width = self.fillWidth)

    def undo(self):
        if len(self.history) > 0:
            self.trimap = self.history.pop()
            self.setSet()

    def save(self):
        image, trimap = self.resizeToNormal()
        self.imageList.save(trimap)

    def saveAlpha(self):
        self.imageList.saveAlpha(self.final)

    def run(self):
        image, trimap = self.resizeToNormal()
        self.outputs = []
        for i, func in enumerate(self.functions):
            output = func(image, trimap)
            if output.ndim == 2:
                output = np.stack([output] * 3, axis = 2)
            self.outputs.append(output)
        self.setResult()

    def getToolObject(self, id):
        if id in [0, 1, 2]:
            return self.tool
        if id > 2 and id < self.n or id == -1:
            return self.resultTool.setId(id)

    def click(self, pos, id):
        tool = self.getToolObject(id)
        if tool is not None:
            tool.click(pos)

    def drag(self, pos, id):
        tool = self.getToolObject(id)
        if tool is not None:
            tool.drag(pos)

    def release(self, pos, id):
        tool = self.getToolObject(id)
        if tool is not None:
            tool.release(pos)

    def setColor(self, color):
        color = config.painterColors[color]
        self.tool.setColor(color)

    def setHistory(self):
        self.history.append(self.trimap.copy())

    def setTool(self, toolName):
        assert toolName in painterTools, toolName + " not implement!!"
        self.tool = painterTools[toolName]
        assert self.tool.toolName == toolName, toolName + " mapping wrong object"

    def initImageLayout(self):
        n, row, col = self.n, self.row, self.col
        imgx, imgy = self.scale
        self.texts = []
        for i in range(3):
            text = ClickLabel(self, i, "None")
            text.setAlignment(Qt.AlignTop)
            text.setFixedSize(QSize(imgx, imgy))
            self.texts.append(text)

        for i, f in enumerate(self.functions):
            text = ClickLabel(self, i + 3, "")
            text.setAlignment(Qt.AlignTop)
            text.setFixedSize(QSize(imgx, imgy))
            self.texts.append(text)

        text = ClickLabel(self, -1, "")
        text.setAlignment(Qt.AlignTop)
        text.setFixedSize(QSize(imgx, imgy))
        self.texts.append(text)

        self.newSet()

        self.imageLayout = QVBoxLayout()
        for i in range(row):
            rowLayout = QHBoxLayout()
            for j in self.texts[i * col: (i + 1) * col]:
                rowLayout.addWidget(j)
            self.imageLayout.addLayout(rowLayout)

    def initToolLayout(self):
        bx, by = self.buttonScale
        bC = self.buttonCol
        blankSize = self.blankSize
        self.toolWidgets = []

        for line in config.toolTexts:
            tempLine = []
            for command in line:
                temp = MyButton(self, config.getText(command), command)
                temp.setFixedSize(QSize(bx, by))
                tempLine.append(temp)
            self.toolWidgets.append(tempLine)

        self.toolLayout = QVBoxLayout()
        self.toolLayout.setAlignment(Qt.AlignTop)
        for line in self.toolWidgets:
            bR = (len(line) - 1) // bC + 1

            for row in range(bR):
                lineLayout = QHBoxLayout()
                lineLayout.setAlignment(Qt.AlignLeft)

                for tool in line[row * bC: (row + 1) * bC]:
                    lineLayout.addWidget(tool)
                self.toolLayout.addLayout(lineLayout)
                addBlankToLayout(self.toolLayout, blankSize[0])

            addBlankToLayout(self.toolLayout, blankSize[1])

    def __init__(self, imageList, functions):
        QWidget.__init__(self)

        self.functions = functions
        self.history = []

        self.imageList = imageList
        self.scale = config.imgScale
        self.n = 4 + len(functions)
        self.row = config.imgRow
        self.col = (self.n + self.row - 1) // self.row

        self.buttonScale = config.buttonScale
        self.buttonCol = config.buttonCol
        self.blankSize = config.blankSize

        self.fillWidth = 2

        self.tool = painterTools['Pen']
        self.tool.setWidget(self)
        self.resultTool = Concater()
        self.resultTool.setK(8)
        self.splitK = 8


        self.output = []
        self.final = None

        self.initImageLayout()
        self.initToolLayout()


        self.mainLayout = QHBoxLayout()
        self.mainLayout.addLayout(self.imageLayout)
        self.mainLayout.addLayout(self.toolLayout)

        self.setLayout(self.mainLayout)


def main(inputList, *args):
    inp = ImageInputs(inputList)
    app = QApplication(sys.argv)

    widget = MyWidget(imageList = inp, functions = args)
    # widget.resize(800, 600)
    widget.show()

    t = app.exec_()
    sys.exit(t)


if __name__ == "__main__":
    # model1 = load_model('/home/wuxian/human_matting/models/alpha_models_0305/alpha_net_100.pth', 0)
    # model2 = load_model('/home/wuxian/human_matting/models/alpha_models_bg/alpha_net_100.pth', 0)
    # model1 = load_model('/data2/human_matting/models/alpha_models_0305/alpha_net_100.pth', 0)
    # model2 = load_model('/data2/human_matting/models/alpha_models_bg/alpha_net_100.pth', 0)

    # a = lambda x, y : deep_matting(x, y, model1, 0)
    # b = lambda x, y : deep_matting(x, y, model2, 0)
    # c = lambda x, y : closed_form_matting_with_trimap(x / 255.0, y[:, :, 0] / 255.0) * 255.0
    a = lambda x, y: y
    b = lambda x, y: x
    c = lambda x, y: x / 2 + y / 2
    main('../list.txt', a, b, c)
