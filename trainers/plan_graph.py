#!/usr/bin/env python
from __future__ import print_function
import pybullet as p
import numpy as np
import time
import random
import math
import imageio
import matplotlib.pyplot as plt
import os
import shutil
import h5py
import imageio
from planning_pybullet.pybullet_tools.kuka_primitives import BodyPath, Attach, Detach
import pickle
import collections
from motion_planners.discrete import astar
import sys

from CuriousSamplePlanner.tasks.three_block_stack import ThreeBlocks

from CuriousSamplePlanner.tasks.ball_ramp import BallRamp
from CuriousSamplePlanner.tasks.pulley import PulleySeesaw
from CuriousSamplePlanner.tasks.bookshelf import BookShelf
from CuriousSamplePlanner.scripts.utils import *
from numpy.random import choice
import torch
from torch import nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from scipy.special import softmax


class GraphNode():
    def __init__(self, config, preconfig, action, node_key=0):
        self.config = config
        self.preconfig = preconfig
        self.node_key = node_key
        self.action = action
        self.novelty = 0

    def conf_equals(self, other_conf):
        if(dist(other_conf, self.config)<0.02):
            return True
        return False

    def set_novelty_score(self, novelty):
        self.novelty = novelty

    def get_batch_data(self):
        return self.config, self.preconfig

class PlanGraph(Dataset):
    def __init__(self, environment=None, plan_graph_path=None, node_sampling="uniform"):
        self.node_key = 0
        self.environment = environment
        self.selection_strategy = node_sampling
        if(plan_graph_path != None):
            self.plan_graph = np.load(plan_graph_path).item()
        else:
            self.plan_graph = collections.OrderedDict()

    def save(self, save_path):
        np.save(save_path, np.array(self.plan_graph))

    def expand_node(self, nselect):
        if(self.selection_strategy == "uniform"):
            return choice(np.array(list(self.plan_graph.keys())), nselect)
        elif(self.selection_strategy == "softmax"):
            vals = np.array([node.novelty for node in self.plan_graph.keys()])
            if(np.std(vals) == 0):
                sm = softmax(vals) 
            else:
                priority = 1
                sm = softmax(priority*(vals-np.mean(vals))/np.std(vals))
            return choice(np.array(list(self.plan_graph.keys())), nselect, p=sm)

    def find_node(self, node_index):
        for node in list(self.plan_graph.keys()):
            if(node.node_key == node_index):
                return node
        return None

    def __len__(self):
        return len(self.plan_graph.keys())-1

    def __getitem__(self, index):
        node = list(self.plan_graph.keys())[index+1]
        config, preconfig = node.get_batch_data()
        self.environment.set_state(config)
        p.stepSimulation()
        img_arr = torch.cat([opt_cuda(torch.tensor(take_picture(yaw, pit, 0)).type(torch.FloatTensor).permute(2, 0 ,1)) for yaw, pit in self.environment.perspectives])
        return img_arr, config, preconfig, node.node_key, index


    def set_novelty_scores(self, index, losses):
        for loss_index, node_index in enumerate(index):
            list(self.plan_graph.keys())[node_index+1].set_novelty_score(losses[loss_index].item())


    def add_node(self, conf, preconf, action, parent_index):
        parent = self.find_node(parent_index)
        new_node = GraphNode(conf, preconf, action, node_key=self.node_key)
        self.plan_graph[new_node] = []
        if(parent != None):
            self.plan_graph[parent].append(new_node)
            self.plan_graph[new_node].append(parent)
        self.node_key+=1
        return new_node

    def is_node(self, conf):

        for node in list(self.plan_graph.keys()):
            if(node.conf_equals(conf)):
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
        return path
