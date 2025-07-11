import re
import subprocess
import typing
from pathlib import Path

import pymel.core as pc
from PySide2 import QtCore, QtWidgets

from . import sui

if typing.TYPE_CHECKING:
    from ._submit import Item, ShotForm, SubmitterWidget
    from .backend.shotactions import Action
    from .backend.shotplaylist import PlaylistItem

ActionType = typing.TypeVar("ActionType", bound="Action")

Tab = typing.TypeVar("Tab", bound="ShotFormExportTypeTab")


def toCamelCase(s: str) -> str:
    """Convert a string to camelCase."""
    splitBy = "_" if "_" in s else " "
    return "".join(
        word.capitalize() if ind > 0 else word.lower()
        for ind, word in enumerate(s.split(splitBy))
    )


class ShotFormExportTypeTab(QtWidgets.QWidget, typing.Generic[ActionType]):
    pathContainer: QtWidgets.QWidget
    pathBox: QtWidgets.QLineEdit
    objectsLayout: QtWidgets.QVBoxLayout
    selectAll: QtWidgets.QCheckBox
    objectsDescription: QtWidgets.QLabel
    stateToggle: QtWidgets.QCheckBox
    browsePath: QtWidgets.QToolButton

    OBJECT_SELECTION_REQUIRED: typing.ClassVar[bool]
    PARENT_ACTION: typing.Type[ActionType]

    CLS_NAME_REGEX = re.compile(r"^(?P<exportType>.+)ExportTab$")

    EXPORT_TYPE: typing.ClassVar[str]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        match = cls.CLS_NAME_REGEX.match(cls.__name__)
        if not match:
            raise ValueError(
                f"Class {cls.__name__} does not match the expected naming convention."
            )

        cls.EXPORT_TYPE = match.group("exportType").strip().replace("_", " ")

    def __init__(
        self,
        parent: "ShotForm",
        *,
        item: typing.Optional["Item"] = None,
    ):
        super().__init__(parent)
        path = Path(__file__).parent.parent / "ui" / "shot_form_export_type_tab.ui"
        sui.loadUi(str(path), self)

        self.item = item
        self.form = parent

        self.selectAll.stateChanged.connect(self._selectAllToggled)
        self.browsePath.clicked.connect(self._browsePath)

        self.pathContainer.setVisible(item is not None)
        self.objectsDescription.setText(self.getObjectsDescription())
        self.populateObjectsDefaults()

    def _selectAllToggled(self, state: QtCore.Qt.CheckState):
        if state == QtCore.Qt.Unchecked and not all(
            item.isChecked()
            for item in self.getObjectWidgets()
            if isinstance(item, QtWidgets.QCheckBox)
        ):
            return
        for item in self.getObjectWidgets():
            if isinstance(item, QtWidgets.QCheckBox):
                item.setChecked(state == QtCore.Qt.Checked)

    def setSelectAllState(self):
        """Set the state of the select all checkbox based on the current selection."""
        all_checked = all(
            item.isChecked()
            for item in self.getObjectWidgets()
            if isinstance(item, QtWidgets.QCheckBox)
        )
        self.selectAll.setChecked(all_checked)

    def _browsePath(self):
        path = self.form.submitterWidget._previousPath
        if not path:
            path = ""
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Folder", path)
        if path:
            self.form.submitterWidget._previousPath = path
        return path

    def populateObjectsDefaults(self):
        """Populate the objects in this tab."""
        raise NotImplementedError(
            "populateObjects method must be implemented in the subclass"
        )

    def updateObjectsStates(self):
        """Update the states of the objects in this tab."""
        assert self.item is not None, "Item must be set"
        action = self.PARENT_ACTION.getActionFromList(self.item.pl_item.actions)
        self.pathBox.setText(action.path)
        for btn in self.getObjectWidgets():
            assert isinstance(btn, QtWidgets.QCheckBox), "Expected QCheckBox"
            btn.setChecked(btn.text() in action.objects)

        self.setSelectAllState()

        self.stateToggle.setChecked(action.enabled)

    def getObjectsDescription(self):
        """Get the description for the objects in this tab."""
        raise NotImplementedError(
            "getObjectsDescription method must be implemented in the subclass"
        )

    @staticmethod
    def getExportPath(parent: "SubmitterWidget", camera: pc.nt.Transform) -> str:
        """Get the save path for this export type."""
        raise NotImplementedError(
            "getSavePath method must be implemented in the subclass"
        )

    def getTabName(self) -> str:
        """Get the name of the tab."""
        raise NotImplementedError(
            "getTabName method must be implemented in the subclass"
        )

    @classmethod
    def getItemInformationLayout(
        cls,
        path: str,
    ) -> QtWidgets.QHBoxLayout:
        """Get the layout for the item information."""
        layout = QtWidgets.QHBoxLayout(spacing=10)
        layout.setObjectName(f"{toCamelCase(cls.EXPORT_TYPE)}InformationLayout")
        # bold font
        label = QtWidgets.QLabel(
            f"{cls.EXPORT_TYPE} Path:",
            objectName=f"{toCamelCase(cls.EXPORT_TYPE)}PathLabel",
            styleSheet="font-weight: bold;",
            sizePolicy=QtWidgets.QSizePolicy(
                QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred
            ),
        )
        push = QtWidgets.QPushButton(
            path,
            flat=True,
            objectName=f"{toCamelCase(cls.EXPORT_TYPE)}PathButton",
            sizePolicy=QtWidgets.QSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
            ),
            styleSheet="text-align:left;",
        )
        push.clicked.connect(lambda: subprocess.call(f"explorer {path}", shell=True))
        layout.addWidget(label)
        layout.addWidget(push)
        layout.addStretch()
        return layout

    def updateInformationWidget(self):
        raise NotImplementedError(
            "updateInformationWidget method must be implemented in the subclass"
        )

    def setupAction(self, pl_item: "PlaylistItem | None" = None) -> ActionType:
        """Get the action associated with this tab."""
        # if self.item is None:
        #     raise ValueError("Item must be set to get the action.")
        if pl_item is None:
            assert self.item is not None, (
                "If item is None, PlaylistItem must be passed to setupAction"
            )
            pl_item = self.item.pl_item

        assert pl_item is not None, "PlaylistItem must not be None"
        action_class = self.PARENT_ACTION
        # assert self.item.pl_item.actions is not None
        action = action_class.getActionFromList(pl_item.actions)
        action.enabled = self.stateToggle.isChecked()
        pathBoxText = self.pathBox.text().strip()
        action.path = (
            pathBoxText
            if pl_item is None or pathBoxText
            else self.getExportPath(self.form.submitterWidget, pl_item.camera)
        )
        action.objects = [
            item.text()
            for item in self.getObjectWidgets()
            if isinstance(item, QtWidgets.QCheckBox) and item.isChecked()
        ]
        return action

    def getObjectWidgets(self) -> typing.List[QtWidgets.QWidget]:
        """Get all checkboxes in the objects layout."""
        return [
            item.widget()
            for item in (
                self.objectsLayout.itemAt(i) for i in range(self.objectsLayout.count())
            )
            if isinstance(item.widget(), QtWidgets.QCheckBox)
        ]
