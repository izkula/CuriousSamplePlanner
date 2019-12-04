#!/usr/bin/env python
from __future__ import print_function

import torch
from numpy.random import choice
from scipy.special import softmax
from torch.utils.data import Dataset

from scripts.utils import *


class GraphNode:
    def __init__(self, config, preconfig, action, command=None, node_key=0):
        self.config = config
        self.preconfig = preconfig
        self.node_key = node_key
        self.action = action
        self.command = command
        self.novelty = 0

    def set_novelty_score(self, novelty):
        self.novelty = novelty

    def conf_equals(self, other_conf):
        if dist(other_conf, self.config) < 0.02:
            return True
        return False

    def get_batch_data(self):
        return self.config, self.preconfig, self.action


class PlanGraph(Dataset):
    def __init__(self, plan_graph_path=None, node_sampling="uniform"):
        self.node_key = 0
        self.selection_strategy = node_sampling
        if plan_graph_path != None:
            # self.plan_graph = np.load(plan_graph_path).item()
            self.plan_graph = np.load(plan_graph_path, allow_pickle=True).item()
        else:
            self.plan_graph = collections.OrderedDict()

    def save(self, save_path):
        np.save(save_path, np.array(self.plan_graph))

    def expand_node(self, nselect, priority=0.0001):
        if self.selection_strategy == "uniform":
            return choice(np.array(list(self.plan_graph.keys())), nselect)
        elif self.selection_strategy == "softmax":
            vals = np.array([node.novelty for node in self.plan_graph.keys()])
            if np.std(vals) == 0:
                sm = softmax(vals)
            else:
                sm = softmax(priority * (vals - np.mean(vals)) / np.std(vals))
            return choice(np.array(list(self.plan_graph.keys())), nselect, p=sm)

    def find_node(self, node_index):
        for node in list(self.plan_graph.keys()):
            if node.node_key == node_index:
                return node
        return None

    def __len__(self):
        return len(self.plan_graph.keys()) - 1

    def __getitem__(self, index):
        node = list(self.plan_graph.keys())[index + 1]
        config, preconfig, action = node.get_batch_data()
        return torch.zeros((1, 3, 84, 84)), config, preconfig, node.node_key, index, action

    def set_novelty_scores(self, index, losses):
        for loss_index, node_index in enumerate(index):
            list(self.plan_graph.keys())[node_index + 1].set_novelty_score(losses[loss_index].item())

    def add_node(self, conf, preconf, action, parent_index, command=None):
        parent = self.find_node(parent_index)
        new_node = GraphNode(conf, preconf, action, node_key=self.node_key, command=command)
        self.plan_graph[new_node] = []
        if parent != None:
            self.plan_graph[parent].append(new_node)
            self.plan_graph[new_node].append(parent)
        self.node_key += 1
        return new_node

    def is_node(self, conf):

        for node in list(self.plan_graph.keys()):
            if node.conf_equals(conf):
                return True
        return False

    def get_optimal_plan(self, start_node, goal_node):
        self.start_node = start_node
        self.goal_node = goal_node
        distance = lambda a, b: 1
        collision = lambda s: False
        print(self.plan_graph)
        path = astar(start_node, goal_node, distance, self.plan_graph, collision)
        print(path)
        # for node_i in range(1, len(path)):
        #     print(path[node_i].command)
        return path

    def get_all_paths(self):
        start_node = self.find_node(0)
        assert start_node is not None
        paths = []
        distance = lambda a, b: 1
        collision = lambda s: False
        for node in list(self.plan_graph.keys()):
            if node.node_key == 0:
                continue
            path = astar(start_node, node, distance, self.plan_graph, collision)
            paths.append(path)
        return paths
