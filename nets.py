from operator import mul
import itertools
from nolearn.lasagne import NeuralNet, BatchIterator
from nolearn.lasagne.handlers import SaveWeights
from nolearn_utils.hooks import SaveTrainingHistory, PlotTrainingHistory, EarlyStopping
from lasagne import objectives
from lasagne.layers import InputLayer
from lasagne.layers import ReshapeLayer, DenseLayer, DropoutLayer, ElemwiseSumLayer, ConcatLayer
from lasagne.layers.dnn import Conv3DDNNLayer, MaxPool3DDNNLayer, Pool3DDNNLayer, batch_norm_dnn
from layers import Unpooling3D, Transformer3DLayer
from lasagne import updates
from lasagne import nonlinearities
from lasagne.init import Constant
import objective_functions as objective_f
import numpy as np


def get_epoch_finished(name, patience):
    return [
        SaveWeights(name + 'model_weights.pkl', only_best=True, pickle=False),
        SaveTrainingHistory(name + 'model_history.pkl'),
        PlotTrainingHistory(name + 'training_history.png'),
        EarlyStopping(patience=patience)
    ]


def get_back_pathway(forward_pathway, multi_channel=True):
    # We create the backwards path of the encoder from the forward path
    # We need to mirror the configuration of the layers and change the pooling operators with unpooling,
    # and the convolutions with deconvolutions (convolutions with diferent padding). This definitions
    # match the values of the possible_layers dictionary
    back_pathway = ''.join(['d' if l is 'c' else 'u' for l in forward_pathway[::-1]])
    last_conv = back_pathway.rfind('d')
    final_conv = 'f' if multi_channel else 'fU'
    back_pathway = back_pathway[:last_conv] + final_conv + back_pathway[last_conv + 1:]

    return back_pathway


def get_layers_string(
        net_layers,
        input_shape,
        convo_size=3,
        pool_size=2,
        dense_size=256,
        number_filters=32,
        multi_channel=True,
        padding='valid'
):
    input_shape_single = tuple(input_shape[:1] + (1,) + input_shape[2:])
    channels = range(0, input_shape[1])
    previous_layer = InputLayer(name='\033[30minput\033[0m', shape=input_shape) if multi_channel\
        else [InputLayer(name='\033[30minput_%d\033[0m' % i, shape=input_shape_single) for i in channels]

    convolutions = dict()
    c_index = 1
    p_index = 1
    c_size = (convo_size, convo_size, convo_size)
    for layer in net_layers:
        if layer == 'c':
            conv_layer = batch_norm_dnn(
                layer=Conv3DDNNLayer(
                    incoming=previous_layer,
                    name='\033[34mconv%d\033[0m' % c_index,
                    num_filters=number_filters,
                    filter_size=c_size,
                    pad=padding
                ),
                name='norm%d' % c_index
            ) if multi_channel else [batch_norm_dnn(
                layer=Conv3DDNNLayer(
                    incoming=layer,
                    name='\033[34mconv%d_%d\033[0m' % (c_index, i),
                    num_filters=number_filters,
                    filter_size=c_size,
                    pad=padding
                ),
                name='norm%d_%d' % (c_index, i)
            ) for layer, i in zip(previous_layer, channels)]
            convolutions['conv%d' % c_index] = conv_layer
            previous_layer = conv_layer
            c_index += 1
        elif layer == 'a':
            previous_layer = Pool3DDNNLayer(
                incoming=previous_layer,
                name='\033[31mavg_pool%d\033[0m' % p_index,
                pool_size=pool_size,
                mode='average_inc_pad'
            ) if multi_channel else [Pool3DDNNLayer(
                incoming=layer,
                name='\033[31mavg_pool%d_%d\033[0m' % (p_index, i),
                pool_size=pool_size,
                mode='average_inc_pad'
            ) for layer, i in zip(previous_layer, channels)]
            p_index += 1
        elif layer == 't':
            b = np.zeros((3, 4), dtype='float32')
            b[0, 0] = 1
            b[1, 1] = 1
            b[2, 2] = 1
            W = Constant(0.0)
            previous_layer = Transformer3DLayer(
                localization_network=DenseLayer(
                    incoming=layer,
                    num_units=12,
                    W=W,
                    b=b.flatten,
                    nonlinearity=None
                ),
                incoming=previous_layer,
                name='\033[33transf\033[0m',
            ) if multi_channel else [Transformer3DLayer(
                localization_network=DenseLayer(
                    incoming=layer,
                    num_units=12,
                    W=W,
                    b=b.flatten,
                    nonlinearity=None
                ),
                incoming=layer,
                name='\033[33transf_%d\033[0m' % i,
            ) for layer, i in zip(previous_layer, channels)]
            p_index += 1
        elif layer == 'm':
            previous_layer = MaxPool3DDNNLayer(
                incoming=previous_layer,
                name='\033[31mmax_pool%d\033[0m' % p_index,
                pool_size=pool_size
            ) if multi_channel else [MaxPool3DDNNLayer(
                incoming=layer,
                name='\033[31mmax_pool%d_%d\033[0m' % (p_index, i),
                pool_size=pool_size
            ) for layer, i in zip(previous_layer, channels)]
            p_index += 1
        elif layer == 'u':
            p_index -= 1
            previous_layer = Unpooling3D(
                incoming=previous_layer,
                name='\033[35munpool%d\033[0m' % p_index,
                pool_size=pool_size
            ) if multi_channel else [Unpooling3D(
                incoming=layer,
                name='\033[35munpool%d_%d\033[0m' % (p_index, i),
                pool_size=pool_size
            ) for layer, i in zip(previous_layer, channels)]
        elif layer == 's':
            previous_layer = ElemwiseSumLayer(
                incomings=[convolutions['conv%d' % (c_index - 1)], previous_layer],
                name='short%d' % (c_index - 1)
            ) if multi_channel else [ElemwiseSumLayer(
                incomings=[convolutional, layer],
                name='short%d_%d' % (c_index - 1, i)
            ) for convolutional, layer, i in zip(convolutions['conv%d' % (c_index - 1)], previous_layer, channels)]
        elif layer == 'd':
            c_index -= 1
            previous_layer = batch_norm_dnn(
                layer=Conv3DDNNLayer(
                    incoming=previous_layer,
                    name='\033[36mdeconv%d\033[0m' % c_index,
                    num_filters=number_filters,
                    filter_size=c_size,
                    pad='full'
                ),
                name='denorm%d' % c_index
            ) if multi_channel else [batch_norm_dnn(
                layer=Conv3DDNNLayer(
                    incoming=layer,
                    name='\033[36mdeconv%d_%d\033[0m' % (c_index, i),
                    num_filters=number_filters,
                    filter_size=c_size,
                    pad='full'
                ),
                name='denorm%d_%d' % (c_index, i)
            ) for layer, i in zip(previous_layer, channels)]
        elif layer == 'o':
            previous_layer = DropoutLayer(
                incoming=previous_layer,
                name='drop%d' % (c_index - 1),
                p=0.5
            ) if multi_channel else [DropoutLayer(
                incoming=layer,
                name='drop%d_%d' % (c_index - 1, i),
                p=0.5
            ) for layer, i in zip(previous_layer, channels)]
        elif layer == 'f':
            c_index -= 1
            previous_layer = Conv3DDNNLayer(
                incoming=previous_layer,
                name='\033[36mfinal\033[0m',
                num_filters=input_shape[1],
                filter_size=c_size,
                pad='full'
            ) if multi_channel else [Conv3DDNNLayer(
                incoming=layer,
                name='\033[36mfinal_%d\033[0m' % i,
                num_filters=1,
                filter_size=c_size,
                pad='full'
            ) for layer, i in zip(previous_layer, channels)]
        elif layer == 'r':
            previous_layer = ReshapeLayer(
                incoming=previous_layer,
                name='\033[32mreshape\033[0m',
                shape=([0], -1)
            )
        elif layer == 'U':
            # Multichannel-only layer
            previous_layer = ConcatLayer(
                incomings=previous_layer,
                name='\033[32munion\033[0m'
            )
        elif layer == 'D':
            previous_layer = DenseLayer(
                incoming=previous_layer,
                name='\033[32mdense\033[0m',
                num_units=dense_size,
                nonlinearity=nonlinearities.softmax
            )
        elif layer == 'S':
            previous_layer = DenseLayer(
                incoming=previous_layer,
                name='\033[32m3d_out\033[0m',
                num_units=reduce(mul, input_shape[2:], 1),
                nonlinearity=nonlinearities.softmax
            )
        elif layer == 'C':
            previous_layer = DenseLayer(
                incoming=previous_layer,
                name='\033[32mclass_out\033[0m',
                num_units=2,
                nonlinearity=nonlinearities.softmax
            )

    return previous_layer


def get_convolutional_block(
        incoming,
        convo_size=3,
        num_filters=32,
        pool_size=2,
        drop=0.5,
        counter=itertools.count()
):
    index = counter.next()
    convolution = Conv3DDNNLayer(
        incoming=incoming,
        name='\033[34mconv%d\033[0m' % index,
        num_filters=num_filters,
        filter_size=convo_size,
        pad='valid'
    )
    normalisation = batch_norm_dnn(
        layer=convolution,
        name='norm%d' % index
    )
    dropout = DropoutLayer(
        incoming=normalisation,
        name='drop%d' % index,
        p=drop
    )
    pool = Pool3DDNNLayer(
        incoming=dropout,
        name='\033[31mavg_pool%d\033[0m' % index,
        pool_size=pool_size,
        mode='average_inc_pad'
    )

    return pool


def create_classifier_net(
        layers,
        patience,
        name,
        obj_f='xent',
        epochs=200
):

    objective_function = {
        'xent': objectives.categorical_crossentropy,
        'pdsc': objective_f.probabilistic_dsc_objective,
        'ldsc': objective_f.logarithmic_dsc_objective
    }

    return NeuralNet(

        layers=layers,

        regression=False,
        objective_loss_function=objective_function[obj_f],
        custom_scores=[
            ('prob dsc', objective_f.accuracy_dsc_probabilistic),
            ('dsc', objective_f.accuracy_dsc),
        ],

        # update=updates.adadelta,
        update=updates.adam,
        update_learning_rate=1e-4,

        on_epoch_finished=get_epoch_finished(name, patience),

        batch_iterator_train=BatchIterator(batch_size=1024),

        verbose=11,
        max_epochs=epochs
    )


def create_segmentation_net(
        layers,
        patience,
        name,
        custom_scores=None,
        epochs=200
):
    return NeuralNet(

        layers=layers,

        regression=True,

        update=updates.adam,
        update_learning_rate=1e-3,

        on_epoch_finished=get_epoch_finished(name, patience),

        custom_scores=custom_scores,

        verbose=11,
        max_epochs=epochs
    )


def create_cnn3d_det_string(
        cnn_path,
        input_shape,
        convo_size,
        padding,
        pool_size,
        number_filters,
        patience,
        multichannel,
        name,
        epochs
):
    # We create the final string defining the net with the necessary input and reshape layers
    # We assume that the user will never put these parameters as part of the net definition when
    # calling the main python function
    final_layers = 'rC' if multichannel else 'rUC'
    final_layers = cnn_path.replace('a', 'ao').replace('m', 'mo') + final_layers

    layer_list = get_layers_string(
        net_layers=final_layers,
        input_shape=input_shape,
        convo_size=convo_size,
        pool_size=pool_size,
        number_filters=number_filters,
        multi_channel=multichannel,
        padding=padding
    )

    return create_classifier_net(
        layer_list,
        patience,
        name,
        epochs=epochs
    )


def create_unet3d_det_string(
        forward_path,
        input_shape,
        convo_size,
        pool_size,
        number_filters,
        patience,
        multichannel,
        name,
        epochs
):
    # We create the final string defining the net with the necessary input and reshape layers
    # We assume that the user will never put these parameters as part of the net definition when
    # calling the main python function
    final_layers = 'i' + forward_path + get_back_pathway(forward_path, multichannel) + 'r' + 'C'

    layer_list = get_layers_string(
        net_layers=final_layers,
        input_shape=input_shape,
        convo_size=convo_size,
        pool_size=pool_size,
        number_filters=number_filters,
        multi_channel=multichannel
    )

    return create_classifier_net(
        layer_list,
        patience,
        name,
        epochs=epochs
    )


def create_unet3d_seg_string(
            forward_path,
            input_shape,
            convo_size,
            pool_size,
            number_filters,
            patience,
            multichannel,
            name,
            epochs
):

    # We create the final string defining the net with the necessary input and reshape layers
    # We assume that the user will never put these parameters as part of the net definition when
    # calling the main python function
    final_layers = 'i' + forward_path + get_back_pathway(forward_path, multichannel) + 'r' + 'S'

    layer_list = get_layers_string(
        net_layers=final_layers,
        input_shape=input_shape,
        convo_size=convo_size,
        pool_size=pool_size,
        number_filters=number_filters,
        multi_channel=multichannel
    )

    return create_segmentation_net(
        layer_list,
        patience,
        name,
        epochs=epochs
    )


def create_unet3d_shortcuts_det_string(
        forward_path,
        input_shape,
        convo_size,
        pool_size,
        number_filters,
        patience,
        multichannel,
        name,
        epochs
):
    # We create the final string defining the net with the necessary input and reshape layers
    # We assume that the user will never put these parameters as part of the net definition when
    # calling the main python function
    back_pathway = get_back_pathway(forward_path, multichannel).replace('d', 'sd').replace('f', 'sf')
    final_layers = (forward_path + back_pathway + 'r' + 'C').replace('csd', 'cd')

    layer_list = get_layers_string(
        net_layers=final_layers,
        input_shape=input_shape,
        convo_size=convo_size,
        pool_size=pool_size,
        number_filters=number_filters,
        multi_channel=multichannel
    )

    return create_classifier_net(
        layer_list,
        patience,
        name,
        epochs=epochs
    )


def create_unet3d_shortcuts_seg_string(
            forward_path,
            input_shape,
            convo_size,
            pool_size,
            number_filters,
            patience,
            multichannel,
            name,
            epochs
):

    # We create the final string defining the net with the necessary input and reshape layers
    # We assume that the user will never put these parameters as part of the net definition when
    # calling the main python function
    back_pathway = get_back_pathway(forward_path, multichannel).replace('d', 'sd').replace('f', 'sf')
    final_layers = (forward_path + back_pathway + 'r' + 'S').replace('csd', 'cd')

    layer_list = get_layers_string(
        net_layers=final_layers,
        input_shape=input_shape,
        convo_size=convo_size,
        pool_size=pool_size,
        number_filters=number_filters,
        multi_channel=multichannel
    )

    return create_segmentation_net(
        layer_list,
        patience,
        multichannel,
        name,
        epochs=epochs
    )


def create_encoder3d_string(
        forward_path,
        input_shape,
        convo_size,
        pool_size,
        number_filters,
        patience,
        multichannel,
        name,
        epochs=200
):
    # We create the final string defining the net with the necessary input and reshape layers
    # We assume that the user will never put these parameters as part of the net definition when
    # calling the main python function
    final_layers = forward_path + get_back_pathway(forward_path, multichannel) + 'r'

    encoder = NeuralNet(
        layers=get_layers_string(final_layers, input_shape, convo_size, pool_size, number_filters, multichannel),

        regression=True,

        update=updates.adam,
        update_learning_rate=1e-3,

        on_epoch_finished=get_epoch_finished(name, patience),

        verbose=11,
        max_epochs=epochs
    )

    return encoder
