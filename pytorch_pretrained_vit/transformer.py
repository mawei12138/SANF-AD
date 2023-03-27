"""
Adapted from https://github.com/lukemelas/simple-bert
"""
 
import numpy as np
from torch import nn
from torch import Tensor 
from torch.nn import functional as F
import torch


def split_last(x, shape):
    "split the last dimension to giveTransformern shape"
    shape = list(shape)
    assert shape.count(-1) <= 1
    if -1 in shape:
        shape[shape.index(-1)] = int(x.size(-1) / -np.prod(shape))
    return x.view(*x.size()[:-1], *shape)


def merge_last(x, n_dims):
    "merge the last n_dims to a dimension"
    s = x.size()
    assert n_dims > 1 and n_dims < len(s)
    return x.view(*s[:-n_dims], -1)


class MultiHeadedSelfAttention(nn.Module):
    """Multi-Headed Dot Product Attention"""
    def __init__(self, dim, num_heads, dropout):
        super().__init__()
        self.proj_q = nn.Linear(dim, dim)
        self.proj_k = nn.Linear(dim, dim)
        self.proj_v = nn.Linear(dim, dim)
        self.drop = nn.Dropout(dropout)
        self.n_heads = num_heads
        self.scores = None # for visualization

    def forward(self, x, mask):
        """
        x, q(query), k(key), v(value) : (B(batch_size), S(seq_len), D(dim))
        mask : (B(batch_size) x S(seq_len))
        * split D(dim) into (H(n_heads), W(width of head)) ; D = H * W
        """
        # (B, S, D) -proj-> (B, S, D) -split-> (B, S, H, W) -trans-> (B, H, S, W)
        q, k, v = self.proj_q(x), self.proj_k(x), self.proj_v(x)
        q, k, v = (split_last(x, (self.n_heads, -1)).transpose(1, 2) for x in [q, k, v])
        # (B, H, S, W) @ (B, H, W, S) -> (B, H, S, S) -softmax-> (B, H, S, S)
        scores = q @ k.transpose(-2, -1) / np.sqrt(k.size(-1))
        if mask is not None:
            mask = mask[:, None, None, :].float()
            scores -= 10000.0 * (1.0 - mask)
        scores = self.drop(F.softmax(scores, dim=-1))
        # (B, H, S, S) @ (B, H, S, W) -> (B, H, S, W) -trans-> (B, S, H, W)
        h = (scores @ v).transpose(1, 2).contiguous()
        # -merge-> (B, S, D)
        h = merge_last(h, 2)
        self.scores = scores
        return h


class PositionWiseFeedForward(nn.Module):
    """FeedForward Neural Networks for each position"""
    def __init__(self, dim, ff_dim):
        super().__init__()
        self.fc1 = nn.Linear(dim, ff_dim)
        self.fc2 = nn.Linear(ff_dim, dim)

    def forward(self, x):
        # (B, S, D) -> (B, S, D_ff) -> (B, S, D)
        return self.fc2(F.gelu(self.fc1(x)))


class Block(nn.Module):
    """Transformer Block"""
    def __init__(self, dim, num_heads, ff_dim, dropout):
        super().__init__()
        self.attn = MultiHeadedSelfAttention(dim, num_heads, dropout)
        self.proj = nn.Linear(dim, dim)
        self.norm1 = nn.LayerNorm(dim, eps=1e-6)
        self.pwff = PositionWiseFeedForward(dim, ff_dim)
        self.norm2 = nn.LayerNorm(dim, eps=1e-6)
        self.drop = nn.Dropout(dropout)

    def forward(self, x, mask):
        h = self.drop(self.proj(self.attn(self.norm1(x), mask)))
        x = x + h
        h = self.drop(self.pwff(self.norm2(x)))
        x = x + h
        return x


class Transformer(nn.Module):
    """Transformer with Self-Attentive Blocks"""
    def __init__(self, num_layers, dim, num_heads, ff_dim, dropout):
        super().__init__()
        self.blocks = nn.ModuleList([
            Block(dim, num_heads, ff_dim, dropout) for _ in range(num_layers)])

    def forward(self, x, mask=None, output_layer_ind = -1):

        for i, block in enumerate(self.blocks):
            x = block(x, mask)
            if i==output_layer_ind: #if output_layer_ind is -1 it will aplly the whole network
                break

        return x

# 12,768,12,3072,0.1
class AnomalyTransformer(nn.Module):
    """Transformer with Self-Attentive Blocks"""
    def __init__(self, num_layers, dim, num_heads, ff_dim, dropout):
        super().__init__()
        # 12个原始的block 新的block
        self.blocks = nn.ModuleList([
            # 768,1,3072,0.1
            Block(dim, num_heads, ff_dim, dropout) for _ in range(num_layers)])
        # 这里可以改成更为轻量的网络，可以尝试一下
        # 克隆后的block
        self.cloned_blocks = nn.ModuleList([
            # 768,1,3072,0.1
            Block(dim, num_heads, ff_dim, dropout) for _ in range(num_layers)])

        # if isinstance(clone_block_ind, int):
        #     clone_block_ind = [clone_block_ind]
        #
        # self.clone_block_ind = clone_block_ind
        # if self.clone_block_ind == -1:
        #     self.clone_block_ind = num_layers - 1
        #
        # self.cloned_block = Block(dim, num_heads, ff_dim, dropout)

    def forward(self, x, mask=None, clone_block_ind =None):
        if clone_block_ind is None:
            # [0,1,..11]
            clone_block_ind = list(range(len(self.blocks)))

        if isinstance(clone_block_ind, int):
            if clone_block_ind ==-1:
                clone_block_ind = len(self.blocks)-1
            clone_block_ind = [clone_block_ind]

        origin_block_outputs, cloned_block_outputs = [], []
        for i, block in enumerate(self.blocks):
            # 同时往block和cloned_block里面输入
            _x = x
            x = block(x, mask)


            if i in clone_block_ind:
                cloned_block = self.cloned_blocks[i]
                cloned_x = cloned_block(_x, mask)

                origin_block_outputs.append(x)
                cloned_block_outputs.append(cloned_x)
        # 应该有11个block,每一个的输出为(b,gh*gw+1,dim)(b,24*24+1,768),沿着dim=0堆叠
        return torch.stack(origin_block_outputs), torch.stack(cloned_block_outputs)


class OlderAnomalyTransformer(nn.Module):
    """Transformer with Self-Attentive Blocks"""

    def __init__(self, num_layers, dim, num_heads, ff_dim, dropout, clone_block_ind):
        super().__init__()

        self.blocks = nn.ModuleList([
            Block(dim, num_heads, ff_dim, dropout) for _ in range(num_layers)])

        self.clone_block_ind = clone_block_ind
        if self.clone_block_ind == -1:
            self.clone_block_ind = num_layers - 1

        self.cloned_block = Block(dim, num_heads, ff_dim, dropout)

    def forward(self, x, mask=None, output_layer_ind=-1):

        for i, block in enumerate(self.blocks):
            _x = x
            x = block(x, mask)
            # if i==output_layer_ind: #if output_layer_ind is -1 it will aplly the whole network
            #     break
            if i == self.clone_block_ind:
                origin_block_outputs = x
                cloned_block_outputs = self.cloned_block(_x, mask)
                break
        return origin_block_outputs, cloned_block_outputs