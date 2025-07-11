import pathlib
import re
import typing
from logging import getLogger

import maya.cmds as cmds
import pymel.core as pc
from PySide2 import QtWidgets

from ..shot_form_tab import ShotFormExportTypeTab
from . import exportutils, fillinout, imaya
from .shotactions import Action
from .shotplaylist import PlaylistUtils

if typing.TYPE_CHECKING:
    from .._submit import Item, ShotForm, SubmitterWidget
    from ..backend.shotplaylist import PlaylistItem

log = getLogger("FBXExport")

# class FBXConfig(typing_extensions.TypedDict):
#     """Configuration for FBX export."""

#     transforms: typing.List[str]


class FBXExport(Action):
    """Export all assets in the current shot as FBX files"""

    # _conf: FBXConfig

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self._conf = self.initConf()

    # @staticmethod
    # def initConf():
    #     return FBXConfig(
    #         transforms=[],
    #     )

    @property
    def objects(self) -> typing.List[str]:
        """Get the list of transforms to export."""
        return self.get("transforms", [])

    @objects.setter
    def objects(self, value: typing.List[str]):
        """Set the list of transforms to export."""
        if not isinstance(value, list):
            raise TypeError("Transforms must be a list")
        self["transforms"] = value

    def perform(self, **kwargs):
        item = self.__item__
        if not item:
            log.error("No item associated with this action. Why did this happen?")
            raise ValueError("No item associated with this action")

        camera = item.camera
        log.info(f"Exporting FBX for camera: {camera.name()}")
        all_groups = PlaylistUtils.getAssetGroups()
        groups = {
            group: transforms
            for group, transforms in all_groups.items()
            if group in self.objects
        }
        log.info(f"Exporting groups: {groups.keys()}")
        pc.select(camera)
        fillinout.fill()
        pc.select(clear=True)
        tempPath = pathlib.Path(self.tempPath.name) / imaya.getNiceName(
            item.name,
        )
        if not tempPath.exists():
            tempPath.mkdir(parents=True, exist_ok=True)
        log.info(f"Temporary path for FBX export: {tempPath}")
        ns_regex = re.compile(
            r"^(?P<namespace>[\w:]+)?(?P<name>MotionSystem|DeformationSystem|FaceGroup)$"
        )
        for group, selections in groups.items():
            if not selections:
                log.warning(f"No selections for group: {group}")
                continue

            group_rigname = group + ":Group"

            dupe = typing.cast(
                "pc.nt.Transform",
                pc.duplicate(
                    group_rigname,
                    name=f"{group}_dupe:Group",
                    renameChildren=True,
                    upstreamNodes=True,
                )[0],
            )

            log.info(f"Duplicated group {group_rigname} to {dupe.name()}")

            dupe_sgs = [
                x
                for x in dupe.getChildren(type=pc.nt.Transform)
                if ns_regex.match(x.name())
            ]

            pc.select(*dupe_sgs, replace=True)
            cmds.SelectHierarchy()
            log.info(f"Hierarchy selected for group: {group}")
            cmds.BakeSimulation()
            log.info(f"Baked simulation for group: {group}")
            file_name = f"{group.rstrip('_rig')}.fbx"
            log.info(f"Exporting {file_name} to {tempPath}")
            file_path = tempPath / file_name
            # file -force -options "v=0;" -typ "FBX export" -pr -es "C:/Users/zaid.ali/Documents/maya/projects/default/scenes/1.fbx";
            cmds.file(
                file_path.as_posix(),
                force=True,
                options="v=0",
                type="FBX export",
                preserveReferences=True,
                exportSelected=True,
            )
            log.info(f"Exported {file_name} to {tempPath}")
            # Delete the temporary duplicated and baked objects
            log.info(f"Deleting duplicates for group: {group}")
            pc.delete(dupe)
            pc.select(clear=True)
        log.info("Exporting all groups completed.")

        for group, selections in groups.items():
            if not selections:
                continue
            file_name = f"{group.rstrip('_rig')}.fbx"
            temp_file_path = tempPath / file_name
            exportutils.copyFile(temp_file_path, self.path + f"/{file_name}")
        log.info(f"FBX export completed. Files saved to {self.path}")

    @staticmethod
    def getTabUI() -> typing.Type["FBXExportTab"]:
        return FBXExportTab


class FBXExportTab(ShotFormExportTypeTab["FBXExport"]):
    OBJECT_SELECTION_REQUIRED = True
    PARENT_ACTION = FBXExport

    def __init__(self, parent: "ShotForm", item: "Item | None" = None):
        super().__init__(parent, item=item)
        self.setObjectName("FBXExportTab")
        if item:
            self.pathBox.setText(
                item.findChild(QtWidgets.QLabel, "fbxPathLabel").text()
            )

    def populateObjectsDefaults(self):
        for group in PlaylistUtils.getAssetGroups():
            btn = QtWidgets.QCheckBox(group, self)
            btn.setChecked(False)
            self.objectsLayout.addWidget(btn)

        self.setSelectAllState()
        for btn in self.getObjectWidgets():
            assert isinstance(btn, QtWidgets.QCheckBox), "Expected QCheckBox"
            btn.clicked.connect(self.setSelectAllState)

    def getObjectsDescription(self):
        """Set the description for the objects in this tab."""
        return "Select the Asset Groups you want to export as FBX baked animations."

    @staticmethod
    def getExportPath(parent: "SubmitterWidget", camera: "pc.nt.Transform") -> str:
        """Get the save path for this export type."""
        return parent.getCachePath(camera)

    def getTabName(self) -> str:
        """Get the name of this tab."""
        return "FBX"

    def updateInformationWidget(self):
        """Update the information widget with the current item information."""
        if self.item is None:
            return
        layout = self.item.informationLayout.findChild(
            QtWidgets.QHBoxLayout, "fbxInformationLayout"
        )
        if layout is None:
            return
        label = layout.findChild(QtWidgets.QLabel, "fbxPathLabel")
        if label:
            label.setText("FBX Path:")
        path_button = layout.findChild(QtWidgets.QPushButton, "fbxPathButton")
        if path_button:
            path_button.setText(self.pathBox.text())

    def setupAction(self, pl_item: "PlaylistItem | None" = None):
        """Setup the action for this tab."""
        action = super().setupAction(pl_item)
        if pl_item is None:
            assert self.item is not None, "Item must be set"
            pl_item = self.item.pl_item
        # only add objects that have keys in the specified range
        org_objects = action.objects
        log.info(f"Original objects for FBX export: {org_objects}")
        action.objects = list(
            PlaylistUtils.getAssetsWithKeys(
                action.objects, pl_item.inFrame, pl_item.outFrame
            )
        )
        log.info(f"Filtered objects for FBX export: {action.objects}")
        if len(action.objects) != len(org_objects):
            removed = set(org_objects) - set(action.objects)
            log.warning(
                f"{len(removed)} objects removed from FBX export due to no animation in range: {', '.join(removed)}"
            )
        return action
