import json
import os.path as osp
import tempfile
import typing
from abc import ABCMeta, abstractmethod

import typing_extensions as te

if typing.TYPE_CHECKING:
    from ..shot_form_tab import ShotFormExportTypeTab
    from .shotplaylist import Playlist, PlaylistItem

dir_path = osp.dirname(__file__)


class ActionList(typing.Dict[str, "Action"]):
    """A list of Actions that can be performed on a :class:`shotplaylist.PlaylistItem`
    or :class:`playlist.Playlist`"""

    def __init__(self, item: "PlaylistItem", *args, **kwargs):
        """Create an Action List"""
        super().__init__(*args, **kwargs)
        self._item = item
        if not getattr(item, "_PlaylistItem__data").get(
            "actions"
        ):  # name mangling lmao
            return
        for ak in item.actions:
            actionsubs = Action.inheritors()
            cls = actionsubs.get(ak)
            if cls:
                self[ak] = cls(item.actions[ak])
                self[ak].__item__ = item
            else:
                self[ak] = item.actions[ak]

    def getActions(self):
        actions: typing.List[Action] = []
        for action in self.values():
            if isinstance(action, Action):
                actions.append(action)

        return actions

    def perform(self, **kwargs):
        for action in self.getActions():
            action.perform(**kwargs)

    def add(self, action):
        if not isinstance(action, Action):
            print(action, type(action))
            raise TypeError("only Actions can be added")
        classname = action.__class__.__name__
        action._item = self._item
        self[classname] = action
        return action

    def remove(self, action):
        key = action
        if isinstance(action, Action):
            key = action.__class__.__name__
        if key in self:
            del self[key]


class Action(typing.Dict[typing.Any, typing.Any], metaclass=ABCMeta):
    _conf: typing.Any
    __item__: "PlaylistItem"
    tempPath = tempfile.TemporaryDirectory(suffix="multishotExport")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.enabled is None:
            self.enabled = True

    @classmethod
    def cleanup(cls):
        cls.tempPath.cleanup()

    @property
    def enabled(self) -> bool:
        return self.get("enabled", False)

    @enabled.setter
    def enabled(self, val):
        if not isinstance(val, bool):
            raise TypeError("enabled must be a boolean value")
        self["enabled"] = val

    @property
    def path(self) -> str:
        return self.get("path", "")

    @path.setter
    def path(self, value: str):
        if not value:
            raise ValueError("Path cannot be empty")
        if not isinstance(value, str):
            raise TypeError("Path must be a string")
        self["path"] = value

    @property
    @abstractmethod
    def objects(self) -> typing.List[object]:
        """Get the objects associated with this action."""
        raise NotImplementedError("objects must be implemented by subclasses")

    @objects.setter
    @abstractmethod
    def objects(self, value: typing.List[object]):
        """Set the objects associated with this action."""
        raise NotImplementedError("objects must be implemented by subclasses")

    @abstractmethod
    def perform(self, **kwargs):
        pass

    @property
    def _item(self):
        return self.__item__

    @_item.setter
    def _item(self, val):
        self.__item__ = val

    plItem = _item

    def read_conf(self, confname=""):
        if not confname:
            confname = self.__class__.__name__
        with open(osp.join(dir_path, confname)) as conf:
            self._conf = json.load(conf)

    def write_conf(self, confname=""):
        if not confname:
            confname = self.__class__.__name__
        with open(osp.join(dir_path, confname), "w+") as conf:
            json.dump(self._conf, conf)

    @property
    def conf(self):
        return self._conf

    @classmethod
    def inheritors(cls):
        return {
            **{sc.__name__: sc for sc in cls.__subclasses__()},
            cls.__name__: cls,
        }

    @classmethod
    def performOnPlaylist(cls, pl: "Playlist"):
        for item in pl.getItems():
            action = cls.getActionFromList(item.actions)
            if action and action.enabled:
                cls.getActionFromList(item.actions).perform()
                yield True
            else:
                yield False

    @classmethod
    def getNumActionsFromPlaylist(cls, pl: "Playlist"):
        num = 0
        for item in pl.getItems():
            action = cls.getActionFromList(item.actions)
            if action and action.enabled:
                num += 1

        return num

    @classmethod
    @typing.overload
    def getActionFromList(
        cls, actionlist: ActionList, forceCreate: te.Literal[True] = True
    ) -> te.Self:
        """Get an Action from an ActionList, optionally creating it if it does not exist."""
        ...

    @classmethod
    @typing.overload
    def getActionFromList(
        cls, actionlist: ActionList, forceCreate: te.Literal[False]
    ) -> typing.Optional[te.Self]:
        """Get an Action from an ActionList, optionally creating it if it does not exist."""
        ...

    @classmethod
    def getActionFromList(
        cls, actionlist: ActionList, forceCreate: bool = True
    ) -> typing.Optional[te.Self]:
        if actionlist.__class__.__name__ != "ActionList":
            print(actionlist.__class__.__name__)
            raise TypeError("Only Action lists can be queried")
        action = actionlist.get(cls.__name__)
        if not action and forceCreate:
            action = cls()
        print(f"Action {cls.__name__} found: {action}")
        return action  # type: ignore[return-value]

    @staticmethod
    def getTabUI() -> typing.Type["ShotFormExportTypeTab[Action]"]:
        """Get the UI for this action. This method should be overridden by subclasses."""
        raise NotImplementedError("getTabUI must be implemented by subclasses")
