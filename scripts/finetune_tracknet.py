"""Fine-tune the k14 ball model so it can find the ball against a pale wall.

Step 2 of 2 (step 1 is scripts/finetune_tracknet_data.py). EXPERIMENTS.md
2026-11-01 (later) has the reasoning and every number. The pod's weights
`weights/pdsc_court3_ft_e2_20261101.tar` are epoch 2 of this script's output, from:

  python3 scripts/finetune_tracknet.py --data /mnt/fast_scratch/ft_data \\
      --weights /mnt/fast_scratch/tracknet_weights/weights_k14_epoch19 \\
      --epochs 4 --lr 3e-5 --wash 0.7 --out /mnt/fast_scratch/ft_model

It continues training the existing saved model; the original TrackNet training code is
not in this repo, so the training target is a reconstruction, not the original recipe:
a filled disc of radius 3 at the ball on the model's 512x288 output grid for each of the
trio's three frames, and the loss is the one pod_infer.py already defines (custom_loss).
Those choices worked (EXPERIMENTS.md), which is the only reason to trust them.

Each sample, as it is drawn:
  - with probability --wash, everything above the far baseline is blended 8-45% (random)
    of the way toward cream, so the ball has to be found against a pale wall
  - brightness x0.85-1.15, and a horizontal flip half the time
  - the court mask is applied last, as the pod does before the model
One checkpoint per epoch is written to <out>_e1, <out>_e2, ... (SavedModel, includes the
optimizer state, so it is ~3x the size of the file the pod needs: reload it with
compile=False and save with include_optimizer=False before packaging).

The loss moves very little (6e-5 -> 5e-5) and epochs differed sharply on the test marks
(epoch 3 was clearly worse than 2 and 4), so pick the checkpoint on a test, never by loss.

Needs TensorFlow 2.15 (the pod's; a newer Keras cannot load the saved model).
"""
import argparse
import json
import os
import random

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import keras.backend as K
import numpy as np
import tensorflow as tf

GRID_H, GRID_W = 288, 512
DISC_RADIUS = 3.0


def custom_loss(y_true, y_pred):
    loss = (-1) * (K.square(1 - y_pred) * y_true * K.log(K.clip(y_pred, K.epsilon(), 1))
                   + K.square(y_pred) * (1 - y_true) * K.log(K.clip(1 - y_pred, K.epsilon(), 1)))
    return K.mean(loss)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="the directory finetune_tracknet_data.py wrote")
    ap.add_argument("--weights", required=True, help="the saved model to continue from")
    ap.add_argument("--out", required=True, help="prefix for the per-epoch checkpoints")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--wash", type=float, default=0.7, help="share of samples with the pale-wall wash")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)

    X = np.load(os.path.join(args.data, "X.npy"), mmap_mode="r")
    vid = np.load(os.path.join(args.data, "vid.npy"))
    masks = np.load(os.path.join(args.data, "masks.npy"))
    with open(os.path.join(args.data, "labels.json")) as f:
        d = json.load(f)
    labels, far_rows, n = d["labels"], [m["far_row"] for m in d["meta"]], len(X)
    yy, xx = np.mgrid[0:GRID_H, 0:GRID_W]

    def sample(i):
        imgs = X[i].astype(np.float32) / 255.0                                  # (3, H, W, 3) RGB
        mask = masks[vid[i]].astype(np.float32)
        lab = [None if l is None else list(l) for l in labels[i]]
        if random.random() < args.wash:
            alpha = random.uniform(0.08, 0.45)
            cream = np.array([205, 200, 190], np.float32) / 255 + np.random.uniform(-0.04, 0.04, 3)
            fr = far_rows[vid[i]]
            imgs[:, :fr] = alpha * imgs[:, :fr] + (1 - alpha) * cream
        imgs = np.clip(imgs * random.uniform(0.85, 1.15), 0, 1)
        if random.random() < 0.5:
            imgs, mask = imgs[:, :, ::-1], mask[:, ::-1]
            lab = [None if l is None else [GRID_W - 1 - l[0], l[1]] for l in lab]
        imgs = imgs * mask[None, :, :, None]
        x = np.concatenate([imgs[k].transpose(2, 0, 1) for k in range(3)], axis=0).astype(np.float32)   # (9, H, W)
        y = np.zeros((3, GRID_H, GRID_W), np.float32)
        for k, l in enumerate(lab):
            if l is not None:
                y[k] = ((xx - l[0]) ** 2 + (yy - l[1]) ** 2 <= DISC_RADIUS ** 2)
        return x, y

    def gen():
        order = list(range(n))
        random.shuffle(order)
        for i in order:
            yield sample(i)

    ds = tf.data.Dataset.from_generator(
        gen, output_signature=(tf.TensorSpec((9, GRID_H, GRID_W), tf.float32),
                               tf.TensorSpec((3, GRID_H, GRID_W), tf.float32))
    ).batch(args.batch).prefetch(2).repeat()

    model = tf.keras.models.load_model(args.weights, custom_objects={"custom_loss": custom_loss}, compile=False)
    model.compile(optimizer=tf.keras.optimizers.Adam(args.lr), loss=custom_loss)

    class SaveEachEpoch(tf.keras.callbacks.Callback):
        def on_epoch_end(self, epoch, logs=None):
            print(f"epoch {epoch + 1} loss {logs['loss']:.5f}", flush=True)
            self.model.save(f"{args.out}_e{epoch + 1}")

    model.fit(ds, epochs=args.epochs, steps_per_epoch=n // args.batch, callbacks=[SaveEachEpoch()], verbose=0)
    print("done", flush=True)


if __name__ == "__main__":
    main()
