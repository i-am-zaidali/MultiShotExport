import os
import os.path as osp
import pathlib
import re
import shutil
import subprocess
import typing

import maya.cmds as cmds
import pymel.core as pc
import typing_extensions as te
from PySide2.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from ..shot_form_tab import ShotFormExportTypeTab
from . import exportutils, fillinout, imaya, shotactions, shotplaylist
from .exceptions import *  # noqa: F403

if typing.TYPE_CHECKING:
    from .._submit import Item, ShotForm, SubmitterWidget

PlayListUtils = shotplaylist.PlaylistUtils
Action = shotactions.Action
errorsList = []
openMotion = osp.join(osp.dirname(__file__), "openMotion.mel").replace("\\", "/")
mel = '\nsource "%s";\n' % openMotion
pc.mel.eval(mel)


class CacheExportConf(te.TypedDict):
    version: int
    time_range_mode: int
    cache_file_dist: te.Literal["OneFile", "OneFilePerFrame"]
    refresh_during_caching: te.Literal[0, 1]
    cache_dir: pathlib.Path
    cache_per_geo: te.Literal[0, 1]
    cache_name: str
    cache_name_as_prefix: te.Literal[0, 1]
    action_to_perform: te.Literal["add", "replace", "merge", "mergeDelete", "export"]
    force_save: int
    simulation_rate: int
    sample_multiplier: int
    inherit_modf_from_cache: te.Literal[0, 1]
    store_doubles_as_float: te.Literal[0, 1]
    cache_format: te.Literal["mcc"]
    do_texture_export: te.Literal[0, 1]
    texture_export_data: typing.Dict[str, typing.List[str]]
    texture_resX: int
    texture_resY: int
    worldSpace: te.Literal[0, 1]


class CacheExport(Action):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, "_conf") or not self._conf:
            self._conf = CacheExport.initConf()
        if not self.path:
            self.path = osp.expanduser("~")
        if not self.get("objects"):
            self["objects"] = []

    @staticmethod
    def initConf():
        return CacheExportConf(
            version=6,
            time_range_mode=0,
            cache_file_dist="OneFile",
            refresh_during_caching=0,
            cache_dir=pathlib.Path.home(),
            cache_per_geo=1,
            cache_name="",
            cache_name_as_prefix=0,
            action_to_perform="export",
            force_save=0,
            simulation_rate=1,
            sample_multiplier=1,
            inherit_modf_from_cache=1,
            store_doubles_as_float=1,
            cache_format="mcc",
            do_texture_export=1,
            texture_export_data={
                "(?i).*badr_robot.*": ["shader:layeredTexture1.outColor"],
                "(?i).*nano_regular.*": ["layeredTexture1.outColor"],
                "(?i).*nano_docking.*": ["layeredTexture1.outColor"],
                "(?i).*nano_covered.*": ["layeredTexture1.outColor"],
                "(?i).*nano_with_bowling_arm.*": ["layeredTexture1.outColor"],
                "(?i).*nano_shawarma.*": ["NanoShawarmaExpRenderPlaneMtl.outColor"],
            },
            texture_resX=1024,
            texture_resY=1024,
            worldSpace=1,
        )

    def perform(self, **kwargs: typing.Any) -> None:
        if self.enabled:
            conf = self._conf
            item = self._item
            conf["start_time"] = item.inFrame
            conf["end_time"] = item.outFrame
            conf["cache_dir"] = pathlib.Path(self.path)
            pc.select(item.camera)
            fillinout.fill()
            if self.exportCache(conf, kwargs.get("local", False)):
                self.exportAnimatedTextures(conf, kwargs.get("local", False))
                pc.delete([x.getParent() for x in self.combineMeshes])
                del self.combineMeshes[:]
                self.exportCam(item.camera, kwargs.get("local", False))

    def exportCam(self, orig_cam: pc.nt.Transform, local=False):
        osp.splitext(cmds.file(query=True, location=True))
        path = osp.join(osp.dirname(self.path), "camera")
        if not osp.exists(path):
            os.mkdir(path)
        itemName = imaya.getNiceName(self.plItem.name) + "_cam" + imaya.getExtension()
        tempFilePath = osp.join(self.tempPath.name, itemName)
        pc.select(orig_cam)
        try:
            p = typing.cast("pc.nt.Transform", pc.ls(selection=True)[0]).firstParent()
            if pc.nt.ParentConstraint in [obj.__class__ for obj in p.getChildren()]:
                flag = True
            else:
                flag = False
        except pc.MayaNodeError:
            flag = False

        if flag:
            pc.select(orig_cam)
            duplicate_cam = pc.duplicate(
                rr=True, name="mutishot_export_duplicate_camera"
            )[0]
            pc.parent(duplicate_cam, w=True)
            pc.select([orig_cam, duplicate_cam])
            constraints = set(pc.ls(type=pc.nt.ParentConstraint))
            pc.mel.eval(
                'doCreateParentConstraintArgList 1 { "0","0","0","0","0","0","0","1","","1" };'
            )
            if constraints:
                cons = (
                    set(pc.ls(type=pc.nt.ParentConstraint))
                    .difference(constraints)
                    .pop()
                )
            else:
                cons = pc.ls(type=pc.nt.ParentConstraint)[0]
            pc.select(cl=True)
            pc.select(duplicate_cam)
            pc.mel.eval(
                'bakeResults -simulation true -t "%s:%s" -sampleBy 1 -disableImplicitControl true -preserveOutsideKeys true -sparseAnimCurveBake false -removeBakedAttributeFromLayer false -removeBakedAnimFromLayer false -bakeOnOverrideLayer false -minimizeRotation true -controlPoints false -shape true {"%s"};'
                % (
                    self.plItem.inFrame,
                    self.plItem.outFrame,
                    duplicate_cam.name(),
                )
            )
            pc.delete(cons)
            name = imaya.getNiceName(orig_cam.name())
            name2 = imaya.getNiceName(orig_cam.firstParent().name())
            pc.rename(orig_cam, "temp_cam_name_from_multiShotExport")
            pc.rename(orig_cam.firstParent(), "temp_group_name_from_multiShotExport")
            pc.rename(duplicate_cam, name)
            for node in pc.listConnections(orig_cam.getShape()):
                if isinstance(node, pc.nt.AnimCurve):
                    try:
                        attr = node.outputs(plugs=True)[0].name().split(".")[-1]
                    except IndexError:
                        continue

                    attribute = ".".join([duplicate_cam.name(), attr])
                    node.output.connect(attribute, f=True)

            pc.select(duplicate_cam)
        tempFilePath = pc.exportSelected(
            tempFilePath,
            force=True,
            expressions=True,
            constructionHistory=False,
            channels=True,
            shader=False,
            constraints=False,
            options="v=0",
            typ=imaya.getFileType(),
            pr=False,
        )
        tempFilePath2 = osp.splitext(tempFilePath)[0] + ".nk"
        pc.mel.openMotion(tempFilePath2, ".txt")
        if local:
            path = exportutils.getLocalDestination(path)
        exportutils.copyFile(tempFilePath, path)
        exportutils.copyFile(tempFilePath2, path)
        if flag:
            pc.delete(duplicate_cam)
            pc.rename(orig_cam, name)
            pc.rename(orig_cam.firstParent(), name2)

    @property
    def path(self) -> str:
        return self.get("path", "")

    @path.setter
    def path(self, path):
        self["path"] = path

    @property
    def objects(self):
        return [pc.PyNode(obj) for obj in self.get("objects", []) if pc.objExists(obj)]

    @objects.setter
    def objects(self, objects):
        self["objects"][:] = objects

    def appendObjects(self, objs):
        objects = {obj.name() for obj in self.objects}  # type: ignore
        objects.update(objs)
        self.objects = list(objects)

    def removeObjects(self, objs):
        objects: set[str] = {obj.name() for obj in self.objects}  # type: ignore
        objects.difference_update(objs)
        self.objects = list(objects)
        if len(self.objects) == 0:
            self.enabled = False

    def MakeMeshes(self, objSets):
        mapping = {}
        self.combineMeshes = []
        names = set()
        count = 1
        for objectSet, obj in (
            (setName, pc.nt.Mesh(setName))
            for setName in objSets
            if not isinstance(pc.PyNode(setName), pc.nt.Mesh)
        ):
            meshes = [
                shape
                for transform in typing.cast("pc.nt.DependNode", obj).dsm.inputs()
                for shape in typing.cast("pc.nt.Transform", transform).getShapes(
                    type="mesh", ni=True
                )
            ]
            if not meshes:
                errorsList.append(
                    "Could not Create cache for "
                    + str(objectSet)
                    + "\nReason: This set is no longer a valid set"
                )
                continue
            combineMesh = pc.createNode("mesh")
            name = imaya.getNiceName(objectSet) + "_cache"
            if name in names:
                name += str(count)
                count += 1
            names.add(name)
            pc.rename(combineMesh, name)

            mapping[osp.normpath(osp.join(self.path, name))] = str(
                getattr(imaya.getRefFromSet(pc.PyNode(objectSet)), "path", "")
            )

            self.combineMeshes.append(combineMesh)
            polyUnite = pc.createNode("polyUnite")
            for i in range(0, len(meshes)):
                meshes[i].outMesh >> polyUnite.inputPoly[i]  # type: ignore
                meshes[i].worldMatrix[0] >> polyUnite.inputMat[i]  # type: ignore

            polyUnite.output >> combineMesh.inMesh  # type: ignore

        if mapping:
            try:
                data = None
                mappingsPath = osp.join(self.path, "mappings.txt")
                if osp.exists(mappingsPath):
                    with open(mappingsPath) as fr:
                        data = eval(fr.read())
                with open(osp.join(self.path, "mappings.txt"), "w") as f:
                    if data:
                        mapping.update(data)
                    f.write(str(mapping))
            except Exception as ex:
                errorsList.append(str(ex))

            try:
                envPath = exportutils.getEnvFilePath()
                with open(osp.join(self.path, "environment.txt"), "w") as f:
                    f.write(str(envPath))
            except Exception as ex:
                errorsList.append(str(ex))

        pc.select(self.combineMeshes)
        return

    def exportCache(self, conf, local=False):
        pc.select(cl=True)
        if self.get("objects"):
            item = self.__item__
            path = conf.get("cache_dir")
            tempPath = pathlib.Path(self.tempPath.name) / imaya.getNiceName(
                item.name,
            )
            if not tempPath.exists():
                tempPath.mkdir(parents=True, exist_ok=True)
            conf["cache_dir"] = tempPath.as_posix()
            command = (
                "doCreateGeometryCache3 {version} "
                "{{ "
                '"{time_range_mode}", '  # 1
                '"{start_time}", '  # 2
                '"{end_time}", '  # 3
                '"{cache_file_dist}", '  # 4
                '"{refresh_during_caching}", '  # 5
                '"{cache_dir}", '  # 6
                '"{cache_per_geo}", '  # 7
                '"{cache_name}", '  # 8
                '"{cache_name_as_prefix}", '  # 9
                '"{action_to_perform}", '  # 10
                '"{force_save}", '  # 11
                '"{simulation_rate}", '  # 12
                '"{sample_multiplier}", '  # 13
                '"{inherit_modf_from_cache}", '  # 14
                '"{store_doubles_as_float}", '  # 15
                '"{cache_format}", '  # 16
                '"{worldSpace}" '  # 17
                "}};"
            ).format(**conf)
            self.MakeMeshes(self.get("objects"))
            pc.Mel.eval(command)

            try:
                for phile in tempPath.iterdir():
                    # if local:
                    #     path = exportutils.getLocalDestination(phile)
                    # saves to network drive by default now
                    exportutils.copyFile(phile, path)

            except Exception as ex:
                pc.warning(str(ex))

            return True
        errorsList.append("No objects found enabled in " + self.plItem.name)
        return False

    def getAnimatedTextures(self, conf: CacheExportConf):
        """Use the conf to find texture attributes to identify texture
        attributes in the present scene/shot"""
        texture_attrs = []
        for key, attrs in conf["texture_export_data"].items():
            for obj in self.objects:
                if re.match(key, obj.name()):  # type: ignore
                    name: str = obj.name()  # type: ignore
                    namespace = ":".join(name.split(":")[:-1])
                    for attr in attrs:
                        nombre = namespace + "." + attr
                        attr = pc.Attribute(namespace + ":" + attr)
                        texture_attrs.append((nombre, attr))

        return texture_attrs

    def exportAnimatedTextures(self, conf, local=False):
        """bake export animated textures from the scene"""
        textures_exported = False
        if not self.get("objects"):
            return False
        animatedTextures = self.getAnimatedTextures(conf)
        if not animatedTextures:
            return False
        tempFilePath = osp.join(self.tempPath.name, "tex")
        if osp.exists(tempFilePath):
            shutil.rmtree(tempFilePath)
        os.mkdir(tempFilePath)
        inframe, outframe = self._item.inFrame, self._item.outFrame
        if not inframe or not outframe:
            inframe, outframe = self._item.autosetInOut()
        start_time = int(inframe)
        end_time = int(outframe)
        rx = conf["texture_resX"]
        ry = conf["texture_resY"]
        for curtime in range(start_time, end_time + 1):
            num = "%04d" % curtime
            pc.currentTime(curtime, e=True)
            for name, attr in animatedTextures:
                fileImageName = osp.join(tempFilePath, ".".join([name, num, "png"]))
                newobj = pc.convertSolidTx(
                    attr,
                    samplePlane=True,
                    rx=rx,
                    ry=ry,
                    fil="png",
                    fileImageName=fileImageName,
                )
                pc.delete(newobj)
                textures_exported = True

        target_dir = osp.join(self.path, "tex")
        try:
            if not osp.exists(target_dir) and not local:
                os.mkdir(target_dir)
        except Exception as ex:
            errorsList.append(str(ex))

        for phile in os.listdir(tempFilePath):
            philePath = osp.join(tempFilePath, phile)
            if local:
                target_dir = exportutils.getLocalDestination(target_dir, depth=4)
            exportutils.copyFile(philePath, target_dir, depth=4)

        return textures_exported

    @staticmethod
    def getTabUI() -> typing.Type["CacheExportTab"]:
        return CacheExportTab


class CacheExportTab(ShotFormExportTypeTab[CacheExport]):
    OBJECT_SELECTION_REQUIRED = True
    PARENT_ACTION = CacheExport

    def __init__(self, parent: "ShotForm", item: "Item | None" = None):
        super().__init__(parent, item=item)
        self.setObjectName("CacheExportTab")
        if item:
            self.pathBox.setText(item.findChild(QLabel, "cachePathLabel").text())

    def populateObjectsDefaults(self):
        for layer in PlayListUtils.getDisplayLayers():
            btn = QCheckBox(layer.name(), self)
            btn.setChecked(layer.visibility.get())
            self.objectsLayout.addWidget(btn)

        self.setSelectAllState()
        for btn in self.getObjectWidgets():
            assert isinstance(btn, QCheckBox), "Expected QCheckBox"
            btn.clicked.connect(self.setSelectAllState)

    def getObjectsDescription(self):
        """Set the description for the objects in this tab."""
        return "Select the display layers you want to export as cache files."

    @staticmethod
    def getExportPath(parent: "SubmitterWidget", camera: "pc.nt.Transform") -> str:
        """Get the save path for this export type."""
        return parent.getCachePath(camera)

    def getTabName(self) -> str:
        """Get the name of this tab."""
        return "Cache"

    def updateInformationWidget(self):
        """Update the information widget with the current item information."""
        if self.item is None:
            return
        layout = self.item.informationLayout.findChild(
            QHBoxLayout, "cacheInformationLayout"
        )
        label = layout.findChild(QLabel, "cachePathLabel")
        if label:
            label.setText("Cache Path:")

        button = layout.findChild(QPushButton, "cachePathButton")
        if button:
            button.setText(self.pathBox.text())
            button.clicked.disconnect()
            button.clicked.connect(
                lambda: subprocess.call(f'explorer "{self.pathBox.text()}"', shell=True)
            )
