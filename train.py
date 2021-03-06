import tensorflow as tf
import numpy as np
from tensorflow import keras
from model import CPC
from nets.resnet_v2 import resnet_v2_101 as resnet

tf.app.flags.DEFINE_string('mode', 'train', 'mode')
tf.app.flags.DEFINE_integer('epochs', 20, 'epochs')
tf.app.flags.DEFINE_integer('batch_size', 30, 'batch size to train in one step')
tf.app.flags.DEFINE_float('learn_rate', 2e-4, 'learn rate for training optimization')

FLAGS = tf.app.flags.FLAGS

mode = FLAGS.mode
epochs = FLAGS.epochs
learn_rate = FLAGS.learn_rate
batch_size = FLAGS.batch_size

def image_preprocess(x):
    x = tf.expand_dims(x, axis=-1)
    x = tf.concat([x, x, x], axis=-1)
    x = tf.image.resize_images(x, (224, 224))
    return x

def chunks(l, n):
    for i in range(0, len(l), n):
        yield l[i:i+n]

# load data
fashion_mnist = keras.datasets.mnist
(train_images, train_labels), (test_images, test_labels) = fashion_mnist.load_data()
if mode == 'train':
    batches = tf.data.Dataset.from_tensor_slices(train_images).repeat(epochs).shuffle(100,
            reshuffle_each_iteration=True).batch(batch_size)
elif mode == 'validation':
    batches = tf.data.Dataset.from_tensor_slices(train_images).repeat(epochs).batch(batch_size)
elif mode == 'infer':
    batches = tf.data.Dataset.from_tensor_slices(test_images).repeat(epochs).shuffle(100,
            reshuffle_each_iteration=True).batch(batch_size)

iterator = batches.make_initializable_iterator()
items = iterator.get_next()
data = image_preprocess(items)

# build graph
## resnet
_, features = resnet(data)
features = features['resnet_v2_101/block3']
features = tf.reshape(features, shape=[batch_size, 7, 7, 1024])
X = tf.reshape(features, shape=[batch_size, 7, 7*1024])
#X = tf.reshape(features[:, :5, :, :], shape=[batch_size, 5, 7*1024])
nr = tf.random_shuffle(tf.constant(list(range(batch_size)), dtype=tf.int32))
nl1 = tf.constant(list(range(5)) + [6], dtype=tf.int32)
nl2 = tf.constant(list(range(5)) + [5], dtype=tf.int32)
nrr1 = [tf.random_shuffle(nl1) for i in range(batch_size)]
nrr2 = [tf.random_shuffle(nl2) for i in range(batch_size)]
#nrri = tf.constant([0, 1])
nrri = [tf.stack([nrr1[i][0], nrr2[i][0]], axis=0) for i in range(batch_size)]
#Y = features[:, -2:, :, :]

Y = []
for i in range(batch_size):
    if i == 0:
        Y.append(tf.expand_dims(features[0, -2:, :, :], axis=0))
    else:
        Y.append(tf.expand_dims(tf.gather(features[i], nrri[i]), axis=0))
        #Y.append(tf.expand_dims(tf.concat([tf.expand_dims(features[i, np.random.choice(5), :, :], axis=0), tf.expand_dims(features[i, np.random.choice(5), :, :], axis=0)], axis=0), axis=0))
print(Y)
Y = tf.concat(Y, axis=0)
print(Y)
#Y_distortion = np.random.uniform(0.75, 1.25, (batch_size, 2, 7, 1024))
#Y_distortion[0].fill(1.)
#Y_distortion = tf.constant(Y_distortion, dtype=tf.float32)
#Y = Y * Y_distortion

Y_label = np.zeros((batch_size), dtype=np.float32)
Y_label[0] = 1
Y_label = tf.constant(Y_label, dtype=np.float32)

print(nr)
X = tf.gather(X, nr)
Y_label = tf.gather(Y_label, nr)
Y = tf.gather(Y, nr)
print(Y)

## cpc
X_len = [5] * batch_size
X_len = tf.constant(X_len, dtype=tf.int32)

cpc = CPC(X, X_len, Y, Y_label)
train_op = tf.train.AdamOptimizer(learn_rate).minimize(cpc.loss)

saver = tf.train.Saver()

# tensorflow
with tf.Session() as sess:
    if mode == 'train':
        sess.run(tf.global_variables_initializer())
        sess.run(iterator.initializer)

        step = 0
        total = int((len(train_images) * epochs) / batch_size)
        
        features = tf.reshape(features, shape=[batch_size, 7 * 7 * 1024])
        debug = tf.reduce_mean(features)

        while True:
            try:
                #print(sess.run([Y_label]))
                #sess.run([nr, nrr])
                _, loss, g, gg, _, ggg, db = sess.run([train_op, cpc.loss, cpc.c_t_debug, cpc.x_debug, items, cpc.probs2, debug])
                if step % 100 == 0:
                    print(g, gg, db)
                    print('loss: ', loss, 'step:', step, '/', total)
                step += 1
            except tf.errors.OutOfRangeError:
                break

        saver.save(sess, './model.ckpt')

    elif mode == 'validation':
        with tf.variable_scope('validation'):
            features = tf.reshape(features, shape=[batch_size, 7 * 7 * 1024])
            out = tf.layers.dense(features, 10)
            labels = tf.placeholder(tf.int32, shape=[batch_size])
            labels_onehot = tf.one_hot(labels, depth=10)
            loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=out, labels=labels_onehot))
            train_op = tf.train.AdamOptimizer(learn_rate).minimize(loss, var_list=[tf.trainable_variables(scope='validation')])
        i=0
        sess.run(tf.global_variables_initializer())
        sess.run(iterator.initializer)
        saver.restore(sess, './model.ckpt')
        s = 0

        debug = tf.reduce_mean(features)
        while True:
            try:
                _, _loss, _out, _, _features = sess.run([train_op, loss, out, items, debug], feed_dict={labels: train_labels[i*batch_size:(i+1)*batch_size]})
                s += np.sum(np.argmax(_out, axis=1) == train_labels[i*batch_size:(i+1)*batch_size])
                #print(_features)
                if i % 100 == 0:
                    print(_loss, s/(batch_size*100))
                    #print(_features)
                    s=0
                if i % 1000 == 0:
                    print(np.argmax(_out, axis=1), train_labels[i*batch_size:(i+1)*batch_size])
                i+=1
            except tf.errors.OutOfRangeError:
                break

        #saver.save(sess, './model_infer.ckpt')
