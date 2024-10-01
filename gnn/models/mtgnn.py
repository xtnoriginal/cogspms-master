from __future__ import division

import numbers

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import init


class NConv(nn.Module):
    def __init__(self):
        super(NConv, self).__init__()

    def forward(self, x, adj):
        x = torch.einsum('ncwl,vw->ncvl', (x, adj))
        return x.contiguous()


class DyNConv(nn.Module):
    def __init__(self):
        super(DyNConv, self).__init__()

    def forward(self, x, adj):
        x = torch.einsum('ncvl,nvwl->ncwl', (x, adj))
        return x.contiguous()


class Linear(nn.Module):
    def __init__(self, c_in, c_out, bias=True):
        super(Linear, self).__init__()
        self.mlp = torch.nn.Conv2d(c_in, c_out, kernel_size=(1, 1), padding=(0, 0), stride=(1, 1), bias=bias)

    def forward(self, x):
        return self.mlp(x)


class Propagation(nn.Module):
    def __init__(self, c_in, c_out, gdep, dropout, alpha):
        super(Propagation, self).__init__()
        self.nconv = NConv()
        self.mlp = Linear(c_in, c_out)
        self.gdep = gdep
        self.dropout = dropout
        self.alpha = alpha

    def forward(self, x, adj):
        adj = adj + torch.eye(adj.size(0)).to(x.device)
        d = adj.sum(1)
        h = x
        dv = d
        a = adj / dv.view(-1, 1)
        for i in range(self.gdep):
            h = self.alpha * x + (1 - self.alpha) * self.nconv(h, a)
        ho = self.mlp(h)
        return ho


class MixPropagation(nn.Module):
    def __init__(self, c_in, c_out, gdep, dropout, alpha):
        super(MixPropagation, self).__init__()
        self.nconv = NConv()
        self.mlp = Linear((gdep + 1) * c_in, c_out)
        self.gdep = gdep
        self.dropout = dropout
        self.alpha = alpha

    def forward(self, x, adj):
        adj = adj + torch.eye(adj.size(0)).to(x.device)
        d = adj.sum(1)
        h = x
        out = [h]
        a = adj / d.view(-1, 1)
        for i in range(self.gdep):
            h = self.alpha * x + (1 - self.alpha) * self.nconv(h, a)
            out.append(h)
        ho = torch.cat(out, dim=1)
        ho = self.mlp(ho)
        return ho


class DyMixPropagation(nn.Module):
    def __init__(self, c_in, c_out, gdep, dropout, alpha):
        super(DyMixPropagation, self).__init__()
        self.nconv = DyNConv()
        self.mlp1 = Linear((gdep + 1) * c_in, c_out)
        self.mlp2 = Linear((gdep + 1) * c_in, c_out)

        self.gdep = gdep
        self.dropout = dropout
        self.alpha = alpha
        self.lin1 = Linear(c_in, c_in)
        self.lin2 = Linear(c_in, c_in)

    def forward(self, x):
        x1 = torch.tanh(self.lin1(x))
        x2 = torch.tanh(self.lin2(x))
        adj = self.nconv(x1.transpose(2, 1), x2)
        adj0 = torch.softmax(adj, dim=2)
        adj1 = torch.softmax(adj.transpose(2, 1), dim=2)

        h = x
        out = [h]
        for i in range(self.gdep):
            h = self.alpha * x + (1 - self.alpha) * self.nconv(h, adj0)
            out.append(h)
        ho = torch.cat(out, dim=1)
        ho1 = self.mlp1(ho)

        h = x
        out = [h]
        for i in range(self.gdep):
            h = self.alpha * x + (1 - self.alpha) * self.nconv(h, adj1)
            out.append(h)
        ho = torch.cat(out, dim=1)
        ho2 = self.mlp2(ho)

        return ho1 + ho2


class Dilated1D(nn.Module):
    def __init__(self, c_in, c_out, dilation_factor=2):
        super(Dilated1D, self).__init__()
        self.tconv = nn.ModuleList()
        self.kernel_set = [2, 3, 6, 7]
        self.tconv = nn.Conv2d(c_in, c_out, (1, 7), dilation=(1, dilation_factor))

    def forward(self, inputs):
        x = self.tconv(inputs)
        return x


class DilatedInception(nn.Module):
    def __init__(self, c_in, c_out, dilation_factor=2):
        super(DilatedInception, self).__init__()
        self.tconv = nn.ModuleList()
        self.kernel_set = [2, 3, 6, 7]
        c_out = int(c_out / len(self.kernel_set))
        for kern in self.kernel_set:
            self.tconv.append(nn.Conv2d(c_in, c_out, (1, kern), dilation=(1, dilation_factor)))

    def forward(self, inputs):
        x = []
        for i in range(len(self.kernel_set)):
            x.append(self.tconv[i](inputs))
        for i in range(len(self.kernel_set)):
            x[i] = x[i][..., -x[-1].size(3):]
        x = torch.cat(x, dim=1)
        return x


class GraphConstructor(nn.Module):
    def __init__(self, nodes, k, dim, device, alpha=3, static_feat=None):
        super(GraphConstructor, self).__init__()
        self.nodes = nodes
        if static_feat is not None:
            xd = static_feat.shape[1]
            self.lin1 = nn.Linear(xd, dim)
            self.lin2 = nn.Linear(xd, dim)
        else:
            self.emb1 = nn.Embedding(nodes, dim)
            self.emb2 = nn.Embedding(nodes, dim)
            self.lin1 = nn.Linear(dim, dim)
            self.lin2 = nn.Linear(dim, dim)

        self.device = device
        self.k = k
        self.dim = dim
        self.alpha = alpha
        self.static_feat = static_feat

    def forward(self, idx):
        if self.static_feat is None:
            node_vec1 = self.emb1(idx)
            node_vec2 = self.emb2(idx)
        else:
            node_vec1 = self.static_feat[idx, :]
            node_vec2 = node_vec1

        node_vec1 = torch.tanh(self.alpha * self.lin1(node_vec1))
        node_vec2 = torch.tanh(self.alpha * self.lin2(node_vec2))

        a = torch.mm(node_vec1, node_vec2.transpose(1, 0)) - torch.mm(node_vec2, node_vec1.transpose(1, 0))
        adj = F.relu(torch.tanh(self.alpha * a))
        mask = torch.zeros(idx.size(0), idx.size(0)).to(self.device)
        mask.fill_(float('0'))
        s1, t1 = (adj + torch.rand_like(adj) * 0.01).topk(self.k, 1)
        mask.scatter_(1, t1, s1.fill_(1))
        adj = adj * mask
        return adj

    def full_adj(self, idx):
        if self.static_feat is None:
            node_vec1 = self.emb1(idx)
            node_vec2 = self.emb2(idx)
        else:
            node_vec1 = self.static_feat[idx, :]
            node_vec2 = node_vec1

        node_vec1 = torch.tanh(self.alpha * self.lin1(node_vec1))
        node_vec2 = torch.tanh(self.alpha * self.lin2(node_vec2))

        a = torch.mm(node_vec1, node_vec2.transpose(1, 0)) - torch.mm(node_vec2, node_vec1.transpose(1, 0))
        adj = F.relu(torch.tanh(self.alpha * a))
        return adj


class LayerNorm(nn.Module):
    __constants__ = ['normalized_shape', 'weight', 'bias', 'eps', 'elementwise_affine']

    def __init__(self, normalized_shape, eps=1e-5, elementwise_affine=True):
        super(LayerNorm, self).__init__()
        if isinstance(normalized_shape, numbers.Integral):
            normalized_shape = (normalized_shape,)
        self.normalized_shape = tuple(normalized_shape)
        self.eps = eps
        self.elementwise_affine = elementwise_affine
        if self.elementwise_affine:
            self.weight = nn.Parameter(torch.Tensor(*normalized_shape))
            self.bias = nn.Parameter(torch.Tensor(*normalized_shape))
        else:
            self.register_parameter('weight', None)
            self.register_parameter('bias', None)
        self.reset_parameters()

    def reset_parameters(self):
        if self.elementwise_affine:
            init.ones_(self.weight)
            init.zeros_(self.bias)

    def forward(self, model_input, idx):
        if self.elementwise_affine:
            return F.layer_norm(model_input, tuple(model_input.shape[1:]), self.weight[:, idx, :], self.bias[:, idx, :],
                                self.eps)
        else:
            return F.layer_norm(model_input, tuple(model_input.shape[1:]), self.weight, self.bias, self.eps)

    def extra_repr(self):
        return '{normalized_shape}, eps={eps}, ' \
               'elementwise_affine={elementwise_affine}'.format(**self.__dict__)


class MTGNN(nn.Module):
    def __init__(self, gcn_true, build_adj, gcn_depth, num_nodes, device, adj_matrix=None, static_feat=None,
                 dropout=0.3, subgraph_size=20, node_dim=40, dilation_exponential=1, conv_channels=32,
                 residual_channels=32, skip_channels=64, end_channels=128, seq_length=12, in_dim=2, out_dim=12,
                 layers=3, propalpha=0.05, tanhalpha=3, layer_norm_affline=True):
        super(MTGNN, self).__init__()
        self.gcn_true = gcn_true
        self.build_adj = build_adj
        self.num_nodes = num_nodes
        self.dropout = dropout
        self.predefined_A = adj_matrix
        self.filter_convs = nn.ModuleList()
        self.gate_convs = nn.ModuleList()
        self.residual_convs = nn.ModuleList()
        self.skip_convs = nn.ModuleList()
        self.g_conv1 = nn.ModuleList()
        self.g_conv2 = nn.ModuleList()
        self.norm = nn.ModuleList()
        self.start_conv = nn.Conv2d(in_channels=in_dim,
                                    out_channels=residual_channels,
                                    kernel_size=(1, 1))
        self.gc = GraphConstructor(num_nodes, subgraph_size, node_dim, device, alpha=tanhalpha,
                                   static_feat=static_feat)

        self.seq_length = seq_length
        self.final_adj = None
        kernel_size = 7
        if dilation_exponential > 1:
            self.receptive_field = int(
                1 + (kernel_size - 1) * (dilation_exponential ** layers - 1) / (dilation_exponential - 1))
        else:
            self.receptive_field = layers * (kernel_size - 1) + 1

        for i in range(1):
            if dilation_exponential > 1:
                rf_size_i = int(
                    1 + i * (kernel_size - 1) * (dilation_exponential ** layers - 1) / (dilation_exponential - 1))
            else:
                rf_size_i = i * layers * (kernel_size - 1) + 1
            new_dilation = 1
            for j in range(1, layers + 1):
                if dilation_exponential > 1:
                    rf_size_j = int(
                        rf_size_i + (kernel_size - 1) * (dilation_exponential ** j - 1) / (dilation_exponential - 1))
                else:
                    rf_size_j = rf_size_i + j * (kernel_size - 1)

                self.filter_convs.append(
                    DilatedInception(residual_channels, conv_channels, dilation_factor=new_dilation))
                self.gate_convs.append(DilatedInception(residual_channels, conv_channels, dilation_factor=new_dilation))
                self.residual_convs.append(nn.Conv2d(in_channels=conv_channels,
                                                     out_channels=residual_channels,
                                                     kernel_size=(1, 1)))
                if self.seq_length > self.receptive_field:
                    self.skip_convs.append(nn.Conv2d(in_channels=conv_channels,
                                                     out_channels=skip_channels,
                                                     kernel_size=(1, self.seq_length - rf_size_j + 1)))
                else:
                    self.skip_convs.append(nn.Conv2d(in_channels=conv_channels,
                                                     out_channels=skip_channels,
                                                     kernel_size=(1, self.receptive_field - rf_size_j + 1)))

                if self.gcn_true:
                    self.g_conv1.append(MixPropagation(conv_channels, residual_channels, gcn_depth, dropout, propalpha))
                    self.g_conv2.append(MixPropagation(conv_channels, residual_channels, gcn_depth, dropout, propalpha))

                if self.seq_length > self.receptive_field:
                    self.norm.append(LayerNorm((residual_channels, num_nodes, self.seq_length - rf_size_j + 1),
                                               elementwise_affine=layer_norm_affline))
                else:
                    self.norm.append(LayerNorm((residual_channels, num_nodes, self.receptive_field - rf_size_j + 1),
                                               elementwise_affine=layer_norm_affline))

                new_dilation *= dilation_exponential

        self.layers = layers
        self.end_conv_1 = nn.Conv2d(in_channels=skip_channels,
                                    out_channels=end_channels,
                                    kernel_size=(1, 1),
                                    bias=True)
        self.end_conv_2 = nn.Conv2d(in_channels=end_channels,
                                    out_channels=out_dim,
                                    kernel_size=(1, 1),
                                    bias=True)
        if self.seq_length > self.receptive_field:
            self.skip0 = nn.Conv2d(in_channels=in_dim, out_channels=skip_channels, kernel_size=(1, self.seq_length),
                                   bias=True)
            self.skipE = nn.Conv2d(in_channels=residual_channels, out_channels=skip_channels,
                                   kernel_size=(1, self.seq_length - self.receptive_field + 1), bias=True)

        else:
            self.skip0 = nn.Conv2d(in_channels=in_dim, out_channels=skip_channels,
                                   kernel_size=(1, self.receptive_field), bias=True)
            self.skipE = nn.Conv2d(in_channels=residual_channels, out_channels=skip_channels, kernel_size=(1, 1),
                                   bias=True)

        self.idx = torch.arange(self.num_nodes).to(device)

    def forward(self, model_input, idx=None):
        seq_len = model_input.size(3)
        assert seq_len == self.seq_length, 'input sequence length not equal to preset sequence length'

        if self.seq_length < self.receptive_field:
            model_input = nn.functional.pad(model_input, (self.receptive_field - self.seq_length, 0, 0, 0))

        if self.gcn_true:
            if self.build_adj:
                if idx is None:
                    adp = self.gc(self.idx)
                else:
                    adp = self.gc(idx)
            else:
                adp = self.predefined_A
            self.final_adj = [adp]

        x = self.start_conv(model_input)
        skip = self.skip0(F.dropout(model_input, self.dropout, training=self.training))
        for i in range(self.layers):
            residual = x
            filter_ = self.filter_convs[i](x)
            filter_ = torch.tanh(filter_)
            gate = self.gate_convs[i](x)
            gate = torch.sigmoid(gate)
            x = filter_ * gate
            x = F.dropout(x, self.dropout, training=self.training)
            s = x
            s = self.skip_convs[i](s)
            skip = s + skip
            if self.gcn_true:
                x = self.g_conv1[i](x, adp) + self.g_conv2[i](x, adp.transpose(1, 0))
            else:
                x = self.residual_convs[i](x)

            x = x + residual[:, :, :, -x.size(3):]
            if idx is None:
                x = self.norm[i](x, self.idx)
            else:
                x = self.norm[i](x, idx)

        skip = self.skipE(x) + skip
        x = F.relu(skip)
        x = F.relu(self.end_conv_1(x))
        x = self.end_conv_2(x)
        return x
