from __future__ import print_function
import argparse
import os
from scipy.ndimage.interpolation import affine_transform
from time import strftime
import numpy as np
from nets import create_cnn3d_register
from utils import color_codes, random_affine3d_matrix
from data_creation import load_register_data


def parse_inputs():
    parser = argparse.ArgumentParser(description='Test different nets with 3D data.')
    parser.add_argument('-f', '--folder', dest='dir_name', default='/home/mariano/DATA/Subtraction/')
    parser.add_argument('-l', '--pool-size', dest='pool_size', type=int, default=2)
    parser.add_argument('-k', '--kernel-size', dest='conv_width', type=int, default=3)
    parser.add_argument('-c', '--conv-blocks', dest='conv_blocks', type=int, default=2)
    parser.add_argument('-n', '--num-filters', action='store', dest='number_filters', type=int, default=32)
    parser.add_argument('-a', '--augment-percentage', dest='augment_p', type=float, default=0.10)
    parser.add_argument('-i', '--input', action='store', dest='input_size', nargs='+', type=int, default=[32, 32, 32])
    parser.add_argument('--baseline-folder', action='store', dest='b_folder', default='time1/preprocessed')
    parser.add_argument('--followup-folder', action='store', dest='f_folder', default='time2/preprocessed')
    parser.add_argument('--image-name', action='store', dest='im_name', default='t1_corrected.nii.gz')
    parser.add_argument('--padding', action='store', dest='padding', default='valid')
    return vars(parser.parse_args())


def get_names_from_path(path, baseline, followup, image):
    # Check if all images should be used
    patients = [f for f in sorted(os.listdir(path))
                if os.path.isdir(os.path.join(path, f))]

    # Prepare the names for each image
    name_list = np.stack([[
                     os.path.join(path, p, baseline, image),
                     os.path.join(path, p, followup, image)
                 ] for p in patients[:30]])

    return name_list


def train_net(
        net,
        x,
        y,
        b_name='\033[30mbaseline\033[0m',
        f_name='\033[30mfollow\033[0m'
):
    c = color_codes()
    print('                Training vector shape ='
          ' (' + ','.join([str(length) for length in x.shape]) + ')')
    print('                Training labels shape ='
          ' (' + ','.join([str(length) for length in y.shape]) + ')')
    print(c['c'] + '[' + strftime("%H:%M:%S") + ']    ' + c['g'] +
          'Training (' + c['b'] + 'registration' + c['nc'] + c['g'] + ')' + c['nc'])

    x_train = np.split(x, 2, axis=1)
    b_inputs = (b_name, x_train[0])
    f_inputs = (f_name, x_train[1])
    inputs = dict([b_inputs, f_inputs])
    net.fit(inputs, y)


def test_net(
        net,
        x,
        b_name='\033[30mbaseline\033[0m',
        f_name='\033[30mfollow\033[0m',
        loc_name='\033[33mloc_net\033[0m'
):
    import theano
    import lasagne
    c = color_codes()
    # We try to get the last weights to keep improving the net over and over
    x_test = np.split(x, 2, axis=1)
    b_inputs = (b_name, x_test[0])
    f_inputs = (f_name, x_test[1])
    inputs = dict([b_inputs, f_inputs])
    print(c['c'] + '[' + strftime("%H:%M:%S") + ']    ' + c['g'] +
          'Predicting (' + c['b'] + 'images' + c['nc'] + c['g'] + ')' + c['nc'])
    print('                Testing vector shape ='
          ' (' + ','.join([str(length) for length in x.shape]) + ')')
    y_test = net.predict(inputs)
    print(c['c'] + '[' + strftime("%H:%M:%S") + ']    ' + c['g'] +
          'Predicting (' + c['b'] + 'transformations' + c['nc'] + c['g'] + ')' + c['nc'])

    f = theano.function(
        [
            net.layers_[b_name].input_var,
            net.layers_[f_name].input_var
        ],
        lasagne.layers.get_output(
            net.layers_[loc_name],
            {
                b_name: net.layers_[b_name].input_var,
                f_name: net.layers_[f_name].input_var
            }
        ),
        name='registration'
    )

    rand_transf = [random_affine3d_matrix(x_range=1/36.0, y_range=1/36.0, z_range=1/36.0) for x_t in x_test[0]]
    x_test_random = np.stack([affine_transform(x_t, t) for x_t, t in zip(x_test[0], rand_transf)])
    transforms = f(x_test_random, x_test[0])

    for tt, t in zip(transforms, rand_transf):
        print('%s   %s' % (','.join(['%f' % ts for ts in t[0, :]]), ','.join(['%f' % tts for tts in tt[:4]])))
        print('%s = %s' % (','.join(['%f' % ts for ts in t[1, :]]), ','.join(['%f' % tts for tts in tt[4:8]])))
        print('%s   %s' % (','.join(['%f' % ts for ts in t[2, :]]), ','.join(['%f' % tts for tts in tt[8:12]])))

    return y_test, transforms


def main():
    c = color_codes()
    options = parse_inputs()

    print(c['c'] + '[' + strftime("%H:%M:%S") + '] ' + 'Starting the registration training' + c['nc'])

    dir_name = options['dir_name']
    baseline_name = options['b_folder']
    followup_name = options['f_folder']
    image_name = options['im_name']
    input_size = options['input_size']

    n_filters = options['number_filters']
    pool_size = options['pool_size']
    conv_width = options['conv_width']
    conv_blocks = options['conv_blocks']

    augment_p = options['augment_p']

    seed = np.random.randint(np.iinfo(np.int32).max)

    input_size_s = 'x'.join([str(length) for length in input_size])
    sufix = 's%s.c%s.n%s.a%f' % (input_size_s, conv_width, n_filters, augment_p)
    net_name = os.path.join(dir_name, 'deep-exp_registration.' + sufix + '.')
    net = create_cnn3d_register(
        input_shape=input_size,
        convo_size=conv_width,
        convo_blocks=conv_blocks,
        pool_size=pool_size,
        number_filters=n_filters,
        data_augment_p=augment_p,
        patience=100,
        name=net_name,
        epochs=2000
    )

    print(c['c'] + '[' + strftime("%H:%M:%S") + ']    ' +
          c['g'] + 'Loading the data for ' + c['b'] + 'iteration 1' + c['nc'])

    names = get_names_from_path(dir_name, baseline_name, followup_name, image_name)

    x_train, y_train = load_register_data(
        names=names,
        image_size=input_size,
        seed=seed,
    )

    # We try to get the last weights to keep improving the net over and over
    try:
        net.load_params_from(net_name + 'model_weights.pkl')
    except IOError:
        pass

    train_net(net, x_train, y_train)

    test_net(net, x_train)


if __name__ == '__main__':
    main()
