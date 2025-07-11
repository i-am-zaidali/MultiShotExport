import logging
import os
import os.path as osp
import re
import shutil
import subprocess
import traceback
import typing
from pathlib import Path

import pymel.core as pc
import typing_extensions as te
from PySide2 import QtCore
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if typing.TYPE_CHECKING:
    from .shot_form_tab import ShotFormExportTypeTab

from . import backend, sui
from .backend import imaya
from .backend import shotplaylist as sp
from .backend.shotactions import Action

log = logging.getLogger("submit")
qApp: QApplication = QApplication.instance()  # type: ignore


CacheExport = backend.CacheExport
exportutils = backend.exportutils
Playlist = backend.Playlist
PlaylistItem = sp.PlaylistItem
PlayblastExport = backend.PlayblastExport
PlayListUtils = backend.PlayListUtils
cacheexport = backend.cacheexport
root_path = osp.dirname(osp.dirname(__file__))
ui_path = osp.join(root_path, "ui")
icon_path = osp.join(root_path, "icons")


# class Submitter(QMainWindow): # had to remove this because of maya's garbage collection.
# for more context check the following link:
# https://www.tech-artists.org/t/pyside-in-maya-internal-c-object-already-deleted-for-returned-pyside-objects/4877/6
class SubmitterWidget(QWidget):
    parent: typing.Callable[[], "SubmitterWindow"]
    # parent: "SubmitterWindow"
    _previousPath = ""
    _playlist: Playlist

    MainWidget: QWidget
    centralwidget: QWidget
    selectAllButton: QCheckBox
    addButton: QToolButton
    collapseButton: QToolButton
    deleteSelectedButton: QToolButton
    searchBox: QLineEdit
    scrollArea: QScrollArea
    scrollAreaWidgetContents: QWidget
    label_3: QLabel
    pathBox: QLineEdit
    browseButton: QToolButton
    selectedLabel: QLabel
    label: QLabel
    totalLabel: QLabel
    defaultResolutionButton: QCheckBox
    applyCacheButton: QCheckBox
    hdButton: QCheckBox
    hdOnlyButton: QCheckBox
    audioButton: QCheckBox
    localButton: QCheckBox
    exportButton: QPushButton
    stopButton: QPushButton
    closeButton: QPushButton
    progressBar: QProgressBar
    menuBar: QMenuBar
    menuOptions: QMenu
    item_layout: QVBoxLayout

    cacheEnableAction: QAction
    cacheDisableAction: QAction
    playblastEnableAction: QAction
    playblastDisableAction: QAction

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        sui.loadUi(os.path.join(ui_path, "submitter.ui"), self)
        #  self.setupUi(self)
        self.__colors_mapping__ = {
            "Red": 4,
            "Green": 14,
            "Yellow": 17,
            "Black": 1,
        }
        self.progressBar.hide()
        self.collapsed = False
        self.stop = False
        self.breakdownWindow = None
        self.addButton.setIcon(QIcon(osp.join(icon_path, "ic_add.png")))
        self.collapseButton.setIcon(
            QIcon(osp.join(icon_path, "ic_toggle_collapse"))
        )
        self.deleteSelectedButton.setIcon(
            QIcon(osp.join(icon_path, "ic_delete.png"))
        )
        search_ic_path = osp.join(icon_path, "ic_search.png").replace("\\", "/")
        style_sheet = (
            "\nbackground-image: url(%s);"
            + "\nbackground-repeat: no-repeat;"
            + "\nbackground-position: center left;"
        ) % search_ic_path
        style_sheet = self.searchBox.styleSheet() + style_sheet
        self.searchBox.setStyleSheet(style_sheet)
        self.collapseButton.clicked.connect(self.toggleCollapseAll)
        self.addButton.clicked.connect(self.showForm)
        self.selectAllButton.clicked.connect(self.selectAll)
        self.deleteSelectedButton.clicked.connect(self.deleteSelected)
        self.searchBox.textChanged.connect(self.searchShots)
        self.searchBox.returnPressed.connect(
            lambda: self.searchShots(str(self.searchBox.text()))
        )
        self.exportButton.clicked.connect(self.export)
        self.browseButton.clicked.connect(self.browseFolder)
        self.cacheEnableAction.triggered.connect(self.enableCacheSelected)
        self.cacheDisableAction.triggered.connect(self.disableCacheSelected)
        self.playblastEnableAction.triggered.connect(
            self.enablePlayblastSelected
        )
        self.playblastDisableAction.triggered.connect(
            self.disablePlayblastSelected
        )
        self.stopButton.clicked.connect(self.setStop)
        self.hdButton.toggled.connect(self.hdToggled)
        self._playlist = Playlist()
        self.items: typing.List[Item] = []
        self.populate()
        self.applyCacheButton.hide()
        self.audioButton.hide()
        self.stopButton.hide()
        self.hdButton.hide()
        self.defaultResolutionButton.hide()
        self.localButton.hide()
        self.hdOnlyButton.hide()

    def hdToggled(self, val):
        if not val:
            self.hdOnlyButton.setChecked(False)

    def enableCacheSelected(self):
        for item in self._playlist.getItems():
            if item.selected:
                CacheExport.getActionFromList(item.actions).enabled = True
                item.saveToScene()

    def disableCacheSelected(self):
        for item in self._playlist.getItems():
            if item.selected:
                CacheExport.getActionFromList(item.actions).enabled = False
                item.saveToScene()

    def enablePlayblastSelected(self):
        for item in self._playlist.getItems():
            if item.selected:
                PlayblastExport.getActionFromList(item.actions).enabled = True
                item.saveToScene()

    def disablePlayblastSelected(self):
        for item in self._playlist.getItems():
            if item.selected:
                PlayblastExport.getActionFromList(item.actions).enabled = False
                item.saveToScene()

    def browseFolder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Folder", "")
        if path:
            self.pathBox.setText(str(Path(path).resolve()))

    def setSelectedCount(self):
        count = 0
        for item in self.items:
            if item.isChecked():
                count += 1

        self.selectedLabel.setText("Selected: " + str(count))

    def setTotalCount(self):
        self.totalLabel.setText("Total: " + str(len(self.items)))

    def toggleCollapseAll(self):
        self.collapsed = not self.collapsed
        for item in self.items:
            item.toggleCollapse(self.collapsed)

    def searchShots(self, text):
        text = str(text).lower()
        for item in self.items:
            if text in item.getTitle().lower():
                item.show()
            else:
                item.hide()

    def selectAll(self):
        for item in self.items:
            item.setChecked(self.selectAllButton.isChecked())

        self.setSelectedCount()

    def deleteSelected(self):
        flag = False
        for i in self.items:
            if i.isChecked():
                flag = True
                break

        if not flag:
            msg = "Shots not selected"
            icon = QMessageBox.Information
            btns = QMessageBox.StandardButton.Ok
        else:
            msg = "Are you sure, remove selected shots?"
            icon = QMessageBox.Question
            btns = (
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel
            )
        btn = sui.showMessage(
            self, title="Remove Selected", msg=msg, btns=btns, icon=icon
        )
        if btn == QMessageBox.Yes:
            temp = []
            for item in self.items:
                if item.isChecked():
                    item.deleteLater()
                    self._playlist.removeItem(item.pl_item)
                    temp.append(item)

            for itm in temp:
                self.items.remove(itm)

        self.setSelectedCount()
        self.setTotalCount()

    def itemClicked(self, *args):
        flag = True
        for item in self.items:
            if not item.isChecked():
                flag = False
                break

        self.selectAllButton.setChecked(flag)
        self.setSelectedCount()

    def showForm(self):
        msg = ""
        if not self.getSeqPath():
            msg = "Sequence path not specified"
        else:
            if not osp.exists(self.getSeqPath()):
                msg = "Sequence path does not exist"
        if msg:
            sui.showMessage(
                self,
                title="Sequence Path Error",
                msg=msg,
                icon=QMessageBox.Information,
            )
            return
        ShotForm(self).show()

    def removeItem(self, item):
        self.items.remove(item)
        item.deleteLater()
        self._playlist.removeItem(item.pl_item)
        self.setSelectedCount()
        self.setTotalCount()

    def clear(self):
        for item in self.items:
            item.deleteLater()
            self._playlist.removeItem(item.pl_item)

        del self.items[:]
        self.setSelectedCount()
        self.setTotalCount()

    def getItems(self):
        return self.items

    def getSeqPath(self):
        return self.pathBox.text()

    @typing.overload
    def getItem(self, pl_item: PlaylistItem) -> typing.Optional["Item"]: ...

    @typing.overload
    def getItem(
        self,
        pl_item: PlaylistItem,
        forceCreate: te.Literal[True],
        extra_widgets: typing.Optional[typing.List[QHBoxLayout]] = None,
    ) -> "Item": ...

    def getItem(
        self,
        pl_item: PlaylistItem,
        forceCreate: bool = False,
        extra_widgets: typing.Optional[typing.List[QHBoxLayout]] = None,
    ) -> typing.Optional["Item"]:
        thisItem = None
        for item in self.items:
            if item.pl_item == pl_item:
                thisItem = item

        if not thisItem and forceCreate:
            thisItem = self.createItem(pl_item, extra_widgets)
        return thisItem

    def populate(self):
        for pl_item in self._playlist.getItems():
            try:
                self.createItem(pl_item)

            except Exception:
                self._playlist.removeItem(pl_item)

    def editItem(self, item: "Item"):
        ShotForm(self, item).show()

    def createItem(
        self,
        pl_item: PlaylistItem,
        extra_widgets: typing.Optional[typing.List[QHBoxLayout]] = None,  # type: ignore
    ) -> "Item":
        if not extra_widgets:
            extra_widgets: typing.List[QHBoxLayout] = []
            for sub in Action.inheritors().values():
                try:
                    tab = sub.getTabUI()

                except NotImplementedError:
                    continue

                action = sub.getActionFromList(
                    pl_item.actions, forceCreate=False
                )
                path = (
                    action.path
                    if action
                    else tab.getExportPath(self, pl_item.camera)
                )
                path = ""
                if action:
                    path = action.path

                if not path:
                    try:
                        path = tab.getExportPath(self, pl_item.camera)

                    except Exception as e:
                        sui.showMessage(
                            self,
                            msg=f"There was an error getting the export path for {tab.EXPORT_TYPE} for the shot. The shot is being deleted",
                            details=traceback.format_exc(),
                        )
                        raise e

                extra_widgets.append(tab.getItemInformationLayout(path))

        item = Item(self, pl_item, extra_widgets)

        self.items.append(item)
        self.item_layout.addWidget(item)
        item.setChecked(self.selectAllButton.isChecked())
        item.toggleCollapse(self.collapsed)
        item.update()
        self.setSelectedCount()
        self.setTotalCount()
        return item

    def setHUDColor(self):
        color = "Green"
        exportutils.setHUDColor(
            self.__colors_mapping__.get(color),
            self.__colors_mapping__.get(color),
        )

    def isItemSelected(self):
        selected = False
        for item in self._playlist.getItems():
            if item.selected:
                selected = True
                break

        return selected

    def isActionEnabled(self):
        shots = []
        for item in self.playlist.getItems():
            if item.selected:
                enabled = False
                # assert item.actions is not None
                for action in item.actions.getActions():
                    if action.enabled:
                        enabled = True
                        break

                if not enabled:
                    shots.append(item.name)

        return shots

    def allPathsExist(self):
        shots = {}
        for item in self.playlist.getItems():
            if item.selected:
                # assert item.actions is not None
                for action in item.actions.getActions():
                    if action.enabled and not osp.exists(action.path):  # type: ignore
                        if item.name in shots:
                            shots[item.name].append(action.path)  # type: ignore
                        else:
                            shots[item.name] = [action.path]  # type: ignore

        return shots

    def ldLinked(self):
        objects = []
        for item in self.playlist.getItems():
            if item.selected:
                # assert item.actions is not None
                ce = CacheExport.getActionFromList(item.actions)
                for _set in ce.get("objects", []):
                    ref = imaya.getRefFromSet(pc.PyNode(_set))
                    if ref and osp.exists(str(ref.path)):
                        if not exportutils.linkedLD(str(ref.path)):
                            objects.append(_set)
                    else:
                        objects.append(_set)

        return objects

    def allCamerasGood(self):
        shots = []
        for item in self.playlist.getItems():
            if item.selected and not exportutils.camHasKeys(item.camera):
                shots.append(item.name)

        return shots

    def setStop(self):
        self.stop = True

    def export(self):
        self.exportNow()
        self.stopButton.hide()
        self.closeButton.show()

    def exportNow(self):
        self.stopButton.show()
        self.closeButton.hide()
        if not self.isItemSelected():
            sui.showMessage(
                self,
                title="No selection",
                msg="No shot selected to export",
                icon=QMessageBox.Information,
            )
            return
        if self.applyCacheButton.isChecked():
            badObjects = self.ldLinked()
            if badObjects:
                numObjects = len(badObjects)
                s = "s" if numObjects > 1 else ""
                detail = ""
                for obj in badObjects:
                    detail += obj + "\n"

                sui.showMessage(
                    self,
                    title="LD Error",
                    msg="Could not find LD path for "
                    + str(numObjects)
                    + " set"
                    + s
                    + "\nThere is no guarantee that the exported"
                    "cache will be compatible with the LD",
                    details=detail,
                    icon=QMessageBox.Information,
                )
                return
        badShots = self.isActionEnabled()
        if badShots:
            numShots = len(badShots)
            s = "s" if numShots > 1 else ""
            detail = ""
            for i, shot in enumerate(badShots):
                detail += str(i + 1) + " - " + shot + "\n\n"

            sui.showMessage(
                self,
                title="No Action",
                msg=str(numShots)
                + " shot"
                + s
                + " selected, but no action enabled",
                details=detail,
                icon=QMessageBox.Information,
            )
            return
        badShots = self.allPathsExist()
        if badShots and not self.localButton.isChecked():
            numShots = len(badShots)
            s = "s" if numShots > 1 else ""
            detail = ""
            for shot, paths in badShots.items():
                detail += shot + "\n"
                for path in paths:
                    detail += path + "\n"

                detail += "\n"

            sui.showMessage(
                self,
                title="Path not found",
                msg=str(numShots)
                + " shot"
                + s
                + " selected, but no path found",
                details=detail,
                icon=QMessageBox.Information,
            )
            return
        if self.audioButton.isChecked():
            audioNodes = exportutils.getAudioNodes()
            if not audioNodes:
                btn = sui.showMessage(
                    self,
                    title="No Audio",
                    msg="No audio found in the scene",
                    ques="Do you want to proceed anyway?",
                    icon=QMessageBox.Question,
                    btns=QMessageBox.Yes | QMessageBox.No,
                )
                if btn == QMessageBox.No:
                    return
            if len(audioNodes) > 1:
                sui.showMessage(
                    self,
                    title="Audio Files",
                    msg="More than one audio files found in the scene, "
                    + "keep only one audio file",
                    icon=QMessageBox.Information,
                )
                return
        badShots = self.allCamerasGood()
        if badShots:
            s = "s" if len(badShots) > 1 else ""
            ss = "" if len(badShots) > 1 else "es"
            sui.showMessage(
                self,
                title="Bad Cameras",
                msg="Camera%s in %s selected shot%s do%s not "
                "have keys (in out)" % (s, len(badShots), s, ss),
                icon=QMessageBox.Information,
                details=("\n").join(badShots),
            )
            return
        try:
            for directory in exportutils.home.iterdir():
                shutil.rmtree(directory)

        except Exception:
            pass

        try:
            for directory in exportutils.localPath.iterdir():
                shutil.rmtree(directory)

        except Exception:
            pass

        try:
            self.exportButton.setEnabled(False)
            self.closeButton.setEnabled(False)
            self.progressBar.show()
            self.progressBar.setMinimum(0)
            state = PlayListUtils.getDisplayLayersState()
            exportutils.setOriginalCamera()
            exportutils.setOriginalFrame()
            exportutils.setSelection()
            exportutils.saveHUDColor()
            exportutils.hideShowCurves(True)
            exportutils.hideFaceUi()
            self.setHUDColor()
            backend.playblast.showNameLabel()
            errors = {}
            self.progressBar.setValue(0)
            self.stopButton.setEnabled(True)
            generator = self._playlist.performActions(
                sound=self.audioButton.isChecked(),
                hd=self.hdButton.isChecked(),
                applyCache=self.applyCacheButton.isChecked(),
                local=self.localButton.isChecked(),
                hdOnly=self.hdOnlyButton.isChecked(),
                defaultResolution=self.defaultResolutionButton.isChecked(),
            )
            self.progressBar.setMaximum(typing.cast("int", next(generator)))
            qApp.processEvents()
            for i, val in enumerate(generator):
                if isinstance(val, tuple):
                    errors[val[0].name] = val[1]
                self.progressBar.setValue(i + 1)
                qApp.processEvents()
                if self.stop:
                    self.stop = False
                    break
                qApp.processEvents()

            exportutils.saveMayaFile(self.playlist.getItems())
            temp = " shots " if len(errors) > 1 else " shot "
            if errors:
                detail = ""
                for shot, err in errors.items():
                    detail += "Shot: " + shot + "\nReason: " + str(err) + "\n\n"
                    log.error("Error", exc_info=err)

                sui.showMessage(
                    self,
                    title="Error",
                    msg=str(len(errors)) + temp + "not exported successfully",
                    icon=QMessageBox.Critical,
                    details=detail,
                )

            sui.showMessage(
                self,
                title="Export Complete",
                msg="Export completed successfully for "
                + str(len(self._playlist.getItems())),
                icon=QMessageBox.Information,
                details="Exported shots: "
                + ", ".join([item.name for item in self.playlist.getItems()]),
            )

        except Exception as ex:
            sui.showMessage(
                self,
                title="Error",
                msg=str(ex),
                icon=QMessageBox.Critical,
                # show the traceback in the details:
                details="\n".join(
                    traceback.format_exception(type(ex), ex, ex.__traceback__)
                ),
            )
        finally:
            self.progressBar.hide()
            PlayListUtils.restoreDisplayLayersState(state)
            exportutils.restoreOriginalCamera()
            exportutils.restoreOriginalFrame()
            exportutils.restoreSelection()
            exportutils.restoreHUDColor()
            exportutils.hideShowCurves(False)
            exportutils.showFaceUi()
            backend.playblast.removeNameLabel()
            self.exportButton.setEnabled(True)
            self.closeButton.setEnabled(True)
            self.stopButton.hide()
            self.closeButton.show()

        if exportutils.errorsList:
            detail = ""
            for error in exportutils.errorsList:
                detail += error + "\n\n"

            sui.showMessage(
                self,
                title="Error",
                msg="Errors occurred while exporting shots\n"
                + "your files might be copied to: "
                + str(exportutils.home),
                details=detail,
                icon=QMessageBox.Warning,
            )
            exportutils.errorsList[:] = []
        if cacheexport.errorsList:
            detail = ""
            for error in cacheexport.errorsList:
                detail += error + "\n\n"

            sui.showMessage(
                self,
                title="Error",
                msg="Errors occurred while exporting or applying cache\n",
                details=detail,
                icon=QMessageBox.Warning,
            )
            cacheexport.errorsList[:] = []

    @property
    def playlist(self):
        return self._playlist

    def closeEvent(self, event):
        self.deleteLater()
        Action.cleanup()

    def getBasePath(self, cameraName):
        prefix = self.getSeqPath()
        prefixPath = osp.join(prefix, "SHOTS")
        if not osp.exists(prefixPath):
            os.mkdir(prefixPath)
        cameraName = re.sub("(?i)^ep\\d*_", "", str(cameraName))
        shotPath = osp.join(prefixPath, str(cameraName))
        if not osp.exists(shotPath):
            os.mkdir(shotPath)
        return osp.join(shotPath, "animation")

    def getCachePath(self, cameraName):
        animPath = self.getBasePath(cameraName)
        if not osp.exists(animPath):
            os.mkdir(animPath)
        cachePath = osp.join(animPath, "cache")
        if not osp.exists(cachePath):
            os.mkdir(cachePath)
        return cachePath

    def getPlayblastPath(self, cameraName):
        animPath = self.getBasePath(cameraName)
        if not osp.exists(animPath):
            os.mkdir(animPath)
        previewPath = osp.join(animPath, "preview")
        if not osp.exists(previewPath):
            os.mkdir(previewPath)
        return previewPath


class SubmitterWindow(QMainWindow):
    submitterWidget: SubmitterWidget

    def __init__(self):
        super().__init__(sui.get_maya_window())
        self.submitterWidget = SubmitterWidget(self)
        self.centralLayout = QVBoxLayout(self)
        self.centralLayout.setContentsMargins(0, 0, 0, 0)
        self.centralLayout.addWidget(self.submitterWidget)
        # fit to the size of the widgets
        self.setCentralWidget(self.submitterWidget)


class ShotForm(QDialog):
    cameraLayout: QVBoxLayout
    # fbxEnableButton: QCheckBox
    # fbxPathBox: QLineEdit
    autoCreateButton: QCheckBox
    stackedWidget: QStackedWidget
    nameBox: QLineEdit
    fillButton: QToolButton
    cameraBox: QComboBox
    camCountLabel: QLabel
    keyFrameButton: QCheckBox
    startFrameBox: QSpinBox
    endFrameBox: QSpinBox
    selectAllCameras: QCheckBox
    createButton: QPushButton
    cancelButton: QPushButton
    # playblastEnableButton: QCheckBox
    # selectAllButton: QCheckBox
    # scrollArea: QScrollArea
    # scrollAreaWidgetContents: QWidget
    # playblastPathBox: QLineEdit
    # playblastBrowseButton: QToolButton
    # cacheEnableButton: QCheckBox
    # selectAllButton2: QCheckBox
    # scrollAreaWidgetContents_2: QWidget
    # cachePathBox: QLineEdit
    # cacheBrowseButton: QToolButton
    progressBar: QProgressBar
    # layerlayout: QVBoxLayout
    exportTypeTabs: QTabWidget

    def __init__(
        self,
        parent: SubmitterWidget,
        item: typing.Optional["Item"] = None,
    ):
        super().__init__(parent)
        sui.loadUi(os.path.join(ui_path, "form.ui"), self)
        #  self.setupUi(self)
        self.parentWin: SubmitterWindow = parent.parent()
        self.submitterWidget = parent
        self.progressBar.hide()
        self.startFrame = None
        self.endFrame = None
        self.item = item
        self.pl_item = typing.cast(
            "PlaylistItem | None", getattr(item, "pl_item", None)
        )
        self.layerButtons: typing.List[QCheckBox] = []
        self.objectButtons: typing.List[QCheckBox] = []
        self.cameraButtons: typing.List[QCheckBox] = []
        self.addCameras()
        # self.addObjects()
        # self.addLayers()
        self.exportTypeTabs.clear()
        self.tabs: typing.List["ShotFormExportTypeTab[Action]"] = []
        subs = Action.inheritors()
        for sub in subs.values():
            try:
                tabType = sub.getTabUI()
            except NotImplementedError:
                print("There was an error getting the tab type for", sub)
                continue

            tab = tabType(self, item=self.item)
            self.tabs.append(tab)

            self.exportTypeTabs.addTab(tab, tab.getTabName())

        if self.pl_item:
            self.createButton.setText("Ok")
            self.populate()
            self.autoCreateButton.setChecked(False)
            self.stackedWidget.setCurrentIndex(0)
            self.autoCreateButton.hide()
        # else:
        #     self.fillPathBoxes()
        self.fillButton.setIcon(QIcon(osp.join(icon_path, "ic_fill.png")))
        self.cameraBox.activated.connect(self.handleCameraBox)
        self.createButton.clicked.connect(self.callCreate)
        self.keyFrameButton.clicked.connect(self.handleKeyFrameClick)
        # self.playblastBrowseButton.clicked.connect(self.playblastBrowseFolder)
        # self.cacheBrowseButton.clicked.connect(self.cacheBrowseFolder)
        self.fillButton.clicked.connect(self.fillName)
        # self.selectAllButton.clicked.connect(self.selectAll)
        # self.selectAllButton2.clicked.connect(self.selectAll2)
        self.selectAllCameras.clicked.connect(self.handleSelectAllCameras)
        self.autoCreateButton.toggled.connect(self.switchStackedWidget)

    def switchStackedWidget(self, stat):
        self.stackedWidget.setCurrentIndex(int(stat))

    # def selectAll(self):
    #     checked = self.selectAllButton.isChecked()
    #     for btn in self.layerButtons:
    #         btn.setChecked(checked)

    # def selectAll2(self):
    #     checked = self.selectAllButton2.isChecked()
    #     for btn in self.objectButtons:
    #         btn.setChecked(checked)

    # def setSelectAllButton(self):
    #     flag = True
    #     for btn in self.layerButtons:
    #         if not btn.isChecked():
    #             flag = False
    #             break

    #     self.selectAllButton.setChecked(flag)

    # def setSelectAllButton2(self):
    #     flag = True
    #     for btn in self.objectButtons:
    #         if not btn.isChecked():
    #             flag = False
    #             break

    #     self.selectAllButton2.setChecked(flag)

    # def fillPathBoxes(self):
    #     path1 = self.getPlayblastPath(self.getCurrentCameraName())
    #     if osp.exists(path1):
    #         self.playblastPathBox.setText(path1)
    #     path2 = self.getCachePath(self.getCurrentCameraName())
    #     if osp.exists(path2):
    #         self.cachePathBox.setText(path2)

    # def addLayers(self):
    #     for layer in PlayListUtils.getDisplayLayers():
    #         btn = QCheckBox(layer.name(), self)
    #         btn.setChecked(layer.visibility.get())
    #         self.layerLayout.addWidget(btn)
    #         self.layerButtons.append(btn)

    #     self.setSelectAllButton()
    #     for btn in self.layerButtons:
    #         btn.clicked.connect(self.setSelectAllButton)

    # def addObjects(self):
    #     for obj in exportutils.getObjects():
    #         btn = QCheckBox(obj, self)
    #         self.objectsLayout.addWidget(btn)
    #         self.objectButtons.append(btn)

    #     for btn in self.objectButtons:
    #         btn.clicked.connect(self.setSelectAllButton2)

    def getCurrentCameraName(self):
        return self.cameraBox.currentText().replace(":", "_").replace("|", "_")

    def fillName(self):
        self.nameBox.setText(self.getCurrentCameraName())

    # def cacheBrowseFolder(self):
    #     path = self.browseFolder()
    #     if path:
    #         self.cachePathBox.setText(path)

    # def playblastBrowseFolder(self):
    #     path = self.browseFolder()
    #     if path:
    #         self.playblastPathBox.setText(path)

    # def browseFolder(self):
    #     path = self.submitterWidget._previousPath
    #     if not path:
    #         path = ""
    #     path = QFileDialog.getExistingDirectory(self, "Select Folder", path)
    #     if path:
    #         self.submitterWidget._previousPath = path
    #     return path

    def handleCameraBox(self, camera):
        camera = str(camera)
        if self.keyFrameButton.isChecked():
            self.startFrame, self.endFrame = self.getKeyFrame()
            self.startFrameBox.setValue(self.startFrame)
            self.endFrameBox.setValue(self.endFrame)
        # self.fillPathBoxes()

    def addCameras(self):
        cams = pc.ls(type=pc.nt.Camera)
        names = [
            cam.firstParent().name()
            for cam in cams
            if not cam.orthographic.get()
        ]
        self.cameraBox.addItems(names)
        self.camCountLabel.setText(str(len(names)))
        self.addCamerasToStackedWidget(names)

    def handleSelectAllCameras(self):
        for btn in self.cameraButtons:
            btn.setChecked(self.selectAllCameras.isChecked())

    def toggleSelectedAllCameras(self):
        flag = True
        for btn in self.cameraButtons:
            if not btn.isChecked():
                flag = False
                break

        self.selectAllCameras.setChecked(flag)

    def addCamerasToStackedWidget(self, names):
        for name in names:
            btn = QCheckBox(name, self)
            btn.clicked.connect(self.toggleSelectedAllCameras)
            btn.setChecked(True)
            self.cameraLayout.addWidget(btn)
            self.cameraButtons.append(btn)

    def getSelectedCameras(self):
        return [btn.text() for btn in self.cameraButtons if btn.isChecked()]

    def populate(self):
        assert self.pl_item is not None, "Playlist item is None"
        self.nameBox.setText(self.pl_item.name)
        camera = self.pl_item.camera
        for index in range(self.cameraBox.count()):
            if camera == str(self.cameraBox.itemText(index)):
                self.cameraBox.setCurrentIndex(index)
                break

        # assert self.pl_item.inFrame is not None and self.pl_item.outFrame is not None

        self.startFrameBox.setValue(self.pl_item.inFrame)
        self.endFrameBox.setValue(self.pl_item.outFrame)
        # playblast = PlayblastExport.getActionFromList(self.pl_item.actions)
        # self.playblastPathBox.setText(playblast.path)
        # for layer in self.layerButtons:
        #     if str(layer.text()) in playblast.getLayers():
        #         layer.setChecked(True)
        #     else:
        #         layer.setChecked(False)

        # self.playblastEnableButton.setChecked(playblast.enabled)
        # cacheAction = CacheExport.getActionFromList(self.pl_item.actions)
        # for btn in self.objectButtons:
        #     if str(btn.text()) in cacheAction.objects:
        #         btn.setChecked(True)

        # self.cacheEnableButton.setChecked(cacheAction.enabled)
        # self.cachePathBox.setText(cacheAction.path)

        for tab in self.tabs:
            tab.updateObjectsStates()

    def getKeyFrame(
        self, camera: typing.Optional[pc.nt.Transform] = None
    ) -> typing.Tuple[int, int]:
        if camera is None:
            camera = typing.cast(
                "pc.nt.Transform", pc.PyNode(str(self.cameraBox.currentText()))
            )
        animCurves = pc.listConnections(camera, scn=True, d=False, s=True)
        if not animCurves:
            sui.showMessage(
                self,
                title="No Inout",
                msg=f"No in out found on {camera.name()}",
                icon=QMessageBox.Warning,
            )
            self.keyFrameButton.setChecked(False)
            return (0, 1)
        frames = pc.keyframe(animCurves[0], q=True)
        if not frames:
            sui.showMessage(
                self,
                msg=f"No in out found on {camera.name()}",
                icon=QMessageBox.Warning,
                title="No Inout",
            )
            self.keyFrameButton.setChecked(False)
            return (0, 1)
        return (frames[0], frames[-1])

    def handleKeyFrameClick(self):
        if self.keyFrameButton.isChecked():
            self.startFrame, self.endFrame = self.getKeyFrame()
            self.startFrameBox.setValue(self.startFrame)
            self.endFrameBox.setValue(self.endFrame)

    def autoCreate(self):
        return self.autoCreateButton.isChecked()

    def callCreate(self):
        # playblastPath = str(self.playblastPathBox.text())
        # cachePath = str(self.cachePathBox.text())
        # if self.playblastEnableButton.isChecked() and not self.autoCreate():
        #     if not playblastPath:
        #         sui.showMessage(
        #             self,
        #             title="No Path",
        #             msg="Playblast Path not specified",
        #             icon=QMessageBox.Warning,
        #         )
        #         return
        #     if not osp.exists(playblastPath):
        #         sui.showMessage(
        #             self,
        #             title="Error",
        #             msg="Playblast path does not " + "exist",
        #             icon=QMessageBox.Information,
        #         )
        #         return
        # if self.cacheEnableButton.isChecked():
        #     if not self.autoCreate():
        #         if not cachePath:
        #             sui.showMessage(
        #                 self,
        #                 title="Cache Path",
        #                 msg="Cache Path not specified",
        #                 icon=QMessageBox.Warning,
        #             )
        #             return
        #         if not osp.exists(cachePath):
        #             sui.showMessage(
        #                 self,
        #                 title="Error",
        #                 msg="Cache path does not " + "exist",
        #                 icon=QMessageBox.Information,
        #             )
        #             return
        #     if not [obj for obj in self.objectButtons if obj.isChecked()]:
        #         sui.showMessage(
        #             self,
        #             title="Shot Export",
        #             msg="No object selected "
        #             + "for cache, select at least one or uncheck the "
        #             + '"Enable" button',
        #         )
        #         return

        for tab in self.tabs:
            if tab.stateToggle.isChecked():
                if tab.OBJECT_SELECTION_REQUIRED and all(
                    btn.isChecked() is False
                    for btn in tab.getObjectWidgets()
                    if isinstance(btn, QCheckBox)
                ):
                    sui.showMessage(
                        self,
                        title="Shot Export",
                        msg="No object selected for "
                        + tab.getTabName()
                        + ", select at least one or uncheck the "
                        + '"Enable" button',
                    )
                    return

                if self.item and not Path(tab.pathBox.text()).exists():
                    sui.showMessage(
                        self,
                        title="Shot Export",
                        msg=f"Path for {tab.getTabName()} does not exist",
                    )
                    return

        if not self.item:
            self.createAll()
        else:
            name = str(self.nameBox.text())
            if not name:
                sui.showMessage(
                    self, title="Shot name", msg="Shot name not specified"
                )
                return
            camera = typing.cast(
                "pc.nt.Transform", pc.PyNode(str(self.cameraBox.currentText()))
            )
            if self.keyFrameButton.isChecked():
                start = self.startFrame
                end = self.endFrame
                assert start is not None and end is not None
            else:
                start = self.startFrameBox.value()
                end = self.endFrameBox.value()
            self.create(name, camera, start, end)

    def getSelectedLayers(self):
        return [
            str(layer.text())
            for layer in self.layerButtons
            if layer.isChecked()
        ]

    def createAll(self):
        prefixPath = self.getSeqPath()
        if not osp.exists(prefixPath):
            sui.showMessage(
                self,
                title="Error",
                msg="Sequence path does not exist",
                icon=QMessageBox.Information,
            )
            self.progressBar.hide()
            return
        cams = self.getSelectedCameras()
        if not cams:
            sui.showMessage(
                self,
                title="Shot Export",
                msg="No camera selected",
                icon=QMessageBox.Information,
            )
            self.progressBar.hide()
            return
        _max = len(cams)
        self.progressBar.setMaximum(_max)
        self.progressBar.show()
        for i, name in enumerate(cams):
            pathName = name.split(":")[-1].split("|")[-1]
            cam = typing.cast("pc.nt.Transform", pc.PyNode(name))
            start, end = self.getKeyFrame(cam)
            self.create(pathName, cam, start, end)
            self.progressBar.setValue(i + 1)
            qApp.processEvents()

        self.progressBar.hide()
        self.progressBar.setValue(0)
        self.accept()

    def getSeqPath(self):
        return str(self.submitterWidget.pathBox.text())

    def getSelectedObjects(self):
        objs = []
        for obj in self.objectButtons:
            if obj.isChecked():
                objs.append(str(obj.text()))

        return objs

    def create(
        self,
        name: str,
        camera: pc.nt.Transform,
        start: int,
        end: int,
    ):
        if self.pl_item:
            self.pl_item.name = name
            self.pl_item.camera = camera
            self.pl_item.inFrame = start
            self.pl_item.outFrame = end
            widgets: typing.List[QHBoxLayout] = []
            for tab in self.tabs:
                tab.setupAction()
                path = tab.pathBox.text() or tab.getExportPath(
                    self.submitterWidget, camera=camera
                )
                widgets.append(tab.getItemInformationLayout(path))
            # pb = PlayblastExport.getActionFromList(self.pl_item.actions)
            # pb.enabled = self.playblastEnableButton.isChecked()
            # pb.path = playblastPath
            # pb.addLayers(self.getSelectedLayers())
            # ce = CacheExport.getActionFromList(self.pl_item.actions)
            # ce.enabled = self.cacheEnableButton.isChecked()
            # ce.path = cachePath
            # ce.objects = self.getSelectedObjects()
            # fbxe = FBXExport.getActionFromList(self.pl_item.actions)
            # fbxe.enabled = self.fbxEnableButton.isChecked()
            # fbxe.path = self.fbxPathBox.text()
            self.pl_item.saveToScene()
            self.submitterWidget.getItem(self.pl_item, True, widgets).update()
            for tab in self.tabs:
                tab.updateInformationWidget()

            self.accept()
        else:
            if not PlayListUtils.getAttrs(camera):
                playlist = self.submitterWidget.playlist
                newItem = playlist.addNewItem(camera)
                newItem.name = name
                newItem.inFrame = start
                newItem.outFrame = end
                widgets: typing.List[QHBoxLayout] = []
                for tab in self.tabs:
                    action = tab.setupAction(newItem)
                    newItem.actions.add(action)
                    path = tab.pathBox.text() or tab.getExportPath(
                        self.submitterWidget, camera=camera
                    )
                    widgets.append(tab.getItemInformationLayout(path))
                # pb = PlayblastExport()
                # pb.enabled = self.playblastEnableButton.isChecked()
                # pb.addLayers(self.getSelectedLayers())
                # if playblastPath:
                #     pb.path = playblastPath
                # ce = CacheExport()
                # ce.enabled = self.cacheEnableButton.isChecked()
                # ce.objects = self.getSelectedObjects()
                # if cachePath:
                #     ce.path = cachePath
                # newItem.actions.add(pb)
                # newItem.actions.add(ce)
                newItem.saveToScene()
                self.submitterWidget.createItem(newItem, widgets)

    def closeEvent(self, event):
        self.deleteLater()


class Item(QWidget):
    text = "Select One Path"
    version = int(re.search("\\d{4}", pc.about(v=True)).group())  # type: ignore
    clicked = QtCore.Signal()
    pl_item: PlaylistItem

    addButton: QToolButton
    deleteButton: QToolButton
    appendButton: QToolButton
    editButton: QToolButton
    collapseButton: QPushButton
    switchButton: QToolButton
    nameLabel: QLabel
    removeButton: QToolButton
    selectButton: QCheckBox
    titleFrame: QFrame
    frame: QFrame
    frameLabel: QPushButton
    cameraLabel: QPushButton
    # playblastPathLabel: QPushButton
    # cachePathLabel: QPushButton
    # FBXPathLabel: QPushButton
    informationLayout: QVBoxLayout

    def __init__(
        self,
        parent: SubmitterWidget,
        pl_item: PlaylistItem,
        extra_information: typing.Optional[typing.Iterable[QHBoxLayout]] = None,
    ):
        super().__init__(parent=parent)
        sui.loadUi(uifile=osp.join(ui_path, "item.ui"), baseinstance=self)
        self.pl_item = pl_item
        #  self.setupUi(self)
        self.parentWin: SubmitterWindow = parent.parent()
        self.submitterWidget = parent
        self.collapsed = False
        self.setStyleSheet(
            "background-image: url(%s);\n"
            + "background-repeat: no-repeat;\n"
            + "background-position: center right"
        )
        self.editButton.setIcon(QIcon(osp.join(icon_path, "ic_edit.png")))
        self.deleteButton.setIcon(QIcon(osp.join(icon_path, "ic_delete.png")))
        self.collapseButton.setIcon(
            QIcon(osp.join(icon_path, "ic_collapse.png"))
        )
        self.switchButton.setIcon(
            QIcon(osp.join(icon_path, "ic_switch_camera.png"))
        )
        self.appendButton.setIcon(
            QIcon(osp.join(icon_path, "ic_append_char.png"))
        )
        self.removeButton.setIcon(
            QIcon(osp.join(icon_path, "ic_remove_char.png"))
        )
        self.addButton.setIcon(QIcon(osp.join(icon_path, "ic_add_char.png")))
        self.editButton.clicked.connect(self.edit)
        self.clicked.connect(self.submitterWidget.itemClicked)
        self.selectButton.clicked.connect(self.submitterWidget.itemClicked)
        self.selectButton.clicked.connect(self.toggleSelected)
        self.deleteButton.clicked.connect(self.delete)
        self.titleFrame.mousePressEvent = lambda event: self.toggleCollapse(
            self.frame.isVisible()
        )
        self.ICMCEF = ItemCollapseMouseClickEventFilter(
            self.titleFrame,
            lambda e: self.toggleCollapse(self.frame.isVisible()),
        )
        self.collapseButton.clicked.connect(
            lambda: self.toggleCollapse(self.frame.isVisible())
        )
        self.switchButton.clicked.connect(self.switchCamera)
        self.appendButton.clicked.connect(self.turnSelectedObjectsOn)
        self.removeButton.clicked.connect(self.turnSelectedObjectsOff)
        self.addButton.clicked.connect(self.turnOnlySelectedObjectsOn)
        # self.label.mouseDoubleClickEvent = lambda event: self.openLocation()
        # self.label_2.mouseDoubleClickEvent = lambda event: self.openLocation2()
        # doesnt work in pyside2
        # self.playblastPathLabel.clicked.connect(
        #     lambda event: self.openLocation()
        # )
        # self.cachePathLabel.clicked.connect(lambda event: self.openLocation2())

        label_text_align = "text-align:left;"

        self.frameLabel.setStyleSheet(label_text_align)
        # self.playblastPathLabel.setStyleSheet(label_text_align)
        # self.cachePathLabel.setStyleSheet(label_text_align)
        self.cameraLabel.setStyleSheet(label_text_align)

        # self.extra_widgets = extra_widgets or []
        print(f"extra info = {extra_information}")
        for child in extra_information or []:
            if isinstance(child, QHBoxLayout):
                self.informationLayout.addWidget(
                    QFrame(
                        parent=self.frame,
                        frameShape=QFrame.Shape.HLine,
                        frameShadow=QFrame.Shadow.Sunken,
                    )
                )
                self.informationLayout.addLayout(child)
            else:
                raise TypeError(
                    "Extra widgets must be instances of QHBoxLayout, got %s"
                    % type(child).__name__
                )

        print(
            [
                self.informationLayout.itemAt(i)
                for i in range(self.informationLayout.count())
            ]
        )

    def switchCamera(self):
        assert self.pl_item is not None, "Playlist item is None"
        exportutils.switchCam(self.pl_item.camera)

    def turnSelectedObjectsOff(self):
        assert self.pl_item is not None, "Playlist item is None"
        action = CacheExport.getActionFromList(self.pl_item.actions)
        if action:
            objects = backend.findAllConnectedGeosets()
            if not objects:
                sui.showMessage(
                    self,
                    title="Shot Export",
                    msg="No objects found in the selection",
                    icon=QMessageBox.Information,
                )
                return
            action.removeObjects([obj.name() for obj in objects])
            self.pl_item.saveToScene()
            length = len(objects)
            temp = "s" if length > 1 else ""
            exportutils.showInViewMessage(
                str(length)
                + " object%s removed form %s" % (temp, self.pl_item.name)
            )

    def turnSelectedObjectsOn(self):
        assert self.pl_item is not None, "Playlist item is None"
        action = CacheExport.getActionFromList(self.pl_item.actions)
        if action:
            objects = backend.findAllConnectedGeosets()
            if not objects:
                sui.showMessage(
                    self,
                    title="Shot Export",
                    msg="No objects found in the selection",
                    icon=QMessageBox.Information,
                )
                return
            action.appendObjects([obj.name() for obj in objects])
            self.pl_item.saveToScene()
            length = len(objects)
            temp = "s" if length > 1 else ""
            exportutils.showInViewMessage(
                str(length)
                + " object%s added to %s" % (temp, self.pl_item.name)
            )

    def turnOnlySelectedObjectsOn(self):
        assert self.pl_item is not None, "Playlist item is None"
        action = CacheExport.getActionFromList(self.pl_item.actions)
        if action:
            objects = backend.findAllConnectedGeosets()
            if not objects:
                sui.showMessage(
                    self,
                    title="Shot Export",
                    msg="No objects found in the selection",
                    icon=QMessageBox.Information,
                )
                return
            action.objects = [obj.name() for obj in objects]
            self.pl_item.saveToScene()
            length = len(objects)
            temp = "s" if length > 1 else ""
            exportutils.showInViewMessage(
                str(length)
                + " object%s added to %s" % (temp, self.pl_item.name)
            )

    def update(
        self,
    ):
        if self.pl_item:
            self.setTitle(self.pl_item.name)
            self.setCamera(self.pl_item.camera.name())
            # playblastPath = PlayblastExport.getActionFromList(
            #     self.pl_item.actions
            # ).path
            # self.setPlayblastPath(str(Path(playblastPath)))
            # self.setCachePath(
            #     str(
            #         Path(
            #             CacheExport.getActionFromList(self.pl_item.actions).path
            #         )
            #     )
            # )

            self.setFrame(
                "%d to %d" % (self.pl_item.inFrame, self.pl_item.outFrame)
            )

    def collapse(self, event=None):
        if self.collapsed:
            self.frame.show()
            self.collapsed = False
            path = osp.join(icon_path, "ic_collapse.png")
        else:
            self.frame.hide()
            self.collapsed = True
            path = osp.join(icon_path, "ic_expand.png")
        path = path.replace("\\", "/")
        self.collapseButton.setIcon(QIcon(path))

    def toggleCollapse(self, state):
        self.collapsed = not state
        self.collapse()

    def openLocation(self):
        assert self.pl_item is not None, "Playlist item is None"
        pb = PlayblastExport.getActionFromList(self.pl_item.actions)
        if not osp.exists(pb.path):
            sui.showMessage(
                self.submitterWidget,
                title="Path Error",
                msg="Path does not exist",
                icon=QMessageBox.Information,
            )
            return
        subprocess.call("explorer %s" % pb.path, shell=True)

    def openLocation2(self):
        assert self.pl_item is not None, "Playlist item is None"
        ce = CacheExport.getActionFromList(self.pl_item.actions)
        if not osp.exists(ce.path):
            sui.showMessage(
                self.submitterWidget,
                title="Path Error",
                msg="Path does not exist",
                icon=QMessageBox.Information,
            )
            return
        subprocess.call("explorer %s" % ce.path, shell=True)

    def delete(self):
        btn = sui.showMessage(
            self,
            title="Delete Shot",
            msg="Are you sure, delete " + '"' + self.getTitle() + '"?',
            icon=QMessageBox.Critical,
            btns=QMessageBox.Yes | QMessageBox.No,
        )
        if btn == QMessageBox.Yes:
            self.submitterWidget.removeItem(self)

    def setTitle(self, title):
        self.nameLabel.setText(title)

    def getTitle(self):
        return str(self.nameLabel.text())

    def setCamera(self, camera):
        self.cameraLabel.setText(camera)

    def getCamera(self):
        return str(self.cameraLabel.text())

    def setFrame(self, frame):
        self.frameLabel.setText(frame)

    def getFrame(self):
        return str(self.frameLabel.text())

    # def setPlayblastPath(self, path):
    #     self.playblastPathLabel.setText(path)

    # def getPlayblastPath(self):
    #     return str(self.playblastPathLabel.text())

    # def setCachePath(self, path):
    #     self.cachePathLabel.setText(path)

    # def getCachePath(self):
    #     return str(self.cachePathLabel.text())

    # def setFBXPath(self, path):
    #     self.FBXPathLabel.setText(path)

    # def getFBXPath(self):
    #     return str(self.FBXPathLabel.text())

    def setChecked(self, state):
        if self.pl_item:
            self.pl_item.selected = state
        self.selectButton.setChecked(state)

    def isChecked(self):
        return self.selectButton.isChecked()

    def toggleSelected(self):
        if self.pl_item:
            self.pl_item.selected = not self.pl_item.selected

    def toggleSelection(self):
        if self.pl_item:
            self.pl_item.selected = not self.selectButton.isChecked()
        self.selectButton.setChecked(not self.selectButton.isChecked())

    def mouseReleaseEvent(self, event):
        self.clicked.emit()

    def edit(self):
        self.submitterWidget.editItem(self)


class ItemCollapseMouseClickEventFilter(QtCore.QObject):
    def __init__(self, widget, callback):
        super().__init__(widget)
        self.callback = callback
        self._widget = widget
        self.widget.installEventFilter(self)

    @property
    def widget(self):
        return self._widget

    def eventFilter(self, obj, event):
        if (
            obj is self.widget
            and event.type() == QtCore.QEvent.MouseButtonPress
        ):
            self.callback(event)
        return super().eventFilter(obj, event)
