import numpy as np
from common.skeleton import nwucla_17_skeleton
from common.mocap_dataset import MocapDataset

class NTUDataset(MocapDataset):
    def __init__(self, path):
        super().__init__(fps=30, skeleton=nwucla_17_skeleton)
        self.load_dataset(path)

    def load_dataset(self, path):
        print('Loading NTU RGB+D 3D dataset...')
        data = np.load(path, allow_pickle=True)
        self._data = data['positions_3d'].item()
        self._cameras = data['cameras'].item()

    def supports_semi_supervised(self):
        return True
