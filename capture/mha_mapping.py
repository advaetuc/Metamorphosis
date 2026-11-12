"""DNA-specific native raw-to-GUI mapping, used only during MHA capture/baking."""
from ..riglogic import bake
from ..dna import dnaio


class Mapper:
    def __init__(self, scene, board, explicit_path=''):
        from ..core.operators import get_preferences
        import bpy
        path = explicit_path
        if not path:
            candidates = [obj for obj in scene.objects if obj.type == 'ARMATURE'
                          and obj.get(bake.RIG_KEY_DNA)
                          and (obj == board or obj.get(bake.RIG_KEY_BOARD_OBJECT) == board.name)]
            if len(candidates) != 1:
                raise ValueError('Select the original head DNA in MHA Head DNA for this face board')
            path = candidates[0][bake.RIG_KEY_DNA]
        prefs = get_preferences(bpy.context)
        folder = prefs.bindings_folder if prefs else ''
        self.reader = self.manager = self.instance = None
        try:
            self.reader = dnaio.open_reader(bpy.path.abspath(path), folder)
            _, native, _ = dnaio.load_bindings(folder)
            self.manager = native.RigLogic(self.reader, native.Configuration(), None)
            self.instance = native.RigInstance(rigLogic=self.manager, memRes=None)
            self.raw = {str(self.reader.getRawControlName(i)).replace('.', '_'): i
                        for i in range(self.reader.getRawControlCount())}
            self.gui = []
            for i in range(self.reader.getGUIControlCount()):
                bone, _, axis = str(self.reader.getGUIControlName(i)).rpartition('.')
                if bone in board.pose.bones and axis in ('tx', 'ty', 'tz'):
                    self.gui.append((i, bone, 'xyz'.index(axis[-1])))
            if not self.gui:
                raise ValueError('Head DNA does not match this face board')
            self.validated = False
        except Exception:
            self.close()
            raise

    def __call__(self, values, **_options):
        if not self.validated:
            missing = set(values)-set(self.raw)
            if missing:
                raise ValueError('MHA controls absent from head DNA: '+', '.join(sorted(missing)[:3]))
            self.validated = True
        for name, index in self.raw.items():
            self.instance.setRawControl(index, float(values.get(name, 0.0)))
        self.manager.mapRawToGUIControls(self.instance)
        return {(bone, axis): float(self.instance.getGUIControl(index)) for index, bone, axis in self.gui}

    def close(self):
        for name in ('instance', 'manager', 'reader'):
            handle = getattr(self, name, None)
            if handle is not None:
                dnaio.release_handle(handle)
                setattr(self, name, None)
