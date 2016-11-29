import numpy as np
from time import clock
from numpy.random import random
from nolearn.lasagne import BatchIterator
from scipy.ndimage.interpolation import affine_transform


class Affine3DTransformBatchIterator(BatchIterator):
    """
    Apply affine transform (scale, translate and rotation)
    with a random chance
    """
    def __init__(self, affine_p, parameter_range=(-1, 1), input_layers=list(),
                 *args, **kwargs):
        super(Affine3DTransformBatchIterator,
              self).__init__(*args, **kwargs)
        self.range = max(parameter_range) - min(parameter_range)
        self.min = min(parameter_range)
        self.affine_p = affine_p
        self.input_layers = input_layers

    def transform(self, xb, yb):
        xb, yb = super(Affine3DTransformBatchIterator,
                       self).transform(xb, yb)
        # Skip if affine_p is 0. Setting affine_p may be useful for quickly
        # disabling affine transformation
        if self.affine_p == 0:
            return xb, yb

        seed = np.random.randint(clock())
        scale_v = np.expand_dims(np.array([.0, .0, .0, 1.0]), axis=0)
        xb_transformed = xb.copy()
        if isinstance(xb, dict):
            for k in self.input_layers:
                np.random.seed(seed)
                x_t = np.random.permutation(xb_transformed[k])
                for i in range(int(x_t.shape[0] * self.affine_p)):
                    t = np.concatenate([2 * np.random.random((3, 4)) - 1, scale_v])
                    img_transformed = affine_transform(x_t[i], t)
                    xb_transformed[k][i] = img_transformed
        else:
            np.random.seed(seed)
            xb_transformed = np.random.permutation(xb)
            for i in range(int(xb.shape[0] * self.affine_p)):
                img_transformed = affine_transform(xb[i], self.range * (random((4, 4)) - self.min))
                xb_transformed[i] = img_transformed

        return xb_transformed, yb
