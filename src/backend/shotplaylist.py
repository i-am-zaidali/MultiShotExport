import collections
import contextlib
import itertools
import json
import re
import typing
from logging import getLogger

import maya.cmds as cmds
import pymel.core as pc
import typing_extensions as te

from .shotactions import Action, ActionList

log = getLogger("ShotPlaylist")


class Playlist:
    def __new__(cls, code="", populate=True):
        if not isinstance(code, str):
            raise TypeError("code must be string or unicode")
        code = re.sub("[^a-z]", "", code.lower())
        if not plu.__playlistinstances__.get(code):
            plu.__playlistinstances__[code] = super().__new__(cls)
        else:
            plu.__playlistinstances__[code].sync()
        return plu.__playlistinstances__[code]

    def __init__(self, code="", populate=True):
        self._code = code
        self.actionsOrder = ("PlayblastExport", "CacheExport", "FBXExport")
        if populate:
            self.populate()

    @property
    def code(self):
        return self._code

    def populate(self):
        attrs = plu.getSceneAttrs()
        for a in attrs:
            PlaylistItem(a, readFromScene=True, saveToScene=False)

    def __itemBelongs(self, item: "PlaylistItem"):
        return bool(not self._code or self._code in item.__playlistcodes__)

    def __addCodeToItem(self, item: "PlaylistItem"):
        if self._code and not self.__itemBelongs(item):
            item.__playlistcodes__.append(self._code)

    def __removeCodeFromItem(self, item: "PlaylistItem"):
        if self._code and self.__itemBelongs(item):
            item.__playlistcodes__.remove(self._code)

    def sync(self, deleteBadItems=False):
        for item in plu.__iteminstances__.values():
            if self.__itemBelongs(item):
                try:
                    item.readFromScene()
                except pc.MayaNodeError:
                    if deleteBadItems:
                        item.__remove__()

    def store(self, removeBadItems=True):
        for item in plu.__iteminstances__.values():
            if self.__itemBelongs(item):
                try:
                    item.saveToScene()
                except pc.MayaNodeError:
                    if removeBadItems:
                        item.__remove__()

    def addItem(self, item):
        self.__addCodeToItem(item)

    def addNewItem(self, camera):
        newItem = PlaylistItem(plu.createNewAttr(camera))
        self.addItem(newItem)
        return newItem

    def removeItem(self, item):
        if not self._code:
            item.__remove__()
        else:
            self.__removeCodeFromItem(item)

    def getItems(self, name=""):
        return [
            item
            for item in plu.__iteminstances__.values()
            if self.__itemBelongs(item)
        ]

    def performActions(self, **kwargs):
        allActions: typing.Dict[str, typing.List[Action]] = {}
        for item in self.getItems():
            if item.selected:
                assert item.actions is not None
                for action in item.actions.getActions():
                    if action.enabled:
                        allActions.setdefault(
                            action.__class__.__name__, []
                        ).append(action)

        log.info(allActions)
        counter = itertools.count()
        collections.deque(
            zip(counter, itertools.chain(*allActions.values())), maxlen=0
        )
        yield next(counter)  # count of all the actions.
        for actiontype in self.actionsOrder:
            actions = allActions.get(actiontype)
            if not actions:
                continue
            for action in actions:
                try:
                    log.info(f"Performing action: {action}")
                    action.perform(**kwargs)
                    log.info(f"Action {action} performed successfully")
                    yield action
                except Exception as ex:
                    log.error(f"Error performing action {action}: {ex}")
                    yield (action.plItem, ex)


class PlaylistItem:
    def __new__(cls, attr, *args, **kwargs):
        if not isinstance(attr, pc.Attribute):
            print(attr, type(attr))
            raise TypeError("'attr' can only be of type pymel.core.Attribute")
        if not attr.objExists() or not attr.node().getShapes(type="camera"):
            raise TypeError(
                "Attribute %s does not exist on a camera" % attr.name
            )
        if not plu.__iteminstances__.get(attr):
            plu.__iteminstances__[attr] = super().__new__(cls)
        return plu.__iteminstances__[attr]

    def __init__(
        self,
        attr: pc.Attribute,
        name: str = "",
        inframe: typing.Optional[int] = None,
        outframe: typing.Optional[int] = None,
        selected: bool = False,
        readFromScene: bool = False,
        saveToScene: bool = True,
    ):
        if not isinstance(name, str):
            raise TypeError("'name' can only be of type str")
        self.__attr = attr
        self._camera = self.__attr.node()
        self.__data = {}
        if readFromScene:
            self.readFromScene()
        if name:
            self.name = name
        if inframe:
            self.inFrame = inframe
        if outframe:
            self.outFrame = outframe
        if not self.name:
            self.name = self.camera.name().split("|")[-1].split(":")[-1]
        if (
            not inframe
            or not outframe
            or not self.__data.get("inFrame")
            or not self.__data.get("outFrame")
        ):
            self.autosetInOut()
        if "playlistcodes" not in self.__data:
            self.__data["playlistcodes"] = []
        if not self.__data.get("actions"):
            self.actions = ActionList(self)
        self._selected = selected
        if saveToScene:
            self.saveToScene()

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, val):
        self._selected = val

    @property
    def name(self) -> str:
        return self.__data.get("name", "")

    @name.setter
    def name(self, name):
        if not isinstance(name, str):
            raise TypeError("Name must be a string")
        self.__data["name"] = name

    @property
    def inFrame(self) -> int:
        return self.__data.get("inFrame", 0)

    @inFrame.setter
    def inFrame(self, inFrame):
        if not isinstance(inFrame, (int, float)):
            raise TypeError("In frame must be a number")
        self.__data["inFrame"] = inFrame

    @property
    def outFrame(self) -> int:
        return self.__data.get("outFrame", 1)

    @outFrame.setter
    def outFrame(self, outFrame):
        if not isinstance(outFrame, (int, float)):
            raise TypeError("Out frame must be a number")
        self.__data["outFrame"] = outFrame

    @property
    def camera(self) -> pc.nt.Transform:
        return self.__attr.node()  # type: ignore[return-value]

    @camera.setter
    def camera(
        self,
        val: typing.Union[
            pc.nt.Transform,
            typing.Tuple[pc.nt.Transform, bool, bool],
            typing.Any,
        ],
    ):
        if isinstance(val, tuple):
            if len(val) != 3:
                raise TypeError(
                    "value must either be a tuple of (camera, dontDelete, dontSave) or just a camera"
                )
            else:
                camera, dontDelete, dontSave = val
                assert (
                    isinstance(camera, pc.nt.Transform)
                    and isinstance(dontDelete, bool)
                    and isinstance(dontSave, bool)
                ), (
                    f"Expected (pc.nt.Transform, bool, bool), got ({type(camera)} ({camera}), {type(dontDelete)} ({dontDelete}), {type(dontSave)} ({dontSave}))"
                )

        else:
            assert isinstance(val, pc.nt.Transform), (
                f"Expected `pc.nt.Transform`, got {type(val)} ({val})"
            )
            camera, dontDelete, dontSave = (val, False, False)

        if plu.isNodeValid(camera) and camera != self._camera:
            oldattr = self.__attr
            self.__attr = plu.createNewAttr(camera)
            if not dontDelete:
                plu.deleteAttr(oldattr)
            if not dontSave:
                self.saveToScene()
            plu.__iteminstances__[self.__attr] = self
            del plu.__iteminstances__[oldattr]

    @property
    def actions(self) -> ActionList:
        actionlist = self.__data.get("actions")
        assert actionlist is not None
        return actionlist

    @actions.setter
    def actions(self, value):
        if isinstance(value, ActionList):
            self.__data["actions"] = value
        else:
            raise TypeError("Invalid type: %s Expected" % str(ActionList))

    def saveToScene(self):
        if not self.existsInScene():
            if self.nodeExistsInScene():
                self.camera = (self.__attr.node(), True, True)
            else:
                raise pc.MayaNodeError(
                    "camera %s does not exist" % self.__attr.node().name()
                )
        print("saving to scene: ", self.__data)
        datastring = json.dumps(self.__data)
        self.__attr.set(datastring)

    def readFromScene(self):
        if not self.existsInScene():
            raise pc.MayaNodeError(
                "Attribute %s Does not exist in scene" % self.__attr.name()
            )
        datastring = self.__attr.get()
        if datastring:
            self.__data = json.loads(datastring)
            if "actions" not in self.__data:
                self.__data["actions"] = {}
            self.actions = ActionList(self)

    @property
    def __playlistcodes__(self) -> typing.List[str]:
        return self.__data.get("playlistcodes", [])

    def existsInScene(self):
        return pc.objExists(self.__attr)

    def nodeExistsInScene(self):
        return self.__attr.node().objExists()

    def __remove__(self):
        with contextlib.suppress(KeyError):
            plu.__iteminstances__.pop(self.__attr)

        with contextlib.suppress(pc.MayaAttributeError):
            self.__attr.delete()

    def autosetInOut(self):
        inframe, outframe = (None, None)
        camera = self._camera
        animCurves = pc.listConnections(camera, scn=True, d=False, s=True)
        if animCurves:
            frames = typing.cast(
                "typing.List[int]", pc.keyframe(animCurves[0], q=True)
            )
            if frames:
                inframe, outframe = frames[0], frames[-1]
        if not inframe or not outframe:
            if not self.inFrame or not self.outFrame:
                self.inFrame, self.outFrame = (0, 1)
        else:
            self.inFrame, self.outFrame = inframe, outframe

        return self.inFrame, self.outFrame


class PlaylistUtils(object):
    attrPattern = re.compile(r".*\.ShotInfo_(\d{2})")
    __iteminstances__: typing.Dict[pc.Attribute, PlaylistItem] = {}
    __playlistinstances__: typing.Dict[str, Playlist] = {}

    @staticmethod
    def isNodeValid(node: pc.PyNode) -> te.TypeGuard[pc.nt.Transform]:
        if not isinstance(node, pc.nt.Transform) or not node.getShapes(
            type="camera"
        ):
            raise TypeError(
                f"node {repr(node)} must be a pc.nt.Transform of a camera shape"
            )
        return True

    @staticmethod
    def getSceneAttrs():
        """Get all shotInfo attributes in the Scene (or current namespace)"""
        attrs: typing.List[pc.Attribute] = []
        for camera in pc.ls(cameras=True):
            node = camera.firstParent()
            if isinstance(node, pc.nt.Transform):
                attrs.extend(PlaylistUtils.getAttrs(node))

        return attrs

    @staticmethod
    def getAttrs(node: pc.PyNode):
        """Get all ShotInfo attributes from the node"""
        attrs: typing.List[pc.Attribute] = []
        if PlaylistUtils.isNodeValid(node):
            for attr in node.listAttr():
                if PlaylistUtils.attrPattern.match(str(attr)):
                    with contextlib.suppress(Exception):
                        attr.setLocked(False)

                    attrs.append(attr)

        return attrs

    @staticmethod
    def getSmallestUnusedAttrName(node):
        attrs = PlaylistUtils.getAttrs(node)
        for i in range(100):
            attrName = f"ShotInfo_{i:02d}"
            nodeattr = node + "." + attrName
            if nodeattr not in attrs:
                return attrName

        raise ValueError(
            "No unused ShotInfo attribute found on node %s" % node.name()
        )

    @staticmethod
    def createNewAttr(node: pc.nt.Transform) -> pc.Attribute:
        """:type node: pymel.core.nodetypes.Transform()"""
        attrName = PlaylistUtils.getSmallestUnusedAttrName(node)
        pc.addAttr(node, ln=attrName, dt="string", h=True)
        attr = node.attr(attrName)
        return attr

    @staticmethod
    def isAttrValid(attr):
        """Check if the given attribute is where shot info should be stored.
        It must be a string attribute on a camera transform node

        :type attr: pymel.core.Attribute()
        :raises TypeError: if attribute is not the expected type
        """
        if not isinstance(attr, pc.Attribute) or attr.type() != "string":
            raise TypeError(
                "'attr' can only be of type pymel.core.Attribute of type string"
            )
        if not attr.objExists() or not attr.node().getShapes(type="camera"):
            raise TypeError(
                "Attribute %s does not exist on a camera" % attr.name
            )
        if not PlaylistUtils.attrPattern.match(attr.attrName(longName=True)):
            raise TypeError(
                "Attribute %s does not have the correct name" % attr.name
            )
        return True

    @staticmethod
    def deleteAttr(attr: pc.Attribute):
        """
        :type attr: pymel.core.Attribute()
        """
        attr.delete()

    @staticmethod
    def getAllPlaylists():
        codes = set()
        masterPlaylist = Playlist()
        playlists = [masterPlaylist]
        for item in masterPlaylist.getItems():
            codes.update(item.__playlistcodes__)

        for c in codes:
            playlists.append(Playlist(c, False))

    @staticmethod
    def getDisplayLayers() -> typing.List[pc.nt.DisplayLayer]:
        try:
            return [
                pc.nt.DisplayLayer(layer)
                for layer in pc.layout(
                    "LayerEditorDisplayLayerLayout",
                    query=True,
                    childArray=True,
                )
            ]
        except TypeError:
            pc.warning("Display layers not found in the scene")
            return []

    @staticmethod
    def getDisplayLayersState():
        state = {
            layer: typing.cast("bool", layer.visibility.get())
            for layer in PlaylistUtils.getDisplayLayers()
        }
        for layer in PlaylistUtils.getDisplayLayers():
            state[layer] = layer.visibility.get()

        return state

    @staticmethod
    def restoreDisplayLayersState(state: typing.Dict[pc.nt.DisplayLayer, bool]):
        for layer, visibility in state.items():
            layer.visibility.set(visibility)

    @staticmethod
    def getAssetGroups():
        groups: typing.Dict[str, typing.List[pc.nt.Transform]] = {}
        namespaces = pc.listNamespaces(recursive=True)
        SUB_NAMESPACES = ["MotionSystem", "DeformationSystem", "FaceGroup"]
        for namespace in (ns.lstrip(":") for ns in namespaces):
            if (
                # namespace.endswith("_rig") and
                pc.objExists(namespace + ":Group")
                and all(
                    cmds.objExists(namespace + ":" + sub)
                    for sub in SUB_NAMESPACES
                )
            ):
                groups[namespace] = [
                    pc.nt.Transform(namespace + ":" + sub)
                    for sub in SUB_NAMESPACES
                ]

        return groups

    @staticmethod
    def getAssetsWithKeys(
        namespaces: typing.List[str], inframe: int, outframe: int
    ):
        from .exportutils import has_keys_in_range

        for ns in namespaces:
            # if not ns.endswith("_rig"):
            #     continue
            motion = pc.nt.Transform(ns + ":MotionSystem")
            if not motion.objExists():
                log.warning(
                    "MotionSystem not found for namespace %s, skipping" % ns
                )
                continue

            if has_keys_in_range(motion, inframe, outframe):
                log.info(
                    "Found animation in MotionSystem %s for frames %d-%d"
                    % (ns, inframe, outframe)
                )
                yield ns


plu = PlaylistUtils
