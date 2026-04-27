"""CAM++ 说话人验证模型（纯 PyTorch，无 modelscope 依赖）。

基于阿里达摩院 CAM++ 架构，从 modelscope 的 DTDNN.py / DTDNN_layers.py 提取，
去掉了 modelscope 的注册系统和 TorchModel 基类依赖。
版权：Copyright (c) Alibaba, Inc. and its affiliates.
"""

import os
from collections import OrderedDict
from typing import Any, Dict

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.checkpoint as cp
import torchaudio.compliance.kaldi as Kaldi


# ---------------------------------------------------------------------------
# Layers (from DTDNN_layers.py)
# ---------------------------------------------------------------------------

def _get_nonlinear(config_str, channels):
    nonlinear = nn.Sequential()
    for name in config_str.split('-'):
        if name == 'relu':
            nonlinear.add_module('relu', nn.ReLU(inplace=True))
        elif name == 'prelu':
            nonlinear.add_module('prelu', nn.PReLU(channels))
        elif name == 'batchnorm':
            nonlinear.add_module('batchnorm', nn.BatchNorm1d(channels))
        elif name == 'batchnorm_':
            nonlinear.add_module('batchnorm', nn.BatchNorm1d(channels, affine=False))
        else:
            raise ValueError(f'Unexpected module ({name}).')
    return nonlinear


class _StatsPool(nn.Module):
    def forward(self, x):
        mean = x.mean(dim=-1)
        std = x.std(dim=-1, unbiased=True)
        return torch.cat([mean, std], dim=-1)


class _TDNNLayer(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, stride=1,
                 padding=0, dilation=1, bias=False, config_str='batchnorm-relu'):
        super().__init__()
        if padding < 0:
            padding = (kernel_size - 1) // 2 * dilation
        self.linear = nn.Conv1d(in_channels, out_channels, kernel_size,
                                stride=stride, padding=padding, dilation=dilation, bias=bias)
        self.nonlinear = _get_nonlinear(config_str, out_channels)

    def forward(self, x):
        return self.nonlinear(self.linear(x))


class _CAMLayer(nn.Module):
    def __init__(self, bn_channels, out_channels, kernel_size, stride, padding, dilation, bias, reduction=2):
        super().__init__()
        self.linear_local = nn.Conv1d(bn_channels, out_channels, kernel_size,
                                      stride=stride, padding=padding, dilation=dilation, bias=bias)
        self.linear1 = nn.Conv1d(bn_channels, bn_channels // reduction, 1)
        self.relu = nn.ReLU(inplace=True)
        self.linear2 = nn.Conv1d(bn_channels // reduction, out_channels, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        y = self.linear_local(x)
        context = x.mean(-1, keepdim=True) + self._seg_pooling(x)
        context = self.relu(self.linear1(context))
        m = self.sigmoid(self.linear2(context))
        return y * m

    @staticmethod
    def _seg_pooling(x, seg_len=100):
        seg = F.avg_pool1d(x, kernel_size=seg_len, stride=seg_len, ceil_mode=True)
        shape = seg.shape
        seg = seg.unsqueeze(-1).expand(*shape, seg_len).reshape(*shape[:-1], -1)
        return seg[..., :x.shape[-1]]


class _CAMDenseTDNNLayer(nn.Module):
    def __init__(self, in_channels, out_channels, bn_channels, kernel_size,
                 stride=1, dilation=1, bias=False, config_str='batchnorm-relu', memory_efficient=False):
        super().__init__()
        padding = (kernel_size - 1) // 2 * dilation
        self.memory_efficient = memory_efficient
        self.nonlinear1 = _get_nonlinear(config_str, in_channels)
        self.linear1 = nn.Conv1d(in_channels, bn_channels, 1, bias=False)
        self.nonlinear2 = _get_nonlinear(config_str, bn_channels)
        self.cam_layer = _CAMLayer(bn_channels, out_channels, kernel_size,
                                   stride=stride, padding=padding, dilation=dilation, bias=bias)

    def bn_function(self, x):
        return self.linear1(self.nonlinear1(x))

    def forward(self, x):
        if self.training and self.memory_efficient:
            x = cp.checkpoint(self.bn_function, x)
        else:
            x = self.bn_function(x)
        return self.cam_layer(self.nonlinear2(x))


class _CAMDenseTDNNBlock(nn.ModuleList):
    def __init__(self, num_layers, in_channels, out_channels, bn_channels, kernel_size,
                 stride=1, dilation=1, bias=False, config_str='batchnorm-relu', memory_efficient=False):
        super().__init__()
        for i in range(num_layers):
            self.add_module(f'tdnnd{i+1}', _CAMDenseTDNNLayer(
                in_channels=in_channels + i * out_channels,
                out_channels=out_channels, bn_channels=bn_channels,
                kernel_size=kernel_size, stride=stride, dilation=dilation,
                bias=bias, config_str=config_str, memory_efficient=memory_efficient))

    def forward(self, x):
        for layer in self:
            x = torch.cat([x, layer(x)], dim=1)
        return x


class _TransitLayer(nn.Module):
    def __init__(self, in_channels, out_channels, bias=True, config_str='batchnorm-relu'):
        super().__init__()
        self.nonlinear = _get_nonlinear(config_str, in_channels)
        self.linear = nn.Conv1d(in_channels, out_channels, 1, bias=bias)

    def forward(self, x):
        return self.linear(self.nonlinear(x))


class _DenseLayer(nn.Module):
    def __init__(self, in_channels, out_channels, bias=False, config_str='batchnorm-relu'):
        super().__init__()
        self.linear = nn.Conv1d(in_channels, out_channels, 1, bias=bias)
        self.nonlinear = _get_nonlinear(config_str, out_channels)

    def forward(self, x):
        if len(x.shape) == 2:
            x = self.linear(x.unsqueeze(dim=-1)).squeeze(dim=-1)
        else:
            x = self.linear(x)
        return self.nonlinear(x)


class _BasicResBlock(nn.Module):
    expansion = 1

    def __init__(self, in_planes, planes, stride=1):
        super().__init__()
        self.conv1 = nn.Conv2d(in_planes, planes, 3, stride=(stride, 1), padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(planes)
        self.conv2 = nn.Conv2d(planes, planes, 3, stride=1, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(planes)
        self.shortcut = nn.Sequential()
        if stride != 1 or in_planes != self.expansion * planes:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_planes, self.expansion * planes, 1, stride=(stride, 1), bias=False),
                nn.BatchNorm2d(self.expansion * planes))

    def forward(self, x):
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        out += self.shortcut(x)
        return F.relu(out)


# ---------------------------------------------------------------------------
# FCM + CAMPPlus (from DTDNN.py)
# ---------------------------------------------------------------------------

class _FCM(nn.Module):
    def __init__(self, block=_BasicResBlock, num_blocks=(2, 2), m_channels=32, feat_dim=80):
        super().__init__()
        self.in_planes = m_channels
        self.conv1 = nn.Conv2d(1, m_channels, 3, stride=1, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(m_channels)
        self.layer1 = self._make_layer(block, m_channels, num_blocks[0], stride=2)
        self.layer2 = self._make_layer(block, m_channels, num_blocks[1], stride=2)
        self.conv2 = nn.Conv2d(m_channels, m_channels, 3, stride=(2, 1), padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(m_channels)
        self.out_channels = m_channels * (feat_dim // 8)

    def _make_layer(self, block, planes, num_blocks, stride):
        strides = [stride] + [1] * (num_blocks - 1)
        layers = []
        for s in strides:
            layers.append(block(self.in_planes, planes, s))
            self.in_planes = planes * block.expansion
        return nn.Sequential(*layers)

    def forward(self, x):
        x = x.unsqueeze(1)
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.layer1(out)
        out = self.layer2(out)
        out = F.relu(self.bn2(self.conv2(out)))
        shape = out.shape
        return out.reshape(shape[0], shape[1] * shape[2], shape[3])


class CAMPPlusModel(nn.Module):
    """CAM++ embedding network."""

    def __init__(self, feat_dim=80, embedding_size=512, growth_rate=32,
                 bn_size=4, init_channels=128, config_str='batchnorm-relu',
                 memory_efficient=True):
        super().__init__()
        self.head = _FCM(feat_dim=feat_dim)
        channels = self.head.out_channels
        self.xvector = nn.Sequential(OrderedDict([
            ('tdnn', _TDNNLayer(channels, init_channels, 5, stride=2, dilation=1, padding=-1, config_str=config_str)),
        ]))
        channels = init_channels
        for i, (num_layers, kernel_size, dilation) in enumerate(zip((12, 24, 16), (3, 3, 3), (1, 2, 2))):
            block = _CAMDenseTDNNBlock(num_layers, channels, growth_rate, bn_size * growth_rate,
                                       kernel_size, dilation=dilation, config_str=config_str, memory_efficient=memory_efficient)
            self.xvector.add_module(f'block{i+1}', block)
            channels += num_layers * growth_rate
            self.xvector.add_module(f'transit{i+1}', _TransitLayer(channels, channels // 2, bias=False, config_str=config_str))
            channels //= 2
        self.xvector.add_module('out_nonlinear', _get_nonlinear(config_str, channels))
        self.xvector.add_module('stats', _StatsPool())
        self.xvector.add_module('dense', _DenseLayer(channels * 2, embedding_size, config_str='batchnorm_'))

    def forward(self, x):
        x = x.permute(0, 2, 1)
        x = self.head(x)
        return self.xvector(x)


# ---------------------------------------------------------------------------
# 高层封装（替代 modelscope 的 SpeakerVerificationCAMPPlus）
# ---------------------------------------------------------------------------

class SpeakerVerificationCAMPPlus:
    """CAM++ 说话人验证，纯 PyTorch 实现。"""

    def __init__(self, model_dir: str, model_config: Dict[str, Any],
                 device: str = "cpu", pretrained_model: str = "campplus_cn_common.bin"):
        self.model_dir = model_dir
        feat_dim = model_config.get("fbank_dim", 80)
        emb_size = model_config.get("emb_size", 192)
        self._device = torch.device(device)

        self.embedding_model = CAMPPlusModel(feat_dim, emb_size)
        weights_path = os.path.join(model_dir, pretrained_model)
        self.embedding_model.load_state_dict(
            torch.load(weights_path, map_location=torch.device("cpu")), strict=True,
        )
        self.embedding_model.to(self._device)
        self.embedding_model.eval()
        self._feat_dim = feat_dim

    def forward(self, audio):
        if isinstance(audio, np.ndarray):
            audio = torch.from_numpy(audio)
        if len(audio.shape) == 1:
            audio = audio.unsqueeze(0)
        feature = self._extract_feature(audio)
        embedding = self.embedding_model(feature.to(self._device))
        return embedding.detach().cpu()

    def __call__(self, audio):
        return self.forward(audio)

    def _extract_feature(self, audio):
        features = []
        for au in audio:
            feature = Kaldi.fbank(au.unsqueeze(0), num_mel_bins=self._feat_dim)
            feature = feature - feature.mean(dim=0, keepdim=True)
            features.append(feature.unsqueeze(0))
        return torch.cat(features)
