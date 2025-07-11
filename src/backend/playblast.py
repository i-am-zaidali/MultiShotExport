import contextlib
import json
import os
import os.path as osp
import subprocess
import threading
import typing
from typing import TYPE_CHECKING

import pymel.core as pc
from PySide2.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton

from ..shot_form_tab import ShotFormExportTypeTab
from . import exportutils, imaya, shotactions, shotplaylist
from .exceptions import *  # noqa: F403

if TYPE_CHECKING:
    from .._submit import Item, ShotForm, SubmitterWidget
    from ..backend.shotplaylist import PlaylistItem

PlayListUtils = shotplaylist.PlaylistUtils
Action = shotactions.Action
__poly_count__ = False
__HUD_DATE__ = "__HUD_DATE__"
__HUD_LABEL__ = "__HUD_LABEL__"
__HUD_USERNAME__ = "__HUD_USERNAME__"
__CURRENT_FRAME__ = 0.0


def playblast(data):
    pc.playblast(
        st=data["start"],
        et=data["end"],
        f=data["path"],
        fo=True,
        quality=100,
        w=1280,
        h=720,
        compression="MS-CRAM",
        percent=100,
        format="avi",
        sequenceTime=0,
        clearCache=True,
        viewer=False,
        showOrnaments=True,
        fp=4,
        offScreen=True,
    )


def getUsername():
    return ""


def label():
    return ""


def recordCurrentFrame():
    global __CURRENT_FRAME__
    __CURRENT_FRAME__ = pc.currentTime()


def restoreCurrentFrame():
    pc.currentTime(__CURRENT_FRAME__)


def hidePolyCount():
    global __poly_count__
    if pc.optionVar(q="polyCountVisibility"):
        __poly_count__ = True
        pc.Mel.eval("setPolyCountVisibility(0)")


def showPolyCount():
    global __poly_count__
    if __poly_count__:
        pc.Mel.eval("setPolyCountVisibility(1)")
        __poly_count__ = False


def showNameLabel():
    if pc.headsUpDisplay(__HUD_LABEL__, q=True, exists=True):
        pc.headsUpDisplay(__HUD_LABEL__, remove=True)
    pc.headsUpDisplay(
        __HUD_LABEL__,
        section=2,
        block=pc.headsUpDisplay(nfb=2),
        blockSize="large",
        dfs="large",
        command=label,
    )
    if pc.headsUpDisplay(__HUD_USERNAME__, q=True, exists=True):
        pc.headsUpDisplay(__HUD_USERNAME__, remove=True)
    pc.headsUpDisplay(
        __HUD_USERNAME__,
        section=3,
        block=pc.headsUpDisplay(nfb=3),
        blockSize="large",
        dfs="large",
        command=getUsername,
    )
    pc.headsUpDisplay(__HUD_USERNAME__, e=True, dfs="large")


def showDate():
    global __HUD_DATE__
    if pc.headsUpDisplay(__HUD_DATE__, q=True, exists=True):
        pc.headsUpDisplay(__HUD_DATE__, remove=True)
    pc.headsUpDisplay(
        __HUD_DATE__,
        section=1,
        block=pc.headsUpDisplay(nfb=1),
        blockSize="large",
        dfs="large",
        command='import pymel.core as pc;pc.date(format="DD/MM/YYYY hh:mm")',
    )


def removeNameLabel():
    if pc.headsUpDisplay(__HUD_LABEL__, exists=True):
        pc.headsUpDisplay(__HUD_LABEL__, rem=True)
    if pc.headsUpDisplay(__HUD_USERNAME__, exists=True):
        pc.headsUpDisplay(__HUD_USERNAME__, rem=True)


def removeDate():
    if pc.headsUpDisplay(__HUD_DATE__, exists=True):
        pc.headsUpDisplay(__HUD_DATE__, rem=True)


class PlayblastExport(Action):
    _conf = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._conf = self.initConf()
        if not self.get("layers"):
            self["layers"] = []
        if not self.path:
            self.path = osp.expanduser("~")

    @staticmethod
    def initConf():
        conf = {}
        playblastargs = {}
        playblastargs["format"] = "qt"
        playblastargs["fo"] = True
        playblastargs["quality"] = 100
        playblastargs["w"] = 1280
        playblastargs["h"] = 720
        playblastargs["percent"] = 100
        playblastargs["compression"] = "H.264"
        playblastargs["format"] = "qt"
        playblastargs["sequenceTime"] = 0
        playblastargs["clearCache"] = True
        playblastargs["viewer"] = False
        playblastargs["showOrnaments"] = True
        playblastargs["fp"] = 4
        playblastargs["offScreen"] = True
        huds = {}
        conf["playblastargs"] = playblastargs
        conf["HUDs"] = huds
        return conf

    def perform(self, readconf=True, **kwargs):
        if self.enabled:
            for layer in PlayListUtils.getDisplayLayers():
                if layer.name() in self.objects:
                    layer.visibility.set(1)
                else:
                    layer.visibility.set(0)

            item = self.__item__
            try:
                if readconf:
                    self.read_conf()
            except IOError:
                self._conf = PlayblastExport.initConf()

            pc.select(item.camera)
            pc.lookThru(item.camera)
            hidePolyCount()
            showDate()
            exportutils.turnResolutionGateOn(item.camera)
            exportutils.showFrameInfo(item)
            exportutils.setDefaultResolution(
                (1920, 1080), default=kwargs.get("defaultResolution", False)
            )
            exportutils.turn2dPanZoomOff(item.camera)
            if not kwargs.get("hdOnly"):
                t = threading.Thread(
                    target=self.makePlayblast,
                    kwargs={
                        "sound": kwargs.get("sound"),
                        "local": kwargs.get("local"),
                    },
                )
                t.start()

            exportutils.turnResolutionGateOff(item.camera)
            if kwargs.get("hd"):
                exportutils.turnResolutionGateOffPer(item.camera)
                exportutils.setDefaultResolution((1920, 1080))
                # t = threading.Thread(
                #     target=self.makePlayblast,
                #     kwargs={
                #         "sound": kwargs.get("sound"),
                #         "hd": True,
                #         "local": kwargs.get("local"),
                #     },
                # )
                # t.start()
                self.makePlayblast(
                    sound=kwargs.get("sound"),
                    hd=True,
                    local=kwargs.get("local", False),
                )
                showNameLabel()
            exportutils.removeFrameInfo(all=True)
            removeDate()
            removeNameLabel()
            showPolyCount()
            exportutils.restoreDefaultResolution()
            exportutils.restore2dPanZoom(item.camera)
        exportutils.restoreFrameInfo()

    @property
    def objects(self) -> typing.List[str]:
        """Get the list of objects to export."""
        return self.get("layers", [])

    @objects.setter
    def objects(self, value: typing.List[str]):
        """Set the list of objects to export."""
        if not isinstance(value, list):
            raise TypeError("Layers must be a list")
        self["layers"][:] = value

    @property
    def path(self) -> str:
        return self.get("path", "")

    @path.setter
    def path(self, val):
        self["path"] = val

    def addHUDs(self):
        conf = self._conf
        for hud in conf.get("HUDs", {}):
            if pc.headsUpDisplay(hud, q=True, exists=True):
                pc.headsUpDisplay(hud, remove=True)
            pc.headsUpDisplay(hud, **conf["HUDS"][hud])

    def removeHUDs(self):
        conf = self._conf
        for hud in conf.get("HUDs", []):
            if pc.headsUpDisplay(hud, q=True, exists=True):
                pc.headsUpDisplay(hud, remove=True)

    def makePlayblast(
        self,
        item: "PlaylistItem | None" = None,
        sound=None,
        hd=False,
        local=False,
    ):
        if not item:
            item = self.__item__
            if not item:
                pc.warning("Item not set: cannot make playblast")
        if sound:
            sound = exportutils.getAudioNode()
            if not sound:
                sound = [""]
        else:
            sound = [""]
        itemName = imaya.getNiceName(item.name)
        tempFilePath = osp.join(self.tempPath.name, itemName)

        # assert (item.inFrame is not None) and (item.outFrame is not None)

        pc.playblast(
            format="qt",
            fo=1,
            st=item.inFrame,
            et=item.outFrame,
            f=tempFilePath,
            s=str(sound[0]),
            sequenceTime=0,
            clearCache=1,
            viewer=0,
            showOrnaments=1,
            fp=4,
            percent=100,
            compression="H.264",
            quality=100,
            widthHeight=exportutils.getDefaultResolution(),
            offScreen=1,
        )

        # maya.utils.executeInMainThreadWithResult(get_playblast)

        tempFilePath += ".mov"
        if hd:
            depth = 4
            path: str = self.path  # type: ignore
            with contextlib.suppress(Exception):
                os.mkdir(path)

        else:
            depth = 3
            path: str = self.path  # type: ignore
        infoFilePath = osp.join(osp.dirname(tempFilePath), itemName + ".json")
        infoFileOrigPath = osp.join(path, itemName + ".json")
        data = ""
        if osp.exists(infoFileOrigPath):
            with open(infoFileOrigPath) as ifr:
                data = json.loads(ifr.read())
        with open(infoFilePath, "a") as infoFile:
            newData = [
                {
                    "user": getUsername(),
                    "time": pc.date(format="DD/MM/YYYY hh:mm"),
                    "inOut": "-".join([str(item.inFrame), str(item.outFrame)]),
                    "name": itemName,
                    "focalLength": item.camera.focalLength.get(),
                }
            ]
            if data:
                if isinstance(data, list):
                    newData[0]["user"] = data[0]["user"]
                    newData.extend(data)
                if isinstance(data, dict):
                    newData[0]["user"] = data["user"]
                    newData.append(data)
            infoFile.write(json.dumps(newData))
        # if local:
        #     path = exportutils.getLocalDestination(path, depth)
        exportutils.copyFile(infoFilePath, self.path, depth=3)
        exportutils.copyFile(tempFilePath, path, depth=depth)

    @staticmethod
    def getTabUI() -> typing.Type["PlayblastExportTab"]:
        """Get the UI for this action."""
        return PlayblastExportTab


class PlayblastExportTab(ShotFormExportTypeTab["PlayblastExport"]):
    OBJECT_SELECTION_REQUIRED = False
    PARENT_ACTION = PlayblastExport

    def __init__(self, parent: "ShotForm", item: "Item | None" = None):
        super().__init__(parent, item=item)
        self.setObjectName("PlayblastExportTab")
        if item:
            self.pathBox.setText(item.findChild(QLabel, "playblastPathLabel").text())

    def populateObjectsDefaults(self):
        for obj in exportutils.getObjects():
            btn = QCheckBox(obj, self)
            btn.setChecked(False)
            self.objectsLayout.addWidget(btn)

        self.setSelectAllState()
        for btn in self.getObjectWidgets():
            assert isinstance(btn, QCheckBox), "Expected QCheckBox"
            btn.clicked.connect(self.setSelectAllState)

    def getObjectsDescription(self):
        """Set the description for the objects in this tab."""
        return "Select the layers you want to include in the playblast. "

    @staticmethod
    def getExportPath(parent: "SubmitterWidget", camera: "pc.nt.Transform") -> str:
        """Get the save path for this export type."""
        return parent.getPlayblastPath(camera)

    def getTabName(self) -> str:
        return "Playblast"

    def updateInformationWidget(self):
        """Update the information widget with the current item information."""
        if self.item is None:
            return
        layout = self.item.informationLayout.findChild(
            QHBoxLayout, "playblastInformationLayout"
        )
        # Update the playblast path label
        label = layout.findChild(QLabel, "playblastPathLabel")
        if label:
            label.setText("Playblast Path:")
        # Update the playblast path button
        button = layout.findChild(QPushButton, "playblastPathButton")
        if button:
            button.setText(self.pathBox.text())
            button.clicked.disconnect()
            button.clicked.connect(
                lambda: subprocess.call(f'explorer "{self.pathBox.text()}"', shell=True)
            )
