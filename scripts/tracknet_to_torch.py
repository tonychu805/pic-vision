#!/usr/bin/env python3
"""Convert TrackNet Keras weights to the PyTorch file the pod loads (src/tracknet_torch.py).

Two steps, because TensorFlow and a current PyTorch don't share an environment
on the workstation:

  # 1. in the TF 2.15 env: the layer graph + weights out of the SavedModel / .h5
  python scripts/tracknet_to_torch.py dump /path/to/weights_k14_epoch19 /tmp/k14
  # 2. in any env with torch: build the module, load the weights, save the .pt
  python scripts/tracknet_to_torch.py build /tmp/k14 /path/to/tracknet_k14.pt

Check the result against the Keras model before using it (EXPERIMENTS 2026-11-12).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def dump(src, out):
    import numpy as np
    import tensorflow as tf
    m = tf.keras.models.load_model(src, compile=False)
    layers, weights = [], {}
    for layer in m.layers:
        c = layer.get_config()
        inputs = []
        for node in layer._inbound_nodes:
            for t in tf.nest.flatten(node.input_tensors):
                inputs.append(t._keras_history.layer.name)
        spec = {"name": layer.name, "type": type(layer).__name__, "inputs": inputs}
        w = layer.get_weights()
        if spec["type"] == "Conv2D":
            spec.update(filters=c["filters"], kernel=list(c["kernel_size"]), strides=list(c["strides"]),
                        padding=c["padding"], activation=c["activation"], use_bias=c["use_bias"])
            weights[f"layers.{layer.name}.weight"] = np.transpose(w[0], (3, 2, 0, 1))   # (kh,kw,in,out) -> (out,in,kh,kw)
            if c["use_bias"]:
                weights[f"layers.{layer.name}.bias"] = w[1]
        elif spec["type"] == "BatchNormalization":
            spec.update(epsilon=c["epsilon"], axis=c["axis"])
            for key, v in zip(("weight", "bias", "running_mean", "running_var"), w):
                weights[f"layers.{layer.name}.{key}"] = v
        elif spec["type"] == "Activation":
            spec.update(activation=c["activation"])
        elif spec["type"] == "MaxPooling2D":
            spec.update(pool=list(c["pool_size"]), strides=list(c["strides"] or c["pool_size"]), padding=c["padding"])
        elif spec["type"] == "UpSampling2D":
            spec.update(size=list(c["size"]), interpolation=c["interpolation"])
        elif spec["type"] == "Concatenate":
            spec.update(axis=c["axis"])
        layers.append(spec)
    json.dump({"input": list(m.input_shape[1:]), "layers": layers, "source": os.path.abspath(src)},
              open(out + ".json", "w"), indent=1)
    np.savez(out + ".npz", **weights)
    print(f"{len(layers)} layers, {len(weights)} tensors -> {out}.json / .npz")


def build(prefix, out):
    import numpy as np
    import torch
    from src.tracknet_torch import TrackNet
    spec = json.load(open(prefix + ".json"))
    model = TrackNet(spec)
    w = np.load(prefix + ".npz")
    state = {k: torch.from_numpy(np.ascontiguousarray(w[k])) for k in w.files}
    missing, unexpected = model.load_state_dict(state, strict=True), None
    torch.save({"spec": spec, "state_dict": model.state_dict()}, out)
    print(f"{sum(p.numel() for p in model.parameters())} parameters -> {out}")


if __name__ == "__main__":
    {"dump": dump, "build": build}[sys.argv[1]](sys.argv[2], sys.argv[3])
