"""TrackNet (the ball model) in PyTorch, so the pod needs no TensorFlow (2026-11-12).

The pod used to pull our own 9.3 GB image (runpod/pytorch + TensorFlow 2.15
with its CUDA libraries) and stalled whenever a host did not have it cached
(staging 2026-11-12: three pods in a row stuck "awaiting_container" for 4 min).
TensorFlow was there only for this model. Without it the pod runs on the
stock runpod/pytorch image, which already has torch.

The network is rebuilt from the Keras model's own layer list, so any TrackNet
weights convert the same way (scripts/tracknet_to_torch.py): one .pt file
holding {"spec": layer graph, "state_dict": weights}. Not TorchScript: a
trace from a newer torch may not load in the pod's torch 2.1; a state dict
does.

One quirk carried over exactly: the Keras BatchNormalization layers use the
default axis=-1 with channels-first data, so they normalise per pixel COLUMN
(one scale per x position), not per channel. ColumnNorm below does that.
"""
import torch
from torch import nn


class ColumnNorm(nn.Module):
    """Keras BatchNormalization(axis=-1) on NCHW data, inference only: per-column affine."""

    def __init__(self, width, eps):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(width))
        self.bias = nn.Parameter(torch.zeros(width))
        self.register_buffer("running_mean", torch.zeros(width))
        self.register_buffer("running_var", torch.ones(width))

    def forward(self, x):
        scale = self.weight / torch.sqrt(self.running_var + self.eps)
        return x * scale + (self.bias - self.running_mean * scale)


class TrackNet(nn.Module):
    """Runs the Keras layer graph in its own (topological) order."""

    def __init__(self, spec):
        super().__init__()
        self.spec = spec
        self.layers = nn.ModuleDict()
        channels, width = {}, {}
        c_in, _, w_in = spec["input"]
        for L in spec["layers"]:
            name, kind, ins = L["name"], L["type"], L["inputs"]
            if kind == "InputLayer":
                channels[name], width[name] = c_in, w_in
                continue
            c, w = channels[ins[0]], width[ins[0]]
            if kind == "Conv2D":
                k = L["kernel"]
                if L["padding"] != "same" or any(v % 2 == 0 for v in k) or L["strides"] != [1, 1]:
                    raise ValueError(f"{name}: only stride-1 'same' convolutions with odd kernels are supported")
                self.layers[name] = nn.Conv2d(c, L["filters"], tuple(k), padding=(k[0] // 2, k[1] // 2),
                                              bias=L["use_bias"])
                if L["activation"] != "linear":
                    raise ValueError(f"{name}: conv activation {L['activation']} not supported")
                c = L["filters"]
            elif kind == "BatchNormalization":
                if L["axis"] not in ([3], 3, -1):
                    raise ValueError(f"{name}: batch norm over axis {L['axis']} not supported")
                self.layers[name] = ColumnNorm(w, L["epsilon"])
            elif kind == "MaxPooling2D":
                if L["padding"] != "valid":
                    raise ValueError(f"{name}: pooling padding {L['padding']} not supported")
                self.layers[name] = nn.MaxPool2d(tuple(L["pool"]), tuple(L["strides"] or L["pool"]))
                w //= L["pool"][1]
            elif kind == "UpSampling2D":
                if L["interpolation"] != "nearest":
                    raise ValueError(f"{name}: upsampling {L['interpolation']} not supported")
                self.layers[name] = nn.Upsample(scale_factor=tuple(float(s) for s in L["size"]), mode="nearest")
                w *= L["size"][1]
            elif kind == "Activation":
                if L["activation"] not in ("relu", "sigmoid", "linear"):
                    raise ValueError(f"{name}: activation {L['activation']} not supported")
            elif kind == "Concatenate":
                if L["axis"] not in (1, -3):
                    raise ValueError(f"{name}: concatenation over axis {L['axis']} not supported")
                c = sum(channels[i] for i in ins)
            else:
                raise ValueError(f"{name}: layer type {kind} not supported")
            channels[name], width[name] = c, w
        self.output = spec["layers"][-1]["name"]

    def forward(self, x):
        out = {}
        for L in self.spec["layers"]:
            name, kind, ins = L["name"], L["type"], L["inputs"]
            if kind == "InputLayer":
                out[name] = x
            elif kind == "Concatenate":
                out[name] = torch.cat([out[i] for i in ins], dim=1)
            elif kind == "Activation":
                v = out[ins[0]]
                act = L["activation"]
                out[name] = torch.relu(v) if act == "relu" else torch.sigmoid(v) if act == "sigmoid" else v
            else:
                out[name] = self.layers[name](out[ins[0]])
        return out[self.output]


def load(path, device="cuda", half=True):
    """The converted model from a .pt file, in eval mode, fp16 on a GPU unless half=False."""
    try:
        blob = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:                      # torch < 1.13 has no weights_only
        blob = torch.load(path, map_location="cpu")
    model = TrackNet(blob["spec"])
    model.load_state_dict(blob["state_dict"])
    model = model.to(device).eval()
    return model.half() if half and device != "cpu" else model
